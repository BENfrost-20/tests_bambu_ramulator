"""Publish curated run records and export calibration features using the stdlib."""

import csv
import errno
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile


# rate (MT/s), nBL, nRCD (read), nRP, nRCDWR (if distinct).
# Values from src/dram/impl/{DDR3,DDR4,DDR5,HBM2}.cpp at d1723a4.
TIMING_PRESETS = {
    ("DDR3", "DDR3_800D"): (800, 4, 5, 5, None),
    ("DDR3", "DDR3_1600K"): (1600, 4, 11, 11, None),
    ("DDR4", "DDR4_2400R"): (2400, 4, 16, 16, None),
    ("DDR5", "DDR5_3200C"): (3200, 8, 28, 28, None),
    ("HBM2", "HBM2_2Gbps"): (2000, 4, 7, 7, 7),
}
HLS_OPTIONS = {
    "top-fname": "top",
    "device-name": "device",
    "clock-period": "clock_period_ns",
    "compiler": "compiler",
    "simulator": "simulator",
    "channels-number": "channels",
    "channels-type": "channels_type",
    "tb-queue-size": "queue_size",
    "memory-allocation-policy": "memory_policy",
    "generate-interface": "interface",
    "max-sim-cycles": "max_sim_cycles",
    "std": "language_standard",
}
DRAM_COLUMNS = (
    "dram_standard", "dram_org_preset", "dram_timing_preset", "dram_channels",
    "dram_ranks", "dram_clock_ratio", "dram_rate_mt_s", "dram_tck_ps",
    "dram_burst_length_cycles", "dram_burst_length_ns", "dram_trcd_cycles",
    "dram_trcd_ns", "dram_trcd_write_cycles", "dram_trcd_write_ns",
    "dram_trp_cycles", "dram_trp_ns", "dram_feature_note",
)


def write_csv(path, columns, rows):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                     prefix="." + path.name + ".", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            writer = csv.DictWriter(handle, columns)
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


def yaml_mapping(text):
    """Read plain block mappings and JSON. Keep other values opaque."""
    if text.lstrip().startswith("{"):
        return json.loads(text)
    root = {}
    stack = [(-1, root)]
    for line in text.splitlines():
        match = re.fullmatch(r"( *)([A-Za-z_][\w-]*|<<)\s*:\s*(.*)", line)
        if not match:
            continue
        indent, key, value = match.groups()
        while stack[-1][0] >= len(indent):
            stack.pop()
        mapping = stack[-1][1]
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if not value or value.startswith("#"):
            mapping[key] = {}
            stack.append((len(indent), mapping[key]))
        else:
            mapping[key] = value.strip("\"'")
    return root


