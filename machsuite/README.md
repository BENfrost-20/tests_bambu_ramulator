# MachSuite

The runner stages the modified AXI SpMV/CRS and scale-4 BFS cases from the
supplied `Archive 2/MachSuite_modified.zip`. It uses the original kernel,
harness, `input.data` and `check.data`. SpMV compares the output vector to
within 1e-6. The BFS harness checks horizon counts, and the runner also compares
its `output.data` to the supplied reference byte for byte.
Set `BENCHMARK_ARCHIVES` to the directory containing the ZIPs if they have been moved.
