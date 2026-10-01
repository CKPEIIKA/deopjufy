"""Contract tests for the read-only file mapping boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from deopjufier.io import open_mmap


def test_open_mmap_yields_mapping_for_regular_file(tmp_path: Path) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"abc")

    with open_mmap(sample) as mapped:
        assert mapped is not None
        assert mapped[:] == b"abc"


def test_open_mmap_yields_none_for_empty_file(tmp_path: Path) -> None:
    sample = tmp_path / "empty.bin"
    sample.write_bytes(b"")

    with open_mmap(sample) as mapped:
        assert mapped is None


def test_open_mmap_propagates_caller_os_errors(tmp_path: Path) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"abc")

    with pytest.raises(BrokenPipeError), open_mmap(sample):
        raise BrokenPipeError
