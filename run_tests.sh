#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: run_tests.sh [--smoke | --all | --suite NAME | --clean]
                    [--board NAME] [--config PATH] [--tag LABEL] [--archive LABEL]
                    [--dry-run] [--tmux] [--keep-work]
       run_tests.sh --clean-work [--older-than-days N] [--dry-run]
       run_tests.sh --list-boards
       run_tests.sh --export-dataset [output.csv]
       run_tests.sh --export-summary [output.csv]
       run_tests.sh --compare-test TEST_NAME
       run_tests.sh --untrack-runs
       run_tests.sh --check-baseline
Suites: smoke, micro, polybench, machsuite, diagnostic
Default: --smoke. --all runs the four regular suites.
--clean removes finished PASS work with saved evidence.
--keep-work preserves work directories for manual inspection.
--tmux starts a detached session, or runs inline from an existing tmux pane.
Completed tests append to results/<board>.csv; detailed run evidence stays local.
--archive publishes an additional local evidence snapshot.
--export-dataset exports all history; --export-summary selects latest PASS per board/test.
--untrack-runs stages Git removal of old run folders without deleting local files.
HELP
}

die() { printf '%s\n' "$*" >&2; exit 2; }

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
case "${1:-}" in
    --check-baseline|--list-boards|--export-dataset|--export-summary|--compare-test|--clean-work|--untrack-runs)
        case "$1" in
            --check-baseline|--list-boards|--untrack-runs)
                [[ $# -eq 1 ]] || die "$1 does not take arguments."
                ;;
            --export-dataset|--export-summary)
                [[ $# -le 2 && "${2:-}" != --* ]] || die "$1 takes at most one output path."
                ;;
            --compare-test)
                [[ $# -eq 2 && -n "$2" && "$2" != --* ]] || die "--compare-test requires one test name."
                ;;
            --clean-work) ;; # The Python maintenance parser validates its options.
        esac
        command -v python3 >/dev/null || die "python3 is required."
        exec python3 "$root/runner.py" "$@"
        ;;
esac

run_in_tmux() {
    local session="bambu_test_${board}_${tag//./_}"
    local snapshot
    snapshot="$(mktemp "${TMPDIR:-/tmp}/bambu-tmux-env.XXXXXXXX")"
    trap 'rm -f -- "$snapshot"' EXIT
    # A running tmux server may have an older environment. Keep exports and
    # arguments in a private file, separated by an empty NUL-delimited field.
    {
        printf '%s\0' "$root/run_tests.sh" "$@"
        printf '\0'
        /usr/bin/env -0
    } > "$snapshot"
    if ! tmux new-session -d -s "$session" -c "$PWD" -- \
        "$(command -v python3)" -I -c '
import os
import sys

snapshot = sys.argv[1]
with open(snapshot, "rb") as stream:
    command, exports = stream.read().split(b"\0\0", 1)
os.unlink(snapshot)
script, *args = command.split(b"\0")
env = dict(entry.split(b"=", 1) for entry in exports.split(b"\0") if entry)
for name in (b"TMUX", b"TMUX_PANE", b"TERM"):
    if name in os.environb:
        env[name] = os.environb[name]
os.execve(script, [script, *(arg for arg in args if arg != b"--tmux")], env)
' "$snapshot"; then
        die "Could not start tmux session $session. If the name is in use, choose a different --tag."
    fi
    trap - EXIT
    printf 'Started detached tmux session %s\n' "$session"
    printf 'Attach: tmux attach -t %s\n' "$session"
    printf 'Live summary (from %s): watch -n 2 cat results/latest/summary.csv\n' "$root"
    printf 'Stop: tmux kill-session -t =%s\n' "$session"
}

original_args=("$@")
suite=""
board="xcu250"
config=""
tag=""
archive=""
dry_run=0
detach=0
keep_work=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --smoke|--all|--clean)
            [[ -z "$suite" ]] || die "Choose one suite or --clean."
            suite="${1#--}"
            shift
            ;;
        --suite|--board|--config|--tag|--archive)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "$1 requires a value."
            case "$1" in
                --suite)
                    [[ -z "$suite" ]] || die "Choose one suite or --clean."
                    case "$2" in
                        smoke|micro|polybench|machsuite|diagnostic) suite="$2" ;;
                        *) die "Unknown suite: $2" ;;
                    esac
                    ;;
                --config) config="$2" ;;
                --board) board="$2" ;;
                --tag) tag="$2" ;;
                --archive) archive="$2" ;;
            esac
            shift 2
            ;;
        --dry-run) dry_run=1; shift ;;
        --tmux) detach=1; shift ;;
        --keep-work) keep_work=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

suite="${suite:-smoke}"
tag="${tag:-${archive:-$suite}}"
[[ "$tag" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]] || die "Invalid tag (use 1–64 letters, digits, dots, underscores or hyphens)."
if [[ -n "$archive" ]]; then
    [[ "$archive" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]] || die "Invalid archive label (use the same format as --tag)."
    [[ "$suite" != clean && "$dry_run" -eq 0 ]] || die "--archive requires a simulation suite without --dry-run."
fi
[[ "$suite" != clean || -z "$config" ]] || die "--clean does not take --config."
if [[ "$suite" != clean ]]; then
    if [[ -z "${BAMBU_HLS:-}" || -z "${RAMULATOR2_DIR:-}" ]]; then
        if [[ -f "$root/env.sh" ]]; then
            set -a
            source "$root/env.sh"
            set +a
            IFS=$' \t\n'
            export BAMBU_LOCAL_ENV_FILE="$root/env.sh"
            printf '[INFO] Loaded environment from local env.sh\n'
        fi
        if [[ -z "${BAMBU_HLS:-}" || -z "${RAMULATOR2_DIR:-}" ]]; then
            printf '[INFO] Configure the required variables by copying env.example.sh to env.sh in %s.\n' "$root" >&2
        fi
    fi
fi
command -v python3 >/dev/null || die "python3 is required. Check PATH in env.example.sh."
# Validate the profile before creating a detached session.
python3 "$root/runner.py" --validate-board "$board"
if (( detach )); then
    if [[ -n "${TMUX:-}" ]]; then
        printf 'Already inside tmux. Running in this pane.\n'
    else
        command -v tmux >/dev/null || die "tmux is required for --tmux. Install it or run without --tmux."
        run_in_tmux "${original_args[@]}"
        exit 0
    fi
fi
exec python3 "$root/runner.py" "$suite" "$tag" "$config" "$dry_run" "$archive" "$board" "$keep_work"
