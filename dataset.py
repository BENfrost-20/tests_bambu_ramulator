"""Keep local run evidence and report from append-only per-board datasets."""

import csv
import datetime as dt
import errno
import fcntl
import gzip
import json
from pathlib import Path
import re
import shutil
import tempfile

from workspace import BOARD_COLUMNS


def write_csv(path, columns, rows):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                     prefix="." + path.name + ".", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            writer = csv.DictWriter(handle, columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def publish_archive(run, label, timestamp):
    """Publish a small, relocatable archive before removing any local artifacts."""
    columns, rows = read_csv(run / "summary.csv")
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    board = metadata.get("board_profile", {}).get("name", "unknown")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", board):
        raise ValueError(f"Invalid archive board {board}")
    archive_root = run.parent / "archive" / board
    archive_root.mkdir(parents=True, exist_ok=True)
    metadata.update(archive_schema_version=2, experiment_label=label, source_run=run.name)
    columns = ["board", *(column for column in columns if column != "board")]
    logs = []
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=archive_root) as temporary:
        pending = Path(temporary)
        (pending / "config_snapshot").mkdir()
        (pending / "logs").mkdir()
        curated = []
        for row in rows:
            row["board"] = board
            archived = row.copy()
            name = row["test_name"]
            case = metadata["cases"][name]
            if row["yaml_config"]:
                yaml = run / row["yaml_config"]
                archived["yaml_config"] = f"config_snapshot/{name}.yaml"
                shutil.copyfile(yaml, pending / archived["yaml_config"])
                case["yaml_config"] = archived["yaml_config"]
                case["inputs"] = json.loads((yaml.parent / "inputs.json").read_text(encoding="utf-8"))
            if row["log_file"]:
                log = run / row["log_file"]
                archived["log_file"] = f"logs/{name}.log.gz"
                destination = pending / archived["log_file"]
                if log.suffix == ".gz":
                    shutil.copyfile(log, destination)
                else:
                    with log.open("rb") as source, destination.open("wb") as output:
                        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                            shutil.copyfileobj(source, compressed)
                logs.append((log, row, archived["log_file"]))
            curated.append(archived)
        write_csv(pending / "summary.csv", columns, curated)
        (pending / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8")
        prefix = f"run_{timestamp}_{metadata.get('tag') or label}"
        for index in range(1000):
            archive = archive_root / (f"{prefix}_{index + 1}" if index else prefix)
            if archive.exists():
                continue
            try:
                pending.rename(archive)
                break
            except OSError as exc:
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
        else:
            raise ValueError(f"Could not allocate an archive directory for {prefix}")

    # Keep latest usable and leave workspace retention to the runner's case policy.
    for _, row, compressed_path in logs:
        row["log_file"] = str(Path("..") / archive.relative_to(run.parent) / compressed_path)
    write_csv(run / "summary.csv", columns, rows)
    for log, _, _ in logs:
        if log.parent.resolve() == (run / "logs").resolve():
            log.unlink()
    return archive


def board_datasets(results, board_names=()):
    """Read locked board files; ignore combined CSV exports in the same directory."""
    rows, sources = [], set()
    known = set(board_names)
    for path in sorted(results.glob("*.csv")):
        if path.is_symlink():
            if path.stem in known:
                raise ValueError(f"Canonical board CSV must be a regular file: {path}")
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            reader = csv.DictReader(handle)
            columns, records = reader.fieldnames, list(reader)
        if columns is None and not records:
            # A writer can create the file just before acquiring its first lock.
            continue
        if columns != list(BOARD_COLUMNS):
            if path.stem in known:
                raise ValueError(f"Incompatible CSV header in {path}")
            continue
        if not records and path.stem not in known:
            continue
        # A combined export has other board names and is never an input dataset.
        if any(row.get("board") != path.stem for row in records):
            if path.stem in known:
                raise ValueError(f"Board values do not match dataset filename {path}")
            continue
        for row in records:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Incomplete CSV row in {path}; inspect the file before continuing")
        sources.add(path.resolve())
        rows.extend(records)
    return rows, sources


def latest_passes(rows):
    """Select the latest successful trial per board/benchmark (append order breaks ties)."""
    latest = {}
    for row in rows:
        if row["status"] != "PASS":
            continue
        try:
            timestamp = dt.datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid dataset timestamp {row['timestamp']!r}") from exc
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
        key = row["board"], row["benchmark"]
        if key not in latest or timestamp >= latest[key][0]:
            latest[key] = timestamp, row
    return [latest[key][1] for key in sorted(latest)]


def print_comparison(rows):
    if not rows:
        print("No passing results in the canonical board datasets.")
        return
    columns = ("board", "benchmark", "cycles", "execution_time_s", "dram_reads",
               "dram_writes", "frequency_mhz", "timestamp", "tag")
    cells = [[row[key] or "-" for key in columns] for row in rows]
    widths = [max(len(key), *(len(row[i]) for row in cells)) for i, key in enumerate(columns)]
    print("  ".join(key.upper().ljust(width) for key, width in zip(columns, widths)))
    for row in cells:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)))


def export_dataset(results, output, board_names=(), latest_only=False):
    rows, sources = board_datasets(results, board_names)
    output = output.resolve()
    reserved = sources | {(results / f"{board}.csv").resolve() for board in board_names}
    if output in reserved:
        raise ValueError(f"Export cannot overwrite canonical board history: {output}")
    if latest_only:
        rows = latest_passes(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output, BOARD_COLUMNS, rows)
    return len(rows)


def compare_test(results, test_name, board_names=()):
    rows, _ = board_datasets(results, board_names)
    passing = latest_passes(row for row in rows if row["benchmark"] == test_name)
    print(f"Latest passing results for {test_name}")
    print_comparison(passing)


def export_summary(results, output=None, board_names=()):
    if output is not None:
        return export_dataset(results, output, board_names, latest_only=True)
    rows, _ = board_datasets(results, board_names)
    print_comparison(latest_passes(rows))
