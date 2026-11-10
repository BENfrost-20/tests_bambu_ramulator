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

## Environment and execution

From Bash on the installed Linux host, use the appropriate local prefixes.
These examples use the recorded server layout.

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
- YAML selection is `--config`, then inherited `RAMULATOR2_CONFIG`, then the
  case preset. Overrides apply to every case, including both T09 variants.
  Use a self-contained YAML. The runner preserves the exact bytes and points
  the driver at the snapshot. It clears `RAMULATOR_OVERRIDE_CHANNELS` so
  DRAM topology stays in YAML. Bambu channels are a separate synthesis flag.
- The smoke preset uses **10 ns**, 1 channel and ratio 3. The U250 preset uses
  **5 ns**, 4 channels and ratio 6. The one-channel U250 variant changes only
  the channel count. Bundled alternate presets have explicit clock periods
  in the runner. Set `CLOCK_PERIOD_NS` for a custom YAML if it needs a clock
  different from the case default. The effective period is in the flag snapshot.
- `CASE_TIMEOUT_S` defaults to **2700** seconds per case. The runner uses a
  private working directory, IPC filename, temporary directory and process
  group per case. `--dry-run` stages inputs and commands without synthesis
  or simulation. Tool probes are recorded and successful plans produce a
  header-only CSV. `--clean` removes intermediate `work/` directories
  from completed runs and preserves run metadata, snapshots, logs and
  retained result XML. Each of these commands creates its own run record.

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
| T09 | Same 64-byte-stride checksum with one and four YAML channels | Same output; compare model initialization, traffic and simulated cycles |
| T10 | Native-bus input and AXI output | Same transformed stream, and generated interfaces and aggregate ticks in retained evidence |

These C patterns characterize the traffic Bambu actually synthesizes. Protocol
coverage depends on that RTL. In particular, forcing `RREADY`/`BREADY`, separate
`AW`/`W`, arbitrary strobes, exact RTL cycle windows or specific concurrent
completions would require control beyond these C fixtures. Read-after-write
verifies data visibility; MDPI can acknowledge writes before a DRAM command
issues. The suite does not require T05 to overflow the controller or T08 to
produce a calibrated refresh signature.

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

Each run creates `results/run_YYYYMMDD_HHMMSS_<tag>/` in UTC and atomically
updates `results/latest` to point to the new run. A numeric suffix distinguishes
same-second collisions. Run tags label experiments. Use a unique, descriptive
tag for each calibration sweep.

- `metadata.json` records the run timestamp, suite Git commit and dirty state,
  host/user, configured and effective environment, Bambu and Verilator
  version output, library SHA-256, pre-flight diagnostics, and case outcomes.
- `config_snapshot/<test>/` contains the exact YAML, Bambu arguments as a JSON
  array, staged source and reference inputs, and hashes of the inputs and archive.
- `logs/<test>.log` holds combined stdout/stderr. Beside it are any emitted
  result XML, cycle timing text and MachSuite output data. Generated RTL and
  other simulator artifacts remain in `work/<test>/` until explicitly cleaned.
- `summary.csv` stores status, total accelerator cycles, wall time in seconds,
  accepted read/write requests, and paths relative to the run. Retried requests
  count once when the controller accepts them. Write counts track acceptance.
  Read completions and tick totals are in the case metadata.

A pass requires successful Bambu and testbench completion, functional checks,
and an accepted Ramulator read with a completion under the recorded YAML.
`FAIL` marks a functional mismatch or missing traffic evidence after a completed
simulation. `ERROR` covers missing dependencies, setup failures, timeouts and
incomplete result XML. A completed suite exits 1 if any case fails or errors.
The checked-in vector fixture differs from the vault's two-case 237-cycle run.

For calibration, keep source/input hashes, generated RTL, AXI flags, target
device, queue depth, accelerator period and measurement window fixed. Compare
`total_sim_cycles` with hardware accelerator cycles over the same start-to-done
window, or multiply by the effective accelerator period for simulated time.
`wall_time_s` is host execution time. Change one YAML parameter per tagged
run and use the request counts and read completions to check that you are
comparing the same traffic. MDPI log ticks describe the bridge calls. Detailed
command timings and physical channel balance require separate evidence.
