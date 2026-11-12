- **Dataset and Input**

| Scope | Observed technical state |
|---|---|
| Repository | `tests_bambu_ramulator`; Bash launcher, Python standard-library runner/reporting, C/C++ fixtures and external benchmark ZIPs |
| Current suites | `smoke`: 1 case; `micro`: 12; `polybench`: 2; `machsuite`: 2; `diagnostic`: 3; `--all` selects the first four suites, 17 cases |
| Missing development history | `docs/devlog.md`: [TO BE VERIFIED] |
| Input storage | Checked-in smoke/micro files; external `../Archive 2/Polybench_modified.zip` and `../Archive 2/MachSuite_modified.zip`; directory override: `BENCHMARK_ARCHIVES` |
| Staging | Extract only recipe-listed ZIP members or copy listed local files; preserve source bytes; record archive, input and YAML SHA-256; replace recipe `@/` prefixes with staged input paths |
| YAML | Self-contained `.yaml`/`.yml`; raw bytes containing `!include` are rejected; non-YAML filename is snapshotted as `ramulator2_config.yaml` |
| YAML precedence | Explicit `--config` > diagnostic case preset > selected board default; each case sets `RAMULATOR2_CONFIG` to its snapshot |
| Environment | Linux x86_64 with i386 multilib for simulations; Python 3.8+ standard library; exact Python version and conda/venv environment: [TO BE VERIFIED] |
| Preflight tools | `bambu`, `verilator`, `make`, `objcopy`, `readelf`, `ldd`, `git`, `bash`, `awk`, `bc`, `envsubst`, `timeout`, host Clang and HLS Clang |
| Preflight files | `$BAMBU_HLS/share/panda/libmdpi/Makefile.mk`; `$RAMULATOR2_DIR/libramulator.so`; `src/frontend/frontend.h`, `ext/yaml-cpp/include/yaml-cpp/yaml.h`, `ext/argparse/include/argparse/argparse.hpp` below Ramulator |
| ABI checks | Ramulator shared library must be little-endian ELF32 i386; on Linux, `ldd` must resolve dependencies; 64-bit host libc++ flags must not enter the 32-bit runtime build |
| Version policy | `environment_baseline.json` checks Bambu 2026.06/commit prefix `909639b`, Verilator 4.028/revision `v4.026-92-g890cecc1`, Clang 19.1.x/13.0.x, Ubuntu 20.04.x; version differences warn; missing required tools/files or unsupported architecture block staging |
| Recorded installation | Bambu `909639b4b77944d908ca5180ac9f81b3a48a966b`; Ramulator 2.0 no-spdlog `d1723a4796e799667391931bed2a3af7fe9b0f26`; Clang 19.1.7/13.0.1; GCC 9.4.0 multilib; yaml-cpp 0.7.0; argparse 2.9; current remote installation: [TO BE VERIFIED] |
| Historical server layout | Account home `/data2/home/pelorosso`; settings at `~/thesis/toolchains/settings.sh` and `~/thesis/soda-benchmarks/builds/bambu-candidate-release-ramulator/install/settings.sh`; recorded Ramulator at `~/thesis/soda-benchmarks/external/ramulator2/ramulator2-no-spdlog`; present availability: [TO BE VERIFIED] |
| Remote placeholders | SSH alias: [TO BE VERIFIED]; current remote repository path: [TO BE VERIFIED]; FPGA runtime/deployment paths: [TO BE VERIFIED] |

