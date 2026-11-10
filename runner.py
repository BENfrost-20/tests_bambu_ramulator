"""Stage inputs and record Bambu co-simulation results. Uses the Python 3 standard library."""
from contextlib import suppress
import csv
import datetime as dt
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from machsuite.cases import cases as machsuite_cases
from polybench.cases import cases as polybench_cases


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SMOKE = "default_ddr4.yaml"
U250 = "xcu250_ddr4_2400R.yaml"
PERIODS = {
    SMOKE: "10", U250: "5", "xcu250_ddr4_2400R_1ch.yaml": "5",
    "xcu250_ddr5_3200C.yaml": "3.75", "xcu250_ddr3_1600K.yaml": "7.5",
    "xcu280_hbm2.yaml": "5",
}
COLUMNS = (
    "test_name", "status", "total_sim_cycles", "wall_time_s", "dram_read_reqs",
    "dram_write_reqs", "yaml_config", "log_file",
)
COMMON = [
    "--simulate", "--simulator=VERILATOR", "--compiler=I386_CLANG13", "-m32",
    "--generate-interface=INFER", "--memory-allocation-policy=NO_BRAM",
    "--enable-ramulator-integrated", "--device-name=xcu250-2Lfigd2104",
    "--output-directory=output", "-v5",
]
ONE_CHANNEL = ["--channels-type=MEM_ACC_11", "--channels-number=1"]


def smoke_case(name="smoke_vector_add", config=SMOKE):
    return {
        "name": name, "config": config, "members": ["smoke/vector_add_axi.c", "smoke/test_vector_add.xml"],
        "limit": 100000,
        "flags": [
            "--top-fname=vector_add", "--generate-tb=@/smoke/test_vector_add.xml",
            "--tb-param-size=vec_a:32,vec_b:32,vec_c:32", "@/smoke/vector_add_axi.c", *ONE_CHANNEL,
        ],
    }


def micro_cases():
    # Each tuple sets the synthesized pattern, array sizes, word stride and DRAM preset.
    for name, pattern, words, outputs, stride, config in (
        ("t01_clock", 1, 2, 1, 1, SMOKE),
        ("t02_single_read", 2, 1, 1, 1, SMOKE),
        ("t03_read_after_write", 3, 2, 1, 1, SMOKE),
        ("t04_stream", 4, 512, 512, 1, SMOKE),
        ("t05_queue_pressure", 5, 4096, 4096, 1, SMOKE),
        ("t06_byte_lanes", 6, 2, 1, 1, SMOKE),
        ("t07_row_local", 7, 32769, 1, 1, SMOKE),
        ("t07_row_stride", 7, 32769, 1, 32768, SMOKE),
        ("t08_refresh_stream", 8, 32768, 1, 1, SMOKE),
        ("t09_channels_1", 9, 8192, 1, 16, "xcu250_ddr4_2400R_1ch.yaml"),
        ("t09_channels_4", 9, 8192, 1, 16, U250),
        ("t10_native_and_axi", 10, 512, 512, 1, U250),
    ):
        yield {
            "name": name, "config": config, "members": ["micro/pattern.c", "micro/check.c"],
            "limit": 10000000, "marker": "MICRO CHECK PASS",
            "flags": [
                "--top-fname=memory_pattern", "--generate-tb=@/micro/check.c", "@/micro/pattern.c",
                f"-DPATTERN={pattern}", f"-DWORDS={words}", f"-DOUT_WORDS={outputs}", f"-DSTRIDE={stride}",
                f"--tb-param-size=in:{4 * words},out:{4 * outputs}", "--std=gnu11",
                "--tb-queue-size=64" if pattern == 5 else "--tb-queue-size=20",
                "-fno-tree-vectorize", *ONE_CHANNEL, "--bus-pipelined",
            ],
        }


def select_cases(suite):
    groups = {
        "smoke": [smoke_case()],
        "micro": list(micro_cases()),
        "polybench": list(polybench_cases()),
        "machsuite": list(machsuite_cases()),
        "diagnostic": [
            smoke_case("diagnostic_ddr5", "xcu250_ddr5_3200C.yaml"),
            smoke_case("diagnostic_ddr3", "xcu250_ddr3_1600K.yaml"),
            smoke_case("diagnostic_hbm2", "xcu280_hbm2.yaml"),
        ],
    }
    if suite == "all":
        return [case for name in ("smoke", "micro", "polybench", "machsuite") for case in groups[name]]
    return groups.get(suite, [])


