"""Repository structure conventions used as non-functional guardrails."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FILE_LINE_LIMIT = 1000
PYTHON_FILE_LIMIT = 8
ROOT_PATHS = (PROJECT_ROOT / "deopjufier", PROJECT_ROOT / "tests")


def _iter_python_files() -> list[Path]:
    python_files: list[Path] = []
    for root in ROOT_PATHS:
        for path in root.rglob("*.py"):
            if any(part.startswith(".") for part in path.parts):
                continue
            python_files.append(path)
    return sorted(python_files)


def _iter_python_directories() -> list[Path]:
    python_dirs: list[Path] = []
    for root in ROOT_PATHS:
        for path in root.rglob("*"):
            if not path.is_dir():
                continue
            if any(part.startswith(".") for part in path.parts):
                continue
            if not any(path.glob("*.py")):
                continue
            python_dirs.append(path)
    return sorted(python_dirs)


def test_python_file_line_count_stays_manageable() -> None:
    long_files: list[tuple[str, int]] = []
    for path in _iter_python_files():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > FILE_LINE_LIMIT:
            long_files.append((str(path.relative_to(PROJECT_ROOT)), line_count))
    assert not long_files, f"python files exceed {FILE_LINE_LIMIT} lines: {long_files}"


def test_python_directory_file_cap_keeps_modules_manageable() -> None:
    oversized: list[tuple[str, int]] = []
    for directory in _iter_python_directories():
        count = sum(1 for path in directory.glob("*.py") if path.is_file())
        if count > PYTHON_FILE_LIMIT:
            oversized.append((str(directory.relative_to(PROJECT_ROOT)), count))
    assert not oversized, f"directories exceed {PYTHON_FILE_LIMIT} python files: {oversized}"
