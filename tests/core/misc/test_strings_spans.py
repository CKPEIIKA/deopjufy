"""Byte offsets reported for printable ASCII strings."""

from __future__ import annotations

from pathlib import Path

from deopjufier.strings import iter_ascii_string_spans


def test_ascii_spans_report_offsets_across_chunk_boundaries(tmp_path: Path) -> None:
    data = b"\x00\x00alpha\x01" + b"\x02" * 5 + b"bravo-charlie\x00tail"
    sample = tmp_path / "sample.bin"
    sample.write_bytes(data)

    spans = list(iter_ascii_string_spans(sample, min_length=4, chunk_size=7))

    assert spans == [(2, "alpha"), (13, "bravo-charlie"), (27, "tail")]
    assert all(data[offset : offset + len(text)].decode() == text for offset, text in spans)
    assert list(iter_ascii_string_spans(data, min_length=4)) == spans
