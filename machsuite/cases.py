"""Recipes for the supplied modified MachSuite archive."""

ROOT = "MachSuite_modified/MachSuite"
ARCHIVE = "MachSuite_modified.zip"


def cases():
    for name, relative, macros in (
        ("spmv", "spmv/crs_axi", []),
        ("bfs", "bfs_parallel/queue_axi", ["-DSCALE=4", "-DTHREAD_NUMBER=1", "-fopenmp"]),
    ):
        kernel = f"{ROOT}/{relative}"
        common = f"{ROOT}/common"
        data = f"{kernel}/data/scale4" if name == "bfs" else kernel
        check_file = f"{data}/check.data"
        yield {
            "name": f"machsuite_{name}",
            "archive": ARCHIVE,
            "members": [
                f"{kernel}/{name}.cpp", f"{kernel}/{name}.hpp", f"{kernel}/local_support.cpp",
                *(f"{common}/{filename}" for filename in ("support.hpp", "support.cpp", "harness.cpp")),
                f"{data}/input.data", check_file,
            ],
            "flags": [
                f"--top-fname={name}", f"-I@/{common}", f"@/{kernel}/{name}.cpp",
                f"--generate-tb=@/{kernel}/local_support.cpp",
                f"--generate-tb=@/{common}/harness.cpp", f"--generate-tb=@/{common}/support.cpp",
                f"--tb-arg=@/{data}/input.data", f"--tb-arg=@/{check_file}",
                "--std=gnu++11", "-fno-tree-vectorize", "-fno-delete-null-pointer-checks",
                "--hls-div=NR", "--tb-queue-size=4", "--channels-type=MEM_ACC_11",
                "--channels-number=1", "--bus-pipelined", *macros,
            ],
            "marker": "Success.",
            "byte_check": check_file if name == "bfs" else None,
        }
