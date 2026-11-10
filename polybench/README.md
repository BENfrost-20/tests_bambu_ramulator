# PolyBench/C

The runner stages GEMM and ATAX from the `PolyBenchC_AXI` tree in the supplied
`Archive 2/Polybench_modified.zip`. It uses their original harnesses and common
utilities with MINI float data and the generated MDPI C-model comparison at
1 ULP. GEMM uses one Bambu memory channel and ATAX uses two.
Set `BENCHMARK_ARCHIVES` to the directory containing the ZIPs if they have been moved.
