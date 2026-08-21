"""Block carving helpers for embedded binary resources."""

from __future__ import annotations

import re
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPEG_SIG = b"\xff\xd8"
GIF_SIGS = (b"GIF87a", b"GIF89a")
BMP_SIG = b"BM"
PDF_SIG = b"%PDF-"
_JPEG_MAX_SCAN_BYTES = 32 * 1024 * 1024
_IMAGE_SCAN_WINDOW_BYTES = 8 * 1024 * 1024
_GIF_MAX_SCAN_BYTES = 32 * 1024 * 1024
_BMP_MAX_SCAN_BYTES = 32 * 1024 * 1024
_PDF_MAX_SCAN_BYTES = 32 * 1024 * 1024
_INVALID_GIF_SAMPLE_BYTES = 13
_PDF_TRAILER = b"%%EOF"
_FOUR_BYTES = 4
_TWO_BYTES = 2
_PNG_IHDR_TOTAL_BYTES = 33
_PNG_IHDR_LENGTH = 13
_JPEG_DIMENSION_UPPER_BOUND = 1 << 16
_JPEG_SOF_BASE_PAYLOAD_BYTES = 6
_JPEG_MARKER_PREFIX = 0xFF
_GIF_DIMENSION_LIMIT = 16384
_GIF_GLOBAL_COLOR_TABLE_FLAG = 0x80
_GIF_TRAILER = 0x3B
_GIF_EXTENSION = 0x21
_GIF_IMAGE_DESCRIPTOR = 0x2C
_BMP_CORE_HEADER_SIZE = 12
_BMP_INFO_HEADER_SIZE = 40
_BMP_MIN_HEADER_BYTES = 0x16
_BMP_DIMENSION_LIMIT = 16384
_BMP_ALLOWED_BIT_COUNTS = frozenset({1, 4, 8, 16, 24, 32})
_BMP_ALLOWED_COMPRESSIONS = frozenset({0, 3})
_JPEG_SCAN_SKIP_MARKERS = {
    0x00,
    0x01,
    0xD0,
    0xD1,
    0xD2,
    0xD3,
    0xD4,
    0xD5,
    0xD6,
    0xD7,
}
_JPEG_SOI = 0xD8
_JPEG_EOI = 0xD9
_JPEG_SOS = 0xDA
_JPEG_APP_MARKERS = set(range(0xE0, 0xF0))
_JPEG_DCT_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}
_JPEG_DHT_MARKERS = {0xC4}
_JPEG_DQT_MARKERS = {0xDB}
_JPEG_OTHER_VARIABLE_LEN_MARKERS = {0xDD, 0xDE, 0xDF, 0xFE}
_JPEG_MAX_SOF_COMPONENTS = 4
_JPEG_SOI_MARKERS = {
    *_JPEG_DCT_MARKERS,
    *_JPEG_APP_MARKERS,
    *_JPEG_DHT_MARKERS,
    *_JPEG_DQT_MARKERS,
    *_JPEG_OTHER_VARIABLE_LEN_MARKERS,
    _JPEG_SOS,
}
_JPEG_MARKERS_WITH_LENGTH = _JPEG_SOI_MARKERS | {0xDB, 0xDC}
_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _parse_sof_dimensions(payload: bytes) -> tuple[int, int] | None:
    """Parse JPEG image dimensions from SOF segment payload.

    The segment payload includes all bytes after the SOF length field.
    """
    if len(payload) < _JPEG_SOF_BASE_PAYLOAD_BYTES:
        return None

    precision = payload[0]
    if precision not in (8, 12):
        return None

    height = int.from_bytes(payload[1:3], "big")
    width = int.from_bytes(payload[3:5], "big")
    if width >= _JPEG_DIMENSION_UPPER_BOUND or height >= _JPEG_DIMENSION_UPPER_BOUND:
        return None

    components = payload[5]
    if components == 0 or components > _JPEG_MAX_SOF_COMPONENTS:
        return None

    if len(payload) != _JPEG_SOF_BASE_PAYLOAD_BYTES + components * 3:
        return None

    return (width, height) if width and height else None