def capture(argv, cwd=None, env=None):
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", timeout=15, check=False)
        return {"exit_code": result.returncode, "output": result.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "output": str(exc)}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_run(tag, now):
    RESULTS.mkdir(exist_ok=True)
    prefix = f"run_{now:%Y%m%d_%H%M%S}_{tag}"
    for suffix in range(1000):
        run = RESULTS / (f"{prefix}_{suffix + 1}" if suffix else prefix)
        try:
            run.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError(f"Run directory collision for {prefix}")
    for name in ("config_snapshot", "logs"):
        (run / name).mkdir()
    link = RESULTS / f".latest-{uuid.uuid4().hex}"
    link.symlink_to(run.name, target_is_directory=True)
    try:
        link.replace(RESULTS / "latest")
    finally:
        if link.is_symlink():
            link.unlink()
    return run


def inspect_host():
    names = (
        "bambu", "verilator", "make", "objcopy", "readelf", "ldd", "git",
        "bash", "awk", "bc", "envsubst", "timeout",
    )
    paths = {name: shutil.which(name) for name in names}
    versions = {name: capture([paths[name], "--version"]) if paths[name] else None
                for name in ("bambu", "verilator")}
    errors = [f"{name} was not found on PATH" for name, path in paths.items() if not path]
    for name, version in versions.items():
        if version and version["exit_code"] != 0:
            errors.append(f"{name} --version failed")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        errors.append("I386_CLANG13 co-simulation requires the Linux x86_64 multilib host")
    for name in ("BAMBU_HLS", "BAMBU_HLS_BACKEND_PATH", "RAMULATOR2_DIR"):
        if not os.environ.get(name):
            errors.append(f"{name} is unset")
    if os.environ.get("BAMBU_HLS"):
        makefile = Path(os.environ["BAMBU_HLS"]) / "share/panda/libmdpi/Makefile.mk"
        if not makefile.is_file():
            errors.append(f"Installed MDPI Makefile missing: {makefile}")

    env = os.environ.copy()
    library_info = None
    if env.get("RAMULATOR2_DIR"):
        directory = Path(env["RAMULATOR2_DIR"]).resolve()
        library = directory / "libramulator.so"
        headers = [
            directory / "src/frontend/frontend.h",
            directory / "ext/yaml-cpp/include/yaml-cpp/yaml.h",
            directory / "ext/argparse/include/argparse/argparse.hpp",
        ]
        for path in (library, *headers):
            if not path.is_file() or not os.access(path, os.R_OK):
                errors.append(f"Missing or unreadable Ramulator input: {path}")
        env["RAMULATOR2_DIR"] = str(directory)
        for variable, values in (
            ("LD_LIBRARY_PATH", [str(directory)]),
            ("CPLUS_INCLUDE_PATH", [str(path.parents[1]) for path in headers[1:]]),
        ):
            existing = [item for item in env.get(variable, "").split(":") if item and item not in values]
            env[variable] = ":".join(values + existing)
        if library.is_file() and os.access(library, os.R_OK):
            with library.open("rb") as handle:
                header = handle.read(20)
            elf32_i386 = header[:6] == b"\x7fELF\x01\x01" and header[18:20] == b"\x03\x00"
            library_info = {"path": str(library), "sha256": sha256(library), "elf32_i386": elf32_i386}
            if not elf32_i386:
                errors.append(f"Expected an ELF32 i386 libramulator.so: {library}")
            elif paths["ldd"] and platform.system() == "Linux":
                result = capture([paths["ldd"], str(library)], env=dict(env, LC_ALL="C"))
                library_info["ldd"] = result
                if result["exit_code"] or "not found" in result["output"]:
                    errors.append("The loader could not resolve libramulator.so dependencies; see metadata.json")
    for variable in ("OUT_LVL", "BAMBU_IPC_SIM_CMD", "RAMULATOR_OVERRIDE_CHANNELS"):
        env.pop(variable, None)
    return paths, versions, env, library_info, errors