| Fixture | Format, shape and initialization | Functional check |
|---|---|---|
| Smoke | C `vector_add(int*, int*, int*, int)`; XML `function/testbench` attributes `vec_a`, `vec_b`, `vec_c`, `n`; `n=8`; A=`{1,2,3,4,5,6,7,8}`, B=`{10,20,30,40,50,60,70,80}`, C initially zero | C=`{11,22,33,44,55,66,77,88}`; three direct-offset `m_axi` pointer ports; `--tb-param-size=vec_a:32,vec_b:32,vec_c:32` bytes |
| Micro | `volatile uint32_t in[WORDS]`, `out[OUT_WORDS]`; `in[i]=17u+3u*i`; compile-time `PATTERN`, `WORDS`, `OUT_WORDS`, `STRIDE`; pointer sizes `4*WORDS` and `4*OUT_WORDS` bytes | Check every output and preservation of input, except intentional T03/T06 writes; success line `MICRO CHECK PASS` |
| PolyBench GEMM | ZIP tree `Polybench_modified/PolyBenchC_AXI/linear-algebra/blas/gemm/`; `.c`, `.h`, `tb_gemm.c`, common `utilities/polybench.c` and `.h`; MINI float; NI=20, NJ=25, NK=30; A[20][30], B[30][25], C[20][25] | Existing harness and MDPI C-model comparison; `--max-ulp=1`; 1 Bambu channel |
| PolyBench ATAX | Same ZIP tree under `linear-algebra/kernels/atax/`; MINI float; M=38, N=42; A[38][42], x[42], y[42], tmp[38] | Existing harness and MDPI comparison; `--max-ulp=1`; 2 Bambu channels |
| MachSuite SpMV | ZIP tree `MachSuite_modified/MachSuite/spmv/crs_axi/`; `.cpp`, `.hpp`, `local_support.cpp`, common support/harness; section-delimited textual `input.data` and `check.data`; N=494, NNZ=1666 | Double `val[1666]`, int32 `cols[1666]`, int32 `rowDelimiters[495]`, double `vec[494]`, double `out[494]`; harness success marker `Success.` |
| SpMV sections | Input sections introduced by `%%`: values, columns, row delimiters, dense vector; output/check section: 494 double output values | Harness zero-initializes its argument structure before parsing; no runner data transformation |
| MachSuite BFS | ZIP tree `MachSuite_modified/MachSuite/bfs_parallel/queue_axi/`; `data/scale4/input.data` and `check.data`; `SCALE=4`, header default `EDGE_FACTOR=4`, `THREAD_NUMBER=1`, `N_LEVELS=7`; 16 nodes, 64 edges, starting node 12 | Input sections: one uint32 root, 32 uint32 edge-range entries, 64 uint32 destination entries; nodes store begin/end pairs; levels int8 initialized to `INT8_MAX`; horizon counts uint32[7] |
| BFS reference | Textual check section contains `{1,4,9,1,0,0,0}` | Harness compares 7 horizon counts; runner also requires SHA-256 equality of `output.data` and supplied `check.data`; source comments say uint64 but parser/types use uint32 |
| GEMM initialization | Float alpha=1.5, beta=1.2; C[i][j]=float((i*j+1)%NI)/NI; A[i][j]=float((i*(j+1))%NK)/NK; B[i][j]=float((i*(j+2))%NJ)/NJ | Use supplied `tb_gemm.c` unchanged |
| ATAX initialization | x[i]=1+i/float(N); A[i][j]=float((i+j)%N)/(5*M) | Use supplied `tb_atax.c` unchanged; no normalization, resampling or input filtering in the runner |
| Author-equivalent datasets | Original authors' exact inputs, revisions, floating-point options and graph preprocessing | [TO BE VERIFIED] |

- **Logic / Model / Algorithms**

