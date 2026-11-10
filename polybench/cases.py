"""Recipes for the supplied modified PolyBench/C archive."""

ROOT = "Polybench_modified/PolyBenchC_AXI"
ARCHIVE = "Polybench_modified.zip"


def cases():
    for name, category, channels in (("gemm", "blas", 1), ("atax", "kernels", 2)):
        kernel = f"{ROOT}/linear-algebra/{category}/{name}"
        utils = f"{ROOT}/utilities"
        sources = [f"{kernel}/{name}.{ext}" for ext in ("c", "h")]
        sources += [f"{kernel}/tb_{name}.c", f"{utils}/polybench.c", f"{utils}/polybench.h"]
        yield {
            "name": f"polybench_{name}",
            "archive": ARCHIVE,
            "members": sources,
            "flags": [
                f"--top-fname=kernel_{name}", f"--generate-tb=@/{kernel}/tb_{name}.c",
                f"-I@/{utils}", f"@/{utils}/polybench.c", f"@/{kernel}/{name}.c",
                "-DMINI_DATASET", "-DDATA_TYPE_IS_FLOAT", "-DPOLYBENCH_USE_RESTRICT",
                "--std=gnu11", "-fno-delete-null-pointer-checks", "-p=__float,expf",
                "--hls-fpdiv=SRT4U", "--max-ulp=1", "--tb-queue-size=20", "-s",
                f"--channels-type={'MEM_ACC_11' if channels == 1 else 'MEM_ACC_NN'}",
                f"--channels-number={channels}", "--bus-pipelined",
            ],
        }