_IMAGE_BLOCK_CACHE: dict[tuple[Path, int, int, bool], list[ImageBlock]] = {}
_SVG_START_RE = re.compile(rb"<svg\b", re.IGNORECASE)
_SVG_END_RE = re.compile(rb"</svg\b[^>]*>", re.IGNORECASE)


@dataclass(frozen=True)
class ImageBlock:
    offset: int
    length: int
    kind: str
    extension: str
    valid: bool = True
    error: str | None = None


def _find_png_length(data: bytes, start: int) -> int | None:
    length, error = _find_png_block(data, start)
    if error is not None:
        return None
    return length


def _find_png_block(data: bytes, start: int) -> tuple[int | None, str | None]:
    idx = start + len(PNG_SIG)
    data_len = len(data)
    if idx + (_FOUR_BYTES * 2) > data_len:
        return None, "png_truncated"

    while idx + (_FOUR_BYTES * 2) <= data_len:
        chunk_len = int.from_bytes(data[idx : idx + _FOUR_BYTES], "big")
        chunk_type = data[idx + _FOUR_BYTES : idx + (_FOUR_BYTES * 2)]
        if len(chunk_type) != _FOUR_BYTES:
            return None, "png_invalid_chunk_type"

        idx_data = idx + (_FOUR_BYTES * 2)
        chunk_end = idx_data + chunk_len
        crc_end = chunk_end + _FOUR_BYTES
        if crc_end > data_len:
            return None, "png_truncated_chunk"

        chunk_payload = data[idx_data:chunk_end]
        crc_expected = int.from_bytes(data[chunk_end:crc_end], "big")
        crc_actual = zlib.crc32(chunk_type)
        crc_actual = zlib.crc32(chunk_payload, crc_actual) & 0xFFFFFFFF
        if crc_actual != crc_expected:
            return idx + (_FOUR_BYTES * 2) + chunk_len + _FOUR_BYTES - start, "png_chunk_crc_mismatch"

        idx += (_FOUR_BYTES * 2) + chunk_len + _FOUR_BYTES
        if chunk_type == b"IEND":
            return idx - start, None
    return None, None


def _parse_png_dimensions(payload: bytes) -> tuple[int, int] | None:
    """Read width and height from a candidate PNG IHDR chunk."""
    if payload[:8] != PNG_SIG:
        return None
    if len(payload) < _PNG_IHDR_TOTAL_BYTES:
        return None
    if payload[12:16] != b"IHDR":
        return None
    length = int.from_bytes(payload[8:12], "big")
    if length != _PNG_IHDR_LENGTH:
        return None
    width = int.from_bytes(payload[16:20], "big")
    height = int.from_bytes(payload[20:24], "big")
    if width == 0 or height == 0:
        return None
    return width, height


def _is_displayable_png(payload: bytes) -> bool:
    if _parse_png_dimensions(payload) is None:
        return False
    length, error = _find_png_block(payload, 0)
    return error is None and length == len(payload)


def _is_displayable_jpeg(payload: bytes) -> bool:
    length, error = _parse_jpeg_payload_length(payload, 0)
    return error is None and length == len(payload)


def _is_displayable_simple(payload: bytes, parser: Callable[[bytes, int], int | None]) -> bool:
    length = parser(payload, 0)
    return length == len(payload)


def is_displayable_image_block(payload: bytes, kind: str) -> bool:
    """Return true when an image block is likely renderable by common tools."""
    if not payload:
        return False

    handlers = {
        "png": _is_displayable_png,
        "jpeg": _is_displayable_jpeg,
        "gif": lambda data: _is_displayable_simple(data, _parse_gif_payload_length),
        "bmp": lambda data: _is_displayable_simple(data, _parse_bmp_payload_length),
        "svg": lambda data: bool(data.lstrip().startswith(b"<svg") and data.rstrip().endswith(b"</svg>")),
        "pdf": lambda data: _is_displayable_simple(data, _parse_pdf_payload_length),
    }
    handler = handlers.get(kind)
    return handler(payload) if handler is not None else False


def _read_exact(handle: BinaryIO, size: int) -> bytes | None:
    chunk = handle.read(size)
    return chunk if len(chunk) == size else None


