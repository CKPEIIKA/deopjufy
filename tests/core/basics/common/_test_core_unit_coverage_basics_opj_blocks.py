"""Split coverage for block scanning and low-level OPJ payload helpers."""

from __future__ import annotations

from pathlib import Path

from deopjufier.blocks import (
    ImageBlock,
    _dedupe,
    _find_bmp_payload_length,
    _find_gif_payload_length,
    _find_jpeg_length,
    _find_png_block,
    _find_png_length,
    _find_svg_blocks,
    _parse_pdf_payload_length,
    find_all_blocks,
    find_image_blocks,
)
from deopjufier.inventory import parse_opj_note_sections
from deopjufier.opj import is_opj_signature
from deopjufier.opj.records import _read_opj_payload, _read_opj_size, _skip_opj_payload


def test_find_all_blocks_filters_types(tmp_path: Path) -> None:
    sample = tmp_path / "types.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xae\x42\x60\x82\xff\xd8\xff\xd9")

    png_only = find_all_blocks(sample, types=["png"])
    assert png_only
    assert all(block.kind == "png" for block in png_only)


def test_find_all_blocks_rejects_unknown_filter_types(tmp_path: Path) -> None:
    sample = tmp_path / "types.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xae\x42\x60\x82")

    assert find_all_blocks(sample, types=["unknown"]) == []


def test_find_image_blocks_includes_malformed_png_candidates(tmp_path: Path) -> None:
    sample = tmp_path / "bad_png.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND" + b"\x00\x00\x00\x00")

    blocks = find_image_blocks(sample)
    assert len(blocks) == 1
    assert blocks[0].kind == "png"
    assert not blocks[0].valid
    assert blocks[0].error == "png_chunk_crc_mismatch"


def test_find_image_blocks_captures_gif_heuristic(tmp_path: Path) -> None:
    sample = tmp_path / "gif.opju"
    sample.write_bytes(b"\x00\x00" + b"GIF89a" + b"\x01\x02\x03")
    blocks = find_image_blocks(sample)
    assert any(block.kind == "gif" for block in blocks)


def test_find_image_blocks_excludes_malformed_jpeg_spans(tmp_path: Path) -> None:
    sample = tmp_path / "malformed_jpeg.opju"
    sample.write_bytes(b"\x00\x00\xff\xd8\x00\x00")

    blocks = find_image_blocks(sample)
    assert all(block.kind != "jpeg" for block in blocks)


def test_find_image_blocks_includes_malformed_jpeg_when_requested(tmp_path: Path) -> None:
    sample = tmp_path / "malformed_jpeg.opju"
    sample.write_bytes(b"\x00\x00\xff\xd8\x00\x00")

    blocks = find_image_blocks(sample, allow_invalid_jpeg=True)
    assert len(blocks) == 1
    assert blocks[0].kind == "jpeg"
    assert blocks[0].valid is False
    assert blocks[0].error is not None
    assert blocks[0].error.startswith("jpeg_")


def test_parse_helpers_cover_edge_cases() -> None:
    valid_jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + b"\x01\x02"
        + b"\xff\xd9"
    )

    malformed_png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00"
    png_length, png_error = _find_png_block(malformed_png, 0)
    assert png_length == len(malformed_png)
    assert png_error == "png_chunk_crc_mismatch"

    bad_png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00abcd"
    assert _find_png_length(bad_png, 0) is None

    assert _find_jpeg_length(valid_jpeg, 0) == len(valid_jpeg)

    jpeg_with_restart = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + b"\x01\xff\xd0\x02\xff\xd9"
    )
    assert _find_jpeg_length(jpeg_with_restart, 0) == len(jpeg_with_restart)

    malformed_jpeg = b"\xff\xd8\x00\x00"
    assert _find_jpeg_length(malformed_jpeg, 0) is None

    long_payload = b"\x00" * 80_000
    long_jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + long_payload
        + b"\xff\xd9"
    )
    assert _find_jpeg_length(long_jpeg, 0) == len(long_jpeg)

    assert _find_svg_blocks(b"xx<svg>ok</svg>yy")[0].kind == "svg"
    assert not _find_svg_blocks(b"<svg>")

    valid_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    assert _parse_pdf_payload_length(valid_pdf, 0) == len(valid_pdf)
    assert _parse_pdf_payload_length(b"%PDF-1.4\nno_eof", 0) is None

    valid_gif = b"GIF89a\x01\x00\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;"
    assert _find_gif_payload_length(valid_gif, 0) == len(valid_gif)
    assert _find_gif_payload_length(b"GIF89a", 0) is None

    valid_bmp = (
        b"BM"
        + (58).to_bytes(4, "little")
        + b"\x00\x00"
        + b"\x00\x00"
        + (54).to_bytes(4, "little")
        + (40).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (24).to_bytes(2, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + b"\x00\x00\xff\x00"
    )
    assert _find_bmp_payload_length(valid_bmp, 0) == len(valid_bmp)
    assert _find_bmp_payload_length(b"BM\x00\x00\x00\x00", 0) is None

    deduped = _dedupe(
        [
            ImageBlock(offset=1, length=10, kind="png", extension="png"),
            ImageBlock(offset=5, length=10, kind="jpeg", extension="jpg"),
            ImageBlock(offset=20, length=3, kind="svg", extension="svg"),
        ]
    )
    assert len(deduped) == 2


def test_parse_helpers_cover_opj_payload_boundaries() -> None:
    assert _read_opj_size(b"\x01\x00\x00\x00X", 0) is None
    assert _read_opj_size(b"\x01\x00\x00", 0) is None
    assert _read_opj_size(b"ABCD", 0) is None
    assert _read_opj_size(b"\x02\x00\x00\x00\n", 0) == (2, 5)

    assert _read_opj_payload(b"a\n", 0, 1) == (b"a", 2)
    assert _read_opj_payload(b"abc", 0, 3) is None
    assert _read_opj_payload(b"abc\n", 0, 3) == (b"abc", 4)
    assert _skip_opj_payload(b"abc", 0, 3) is None
    assert _skip_opj_payload(b"abc\n", 0, 3) == 4
    assert _skip_opj_payload(b"abc\n", 0, 0) == 0


def test_parse_opj_note_sections_ignores_cpyua_signature() -> None:
    data = b"CPYUA 4.3318 0\x00\nResults\0\nData1 Temperature:\t25.10242\r\n\r\n\0\n"

    sections = parse_opj_note_sections(data, max_sections=4, max_chars=1000)
    assert sections == []
    assert is_opj_signature(data) is False
