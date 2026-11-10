#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: run_tests.sh [--smoke | --all | --suite NAME | --clean]
                    [--config PATH] [--tag LABEL] [--dry-run]
Suites: smoke, micro, polybench, machsuite, diagnostic
Default: --smoke. --all runs the four regular suites.
--clean removes work directories from finished runs and preserves evidence.
HELP
}

die() { printf '%s\n' "$*" >&2; exit 2; }
suite=""
config=""
tag=""
dry_run=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --smoke|--all|--clean)
            [[ -z "$suite" ]] || die "Choose one suite or --clean."
            suite="${1#--}"
            shift
            ;;
        --suite|--config|--tag)
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
                --tag) tag="$2" ;;
            esac
            shift 2
            ;;
        --dry-run) dry_run=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

suite="${suite:-smoke}"
tag="${tag:-$suite}"
[[ "$tag" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]] || die "Invalid tag (use 1–64 letters, digits, dots, underscores or hyphens)."
[[ "$suite" != clean || -z "$config" ]] || die "--clean does not take --config."
command -v python3 >/dev/null || die "python3 is required."
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$root/runner.py" "$suite" "$tag" "$config" "$dry_run"