| Component | Implemented behavior / constraint |
|---|---|
| Launch | `run_tests.sh` defaults to `--smoke`, board `xcu250`; sources ignored `env.sh` when `BAMBU_HLS` or `RAMULATOR2_DIR` is missing; validates board before optional tmux launch |
| Pipeline | Stage C/C++ and inputs → Bambu/Clang HLS → RTL → Verilator testbench/AXI bridge → DPI-C/shared-memory IPC → MDPI driver → Ramulator timing and callbacks |
| Common Bambu flags | `--simulate --simulator=VERILATOR --compiler=I386_CLANG13 -m32 --generate-interface=INFER --memory-allocation-policy=NO_BRAM --enable-ramulator-integrated --output-directory=output -v5` |
| Per-case flags | Device/period from board profile or clock override; `--max-sim-cycles` plus recipe flags; exact command saved in `inputs.json` and `bambu_flags.json` |
| Smoke channel/limit | `MEM_ACC_11`, 1 Bambu channel; 100000 accelerator cycles |
| Micro flags/limit | GNU11, `-fno-tree-vectorize`, `--bus-pipelined`; 10000000 cycles; testbench queue 64 for T05, 20 otherwise |
| PolyBench flags | `-DMINI_DATASET -DDATA_TYPE_IS_FLOAT -DPOLYBENCH_USE_RESTRICT --std=gnu11 -fno-delete-null-pointer-checks -p=__float,expf --hls-fpdiv=SRT4U --max-ulp=1 --tb-queue-size=20 -s --bus-pipelined` |
| MachSuite flags | GNU++11, `-fno-tree-vectorize -fno-delete-null-pointer-checks --hls-div=NR --tb-queue-size=4 --channels-type=MEM_ACC_11 --channels-number=1 --bus-pipelined`; BFS also `-DSCALE=4 -DTHREAD_NUMBER=1 -fopenmp` |
| Benchmark cycle limit | PolyBench/MachSuite default 200000000 cycles |
| Time limit | `CASE_TIMEOUT_S` defaults to 2700 seconds/case; positive integer required; timeout sends TERM then KILL to that case's process group |
| Isolation | Sequential case loop; private work directory, `TMPDIR`, `BAMBU_IPC_FILENAME`, and new process session per case; workspace paths must contain no whitespace |
| Environment cleanup | Clear inherited `OUT_LVL`, `BAMBU_IPC_SIM_CMD`, `RAMULATOR_OVERRIDE_CHANNELS`; augment loader/include paths from selected Ramulator tree |
| Clock override | `CLOCK_PERIOD_NS` must be a positive decimal; replaces board period; `--config` changes memory YAML only |
| Dry run | Requires tool preflight; stages snapshots and commands; no synthesis/simulation, no board dataset measurement rows; successful plans leave a header-only local summary |
| Integration version | Current runner targets the older Ramulator 2.0 fork; vault 2.1 Python bindings, generated DRAM definitions, gem5 wrappers, Ayna and trace plugins are separate reference material; compatibility: [TO BE VERIFIED] |

| Board profile (`configs/boards.json`) | Bambu device string | Default period | Memory YAML | Declared status |
|---|---|---|---|---|
| `xcu250` | `xcu250-2Lfigd2104` | 5.0 ns | `configs/xcu250_ddr4_2400R.yaml` | stable |
| `xcu280` | `xcu280-2Lfsvh2892` | 4.0 ns | `configs/xcu280_hbm2.yaml` | experimental |
| `xcu55c` | `xcu55c-2Lfsvh2892` | 3.33 ns | `configs/xcu280_hbm2.yaml` | experimental; shared HBM2 model for HBM2e target |

| YAML basename in `configs/` | DRAM / organization / timing | Channels / ranks | Ticks per accelerator cycle | Row policy |
|---|---|---|---|---|
| `default_ddr4.yaml` | DDR4 / `DDR4_8Gb_x8` / `DDR4_2400R` | 1 / 1 | 3 | `ClosedRowPolicy`, cap 4 |
| `xcu250_ddr4_2400R.yaml` | DDR4 / `DDR4_16Gb_x8` / `DDR4_2400R` | 4 / 1 | 6 | `ClosedRowPolicy`, cap 4 |
| `xcu250_ddr4_2400R_1ch.yaml` | DDR4 / `DDR4_16Gb_x8` / `DDR4_2400R` | 1 / 1 | 6 | `ClosedRowPolicy`, cap 4 |
| `xcu250_ddr3_1600K.yaml` | DDR3 / `DDR3_8Gb_x8` / `DDR3_1600K` | 4 / 2 | 6 | `ClosedRowPolicy`, cap 4 |
| `xcu250_ddr5_3200C.yaml` | DDR5 / `DDR5_16Gb_x8` / `DDR5_3200C` | 4 / 1 | 6 | `ClosedRowPolicy`, cap 4 |
| `xcu280_hbm2.yaml` | HBM2 / `HBM2_4Gb` / `HBM2_2Gbps` | 32 / explicit rank absent: [TO BE VERIFIED] | 5 | `OpenRowPolicy` |

