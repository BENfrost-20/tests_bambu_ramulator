# Bambu + Ramulator co-simulation tests

This suite uses installed tools to synthesize C/C++ kernels and co-simulate their
generated RTL with Verilator and Ramulator. The checked-in smoke fixture is the
single eight-element AXI vector add from Bambu. Its expected result is
`[11, 22, 33, 44, 55, 66, 77, 88]`.

## Recorded software bill of materials

| Component | Version on the recorded host | Role |
|---|---|---|
| OS / architecture | Ubuntu **20.04.6 LTS**, **x86_64** | Linux host with 32-bit x86 userspace support |
| Bambu and bambu-cc | PandA **2026.06**, `909639b4b77944d908ca5180ac9f81b3a48a966b` | Installed HLS frontend, runtime and MDPI sources |
| Ramulator | **2.0**, no-spdlog fork, `d1723a4796e799667391931bed2a3af7fe9b0f26` | **ELF32 i386** `libramulator.so`, C++20, GNU libstdc++ |
| Host compiler | Clang/LLVM **19.1.7**, **C++23** | 64-bit Bambu host build; recorded Ramulator compiler also uses Clang 19 |
| Host C++ libraries / linker | **libc++ 19.1.7**, **libc++abi 19.1.7**, **LLD 19.1.7** | 64-bit host runtime and LTO link |
| HLS frontend | Clang/LLVM **13.0.1**, `I386_CLANG13` | LLVM tooling and matching Clang plugins; GNU libstdc++ for the recorded plugins |
| Multilib runtime | System GCC/G++ **9.4.0** | 32-bit GNU libstdc++, libgcc_s, glibc/libm, and `/lib/ld-linux.so.2` |
| RTL simulator | Verilator **4.028**, `v4.026-92-g890cecc1`, 2020-02-06 | Verilated RTL and matching DPI headers |
| Build generator | CMake **3.31.10** (recorded 3.31+ toolchain), Ninja | Recorded production builds; Ninja version unrecorded |
| Bambu dependencies | Boost **1.71**, zlib, Python **3**, Bison, Flex | Recorded build dependencies; individual versions other than Boost unrecorded |
| Other host development packages | GMP, MPFR, MPC, ICU, LZMA, XML2, SuiteSparse, Python 3 development headers | Present on the recorded host; versions unrecorded |
| Ramulator dependencies | yaml-cpp **0.7.0**, argparse **2.9** | Fetched headers; yaml-cpp links into Ramulator, argparse serves its CLI |
| Shell and utilities | Bash, GNU Make, binutils (`objcopy`, `readelf`), `ldd`, Git, GNU coreutils, `awk`, `bc`, `envsubst` | Runtime, linkage checks and provenance; versions unrecorded |

The runner itself uses Python **3.8+** and its standard library.

### Preflight baseline

The version checks use [environment_baseline.json](environment_baseline.json).
Run `./run_tests.sh --check-baseline` after changing the baseline or this table.

<!-- baseline-spec:start -->

| Component | Preflight baseline |
|---|---|
| Bambu | `2026.06`, commit prefix `909639b` |
| Verilator | `4.028`, revision `v4.026-92-g890cecc1` |
| Host Clang | `19.1.x` |
| HLS Clang | `13.0.x` (`I386_CLANG13`) |
| Host OS | `ubuntu` `20.04.x` |

<!-- baseline-spec:end -->

## Environment and execution

Copy [env.example.sh](env.example.sh) to the Git-ignored `env.sh` and edit the
installed tool paths once.

```bash
cp env.example.sh env.sh
# Edit env.sh with this host's installation paths.
./run_tests.sh --smoke
```

When `BAMBU_HLS` or `RAMULATOR2_DIR` is missing, the runner sources the local
`env.sh` before preflight and prints `[INFO] Loaded environment from local env.sh`.
An already configured shell supplies its existing environment. Missing variables
still produce the standard preflight errors, with a pointer to the template.
Run metadata records the loaded file's path and SHA-256, the active `PATH` and
the configured library/header paths.

From Bash on the installed Linux host, use the appropriate local prefixes.
The equivalent manual setup below uses the recorded server layout.

```bash
source "$HOME/thesis/toolchains/settings.sh"
source "$HOME/thesis/soda-benchmarks/builds/bambu-candidate-release-ramulator/install/settings.sh"
IFS=$' \t\n'
export RAMULATOR2_DIR="$HOME/thesis/soda-benchmarks/external/ramulator2/ramulator2-no-spdlog"
./run_tests.sh --smoke --tag baseline
```