def _find_png_block_in_file(
    path: Path,
    start: int,
    *,
    scan_limit: int = _IMAGE_SCAN_WINDOW_BYTES,
) -> tuple[int | None, str | None]:
    if scan_limit <= 0:
        return None, "png_truncated"
    if start < 0:
        return None, "png_truncated"

    with path.open("rb") as fh:
        fh.seek(start)
        header = _read_exact(fh, len(PNG_SIG))
        if header != PNG_SIG:
            return None, "png_truncated"

        consumed = len(PNG_SIG)
        while consumed < scan_limit:
            chunk_len_bytes = _read_exact(fh, _FOUR_BYTES)
            if chunk_len_bytes is None:
                return None, "png_truncated_chunk"

            chunk_type = _read_exact(fh, _FOUR_BYTES)
            if chunk_type is None:
                return None, "png_invalid_chunk_type"

            chunk_len = int.from_bytes(chunk_len_bytes, "big")
            if consumed + (_FOUR_BYTES * 2) > scan_limit:
                return None, "png_truncated_chunk"
            consumed += _FOUR_BYTES * 2

            chunk_payload = _read_exact(fh, chunk_len)
            if chunk_payload is None:
                return None, "png_truncated_chunk"

            crc_expected_bytes = _read_exact(fh, _FOUR_BYTES)
            if crc_expected_bytes is None:
                return None, "png_truncated_chunk"
            consumed += chunk_len + _FOUR_BYTES
            if consumed > scan_limit:
                return None, "png_truncated_chunk"

            crc_expected = int.from_bytes(crc_expected_bytes, "big")
            crc_actual = zlib.crc32(chunk_type)
            crc_actual = zlib.crc32(chunk_payload, crc_actual) & 0xFFFFFFFF
            if crc_actual != crc_expected:
                return consumed, "png_chunk_crc_mismatch"

            if chunk_type == b"IEND":
                return consumed, None

        return None, "png_truncated_chunk"


def _next_jpeg_marker(data: bytes, idx: int, scan_limit: int) -> tuple[int, int] | None:
    next_marker = data.find(bytes([_JPEG_MARKER_PREFIX]), idx, scan_limit)
    if next_marker < 0:
        return None
    idx = next_marker + 1
    while idx < scan_limit and data[idx] == _JPEG_MARKER_PREFIX:
        idx += 1
    if idx >= scan_limit:
        return None
    return idx + 1, data[idx]


def _consume_jpeg_soi(
    *,
    idx: int,
    found_sof: bool,
    allow_leading_nested_soi: bool,
) -> tuple[int, bool, str | None]:
    if allow_leading_nested_soi and not found_sof:
        return idx, found_sof, None
    return idx, found_sof, "jpeg_nested_soi"


def _consume_jpeg_eoi(
    *,
    idx: int,
    start: int,
    found_sof: bool,
) -> tuple[int, bool, int | None, str | None]:
    if not found_sof:
        return idx, False, None, "jpeg_missing_sof"
    return idx, True, idx - start, None


def _consume_jpeg_sos(
    data: bytes,
    idx: int,
    scan_limit: int,
    *,
    start: int,
    found_sof: bool,
    unsupported_seen: bool,
) -> tuple[int | None, str | None, bool, bool]:
    if not found_sof:
        return None, "jpeg_missing_sof", found_sof, unsupported_seen

    segment_end, _payload, error = _jpeg_segment_end(data, idx, scan_limit)
    if segment_end is None:
        return None, error, found_sof, unsupported_seen
    eoi = data.find(b"\xff\xd9", segment_end)
    if eoi < 0:
        return None, "jpeg_missing_eoi", found_sof, unsupported_seen
    return (
        eoi - start + _TWO_BYTES,
        ("jpeg_unsupported_marker" if unsupported_seen else None),
        found_sof,
        unsupported_seen,
    )