- All checked-in YAMLs: frontend `GEM5`, memory system `GenericDRAM`, controller `Generic`, scheduler `FRFCFS`, refresh manager `AllBank`, address mapper `RoBaRaCoCh`.
- Recorded DDR4-2400R parameters: nCL=16, nRCD=16, nRP=16, nRAS=39, nRC=55, nBL=4, tCK≈833 ps; effective runtime values require the selected library/preset: [TO BE VERIFIED].
- `--channels-number` selects the Bambu interface configuration; physical DRAM channel count comes from YAML.
- Current T09 variants change Bambu channels and use the same board YAML unless explicitly overridden; historical saved T09 runs changed per-case physical YAML topology.
- DDR3 diagnostic is an expected setup failure on the pinned fork: `ClosedRowPolicy` queries missing `bankgroup`; retain `ERROR`.
- HBM2 `OpenRowPolicy` avoids a rank lookup; recorded `AllBank` refresh code iterates ranks while HBM2 exposes pseudochannels; smoke success does not validate refresh/timing.
- DDR5 diagnostic is a compatibility probe; verified timing calibration: [TO BE VERIFIED].

| Micro case | PATTERN / WORDS / OUT_WORDS / STRIDE | Operation |
|---|---|---|
| `t01_clock` | 1 / 2 / 1 / 1 | Two reads around 1000 dependent XOR/multiply iterations; loop iterations are not a fixed 1000-cycle RTL window |
| `t02_single_read` | 2 / 1 / 1 / 1 | Copy one input word |
| `t03_read_after_write` | 3 / 2 / 1 / 1 | Store `in[0] XOR 0x12345678` into `in[1]`, then read back |
| `t04_stream` | 4 / 512 / 512 / 1 | Sequential `out[i]=in[i] XOR 0x55aa55aa` |
| `t05_queue_pressure` | 5 / 4096 / 4096 / 1 | Gather `in[(73*i)&(WORDS-1)] + i`; power-of-two WORDS; oracle uses modulo |
| `t06_byte_lanes` | 6 / 2 / 1 / 1 | Byte writes 0x11, 0x22, 0x33, 0x44; little-endian word 0x44332211; guard word preserved |
| `t07_row_local` | 7 / 32769 / 1 / 1 | 1024 alternating loads at offsets 0 and 1 word |
| `t07_row_stride` | 7 / 32769 / 1 / 32768 | Same sum with 128 KiB separation; mapped row/bank relation: [TO BE VERIFIED] |
| `t08_refresh_stream` | 8 / 32768 / 1 / 1 | Sequential checksum |
| `t09_channels_1`, `t09_channels_4` | 9 / 8192 / 1 / 16 | Same 64-byte-stride checksum; Bambu `MEM_ACC_11`/1 versus `MEM_ACC_NN`/4 |
| `t10_native_and_axi` | 10 / 512 / 512 / 1 | Native-bus input, AXI output; same XOR transform as T04 |

| Protocol contract / diagnostic | Required implementation evidence |
|---|---|
| AXI transfers | AW/W/AR/R/B independently transfer on a rising edge with VALID and READY; hold VALID/payload stable during backpressure |
| Ordering | Preserve read-response order within an ARID and write-response order within an AWID; check distinct-ID out-of-order responses separately |
| Bursts | Address/beat counts, byte strobes, final RLAST/WLAST; AW/W may arrive independently |
| Backend rejection | Queue/stall/retry a rejected request; exactly one accepted timing event and no lost/duplicate callbacks |
| Read visibility | Driver samples backing-store bytes at read timing callback; retain returned data/tag until AXI consumption |
| Write visibility | Shared backing store and timing event are separate; BVALID may precede DRAM completion after AW/final W acceptance and data update; accepted-write counter does not prove DRAM commit |
| Clock advance | One coordinated Ramulator instance per DUT in documented integration; count actual ticks, including idle catch-up; inspect `m_state()`/`ramulator_memory_system->tick()` for duplicate advancement |
| Coverage limit | Current C fixtures do not force arbitrary IDs, RREADY/BREADY stalls, AW/W skew, queue rejection, exact cycle windows or refresh commands; generated-RTL/protocol coverage: [TO BE VERIFIED] |

