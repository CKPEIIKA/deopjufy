#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
STATUS=0

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is required" >&2; exit 127; }

run_check() {
  local label="$1"
  shift
  echo "== $label =="
  if "$@"; then
    echo "[ok] $label"
  else
    local exit_code=$?
    echo "[fail:$exit_code] $label" >&2
    STATUS=1
  fi
  echo
}

run_check "Ruff" uv run ruff check .
run_check "Ruff format" uv run ruff format --check .
run_check "Ty" uv run ty check deopjufier --exclude refs/
run_check "Pytest + coverage" env DEOPJUFIER_TEST_TIMEOUT_SECONDS="${DEOPJUFIER_TEST_TIMEOUT_SECONDS:-45}" PYTEST_WORKERS="${PYTEST_WORKERS:-2}" PYTEST_DIST="${PYTEST_DIST:-worksteal}" bash scripts/test.sh --cov=deopjufier --cov-branch --cov-report=term-missing --cov-fail-under="${COV_FAIL_UNDER:-100}" --cov-omit=refs/'*'

exit "$STATUS"