def _consume_jpeg_segment(
    data: bytes,
    idx: int,
    scan_limit: int,
    marker: int,
    *,
    start: int,
    found_sof: bool,
    allow_unsupported_marker: bool,
    allow_leading_nested_soi: bool,
    unsupported_seen: bool,
) -> tuple[int | None, bool, bool, str | None, int | None]:
    """Consume one JPEG segment and return next state.

    Return order:
    - next byte index after a consumed segment,
    - whether SOF was seen,
    - unsupported-marker flag,
    - hard error (or None),
    - final length if the JPEG scan can return.
    """

    if marker == _JPEG_SOI:
        next_idx, found_sof_after, found_error = _consume_jpeg_soi(
            idx=idx,
            found_sof=found_sof,
            allow_leading_nested_soi=allow_leading_nested_soi,
        )
        return next_idx, found_sof_after, unsupported_seen, found_error, None

    if marker == _JPEG_EOI:
        next_idx, has_sof, length, error = _consume_jpeg_eoi(
            idx=idx,
            start=start,
            found_sof=found_sof,
        )
        return next_idx, has_sof, unsupported_seen, error, length

    if marker == _JPEG_SOS:
        length, error, found_sof_after, unsupported_after = _consume_jpeg_sos(
            data,
            idx,
            scan_limit,
            start=start,
            found_sof=found_sof,
            unsupported_seen=unsupported_seen,
        )
        return idx, found_sof_after, unsupported_after, error, length

    seg_end, payload, error = _jpeg_segment_end(data, idx, scan_limit)
    if seg_end is None or payload is None:
        return idx, found_sof, unsupported_seen, error, None

    if marker in _JPEG_SOF_MARKERS:
        if _parse_sof_dimensions(payload) is None:
            return idx, found_sof, unsupported_seen, "jpeg_invalid_sof", None
        return seg_end, True, unsupported_seen, None, None

    if marker not in _JPEG_MARKERS_WITH_LENGTH and not allow_unsupported_marker:
        return idx, found_sof, unsupported_seen, "jpeg_unsupported_marker", None

    if marker not in _JPEG_MARKERS_WITH_LENGTH:
        return seg_end, found_sof, True, None, None

    return seg_end, found_sof, unsupported_seen, None, None


def _jpeg_segment_end(
    data: bytes,
    idx: int,
    scan_limit: int,
) -> tuple[int | None, bytes | None, str | None]:
    if idx + _TWO_BYTES > scan_limit:
        return None, None, "jpeg_truncated"
    seg_len = int.from_bytes(data[idx : idx + _TWO_BYTES], "big")
    if seg_len < _TWO_BYTES:
        return None, None, "jpeg_invalid_segment"
    seg_end = idx + seg_len
    if seg_end > scan_limit:
        return None, None, "jpeg_truncated"
    return seg_end, data[idx + _TWO_BYTES : seg_end], None


def _scan_jpeg_payload(
    data: bytes,
    start: int,
    *,
    allow_unsupported_marker: bool,
    allow_leading_nested_soi: bool,
) -> tuple[int | None, str | None]:
    if start < 0 or start + _TWO_BYTES > len(data) or data[start : start + _TWO_BYTES] != JPEG_SIG:
        return None, "jpeg_truncated"

    idx = start + _TWO_BYTES
    scan_limit = len(data)
    if idx >= scan_limit:
        return None, "jpeg_truncated"

    found_sof = False
    unsupported_seen = False
    while idx < scan_limit:
        marker_data = _next_jpeg_marker(data, idx, scan_limit)
        if marker_data is None:
            return None, "jpeg_no_marker"

        idx, marker = marker_data

        if marker in _JPEG_SCAN_SKIP_MARKERS:
            continue

        (
            next_idx,
            found_sof_after,
            unsupported_after,
            error,
            terminal_length,
        ) = _consume_jpeg_segment(
            data,
            idx,
            scan_limit,
            marker,
            start=start,
            found_sof=found_sof,
            allow_unsupported_marker=allow_unsupported_marker,
            allow_leading_nested_soi=allow_leading_nested_soi,
            unsupported_seen=unsupported_seen,
        )
        if next_idx is None:
            return None, "jpeg_no_marker"

        if error is not None:
            return None, error
        if terminal_length is not None:
            return terminal_length, None

        idx = next_idx
        found_sof = found_sof_after
        unsupported_seen = unsupported_after

    return None, "jpeg_truncated"


def _find_jpeg_length(data: bytes, start: int) -> int | None:
    length, error = _scan_jpeg_payload(
        data,
        start,
        allow_unsupported_marker=False,
        allow_leading_nested_soi=False,
    )
    return length if error is None else None