| Recorded failed attempt / repair boundary | Debugging constraint |
|---|---|
| Bare `int*` smoke mapping | Historical allocation defaulted to 4 bytes; explicitly map each eight-int pointer to 32 bytes |
| Generated PolyBench RTL | Historical 16 zero-width dummy-tag cases and 6 fict-name cases; recorded wrapper-only repair rejected connected-tag/incompatible-width interfaces; exact local replay patches: [TO BE VERIFIED] |
| Fixed-delay disabling | Historical `MDPI_DISABLE_RAMULATOR=1` was unsupported; fixed baseline compiled without a valid `RAMULATOR2_DIR`; this repository currently enables Ramulator in every simulation case |
| Result parsing | Use completed `output/bambu_results.xml`, not obsolete `results.txt`; retain parser/setup failures separately from numerical mismatches |
| Canonical-DUT replay | Retain generated `.mem` files and complete asset manifests; five historical fixed replays failed with missing initialization assets |
| Large BFS stall | Historical scale-15 configuration differed from current scale-4 BFS; advancing simulation clock with stalled memory counters did not establish the precise cause: [TO BE VERIFIED] |
| Optional Bambu unit target | Boost 1.71/C++20 wide-string streaming failure; production workaround omitted `libbambu_unit`; isolated repaired tests reported 65/65 tests and 3462/3462 assertions; patches absent here: [TO BE VERIFIED] |

- Historical controlled comparison, outside the current 17-case runner: 13 PolyBench + 3 MachSuite + (2 GAPBS kernels × 4 core/thread combinations) = 24 workload configurations; each uses Ramulator, fixed 2/2 and fixed 8/8 read/write delays, 72 reported cases.
- Historical control method: freeze source/input/HLS/config hashes; retain 24 verified Ramulator DUTs; replay 48 fixed cases with byte-identical corresponding HDL and initialization assets; preserve all attempts; exact author equivalence: [TO BE VERIFIED].
- Historical GAPBS graph: 8192 vertices; vertex file 8194 uint32 words including header and CSR offsets; edge file 98231 uint32 words including header and 98230 adjacency entries; `MAX_VERTEX_NUMBER=8196` is capacity. No GAPBS recipe exists in this runner.
- Hardware deployment is external to this repository; matched bitstream, XRT host, platform, achieved clock and physical start/done measurements: [TO BE VERIFIED].
- Vault U55C example only: single AXI or two-bank HBM[0]/HBM[1], 256-byte stripes; byte-offset mapping `bank=floor(x/256) mod 2`, `local=floor(x/512)*256+(x mod 256)`; single address relocation `physical=base_BO+(AXI_address-0x40000000)`; banked relocation subtracts `0x20000000` after Bambu removes the bank-select bit.
- Vault U55C control wrapper only: user-managed `xrt::ip`; 0x00 busy bit 0 / sticky done bit 1 and start-write bit 0; 0x10 element count; 0x20/0x24 BO0 low/high base; 0x28/0x2c BO1 low/high base. This control map is not a checked-in test-suite interface.

- **Metrics and Output**

| Metric | Exact calculation / acceptance |
|---|---|
| Accelerator cycles C | Sum all decimal integer `<run>` values under XML `./timing/simulation`; nonempty complete run list and integer `return_value` required |
| Host wall time | `time.monotonic()` after Bambu completion minus the value immediately before launch; formatted to 3 decimal places; canonical `execution_time_s` equals local `wall_time_s` |
| Requested frequency | `frequency_mhz = 1000 / clock_period_ns`; formatted `.12g`; requested HLS clock, not measured FPGA frequency |
| Simulated duration | `time_ns = C * clock_period_ns = C * 1000 / frequency_mhz`; sum across XML executions when C is summed |
| Modeled tick rate | `f_DRAM_MHz = configured_ratio * f_accelerator_MHz`; default 5 ns/ratio 6 → 1200 MHz; historical 10 ns/ratio 3 → 300 MHz |
| Clock reconciliation | For N coordinated accelerator cycles after idle catch-up: `expected_DRAM_ticks=N*configured_ratio`; log events and tick totals are distinct counters |
| Read acceptance count | Count log lines matching `Issued Ramulator2 read request tag \d+` or `Ramulator2 queued read tag \d+ resubmitted`; each matching line contributes 1 |
| Write acceptance count | Count log lines containing `Issued Ramulator2 write request for addr ` or `Ramulator2 queued write submitted for addr `; each matching line contributes 1 |
| Read completion count | Count lines containing `Ramulator2 read completion: tag=`; saved in case metadata |
| DRAM tick count | Sum integer captures from `Advanced Ramulator2 by (\d+) cycles`; saved as `logged_dram_ticks` |
| Functional markers | Micro requires exact stripped line `MICRO CHECK PASS`; MachSuite requires `Success.`; BFS additionally hashes reference/output |
| SpMV error predicate | For each i=0..493, `diff=out[i]-reference[i]`; fail if `(diff < -1e-6) OR (1e-6 < diff)`; harness uses this predicate without an explicit finite-value check |
| PolyBench tolerance | `--max-ulp=1`; exact comparator formula and special-value handling in the selected Bambu runtime: [TO BE VERIFIED] |
| Micro arithmetic | `uint32_t` XOR/add/multiply/checksum operations; compare exact words; T07 oracle `512*(initial(0)+initial(STRIDE))`; T08/T09 oracle `count*17 + 3*STRIDE*count*(count-1)/2`, `count=WORDS/STRIDE` |
| Cycle difference | Historical comparison: `100*(C_local-C_reference)/C_reference` percent; reference is the recorded rounded published count; no current runner implementation |
| Memory-model ratio | Historical comparison: `rho=C_Ramulator/C_fixed`; fixed 2c and 8c are separate denominators; no current runner implementation |
| Not collected by current parser | Per-request latency distributions, row events, refresh traces, bandwidth, power, hardware elapsed time; exact collection/formulas: [TO BE VERIFIED] |

