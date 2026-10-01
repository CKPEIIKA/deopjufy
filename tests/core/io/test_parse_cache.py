"""Per-command memo scope for file-derived results."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from deopjufier.io.parse_cache import file_key, memoized, parse_cache_scope


def _counter() -> tuple[dict[str, int], Callable[[], int]]:
    calls = {"count": 0}

    def compute() -> int:
        calls["count"] += 1
        return calls["count"]

    return calls, compute


def test_results_are_memoized_inside_a_scope(tmp_path: Path) -> None:
    sample = tmp_path / "a.bin"
    sample.write_bytes(b"x")
    calls, compute = _counter()

    with parse_cache_scope():
        assert memoized("test", file_key(sample), compute) == 1
        assert memoized("test", file_key(sample), compute) == 1

    assert calls["count"] == 1


def test_nothing_is_memoized_outside_or_across_scopes(tmp_path: Path) -> None:
    sample = tmp_path / "a.bin"
    sample.write_bytes(b"x")
    calls, compute = _counter()

    memoized("test", file_key(sample), compute)
    memoized("test", file_key(sample), compute)
    with parse_cache_scope():
        memoized("test", file_key(sample), compute)
    with parse_cache_scope():
        memoized("test", file_key(sample), compute)

    assert calls["count"] == 4


def test_file_key_changes_with_file_content(tmp_path: Path) -> None:
    sample = tmp_path / "a.bin"
    sample.write_bytes(b"x")
    before = file_key(sample, "param")
    sample.write_bytes(b"xy")

    assert file_key(sample, "param") != before
    assert file_key(tmp_path / "missing.bin") is None