The installed settings supply `BAMBU_HLS`, `BAMBU_HLS_BACKEND_PATH` and the tool
paths. The runner verifies the ELF32 library and adds its directory and
fetched headers to the loader and compiler search paths for each case. Use
installation and suite paths without whitespace for the Bambu backend.

Preflight reads the distro version from `os-release`. The host Clang probe
prefers the Clang 19 aliases on `PATH` and falls back to `clang`. The frontend
probe uses the Clang 13 aliases for `I386_CLANG13`.

Version mismatches print a yellow `[WARNING]` with the detected and expected
values and are recorded under `environment_warnings` in `metadata.json`.
Missing required binaries or environment variables, failed tool probes, and
unsupported host architectures stop the run before case staging. This also
applies to `--dry-run`. `--clean` can run without the simulation toolchain.

```bash
./run_tests.sh --all --tag ddr4-baseline
./run_tests.sh --suite micro --dry-run --tag inspect
./run_tests.sh --suite polybench
./run_tests.sh --suite machsuite
./run_tests.sh --suite diagnostic
./run_tests.sh --smoke --config configs/xcu250_ddr4_2400R.yaml --tag u250
./run_tests.sh --clean --dry-run
./run_tests.sh --clean
```

- The default is `--smoke`. `--all` runs smoke, micro, PolyBench and MachSuite.
  The workload recipes stage original files from the sibling `Archive 2/`
  directory. Use `BENCHMARK_ARCHIVES` to point to the directory containing the
  ZIPs on a different host.
- YAML selection is `--config`, then an explicit diagnostic preset when using
  `--suite diagnostic`, then the selected board's default. Overrides apply to
  every case, including both T09 variants. The inherited `RAMULATOR2_CONFIG`
  is recorded for provenance, and each case sets it to its chosen YAML snapshot.
  Use a self-contained YAML. The runner preserves the exact bytes and points
  the driver at the snapshot. It clears `RAMULATOR_OVERRIDE_CHANNELS` so
  DRAM topology stays in YAML. Bambu channels are a separate synthesis flag.
- The default `xcu250` profile uses **5 ns**, 4 DRAM channels and ratio 6.
  `CLOCK_PERIOD_NS` overrides the profile clock. `--config` changes only the
  memory config, so set the clock explicitly when that experiment requires it.
  To replay the original 10 ns single-channel smoke setup, use
  `CLOCK_PERIOD_NS=10 ./run_tests.sh --smoke --config configs/default_ddr4.yaml`.
- `CASE_TIMEOUT_S` defaults to **2700** seconds per case. The runner uses a
  private working directory, IPC filename, temporary directory and process
  group per case. `--dry-run` stages inputs and commands without synthesis
  or simulation. Tool probes are recorded and successful plans produce a
  header-only local summary; no rows are added to the board dataset.
  `--keep-work` disables automatic workspace pruning.
  Each simulation command creates its own run record.

## Board profiles and comparisons

```bash
./run_tests.sh --list-boards
./run_tests.sh --smoke --board xcu250 --tag board-comparison
./run_tests.sh --smoke --board xcu280 --tag board-comparison
./run_tests.sh --smoke --board xcu55c --tag board-comparison
./run_tests.sh --compare-test smoke_vector_add
./run_tests.sh --export-summary
./run_tests.sh --export-summary results/cross-board.csv
```

Profiles live in [configs/boards.json](configs/boards.json). The default board
is `xcu250`.

| Board | Bambu device | Clock (ns) | Memory config | Status |
|---|---|---:|---|---|
| `xcu250` | `xcu250-figd2104-2L-e` | 5.0 | `configs/xcu250_ddr4_2400R.yaml`, DDR4, 4 channels | stable |
| `xcu280` | `xcu280-2Lfsvh2892` | 4.0 | `configs/xcu280_hbm2.yaml`, HBM2, 32 channels | experimental |
| `xcu55c` | `xcu55c-2Lfsvh2892` | 3.33 | `configs/xcu280_hbm2.yaml`, HBM2e target, 32 channels | experimental |

U280 and U55C share the existing `HBM2` Ramulator implementation and timing
preset. The profile status is shown by `--list-boards` and retained in run
metadata. The HBM refresh limitation described below applies to both profiles.