def stage_case(case, snapshot, config_override, bambu):
    source_config = Path(config_override).resolve() if config_override else ROOT / "configs" / case.get("config", U250)
    data = source_config.read_bytes()
    if b"!include" in data:
        raise ValueError("Use a self-contained YAML; Ramulator resolves !include relative to runtime paths")
    yaml = snapshot / source_config.name
    yaml.write_bytes(data)
    members = case["members"]
    inputs = snapshot / "inputs"
    source_info = {"yaml_source": str(source_config), "yaml_sha256": sha256(yaml)}
    if "archive" in case:
        archives = Path(os.environ.get("BENCHMARK_ARCHIVES", str(ROOT.parent / "Archive 2")))
        archive = (archives / case["archive"]).resolve()
        source_info.update(archive=str(archive), archive_sha256=sha256(archive))
        with ZipFile(archive) as bundle:
            for name in members:
                target = inputs / name
                target.parent.mkdir(parents=True, exist_ok=True)
                # Extract only the explicit member paths in the recipe.
                target.write_bytes(bundle.read(name))
    else:
        for name in members:
            target = inputs / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
    source_info["inputs_sha256"] = {name: sha256(inputs / name) for name in members}
    period = os.environ.get("CLOCK_PERIOD_NS") or PERIODS.get(
        source_config.name, PERIODS[case.get("config", U250)])
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", period) or float(period) <= 0:
        raise ValueError("CLOCK_PERIOD_NS must be a positive decimal number")
    argv = [
        bambu, *COMMON, f"--clock-period={period}", f"--max-sim-cycles={case.get('limit', 200000000)}",
        *(flag.replace("@/", str(inputs) + "/") for flag in case["flags"]),
    ]
    write_json(snapshot / "bambu_flags.json", argv[1:])
    source_info.update(clock_period_ns=period, argv=argv, ramulator2_config=str(yaml))
    write_json(snapshot / "inputs.json", source_info)
    return argv, yaml


def launch(argv, work, log, env, timeout):
    with log.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {shlex.join(argv)}\n")
        handle.flush()
        with subprocess.Popen(argv, cwd=work, env=env, stdout=handle, stderr=subprocess.STDOUT,
                              start_new_session=True) as process:
            try:
                return process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                if isinstance(exc, KeyboardInterrupt):
                    raise
                handle.write(f"\nRUNNER: wall timeout after {timeout:g}s\n")
                return None


def measure(log):
    reads = writes = completions = ticks = 0
    initialized = False
    used_config = None
    functional_failure = False
    for line in log:
        reads += bool(re.search(r"Issued Ramulator2 read request tag \d+|Ramulator2 queued read tag \d+ resubmitted", line))
        writes += "Issued Ramulator2 write request for addr " in line or "Ramulator2 queued write submitted for addr " in line
        completions += "Ramulator2 read completion: tag=" in line
        step = re.search(r"Advanced Ramulator2 by (\d+) cycles", line)
        if step:
            ticks += int(step[1])
        initialized |= "Ramulator2 successfully initialized for interface " in line
        marker = "Using Ramulator2 config from RAMULATOR2_CONFIG env var: "
        if marker in line:
            used_config = line.split(marker, 1)[1].strip()
        functional_failure |= any(token in line for token in (
            "CHECK FAIL:", "Memory parameter mismatch has been found.", "Benchmark results are incorrect",
        ))
    return reads, writes, completions, ticks, initialized, used_config, functional_failure