def _parse_jpeg_payload_length(data: bytes, start: int) -> tuple[int | None, str | None]:
    """Parse JPEG payload length and error for strict image carving."""
    return _scan_jpeg_payload(
        data,
        start,
        allow_unsupported_marker=False,
        allow_leading_nested_soi=False,
    )


def _parse_jpeg_payload_length_with_fallback(
    data: bytes,
    start: int,
) -> tuple[int | None, str | None]:
    """Parse JPEG payload length with a bounded fallback for unsupported markers."""
    return _scan_jpeg_payload(
        data,
        start,
        allow_unsupported_marker=True,
        allow_leading_nested_soi=True,
    )


def _find_jpeg_length_in_file(
    path: Path,
    start: int,
    *,
    scan_limit: int = _JPEG_MAX_SCAN_BYTES,
    allow_fallback: bool = False,
) -> tuple[int | None, str | None]:
    if scan_limit <= 0:
        return None, "jpeg_truncated"
    if start < 0:
        return None, "jpeg_truncated"

    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(scan_limit)
        if len(data) < 2:
            return None, "jpeg_truncated"
        if allow_fallback:
            parsed_length, _error = _parse_jpeg_payload_length_with_fallback(data, 0)
            return parsed_length, _error

        parsed_length, _error = _parse_jpeg_payload_length(data, 0)
        return parsed_length, _error


def _find_svg_blocks(data: bytes) -> list[ImageBlock]:
    results: list[ImageBlock] = []
    cursor = 0
    for start_match in _SVG_START_RE.finditer(data):
        start = start_match.start()
        if start < cursor:
            continue
        end_match = _SVG_END_RE.search(data, start)
        if not end_match:
            break
        end = end_match.end()
        results.append(ImageBlock(offset=start, length=end - start, kind="svg", extension="svg"))
        cursor = end
    return results


def _gif_signature_valid(data: bytes, start: int) -> bool:
    if start < 0:
        return False
    header = data[start : start + 6]
    return header == GIF_SIGS[0] or header == GIF_SIGS[1]


def _gif_dimensions_valid(data: bytes, start: int) -> bool:
    width = int.from_bytes(data[start + 6 : start + 8], "little")
    height = int.from_bytes(data[start + 8 : start + 10], "little")
    return width > 0 and height > 0 and width <= _GIF_DIMENSION_LIMIT and height <= _GIF_DIMENSION_LIMIT


def _gif_global_table_size(header_flags: int) -> int:
    return 3 * (1 << ((header_flags & 0x07) + 1))


def _gif_apply_global_color_table(data: bytes, pos: int, flags: int, data_len: int) -> int | None:
    if flags & _GIF_GLOBAL_COLOR_TABLE_FLAG == _GIF_GLOBAL_COLOR_TABLE_FLAG:
        pos += _gif_global_table_size(flags)
        if pos > data_len:
            return None
    return pos


def _consume_gif_extension_block(data: bytes, pos: int) -> int | None:
    if pos >= len(data):
        return None
    return _consume_gif_sub_blocks(data, pos + 1)


def _consume_gif_image_block(data: bytes, pos: int, data_len: int) -> int | None:
    if pos + 9 > data_len:
        return None
    local_flags = data[pos + 8]
    pos += 9
    pos_after_color = _gif_apply_global_color_table(data, pos, local_flags, data_len)
    if pos_after_color is None:
        return None

    if pos_after_color >= data_len:
        return None
    pos_after_color += 1
    return _consume_gif_sub_blocks(data, pos_after_color)


def _parse_gif_payload_length(data: bytes, start: int) -> int | None:
    if start < 0 or start + 13 > len(data):
        return None
    if not _gif_signature_valid(data, start):
        return None

    data_len = len(data)
    if not _gif_dimensions_valid(data, start):
        return None

    pos = start + 13
    header_flags = data[start + 10]
    pos = _gif_apply_global_color_table(data, pos, header_flags, data_len)
    if pos is None:
        return None

    seen_payload = False
    while pos < data_len:
        block_id = data[pos]
        pos += 1
        if pos > data_len:
            return None

        if block_id == _GIF_TRAILER:
            return pos - start if seen_payload else None

        if block_id == _GIF_EXTENSION:
            seen_payload = True
            pos = _consume_gif_extension_block(data, pos)
            if pos is None:
                return None
            continue

        if block_id == _GIF_IMAGE_DESCRIPTOR:
            seen_payload = True
            pos = _consume_gif_image_block(data, pos, data_len)
            if pos is None:
                return None
            continue

        return None

    return None