| Status | Current `assess()` behavior |
|---|---|
| `PASS` | Bambu exit 0; XML return 0; C>0; no detected functional failure; Ramulator initialization and exact YAML path confirmed; at least one accepted read and completion; required harness/hash checks pass |
| `FAIL` | Functional mismatch markers; nonzero XML testbench return; absent accepted-read/completion evidence; missing harness marker; BFS byte mismatch |
| `ERROR` | Setup/staging/exception, timeout, incomplete XML, nonzero Bambu exit after earlier checks, zero cycles, missing initialization or mismatched YAML confirmation |
| Acceptance limits | No requirement for reads=completions, positive writes, positive tick count, calibrated latency, or a cycle threshold in current `assess()`; historical smoke acceptance was stricter |
| Process exit | Completed suite returns 1 if any case is FAIL/ERROR, otherwise 0; interruption returns 130 and retains partial evidence |

| Output artifact | Format / exact schema |
|---|---|
| `results/<board>.csv` | UTF-8 CSV; `timestamp,git_commit,board,benchmark,status,cycles,execution_time_s,dram_reads,dram_writes,frequency_mhz,tag` |
| Canonical row policy | Append each completed measurement, including failures; exclusive lock, header validation, flush/fsync; unavailable metrics empty; preflight failures/dry runs/maintenance add no measurement rows |
| `results/run_YYYYMMDD_HHMMSS_<tag>/` | UTC timestamp; numeric collision suffix; `results/latest` atomically points to newest started run |
| `summary.csv` | CSV: `board,test_name,status,total_sim_cycles,wall_time_s,dram_read_reqs,dram_write_reqs,yaml_config,log_file`; paths relative to run |
| `metadata.json` | JSON: host/user/OS, environment and loaded env-file hash, suite commit/status, tools, library hash/ELF/dependencies, baseline warnings/errors, board profile, runner/config hashes, case outcomes/reasons, completions/ticks, retention state |
| `config_snapshot/<case>/` | YAML bytes; `bambu_flags.json` argument array; `inputs.json` provenance/hashes/full argv/period; `inputs/` staged source/header/testbench/data files |
| `logs/<case>.log.gz` | Combined stdout/stderr and final status/reason; completed logs compressed; CSV log path updated |
| Optional copied artifacts | `logs/<case>.bambu_results.xml`, `<case>.bambu_time_simulation.txt`, `<case>.output.data`, when produced |
| Optional archive | `--archive LABEL`: `results/archive/<board>/run_<UTC>_<tag>/`; metadata/summary, flat config YAMLs and compressed logs; archive schema version 2; input hashes/arguments embedded in metadata |
| Work retention | PASS prunes compiled Verilator work/object/wave files after evidence saved; FAIL/ERROR keeps work; `--keep-work` protects it; cleanup skips active processes, protected runs and symlinks |
| Full-history export | `--export-dataset [path]`; default `results/dataset.csv`; read only compatible canonical board CSVs; exclude combined exports; never overwrite canonical history |
| Summary filtering | `--export-summary [path]`: PASS rows only, latest timestamp per `(board, benchmark)`, last append wins timestamp ties; absent timezone treated as UTC; newer failures do not replace a pass |
| Comparison grouping | `--compare-test NAME` uses the same latest-PASS rule; tags, YAML, clocks and input hashes are not grouping keys; match those explicitly for controlled comparisons |
| Calibration filtering | Select PASS rows with required metrics/features; match input/source hashes and start/done window; physical transfer/measurement settings: [TO BE VERIFIED] |