def number(value):
    try:
        if isinstance(value, bool):
            return None
        numeric = float(value)
        if math.isfinite(numeric):
            return int(numeric) if numeric.is_integer() else numeric
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def dram_features(path):
    notes = []

    def mapping(parent, key):
        value = parent.get(key, {})
        if isinstance(value, dict) and "<<" not in value:
            return value
        notes.append(f"unsupported mapping for {key}")
        return {}

    def scalar(parent, key):
        value = parent.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.+-]+", value):
            return value
        return None

    try:
        root = yaml_mapping(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        return {"dram_feature_note": "unsupported YAML syntax"}
    system = mapping(root, "MemorySystem") if isinstance(root, dict) else {}
    dram = mapping(system, "DRAM")
    org, timing = mapping(dram, "org"), mapping(dram, "timing")
    standard, preset = scalar(dram, "impl"), scalar(timing, "preset")
    if not standard:
        notes.append("DRAM implementation unavailable")
    known = TIMING_PRESETS.get((standard, preset))
    if preset and not known:
        notes.append(f"timing preset {preset} unavailable in the preset table")
    rate, burst, rcd, rp, rcd_write = known or (number(timing.get("rate")), None, None, None, None)
    tck = 1000000 // (rate // 2) if rate and rate >= 2 else None
    features = {
        "dram_standard": standard, "dram_org_preset": scalar(org, "preset"),
        "dram_timing_preset": preset, "dram_channels": number(org.get("channel")),
        "dram_ranks": number(org.get("rank")), "dram_clock_ratio": number(system.get("clock_ratio")),
        "dram_rate_mt_s": rate, "dram_tck_ps": tck,
    }
    for label, key, default in (
        ("burst_length", "BL", burst),
        ("trcd", "RCDRD" if standard == "HBM2" else "RCD", rcd),
        ("trcd_write", "RCDWR", rcd_write),
        ("trp", "RP", rp),
    ):
        cycles_key, ns_key = "n" + key, "t" + key
        cycles = number(timing[cycles_key]) if cycles_key in timing else (
            None if ns_key in timing else default)
        if cycles is not None:
            ns = round(cycles * tck / 1000, 6) if tck else None
        else:
            ns = number(timing.get(ns_key))
        features[f"dram_{label}_cycles"] = cycles
        features[f"dram_{label}_ns"] = ns
    features["dram_feature_note"] = ". ".join(notes)
    return features


def hls_features(flags):
    if not flags:
        return {}
    features = {
        "hls_flags": json.dumps(flags, ensure_ascii=False),
        "hls_bus_pipelined": int("--bus-pipelined" in flags),
    }
    for flag in flags:
        key, separator, value = flag.partition("=")
        if key.startswith("--") and key[2:] in HLS_OPTIONS and separator:
            features["hls_" + HLS_OPTIONS[key[2:]]] = value
        elif re.fullmatch(r"-D[A-Za-z_]\w*", key):
            features["define_" + key[2:]] = value if separator else "1"
    return features


def dataset_rows(archive_root):
    summaries = [*archive_root.glob("[!.]*/summary.csv"), *archive_root.glob("[!.]*/[!.]*/summary.csv")]
    for summary_path in sorted(summaries):
        archive = summary_path.parent
        if archive.is_symlink() or archive.parent.is_symlink():
            continue
        metadata = json.loads((archive / "metadata.json").read_text(encoding="utf-8"))
        profile = metadata.get("board_profile", {})
        _, summary = read_csv(summary_path)
        for case in summary:
            inputs = metadata.get("cases", {}).get(case["test_name"], {}).get("inputs", {})
            yaml = case.get("yaml_config")
            flags = hls_features(inputs.get("argv", [])[1:])
            legacy_board = {"xcu250-2Lfigd2104": "xcu250", "xc7z020-1clg484": "xc7z020"}.get(
                flags.get("hls_device"), "unknown")
            row = {key: case.get(key) for key in (
                "test_name", "status", "yaml_config", "log_file",
                "total_sim_cycles", "wall_time_s", "dram_read_reqs", "dram_write_reqs")}
            row.update(
                board=case.get("board") or profile.get("name") or (
                    archive.parent.name if archive.parent != archive_root else legacy_board),
                archive_id=str(archive.relative_to(archive_root)), experiment_label=metadata.get("experiment_label"),
                timestamp_utc=metadata.get("timestamp_utc"), suite=metadata.get("suite"),
                git_commit=metadata.get("git_commit"),
                ramulator_sha256=(metadata.get("ramulator_library") or {}).get("sha256"),
                yaml_sha256=inputs.get("yaml_sha256"),
                inputs_sha256=json.dumps(inputs["inputs_sha256"], sort_keys=True) if "inputs_sha256" in inputs else None,
                cycles=case.get("total_sim_cycles"), dram_reads=case.get("dram_read_reqs"),
                dram_writes=case.get("dram_write_reqs"), timestamp=metadata.get("timestamp_utc"),
                clock_ns=flags.get("hls_clock_period_ns") or (
                    metadata.get("environment", {}).get("CLOCK_PERIOD_NS") or profile.get("default_clock_ns")),
                ramulator_config=Path(inputs.get("yaml_source") or yaml).name if yaml else None,
            )
            if yaml:
                yaml_path = archive / yaml
                if row["yaml_sha256"] and hashlib.sha256(yaml_path.read_bytes()).hexdigest() != row["yaml_sha256"]:
                    raise ValueError(f"Archived YAML hash does not match metadata for {yaml_path}")
                row.update(dram_features(yaml_path))
            row.update(flags)
            yield row


def export_dataset(archive_root, output):
    output = output.resolve()
    if archive_root.resolve() in output.parents:
        raise ValueError("Choose an export path outside the curated archive")
    rows = list(dataset_rows(archive_root))
    defines = sorted({key for row in rows for key in row if key.startswith("define_")})
    identifiers = (
        "board", "test_name", "status", "cycles", "dram_reads", "dram_writes",
        "clock_ns", "ramulator_config", "timestamp", "archive_id", "experiment_label",
        "timestamp_utc", "suite", "git_commit", "ramulator_sha256", "yaml_config",
        "log_file", "yaml_sha256", "inputs_sha256",
    )
    metrics = ("total_sim_cycles", "wall_time_s", "dram_read_reqs", "dram_write_reqs")
    columns = (*identifiers, *DRAM_COLUMNS, *("hls_" + key for key in HLS_OPTIONS.values()),
               "hls_bus_pipelined", "hls_flags", *sorted(defines), *metrics)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output, columns, rows)
    return len(rows)


def compare_test(archive_root, test_name):
    rows = sorted((row for row in dataset_rows(archive_root) if row["test_name"] == test_name),
                  key=lambda row: (row["board"], row.get("timestamp") or "", row["archive_id"]))
    if not rows:
        print(f"No archived records for test {test_name}.")
        return
    columns = ("board", "status", "cycles", "dram_reads", "dram_writes", "clock_ns", "ramulator_config", "timestamp")
    cells = [[str(row[key]) if row.get(key) not in (None, "") else "-" for key in columns] for row in rows]
    widths = [max(len(key), *(len(row[index]) for row in cells)) for index, key in enumerate(columns)]
    print(f"Archived results for {test_name}")
    print("  ".join(key.upper().ljust(width) for key, width in zip(columns, widths)))
    for row in cells:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)))