To add a board, append an object with these fields to `configs/boards.json`.

```json
{
  "name": "my_board",
  "bambu_device": "exact-device-name-supported-by-your-bambu",
  "default_clock_ns": 10.0,
  "default_ramulator_yaml": "configs/my_board.yaml",
  "description": "Description of the target and memory scenario",
  "status": "experimental"
}
```

Add the paired YAML at the path relative to the suite root, then run
`--list-boards` to validate the profile. The device name must be supported by
the installed Bambu technology library.
`--board` selects the device, target clock and regular-suite YAML together.
The diagnostic suite keeps its explicit DDR3/DDR5/HBM2 probes and uses the
selected board's clock. Both the full profile and actual case arguments are
retained in the run metadata.

`--compare-test NAME` reads `results/<board>.csv` and displays the latest
**passing** entry per board for that benchmark, including frequency and tag.
A newer `FAIL` or `ERROR` does not replace an earlier pass. Boards with no
passing entry are omitted. UTC timestamps determine recency; the last appended
row wins a timestamp tie. `--export-summary` applies the same selection to
every benchmark and prints a combined table, or writes it to the optional
output CSV. Reporting commands run without the simulation toolchain.

## Running Long Test Suites in Background (tmux)

On the Ubuntu host, activate the toolchain as above and run this command from
the suite directory with `tmux` installed.

```bash
./run_tests.sh --all --tag ddr4-baseline --tmux
```

The launcher starts `bambu_test_xcu250_ddr4-baseline` in the background and returns
control to your shell. It keeps your working directory and exported environment,
including `RAMULATOR2_DIR`, `LD_LIBRARY_PATH` and `PATH`, even if the tmux server
was started before you activated the toolchain. From an existing tmux pane,
`--tmux` runs the suite in that pane. Session names include the board and tag.
The tag defaults to the archive label or suite name. Dots in tags become underscores in session names.
Use distinct session names for concurrent runs.

To see the console, run `tmux attach -t bambu_test_xcu250_ddr4-baseline`. Press
**Ctrl+b**, then **d** to detach. You can close SSH or your laptop after
detaching. The session continues on the Ubuntu host as long as the host and
tmux server stay up. Reconnect over SSH to the same host and run the attach
command again. The session normally closes when the runner finishes, and its
results remain on disk.

From the suite directory on the host, run `watch -n 2 cat results/latest/summary.csv`
to follow the CSV as cases finish. With concurrent runs, use the specific
`results/run_.../summary.csv` printed in the pane because `latest` follows the
most recently started run. The corresponding files under `logs/` show output
for cases still running. To stop a run launched with `--tmux`, use
`tmux kill-session -t =bambu_test_xcu250_ddr4-baseline`. Partial results are retained.

## Microbenchmarks

| Case | C stimulus and oracle | What to compare |
|---|---|---|
| T01 | Two reads around a 1,000-iteration dependent arithmetic loop, known checksum | RTL cycles and logged DRAM ticks across a compute gap |
| T02 | Load and copy one known word | Returned word and one data-read request/completion for the intended access |
| T03 | Volatile store followed by a read of the same word | Updated buffer and readback |
| T04 | Sequential read and transformed write stream | Exact output and request/completion counts under sustained traffic |
| T05 | Permuted gather and sequential writes, queue parameter 64 | Exact output; inspect rejection/retry messages when present |
| T06 | Four volatile byte stores followed by a 32-bit load | `0x44332211` and preserved guard word on the i386 target |
| T07 | Dependent sum alternating two locations, with near and 128 KiB offsets | Functional checks and latency comparison; verify the mapped bank and row before attributing a difference to conflicts |
| T08 | Long sequential checksum | Execution window, tick count and refresh-related timing if command traces are available |
| T09 | Same 64-byte-stride checksum with one and four Bambu interface channels | Same output; physical DRAM topology follows the board YAML |
| T10 | Native-bus input and AXI output | Same transformed stream, and generated interfaces and aggregate ticks in retained evidence |

These C patterns characterize the traffic Bambu actually synthesizes. Protocol
coverage depends on that RTL. In particular, forcing `RREADY`/`BREADY`, separate
`AW`/`W`, arbitrary strobes, exact RTL cycle windows or specific concurrent
completions would require control beyond these C fixtures. Read-after-write
verifies data visibility; MDPI can acknowledge writes before a DRAM command
issues. The suite does not require T05 to overflow the controller or T08 to
produce a calibrated refresh signature.