- Saved evidence only: 10 November smoke PASS, 119 cycles, and 12 micro PASS rows use earlier configurations; current-equivalent reruns: [TO BE VERIFIED].
- Saved canonical board history: 11 November xcu250 smoke ERROR with missing completed XML; underlying failure log is absent locally, so cause: [TO BE VERIFIED].
- Saved canonical board history: 11 November xcu280 smoke PASS, 68 cycles, 16 reads, 8 writes, 19.464 host seconds, requested 250 MHz; timing/refresh calibration: [TO BE VERIFIED].

- **Inconsistencies detected in the vault**

- **AXI handshakes:** notebook page 2 says channels have different handshakes; `Concepts/axi-memory-transactions.md` and `Topics/Bambu and Ramulator Source Conflicts.md` specify the same independent VALID/READY transfer rule. Earlier wording is recorded as corrected; any generated-RTL violation: [TO BE VERIFIED].
- **Response ordering:** earlier notebook/transcription describes out-of-order responses without ID qualification; corrected notes require same-ID order. Actual generated bridge coverage: [TO BE VERIFIED].
- **Write response:** historical verification treated B acknowledgment before DRAM completion as a fault; corrected architecture notes allow acknowledgment after AXI acceptance/backing-store update while timing is pending. Actual local AW/W/B and backing-store trace: [TO BE VERIFIED].
- **Clock units:** notebook page 12 multiplies “Ramulator cycles” by 5/10 ns; corrected protocol distinguishes accelerator cycles from DRAM ticks. The counter/domain intended by that original wording: [TO BE VERIFIED]. The 10 ns/ratio-3 smoke is a recorded 300 MHz model, distinct from the 5 ns/ratio-6, approximately 1.2 GHz benchmark.
- **Graph counts:** protocol/source-conflict notes retain 8192 vertices and approximately 130000 edges in the reference description versus 98230 local adjacency entries. Exact graph bytes, counting convention, seed and preprocessing equivalence: [TO BE VERIFIED].
- **Synthesizability evidence:** notebook page 9 treats functional tests as sufficient; deployment notes record separate synthesis requirements and a `MinimalAXI4Adapter` synthesis failure. Target-specific synthesis/P&R/achieved timing must have separate evidence; current hardware result: [TO BE VERIFIED].
- **Board timing equivalence:** `Domande.md` asserts U280 and U250 HLS logic timing is 100% identical; protocol uses a specific U250 device while deployment examples target other parts. Validity of substituting device timing libraries: [TO BE VERIFIED].
- **Tool/platform contexts:** 9 November meeting records VCU128/HBM with Vitis/Vivado 2023.2; Bambu-Vitis guides specify U55C/HBM with 2026.1; benchmark protocol uses U250/DDR4. These are distinct recorded flows; actual target, tool version and address/control adaptation for the next hardware run: [TO BE VERIFIED].
- **Performance claims:** meeting notes record 25x slowdown and an unqualified “around 100”; earlier meeting records 25–30x. Workload, input, denominator, units and measurement window needed to reconcile them: [TO BE VERIFIED].
- **Buffer/cache claim:** notebook page 11 associates uniform-random traffic with one-buffer versus multiple-cache performance; benchmark note has no identified matching plot/configuration. Metric, test and claimed relationship: [TO BE VERIFIED].
- **Repository documentation discrepancy:** current README board table spells U250 `xcu250-figd2104-2L-e`; `configs/boards.json` and vault protocol specify `xcu250-2Lfigd2104`. Supported spelling for the installed Bambu technology library: [TO BE VERIFIED].
- **Verification state drift:** vault marks T01–T10 as proposed; repository contains C fixtures and saved functional passes with related names. Full protocol/timing acceptance criteria remain unverified; map each fixture to actual generated stimulus before crediting coverage.
- **Version boundary:** vault 2.1 guide provenance lacks upstream commit/capture date, while server notes pin the 2.0 fork. API/controller compatibility with this repository: [TO BE VERIFIED]; separate examples are not evidence of a completed migration.
