"""Stage inputs and record Bambu co-simulation results. Uses the Python 3 standard library."""
from contextlib import suppress
import csv
import datetime as dt
import getpass
import hashlib
import json
import math
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

from dataset import compare_test, export_dataset, publish_archive
from machsuite.cases import cases as machsuite_cases
from polybench.cases import cases as polybench_cases


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
BASELINE = ROOT / "environment_baseline.json"
BOARDS = ROOT / "configs/boards.json"
HLS_COMPILER = "I386_CLANG13"
COLUMNS = (
    "board", "test_name", "status", "total_sim_cycles", "wall_time_s", "dram_read_reqs",
    "dram_write_reqs", "yaml_config", "log_file",
)
COMMON = [
    "--simulate", "--simulator=VERILATOR", f"--compiler={HLS_COMPILER}", "-m32",
    "--generate-interface=INFER", "--memory-allocation-policy=NO_BRAM",
    "--enable-ramulator-integrated",
    "--output-directory=output", "-v5",
]
ONE_CHANNEL = ["--channels-type=MEM_ACC_11", "--channels-number=1"]


def load_board_profiles():
    configured = json.loads(BOARDS.read_text(encoding="utf-8"))
    if not isinstance(configured, list) or any(not isinstance(profile, dict) for profile in configured):
        raise ValueError("configs/boards.json must contain a list of board profile objects")
    profiles = {}
    for profile in configured:
        missing = {"name", "bambu_device", "default_clock_ns", "default_ramulator_yaml", "description"} - profile.keys()
        if missing:
            raise ValueError(f"Board profile is missing fields: {', '.join(sorted(missing))}")
        name = profile["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError("Board names must use letters, digits, underscores or hyphens")
        if name in profiles:
            raise ValueError(f"Duplicate board profile {name}")
        for field in ("bambu_device", "default_ramulator_yaml", "description"):
            if not isinstance(profile[field], str) or not profile[field].strip():
                raise ValueError(f"Board {name} requires {field}")
        clock = profile["default_clock_ns"]
        if isinstance(clock, bool) or not isinstance(clock, (int, float)) or not math.isfinite(clock) or clock <= 0:
            raise ValueError(f"Board {name} requires a positive finite default_clock_ns")
        if not (ROOT / profile["default_ramulator_yaml"]).is_file():
            raise ValueError(f"Board {name} memory config is missing: {profile['default_ramulator_yaml']}")
        profiles[name] = profile
    if "xcu250" not in profiles:
        raise ValueError("configs/boards.json must define the default xcu250 profile")
    return profiles


def board_profile(name):
    profiles = load_board_profiles()
    if name not in profiles:
        raise ValueError(f"Unknown board {name}. Available boards: {', '.join(profiles)}")
    return profiles[name]


def list_boards():
    print(f"{'BOARD':<12} {'STATUS':<14} {'BAMBU DEVICE':<24} {'CLOCK NS':>9}  RAMULATOR YAML")
    for profile in load_board_profiles().values():
        print(f"{profile['name']:<12} {profile.get('status', 'unspecified'):<14} {profile['bambu_device']:<24} "
              f"{profile['default_clock_ns']:>9}  {profile['default_ramulator_yaml']}")
        print(f"  {profile['description']}")


def smoke_case(name="smoke_vector_add", diagnostic_config=None):
    return {
        "name": name, "diagnostic_config": diagnostic_config,
        "members": ["smoke/vector_add_axi.c", "smoke/test_vector_add.xml"],
        "limit": 100000,
        "flags": [
            "--top-fname=vector_add", "--generate-tb=@/smoke/test_vector_add.xml",
            "--tb-param-size=vec_a:32,vec_b:32,vec_c:32", "@/smoke/vector_add_axi.c", *ONE_CHANNEL,
        ],
    }


def micro_cases():
    # Channel variants change the HLS interface. Physical topology comes from the board YAML.
    for name, pattern, words, outputs, stride in (
        ("t01_clock", 1, 2, 1, 1),
        ("t02_single_read", 2, 1, 1, 1),
        ("t03_read_after_write", 3, 2, 1, 1),
        ("t04_stream", 4, 512, 512, 1),
        ("t05_queue_pressure", 5, 4096, 4096, 1),
        ("t06_byte_lanes", 6, 2, 1, 1),
        ("t07_row_local", 7, 32769, 1, 1),
        ("t07_row_stride", 7, 32769, 1, 32768),
        ("t08_refresh_stream", 8, 32768, 1, 1),
        ("t09_channels_1", 9, 8192, 1, 16),
        ("t09_channels_4", 9, 8192, 1, 16),
        ("t10_native_and_axi", 10, 512, 512, 1),
    ):
        channels = (["--channels-type=MEM_ACC_NN", "--channels-number=4"]
                    if name == "t09_channels_4" else ONE_CHANNEL)
        yield {
            "name": name, "members": ["micro/pattern.c", "micro/check.c"],
            "limit": 10000000, "marker": "MICRO CHECK PASS",
            "flags": [
                "--top-fname=memory_pattern", "--generate-tb=@/micro/check.c", "@/micro/pattern.c",
                f"-DPATTERN={pattern}", f"-DWORDS={words}", f"-DOUT_WORDS={outputs}", f"-DSTRIDE={stride}",
                f"--tb-param-size=in:{4 * words},out:{4 * outputs}", "--std=gnu11",
                "--tb-queue-size=64" if pattern == 5 else "--tb-queue-size=20",
                "-fno-tree-vectorize", *channels, "--bus-pipelined",
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
    errors = [f"{name} was not found on PATH" for name, path in paths.items() if not path]
    for name, aliases in (
        ("clang_host", ("clang-19", "clang-19.0", "clang19", "clang")),
        ("clang_hls", ("clang-13", "clang-13.0", "clang13")),
    ):
        paths[name] = next((path for path in map(shutil.which, aliases) if path), None)
        if not paths[name]:
            errors.append(f"{name} was not found on PATH (tried {', '.join(aliases)})")
    versions = {name: capture([paths[name], "--version"]) if paths[name] else None
                for name in ("bambu", "verilator", "clang_host", "clang_hls")}
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


def read_os_release():
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        fields = {}
        for line in lines:
            key, _, value = line.partition("=")
            if key in ("ID", "VERSION_ID", "PRETTY_NAME"):
                fields[key] = value.strip().strip("\"'")
        return fields
    return {}


def matches_version(detected, expected):
    if expected.endswith(".x"):
        prefix = re.escape(expected[:-2])
        return bool(re.fullmatch(prefix + r"(?:\.\d+)?", detected or ""))
    return detected == expected


def check_baseline_docs():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    bambu, verilator = baseline["bambu"], baseline["verilator"]
    host, hls, distro = baseline["clang_host"], baseline["clang_hls"], baseline["host_os"]
    start, end = "<!-- baseline-spec:start -->", "<!-- baseline-spec:end -->"
    block = "\n".join((
        start, "", "| Component | Preflight baseline |", "|---|---|",
        f"| Bambu | `{bambu['release']}`, commit prefix `{bambu['commit_prefix']}` |",
        f"| Verilator | `{verilator['version']}`, revision `{verilator['revision']}` |",
        f"| Host Clang | `{host['version']}` |",
        f"| HLS Clang | `{hls['version']}` (`{hls['target']}`) |",
        f"| Host OS | `{distro['id']}` `{distro['version']}` |", "", end,
    ))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if readme.count(start) != 1 or readme.count(end) != 1 or block not in readme or (
        "](environment_baseline.json)" not in readme
    ):
        print("README.md baseline is out of sync with environment_baseline.json. Expected block:",
              file=sys.stderr)
        print(block, file=sys.stderr)
        return 1
    print("README.md baseline matches environment_baseline.json.")
    return 0


def environment_warnings(baseline, versions, distro):
    warnings = []

    def output(name):
        probe = versions[name]
        return probe["output"] if probe and probe["exit_code"] == 0 else None

    def extract(text, pattern):
        match = re.search(pattern, text, re.IGNORECASE)
        return match[1] if match else "unavailable"

    def report(component, detected, expected, matches):
        if not matches:
            warnings.append({"component": component, "detected": detected, "expected": expected})

    expected = baseline["bambu"]
    release, commit = expected["release"], expected["commit_prefix"]
    banner = output("bambu")
    if banner is not None:
        actual_release = extract(banner, r"\b(?:PandA|Bambu)\s+(\d+(?:\.\d+)+)\b")
        actual_commit = extract(banner, r"\brevision\s+([0-9a-f]{7,40})\b")
        report("Bambu", f"{actual_release} / commit {actual_commit}", f"{release} / commit {commit}",
               actual_release == release and actual_commit.lower().startswith(commit.lower()))

    expected = baseline["verilator"]
    version, revision = expected["version"], expected["revision"]
    banner = output("verilator")
    if banner is not None:
        actual_version = extract(banner, r"\bVerilator\s+(\d+(?:\.\d+)+)\b")
        actual_revision = extract(banner, r"\b(v\d+(?:\.\d+)+[\w.-]*)")
        report("Verilator", f"{actual_version} ({actual_revision})", f"{version} ({revision})",
               actual_version == version and actual_revision == revision)

    hls_target = baseline["clang_hls"]["target"]
    for name, label in (("clang_host", "Host Clang"), ("clang_hls", "HLS Clang")):
        expected = baseline[name]["version"]
        banner = output(name)
        if banner is not None:
            detected = extract(banner, r"\bclang\s+version\s+(\d+(?:\.\d+)+)")
            matches = matches_version(detected, expected)
            if name == "clang_hls":
                matches = matches and HLS_COMPILER == hls_target
                detected, expected = f"{detected} ({HLS_COMPILER})", f"{expected} ({hls_target})"
            report(label, detected, expected, matches)

    expected = baseline["host_os"]
    distro_id, version = expected["id"], expected["version"]
    detected_id = distro.get("ID", "unavailable")
    detected_version = distro.get("VERSION_ID", "unavailable")
    report("Host OS", distro.get("PRETTY_NAME") or f"{detected_id} {detected_version}",
           f"{distro_id} {version}",
           detected_id.lower() == distro_id.lower() and matches_version(detected_version, version))
    return warnings


def stage_case(case, snapshot, config_override, bambu, profile=None):
    profile = profile or board_profile("xcu250")
    default_config = ROOT / profile["default_ramulator_yaml"]
    if case.get("diagnostic_config"):
        default_config = ROOT / "configs" / case["diagnostic_config"]
    source_config = Path(config_override).resolve() if config_override else default_config
    data = source_config.read_bytes()
    if b"!include" in data:
        raise ValueError("Use a self-contained YAML; Ramulator resolves !include relative to runtime paths")
    yaml = snapshot / (source_config.name if source_config.suffix in (".yaml", ".yml") else "ramulator2_config.yaml")
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
    period = os.environ.get("CLOCK_PERIOD_NS") or str(profile["default_clock_ns"])
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", period) or float(period) <= 0:
        raise ValueError("CLOCK_PERIOD_NS must be a positive decimal number")
    argv = [
        bambu, *COMMON, f"--device-name={profile['bambu_device']}", f"--clock-period={period}",
        f"--max-sim-cycles={case.get('limit', 200000000)}",
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


def main(suite, tag, config, dry_run, archive_label="", board="xcu250"):
    profile = board_profile(board)
    now = dt.datetime.now(dt.timezone.utc)
    run = create_run(tag, now)
    print(f"Run directory: {run}", flush=True)
    paths, versions, env, library, preflight = {}, {}, os.environ.copy(), None, []
    baseline, distro, warnings = None, {}, []
    timeout_text = os.environ.get("CASE_TIMEOUT_S", "2700")
    if suite != "clean":
        paths, versions, env, library, preflight = inspect_host()
        distro = read_os_release()
        try:
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
            warnings = environment_warnings(baseline, versions, distro)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            preflight.append(f"Invalid environment baseline {BASELINE}: {exc}")
        if not re.fullmatch(r"[1-9][0-9]*", timeout_text):
            preflight.append("CASE_TIMEOUT_S must be a positive integer")
        if any(ch.isspace() for ch in str(run)):
            preflight.append("The Bambu backend requires a workspace path without whitespace")
    config_override = config
    metadata = {
        "timestamp_utc": now.isoformat(), "suite": suite, "tag": tag, "dry_run": dry_run,
        "board_profile": profile,
        "git_commit": capture(["git", "rev-parse", "HEAD"], ROOT)["output"],
        "git_status": capture(["git", "status", "--porcelain"], ROOT)["output"],
        "user": getpass.getuser(), "host": socket.gethostname(),
        "os": platform.platform(), "os_release": distro, "architecture": platform.machine(),
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
        "environment_baseline": baseline, "environment_warnings": warnings,
        "preflight_errors": preflight, "cases": {},
    }
    metadata["runner_sha256"] = {
        name: sha256(ROOT / name) for name in
        ("run_tests.sh", "runner.py", "dataset.py", "polybench/cases.py", "machsuite/cases.py")
    }
    metadata["boards_sha256"] = sha256(BOARDS)
    write_json(run / "metadata.json", metadata)
    for warning in warnings:
        print(f"\033[33m[WARNING]\033[0m {warning['component']} detected {warning['detected']} "
              f"(expected {warning['expected']})", flush=True)
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
        elif preflight:
            for error in preflight:
                print(f"[ERROR] Pre-flight: {error}", file=sys.stderr)
            failed = True
        else:
            print(f"{'TEST':<25} {'STATUS':<7} {'CYCLES':>11} {'WALL S':>8} {'READS':>9} {'WRITES':>9}", flush=True)
            for case in select_cases(suite):
                name = case["name"]
                log = run / "logs" / f"{name}.log"
                snapshot = run / "config_snapshot" / name
                snapshot.mkdir()
                row = dict(board=board, test_name=name, log_file=str(log.relative_to(run)))
                details = {}
                started = time.monotonic()
                try:
                    argv, yaml = stage_case(case, snapshot, config_override, paths["bambu"], profile)
                    row["yaml_config"] = str(yaml.relative_to(run))
                    if dry_run:
                        log.write_text(f"RAMULATOR2_CONFIG={shlex.quote(str(yaml))}\n$ {shlex.join(argv)}\n",
                                       encoding="utf-8")
                        print(f"{name:<25} PLANNED", flush=True)
                        metadata["cases"][name] = {"planned": True, "yaml_config": str(yaml)}
                        continue
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
    if archive_label and not preflight:
        archive = publish_archive(run, archive_label, now.strftime("%Y%m%d_%H%M%S"))
        metadata["archive_directory"] = str(archive.relative_to(RESULTS))
        write_json(run / "metadata.json", metadata)
        print(f"Archived experiment: {archive}", flush=True)
    (run / ".complete").touch()
    return int(failed)


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGHUP, interrupt)
    try:
        if sys.argv[1:] == ["--check-baseline"]:
            sys.exit(check_baseline_docs())
        if sys.argv[1:] == ["--list-boards"]:
            list_boards()
            sys.exit(0)
        if sys.argv[1] == "--validate-board":
            board_profile(sys.argv[2])
            sys.exit(0)
        if sys.argv[1] == "--compare-test":
            compare_test(RESULTS / "archive", sys.argv[2])
            sys.exit(0)
        if sys.argv[1] == "--export-dataset":
            output = Path(sys.argv[2]) if len(sys.argv) > 2 else RESULTS / "dataset.csv"
            count = export_dataset(RESULTS / "archive", output)
            print(f"Exported {count} rows to {output.resolve()}")
            sys.exit(0)
        sys.exit(main(*sys.argv[1:4], dry_run=sys.argv[4] == "1",
                      archive_label=sys.argv[5] if len(sys.argv) > 5 else "",
                      board=sys.argv[6] if len(sys.argv) > 6 else "xcu250"))
    except (OSError, ValueError, KeyError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted; partial run evidence was retained.", file=sys.stderr)
        sys.exit(130)
