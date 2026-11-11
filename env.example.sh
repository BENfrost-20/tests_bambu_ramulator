#!/usr/bin/env bash
# Copy to env.sh and replace the example paths with the installed tool locations.
# run_tests.sh loads env.sh when BAMBU_HLS or RAMULATOR2_DIR is missing.

export BAMBU_HLS="/path/to/bambu/install"
export RAMULATOR2_DIR="/path/to/Ramulator-no-spdlog"

# These bin directories must provide clang-19, clang-13 and the matching LLVM tools.
# Include the installed Verilator bin directory if it is outside the system PATH.
export PATH="/path/to/clang-19/bin:/path/to/clang-13/bin:/path/to/verilator/bin:${BAMBU_HLS}/bin:${PATH:-/usr/bin:/bin}"
export BAMBU_HLS_BACKEND_PATH="${BAMBU_HLS}/bin:${PATH}"

# Add any account-local host runtime library directory here if the installation needs it.
export LD_LIBRARY_PATH="${RAMULATOR2_DIR}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CPLUS_INCLUDE_PATH="${RAMULATOR2_DIR}/ext/yaml-cpp/include:${RAMULATOR2_DIR}/ext/argparse/include${CPLUS_INCLUDE_PATH:+:$CPLUS_INCLUDE_PATH}"
