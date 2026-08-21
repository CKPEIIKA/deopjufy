UV ?= uv
SRC_DIR ?= deopjufier
COV_FAIL_UNDER ?= 100
COV_REPORT ?= term-missing
DEOPJUFIER_TEST_TIMEOUT_SECONDS ?= 45
PYTEST_WORKERS ?= 2
PYTEST_DIST ?= worksteal

.PHONY: venv sync lint format typecheck test test-serial coverage coverage-report coverage-gate check clean bench bench-slow refresh-opj-parity

venv:
	$(UV) venv

sync:
	$(UV) pip install -e ".[dev]"

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run ty check $(SRC_DIR) --exclude refs/

test:
	DEOPJUFIER_TEST_TIMEOUT_SECONDS=$(DEOPJUFIER_TEST_TIMEOUT_SECONDS) PYTEST_WORKERS=$(PYTEST_WORKERS) PYTEST_DIST=$(PYTEST_DIST) bash scripts/test.sh

test-serial:
	DEOPJUFIER_TEST_TIMEOUT_SECONDS=$(DEOPJUFIER_TEST_TIMEOUT_SECONDS) PYTEST_WORKERS=0 bash scripts/test.sh

coverage:
	DEOPJUFIER_TEST_TIMEOUT_SECONDS=$(DEOPJUFIER_TEST_TIMEOUT_SECONDS) PYTEST_WORKERS=$(PYTEST_WORKERS) PYTEST_DIST=$(PYTEST_DIST) bash scripts/test.sh --cov=deopjufier --cov-branch --cov-report=$(COV_REPORT) --cov-fail-under=$(COV_FAIL_UNDER) --cov-omit=refs/*

coverage-report:
	DEOPJUFIER_TEST_TIMEOUT_SECONDS=$(DEOPJUFIER_TEST_TIMEOUT_SECONDS) PYTEST_WORKERS=$(PYTEST_WORKERS) PYTEST_DIST=$(PYTEST_DIST) bash scripts/test.sh --cov=deopjufier --cov-branch --cov-report=term-missing --cov-report=html --cov-omit=refs/*

coverage-gate:
	DEOPJUFIER_TEST_TIMEOUT_SECONDS=$(DEOPJUFIER_TEST_TIMEOUT_SECONDS) PYTEST_WORKERS=$(PYTEST_WORKERS) PYTEST_DIST=$(PYTEST_DIST) bash scripts/test.sh --cov=deopjufier --cov-branch --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER) --cov-omit=refs/*

check:
	./scripts/quality.sh

bench:
	$(UV) run python tools/bench.py

bench-slow:
	$(UV) run python tools/bench.py --preset slow

refresh-opj-parity:
	$(UV) run python tools/refresh_opj_parity_fixtures.py


clean:
	python3 -c "import shutil; shutil.rmtree('.ruff_cache', ignore_errors=True); shutil.rmtree('.pytest_cache', ignore_errors=True)"