New T09 runs vary Bambu interface channels. Earlier archived T09 runs selected
per-case physical DRAM channel presets. Include the HLS flags and YAML hashes
when grouping those experiments.

### Diagnostic presets

- **DDR3-1600K** (`xcu250_ddr3_1600K.yaml`) is an expected initialization failure on
  the pinned fork. `ClosedRowPolicy` looks up `bankgroup`, absent in DDR3.
- **HBM2** (`xcu280_hbm2.yaml`) uses `OpenRowPolicy` to avoid a rank lookup during
  row-policy setup. The current `AllBank` refresh implementation iterates ranks,
  while HBM2 exposes pseudochannels. A functional smoke pass can coexist with
  missing modeled refresh. Treat this preset as a diagnostic for timing.
- **DDR5-3200C** (`xcu250_ddr5_3200C.yaml`) is a compatibility probe. All
  diagnostic cases use the same functional and traffic criteria as regular cases,
  so an expected setup failure is recorded as `ERROR`.

## Run records and calibration

Every completed test appends one row to the canonical dataset
`results/<board>.csv`, including `FAIL` and `ERROR` outcomes. Repeated runs
preserve all history. An exclusive file lock covers header validation and
appending, followed by a flush to disk; concurrent runners cannot interleave
rows or duplicate the header. Readers use a shared lock. An incompatible
existing header stops the append and preserves the file for inspection.
Completed case metrics are saved before workspace pruning, even if a later
case fails or the suite is interrupted. Preflight failures, dry runs and
maintenance commands do not add measurement rows.

All board datasets use this exact schema:

```csv
timestamp,git_commit,board,benchmark,status,cycles,execution_time_s,dram_reads,dram_writes,frequency_mhz,tag
```