def assess(case, row, log, work, yaml, exit_code):
    with log.open(encoding="utf-8", errors="replace") as handle:
        reads, writes, completions, ticks, initialized, config, mismatch = measure(handle)
    row.update(dram_read_reqs=reads, dram_write_reqs=writes)
    details = {"bambu_exit_code": exit_code, "read_completions": completions, "logged_dram_ticks": ticks,
               "initialized": initialized, "reported_config": config}
    try:
        simulation = ET.parse(work / "output/bambu_results.xml").find("./timing/simulation")
        if simulation is None:
            raise ValueError("missing timing/simulation")
        runs = [(node.text or "").strip() for node in simulation.findall("run")]
        return_value = simulation.get("return_value")
        if runs and all(re.fullmatch(r"[0-9]+", value) for value in runs):
            row["total_sim_cycles"] = sum(map(int, runs))
        else:
            raise ValueError(f"incomplete cycle data: {runs}")
        if not re.fullmatch(r"-?[0-9]+", return_value or ""):
            raise ValueError(f"incomplete testbench return value: {return_value}")
    except (OSError, ET.ParseError, ValueError) as exc:
        result_error = str(exc)
    else:
        result_error = None
    if exit_code is None:
        return "ERROR", "wall timeout", details
    if mismatch:
        return "FAIL", "functional mismatch", details
    if result_error:
        return "ERROR", f"no completed Bambu result (exit={exit_code}): {result_error}", details
    if int(return_value) != 0:
        return "FAIL", f"testbench returned {return_value}", details
    if exit_code != 0:
        return "ERROR", f"Bambu exited {exit_code}", details
    if not row["total_sim_cycles"]:
        return "ERROR", "no simulated accelerator cycles", details
    if not initialized or config != str(yaml):
        return "ERROR", "MDPI did not confirm initialization with the YAML snapshot", details
    if not reads or not completions:
        return "FAIL", "MDPI did not report an accepted read and completion", details
    if case.get("marker"):
        with log.open(encoding="utf-8", errors="replace") as handle:
            if not any(line.strip() == case["marker"] for line in handle):
                return "FAIL", "functional harness success marker missing", details
    if case.get("byte_check"):
        expected = yaml.parent / "inputs" / case["byte_check"]
        if not (work / "output.data").is_file() or sha256(work / "output.data") != sha256(expected):
            return "FAIL", "BFS output.data differs from check.data", details
    return "PASS", "functional checks and MDPI traffic confirmed", details


def clean_work(run, dry_run):
    removed = []
    for old in sorted(RESULTS.glob("run_*")):
        if old == run or old.is_symlink() or not (old / ".complete").is_file():
            continue
        work = old / "work"
        if work.is_dir() and not work.is_symlink():
            removed.append(str(work.relative_to(RESULTS)))
            if not dry_run:
                with suppress(FileNotFoundError):
                    shutil.rmtree(work)
    return removed