def _consume_gif_sub_blocks(data: bytes, pos: int) -> int | None:
    data_len = len(data)
    while pos < data_len:
        sub_block_size = data[pos]
        pos += 1
        if pos + sub_block_size > data_len:
            return None
        pos += sub_block_size
        if sub_block_size == 0:
            return pos
    return None


def _parse_pdf_payload_length(data: bytes, start: int) -> int | None:
    """Estimate PDF payload length from header and trailing %%EOF marker.

    This parser is intentionally strict: it requires a `%PDF-` header and at
    least one `%%EOF` marker with optional ASCII whitespace following it.
    """
    if start < 0 or start + len(PDF_SIG) > len(data):
        return None
    if data[start : start + len(PDF_SIG)] != PDF_SIG:
        return None

    marker_start = data.find(_PDF_TRAILER, start + len(PDF_SIG))
    if marker_start < 0:
        return None

    trailer_end = marker_start + len(_PDF_TRAILER)
    data_len = len(data)
    while trailer_end < data_len and data[trailer_end] in b"\r\n\t \x0b\x0c":
        trailer_end += 1
    return trailer_end - start


def _find_pdf_length_in_file(
    path: Path,
    start: int,
    *,
    scan_limit: int = _PDF_MAX_SCAN_BYTES,
) -> int | None:
    if scan_limit <= 0:
        return None
    if start < 0:
        return None

    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(scan_limit)
        if len(data) < len(PDF_SIG):
            return None
        return _parse_pdf_payload_length(data, 0)


def _find_gif_payload_length(data: bytes, start: int) -> int | None:
    """Compatibility shim for older test/caller imports."""
    return _parse_gif_payload_length(data, start)


def _parse_bmp_payload_length(data: bytes, start: int) -> int | None:
    if start < 0:
        return None
    if start + _BMP_MIN_HEADER_BYTES > len(data):
        return None
    if data[start : start + 2] != BMP_SIG:
        return None

    declared_size = int.from_bytes(data[start + 2 : start + 6], "little")
    if declared_size <= 0:
        return None
    if declared_size > len(data) - start:
        return None

    pixel_offset = int.from_bytes(data[start + 10 : start + 14], "little")
    if pixel_offset <= 0 or pixel_offset > declared_size:
        return None

    header_size = int.from_bytes(data[start + 14 : start + 18], "little")
    if header_size not in {_BMP_CORE_HEADER_SIZE, _BMP_INFO_HEADER_SIZE}:
        return None

    if header_size == _BMP_CORE_HEADER_SIZE:
        width = int.from_bytes(data[start + 18 : start + 20], "little")
        height = int.from_bytes(data[start + 20 : start + 22], "little")
        bit_count = int.from_bytes(data[start + 24 : start + 26], "little")
        if not (
            1 <= width <= _BMP_DIMENSION_LIMIT
            and 1 <= height <= _BMP_DIMENSION_LIMIT
            and bit_count in _BMP_ALLOWED_BIT_COUNTS
        ):
            return None
    else:
        width = int.from_bytes(data[start + 18 : start + 22], "little")
        height = int.from_bytes(data[start + 22 : start + 26], "little")
        if width == 0 or height == 0:
            return None
        if width > _BMP_DIMENSION_LIMIT or height > _BMP_DIMENSION_LIMIT:
            return None

        bit_count = int.from_bytes(data[start + 28 : start + 30], "little")
        compression = int.from_bytes(data[start + 30 : start + 34], "little")
        if compression not in _BMP_ALLOWED_COMPRESSIONS:
            return None
        if bit_count == 0 or bit_count not in _BMP_ALLOWED_BIT_COUNTS:
            return None
    return declared_size


def _find_bmp_payload_length(data: bytes, start: int) -> int | None:
    """Compatibility shim for older test/caller imports."""
    return _parse_bmp_payload_length(data, start)


__all__ = [name for name in globals() if not name.startswith("__")]