`timestamp` is the UTC test completion time (imported historical entries use
the recorded run timestamp when completion time is unavailable).
`git_commit` identifies the suite checkout, and `benchmark` is the case name (for example `smoke_vector_add`).
`cycles` counts accelerator cycles; `dram_reads` and `dram_writes` count
accepted requests. `execution_time_s` is measured **host wall time** for the
Bambu invocation (the local summary's `wall_time_s`). `frequency_mhz` is the
requested HLS frequency, computed as `1000 / clock_period_ns`, including any
`CLOCK_PERIOD_NS` override; it is not a measured post-route FPGA frequency.
Unavailable metrics are empty. Use `tag` to identify memory/clock parameter
sweeps; the exact YAML and arguments remain in the local run snapshot.

Under `results/`, only top-level CSVs are eligible for Git tracking:
`xcu250.csv`, `xcu280.csv`, `xcu55c.csv` as those boards are run, and optional
combined datasets such as `cross-board.csv`. This keeps Git diffs focused on
numerical records and makes `pandas.read_csv("results/xcu280.csv")` sufficient
for plotting or fitting. Timestamped run directories, archives, logs, work
trees and metadata snapshots remain local and are ignored by Git.

Each run creates `results/run_YYYYMMDD_HHMMSS_<tag>/` in UTC and atomically
updates `results/latest` to point to the new run. A numeric suffix distinguishes
same-second collisions. Run tags label experiments. Use a unique, descriptive
tag for each calibration sweep.

- `metadata.json` records the run timestamp, suite Git commit and dirty state,
  host/user, configured and effective environment, Bambu and Verilator
  version output, library SHA-256, pre-flight diagnostics, case outcomes and
  the complete `board_profile` object.
- `config_snapshot/<test>/` contains the exact YAML, Bambu arguments as a JSON
  array, staged source and reference inputs, and hashes of the inputs and archive.
- `logs/<test>.log` holds combined stdout/stderr. Beside it are any emitted
  result XML, cycle timing text and MachSuite output data. Once the case
  finishes, the log becomes `logs/<test>.log.gz` and the CSV points to it.
- `summary.csv` starts with the `board` column, followed by status, total accelerator cycles, wall time in seconds,
  accepted read/write requests, and paths relative to the run. Retried requests
  count once when the controller accepts them. Write counts track acceptance.
  Read completions and tick totals are in the case metadata.

These detailed per-run summaries remain available for debugging; comparison
and export commands read the canonical board datasets directly.

A pass requires successful Bambu and testbench completion, functional checks,
and an accepted Ramulator read with a completion under the recorded YAML.
`FAIL` marks a functional mismatch or missing traffic evidence after a completed
simulation. `ERROR` covers missing dependencies, setup failures, timeouts and
incomplete result XML. A completed suite exits 1 if any case fails or errors.
Cycle counts are measured outcomes for calibration and have no pass threshold.

### Workspace retention and maintenance

After a `PASS`, the runner saves metrics, XML, metadata, YAML snapshots and the
compressed combined log before pruning generated artifacts. It removes the
Verilator backend's compiled work files, object files and uncompressed wave
dumps such as `.vcd` and `.fst`. Workspace logs become `.log.gz`, and XML,
YAML and other evidence files remain available. `ERROR` and `FAIL` cases
retain their full work tree for debugging.

```bash
./run_tests.sh --smoke --keep-work
./run_tests.sh --all --archive inspect-rtl --keep-work
./run_tests.sh --clean-work --dry-run
./run_tests.sh --clean-work --older-than-days 14
```

`--keep-work` protects the workspace even with `--archive`. The combined log
outside that workspace is still compressed. The retention setting and cleanup
outcome are recorded in `metadata.json`.

`--clean-work` defaults to a minimum age of **7 days** and runs without the
simulation toolchain. It scans `results/work/` and ordinary run work directories.
Old passing work with saved logs, XML and snapshots can be removed completely.
Additional workspace logs, XML, YAML and JSON are saved under
`logs/<test>.artifacts/` before that removal.
For orphaned work, it prunes recognized generated files and retains evidence.
Active runs and simulator process groups, failed cases, `--keep-work` runs and
symlinks are skipped. Archives, run metadata, CSV summaries and configuration
snapshots are retained. `--clean` applies the same safeguards to completed
runs without an age limit.

To stop tracking previously committed timestamped directories while retaining
every local file, run once from the suite directory:

```bash
./run_tests.sh --untrack-runs
git diff --cached --stat
```

This stages cached-only removals for tracked `results/run_*/` directories and
`results/archive/<board>/run_*/` directories. It is the safe, glob-free
equivalent of `git rm -r --cached results/run_*`, and does not delete disk
data. Commit those removals alongside the board CSVs when ready. `.gitignore`
alone cannot untrack files already committed.

### Local evidence snapshots and dataset exports

```bash
./run_tests.sh --suite micro --config configs/xcu250_ddr4_2400R.yaml --archive ddr4-four-channel
./run_tests.sh --export-dataset results/calibration.csv
./run_tests.sh --export-summary results/cross-board.csv
```

`--archive LABEL` publishes finished simulations, including failed cases, in
`results/archive/<board>/run_YYYYMMDD_HHMMSS_<tag>/` (UTC). The tag defaults to
the archive label. Use it with a simulation suite,
optionally in tmux. Preflight failures and interrupted runs retain their local
records. The archive contains only `metadata.json`, `summary.csv`,
`config_snapshot/*.yaml` and `logs/*.log.gz`. Case metadata includes exact
Bambu arguments and source/input hashes. Publication preserves the per-case
workspace retention policy, including error work and `--keep-work`. The local summary
references the compressed logs, and `results/latest` still points at the local
run. This optional archive is entirely local; `--archive` is not required
for appending metrics to the canonical board CSV.

`--export-dataset [output.csv]` reads all top-level board CSVs and writes the
full measurement history, including failures, using the canonical schema. The
default output is `results/dataset.csv`. Combined exports are excluded from
subsequent reads so rerunning an export does not duplicate rows. Exports
cannot overwrite a canonical board file. `--export-summary [output.csv]`
instead selects the latest passing entry per board/benchmark; without a path
it prints a console table. Older archive summaries are local evidence, not
reporting inputs. Detailed YAML/HLS features and hashes remain in the local
snapshots when a model needs more features than the compact dataset contains.

For fitting, filter to `PASS` rows with the metrics and features your model
uses. When pairing simulation and hardware measurements, match the workload
and input hashes in the snapshots and use the same start-to-done window.
Compute simulated nanoseconds as `cycles * 1000 / frequency_mhz`.
Compare matching tags and frequencies when varying parameters across boards;
the latest-pass summary deliberately does not group by parameter settings.