def main(suite, tag, config, dry_run):
    now = dt.datetime.now(dt.timezone.utc)
    run = create_run(tag, now)
    print(f"Run directory: {run}", flush=True)
    paths, versions, env, library, preflight = inspect_host()
    config_override = config or os.environ.get("RAMULATOR2_CONFIG", "")
    metadata = {
        "timestamp_utc": now.isoformat(), "suite": suite, "tag": tag, "dry_run": dry_run,
        "git_commit": capture(["git", "rev-parse", "HEAD"], ROOT)["output"],
        "git_status": capture(["git", "status", "--porcelain"], ROOT)["output"],
        "user": getpass.getuser(), "host": socket.gethostname(),
        "os": platform.platform(), "architecture": platform.machine(),
        "environment": {key: os.environ.get(key) for key in (
            "BAMBU_HLS", "BAMBU_HLS_BACKEND_PATH", "RAMULATOR2_DIR", "RAMULATOR2_CONFIG",
            "RAMULATOR_OVERRIDE_CHANNELS", "LD_LIBRARY_PATH", "CPLUS_INCLUDE_PATH",
            "BENCHMARK_ARCHIVES", "CLOCK_PERIOD_NS", "CASE_TIMEOUT_S",
        )},
        "effective_environment": {key: env.get(key) for key in (
            "RAMULATOR2_DIR", "LD_LIBRARY_PATH", "CPLUS_INCLUDE_PATH", "RAMULATOR_OVERRIDE_CHANNELS",
        )},
        "config_override": str(Path(config_override).resolve()) if config_override else None,
        "tool_paths": paths, "tool_versions": versions, "ramulator_library": library,
        "preflight_errors": preflight, "cases": {},
    }
    metadata["runner_sha256"] = {
        name: sha256(ROOT / name) for name in
        ("run_tests.sh", "runner.py", "polybench/cases.py", "machsuite/cases.py")
    }
    write_json(run / "metadata.json", metadata)
    failed = False
    with (run / "summary.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, COLUMNS)
        writer.writeheader()
        output.flush()
        if suite == "clean":
            removed = clean_work(run, dry_run)
            verb = "Would remove" if dry_run else "Removed"
            metadata["clean_work_directories"] = removed
            print(f"{verb} {len(removed)} finished work directories.")
        else:
            timeout_text = os.environ.get("CASE_TIMEOUT_S", "2700")
            if not re.fullmatch(r"[1-9][0-9]*", timeout_text):
                preflight.append("CASE_TIMEOUT_S must be a positive integer")
            if any(ch.isspace() for ch in str(run)):
                preflight.append("The Bambu backend requires a workspace path without whitespace")
            if preflight:
                label = "Pre-flight (dry run)" if dry_run else "Pre-flight"
                for error in preflight:
                    print(f"{label}: {error}", file=sys.stderr)
            print(f"{'TEST':<25} {'STATUS':<7} {'CYCLES':>11} {'WALL S':>8} {'READS':>9} {'WRITES':>9}", flush=True)
            for case in select_cases(suite):
                name = case["name"]
                log = run / "logs" / f"{name}.log"
                snapshot = run / "config_snapshot" / name
                snapshot.mkdir()
                row = dict(test_name=name, log_file=str(log.relative_to(run)))
                details = {}
                started = time.monotonic()
                try:
                    argv, yaml = stage_case(case, snapshot, config_override, paths["bambu"] or "bambu")
                    row["yaml_config"] = str(yaml.relative_to(run))
                    if dry_run:
                        log.write_text(f"RAMULATOR2_CONFIG={shlex.quote(str(yaml))}\n$ {shlex.join(argv)}\n",
                                       encoding="utf-8")
                        print(f"{name:<25} PLANNED", flush=True)
                        metadata["cases"][name] = {"planned": True, "yaml_config": str(yaml)}
                        continue
                    if preflight:
                        raise ValueError("pre-flight failed; see metadata.json")
                    work = run / "work" / name
                    (work / "tmp").mkdir(parents=True)
                    case_env = dict(env, RAMULATOR2_CONFIG=str(yaml), TMPDIR=str(work / "tmp"),
                                    BAMBU_IPC_FILENAME=str(work / "panda_ipc_mmap"))
                    started = time.monotonic()
                    exit_code = launch(argv, work, log, case_env, int(timeout_text))
                    row["wall_time_s"] = f"{time.monotonic() - started:.3f}"
                    for artifact in ("output/bambu_results.xml", "output/bambu_time_simulation.txt", "output.data"):
                        source = work / artifact
                        if source.is_file():
                            shutil.copyfile(source, log.with_suffix(f".{source.name}"))
                    status, reason, details = assess(case, row, log, work, yaml, exit_code)
                except (OSError, ValueError, KeyError, BadZipFile) as exc:
                    status, reason = "ERROR", str(exc)
                row["status"] = status
                if not dry_run:
                    row.setdefault("wall_time_s", f"{time.monotonic() - started:.3f}")
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(f"\nRUNNER: {status}: {reason}\n")
                writer.writerow(row)
                output.flush()
                metadata["cases"][name] = dict(details, status=status, reason=reason,
                                               yaml_config=row.get("yaml_config"))
                write_json(run / "metadata.json", metadata)
                failed |= status != "PASS"
                print(f"{name:<25} {status:<7} {str(row.get('total_sim_cycles', '-')):>11} "
                      f"{row.get('wall_time_s', '-'):>8} {str(row.get('dram_read_reqs', '-')):>9} "
                      f"{str(row.get('dram_write_reqs', '-')):>9}", flush=True)
    write_json(run / "metadata.json", metadata)
    (run / ".complete").touch()
    return int(failed)


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    try:
        sys.exit(main(*sys.argv[1:4], dry_run=sys.argv[4] == "1"))
    except KeyboardInterrupt:
        print("Interrupted; partial run evidence was retained.", file=sys.stderr)
        sys.exit(130)
