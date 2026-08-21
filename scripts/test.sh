#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
WORKERS="${PYTEST_WORKERS:-2}"
DIST_MODE="${PYTEST_DIST:-worksteal}"
BASE_TEMP=".pytest_cache/test-tmp"

case "$WORKERS" in
  ''|*[!0-9]*)
    echo "ERROR: PYTEST_WORKERS must be a non-negative integer" >&2
    exit 2
    ;;
esac

cleanup() {
  python3 -c 'import shutil; shutil.rmtree(".pytest_cache/test-tmp", ignore_errors=True)'
}

trap cleanup EXIT HUP INT TERM
cleanup
mkdir -p "$(dirname "$BASE_TEMP")"

PYTEST_ARGS=(--basetemp="$BASE_TEMP")
if (( WORKERS > 1 )); then
  PYTEST_ARGS+=(-n "$WORKERS" --dist "$DIST_MODE")
fi

uv run pytest "${PYTEST_ARGS[@]}" "$@"
