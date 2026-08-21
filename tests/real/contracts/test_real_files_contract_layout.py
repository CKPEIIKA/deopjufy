"""Layout sanity checks for real fixture and contract tests."""

from __future__ import annotations

from pathlib import Path


def test_real_fixture_python_layout_keeps_small_directory_fanout() -> None:
    """Keep real fixture/contract modules partitioned to avoid flat growth."""

    root = Path(__file__).resolve().parent.parent
    layouts = [root / "fixtures", root]
    max_files_per_dir = 8

    offenders: list[tuple[Path, int]] = []
    for base in layouts:
        for directory in base.rglob("*"):
            if not directory.is_dir():
                continue
            py_files = sorted(path for path in directory.iterdir() if path.suffix == ".py")
            if len(py_files) > max_files_per_dir:
                offenders.append((directory.relative_to(base), len(py_files)))

    offenders_sorted = sorted(offenders, key=lambda item: str(item[0]))
    normalized = [(str(directory), count) for directory, count in offenders_sorted]

    assert not offenders, f"Real tests python module directories exceeded {max_files_per_dir} files: {normalized!r}"
