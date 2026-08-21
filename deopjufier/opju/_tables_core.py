"""Worksheet-like ColumnTable parsing for OPJU containers."""

from __future__ import annotations

import base64
import binascii
import math
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass

from . import regions as opju_regions
from .analysis import OpjuAnalyzedCandidate
from .common import MAGIC_OPJU
from .regions import OpjuOriginStorageCandidate
from .reports import _extract_escaped_attr


@dataclass(frozen=True)
class OpjuColumnTable:
    name: str
    label: str | None
    offset: int
    length: int
    rows: list[list[str]]


_COLUMN_TABLE_OPEN = b"<columntable"
_COLUMN_TABLE_CLOSE = b"</columntable>"
_STRICT_FAMILY_TAGS = ("Counts", "Percentiles", "CustomPercentiles")
_STRICT_FAMILY_ATTR = "BlobArrElementaryType"
_STRICT_FAMILY_ELEMENT_SIZE = {
    "5": (8, "f8"),
}
_FAMILY_ELEMENT_SIZE = {
    "1": (1, "u1"),
    "2": (2, "u2"),
    "3": (4, "u4"),
    "4": (4, "f4"),
    "5": (8, "f8"),
    "6": (8, "f8"),
}
_FAMILY_ROW_COUNT_TAGS = ("n", "rows", "rowcount")
_FAMILY_BINARY_FORMULA_MARKERS = (
    b"w\x11\x11\x11",
    b"r\x11\x11\x11",
)
_FAMILY_BINARY_FORMULA_MIN_LENGTH = 4
_FAMILY_BINARY_FORMULA_MAX_LENGTH = 180
_FAMILY_BINARY_FORMULA_MIN_ROWS = 20
_FAMILY_BINARY_LEGACY_SEGMENT_MARKER = b"m\x11\x11\x11"
_FAMILY_BINARY_LEGACY_MIN_ROWS = 2
_FAMILY_BINARY_LEGACY_MAX_TOKEN_LENGTH = 120
_FAMILY_FORMULA_ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-*/().,:;<>[]{}= %&!@^$?_'\""
)
_FAMILY_LEGACY_ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;<>[]{}()#_-+*/\\|@!$%^&=_'\"?~"
)
_BLOB_ARRAY_TAG_RE = re.compile(
    r"<(?P<tag>[A-Za-z][A-Za-z0-9_:-]*)(?P<attrs>[^>]*BlobArrElementaryType\s*=\s*(?:\"[^\"]*\"|'[^']*')[^>]*)>(?P<data>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
_XML_ATTR_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_:-]*)\s*=\s*(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<unquoted>[^\s>]+))"
)
_BASE64_NOISE_RE = re.compile(r"[^A-Za-z0-9+/=\s]")


def _is_family_formula_marker(payload: bytes) -> bool:
    return any(payload.startswith(marker) for marker in _FAMILY_BINARY_FORMULA_MARKERS)


def _has_family_formula_marker(payload: bytes) -> bool:
    return any(marker in payload for marker in _FAMILY_BINARY_FORMULA_MARKERS)


def _iter_family_formula_payload_offsets(payload: bytes) -> tuple[int, ...]:
    positions: set[int] = set()
    for marker in _FAMILY_BINARY_FORMULA_MARKERS:
        cursor = 0
        while True:
            index = payload.find(marker, cursor)
            if index < 0:
                break
            if index > 0:
                positions.add(index)
            cursor = index + 1
    return tuple(sorted(positions))


def _iter_candidate_blocks(
    data: bytes,
    *,
    include_decoded: bool,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
) -> Iterable[tuple[int, bytes]]:
    if not data.startswith(MAGIC_OPJU):
        return ()
    if candidates is None:
        candidates = tuple(
            opju_regions.iter_origin_storage_candidates(
                data,
                include_decoded=include_decoded,
            )
        )
    raw_starts_with_decoded_twin: set[int] = set()
    if include_decoded:
        raw_starts_with_decoded_twin = {
            candidate.source_start - 2 for candidate in candidates if candidate.source_kind == "decoded"
        }
    for candidate in candidates:
        if candidate.source_kind == "raw" and candidate.source_start in raw_starts_with_decoded_twin:
            continue
        yield candidate.source_start, candidate.payload


def _decode_opju_column_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("<"):
        return None

    fields: list[str] = []
    current: list[str] = []
    for char in stripped:
        if char in {"\t", ",", ";"}:
            if current:
                fields.append("".join(current))
                current = []
            continue
        current.append(char)

    if current:
        fields.append("".join(current))

    return [field for field in fields if field] or None


def _extract_xml_attributes(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _XML_ATTR_RE.finditer(raw_attrs):
        key = match.group("key")
        if key is None:
            continue

        if match.group("dq") is not None:
            value = match.group("dq")
        elif match.group("sq") is not None:
            value = match.group("sq")
        else:
            value = match.group("unquoted")
        if value is not None:
            attrs[key.lower()] = value

    return attrs


def _extract_xml_attr(raw_attrs: str, name: str) -> str | None:
    value = _extract_xml_attributes(raw_attrs).get(name.lower())
    if value:
        return value
    return None


def _extract_family_row_count(payload: str) -> int:
    lowered = payload.lower()
    for tag in _FAMILY_ROW_COUNT_TAGS:
        open_tag = f"<{tag}>"
        close_tag = f"</{tag}>"
        start = lowered.find(open_tag)
        while start >= 0:
            end = lowered.find(close_tag, start + len(open_tag))
            if end > start:
                raw_value = payload[start + len(open_tag) : end]
                try:
                    value = int(float(raw_value.strip()))
                except ValueError:
                    value = 0
                if value > 0:
                    return value

            start = lowered.find(open_tag, start + 1)

    root_end = lowered.find(">")
    if root_end > 0:
        raw_rows = _extract_xml_attr(payload[: root_end + 1], "Rows")
        if raw_rows is not None:
            try:
                value = int(float(raw_rows))
            except ValueError:
                value = 0
            if value > 0:
                return value

    return 0


def _decode_blob_run_values(
    primitive_size: int,
    primitive_name: str,
    raw_data: str,
    *,
    max_rows: int,
) -> list[str] | None:
    normalized = _BASE64_NOISE_RE.sub("", "".join(raw_data.split()))
    if not normalized:
        return None

    try:
        decoded = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError):
        return None

    if len(decoded) == 0 or len(decoded) % primitive_size != 0:
        return None

    run_length = min(len(decoded) // primitive_size, max_rows)
    if run_length <= 0:
        return None

    values: list[str] = []
    if primitive_name in {"f4", "f8"}:
        fmt = "<f" if primitive_name == "f4" else "<d"
        for index in range(run_length):
            try:
                value = struct.unpack_from(fmt, decoded, index * primitive_size)[0]
            except struct.error:
                return None
            if not math.isfinite(value):
                return None
            values.append(str(float(value)))
        return values

    for index in range(run_length):
        fmt = "<B" if primitive_size == 1 else "<H"
        try:
            value = struct.unpack_from(fmt, decoded, index * primitive_size)[0]
        except struct.error:
            return None
        values.append(str(int(value)))

    return values


def _iter_blob_array_values(
    payload: str,
    *,
    max_rows: int,
) -> list[tuple[str, list[str]]]:
    values: list[tuple[str, list[str]]] = []
    for match in _BLOB_ARRAY_TAG_RE.finditer(payload):
        attrs = match.group("attrs")
        raw_data = match.group("data")
        tag_name = match.group("tag")

        if not attrs:
            continue

        element_type = _extract_xml_attr(attrs, _STRICT_FAMILY_ATTR)
        if element_type is None:
            continue

        primitive = _FAMILY_ELEMENT_SIZE.get(element_type)
        if primitive is None:
            continue

        primitive_size, primitive_name = primitive
        decoded_values = _decode_blob_run_values(
            primitive_size,
            primitive_name,
            raw_data,
            max_rows=max_rows,
        )
        if decoded_values is None:
            continue

        values.append((tag_name, decoded_values))

    return values


def _decode_binary_column_rows(payload: bytes, *, max_rows: int) -> list[list[str]] | None:
    if len(payload) < 12:
        return None
    row_count = int.from_bytes(payload[:4], "little")
    width = int.from_bytes(payload[4:8], "little")
    if width not in (4, 8) or max_rows <= 0:
        return None

    available_rows = (len(payload) - 8) // width
    if available_rows <= 0:
        return None

    if row_count > available_rows:
        return None

    max_rows_to_decode = min(row_count, max_rows)
    if max_rows_to_decode <= 0:
        return None

    expected_size = 8 + max_rows_to_decode * width
    if len(payload) < expected_size:
        return None

    values: list[list[str]] = []
    value_start = 8
    for index in range(max_rows_to_decode):
        start = value_start + index * width
        chunk = payload[start : start + width]
        if len(chunk) < width:
            return None
        value = struct.unpack_from("<d" if width == 8 else "<f", chunk, 0)[0]
        if not math.isfinite(value):
            return None
        values.append([str(value)])
    return values


def _extract_blob_array_values(payload: str, tag: str, *, max_rows: int) -> list[str] | None:
    element = f"<{tag}"
    open_index = payload.find(element)
    payload_search = payload
    close_tag = f"</{tag}>"
    if open_index < 0:
        payload_lower = payload.lower()
        open_index = payload_lower.find(element.lower())
        if open_index < 0:
            return None
        payload_search = payload_lower
        close_tag = f"</{tag.lower()}>"

    if open_index < 0:
        return None

    open_end = payload_search.find(">", open_index + len(element))
    if open_end < 0:
        return None
    close_index = payload_search.find(close_tag, open_end)
    if close_index < 0:
        return None

    open_tag = payload[open_index : open_end + 1]
    attrs = _extract_escaped_attr(open_tag, _STRICT_FAMILY_ATTR)
    if attrs != "5":
        return None
    raw_data = payload[open_end + 1 : close_index]
    if not raw_data:
        return None

    normalized = "".join(raw_data.split())
    try:
        decoded = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError):
        return None

    expected = _STRICT_FAMILY_ELEMENT_SIZE.get(attrs)
    if expected is None:
        return None
    _, primitive_name = expected
    primitive_size = 8
    if primitive_name == "f4":
        primitive_size = 4
    if len(decoded) == 0 or len(decoded) % primitive_size != 0:
        return None

    run_length = min(len(decoded) // primitive_size, max_rows)
    if run_length <= 0:
        return None

    values: list[str] = []
    fmt = "<f" if primitive_name == "f4" else "<d"
    for index in range(run_length):
        try:
            value = struct.unpack_from(fmt, decoded, index * primitive_size)[0]
        except struct.error:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        values.append(str(float(value)))
    return values


def _decode_family_formula_token(raw: bytes) -> str | None:
    if not raw:
        return None
    if len(raw) < _FAMILY_BINARY_FORMULA_MIN_LENGTH:
        return None
    if len(raw) > _FAMILY_BINARY_FORMULA_MAX_LENGTH:
        return None
    if any(b in {0, 9, 10, 13} for b in raw):
        return None
    if any(b < 32 or b >= 127 for b in raw):
        return None

    text = raw.decode("ascii", errors="ignore").strip()
    if not text.startswith("="):
        return None
    if len(text) < _FAMILY_BINARY_FORMULA_MIN_LENGTH:
        return None
    if not text[1:] or any(char not in _FAMILY_FORMULA_ALLOWED_CHARS for char in text):
        return None
    if not any(char.isalnum() for char in text[1:]):
        return None
    return text


def _decode_family_legacy_token(raw: bytes) -> str | None:
    if not raw:
        return None
    if len(raw) > _FAMILY_BINARY_LEGACY_MAX_TOKEN_LENGTH:
        return None
    if any(
        byte
        in {
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
        }
        for byte in raw
    ):
        return None
    text = raw.decode("ascii", errors="ignore").strip()
    if not text:
        return None
    if len(text) < 2:
        return None
    if not text[0].isprintable() or not text[-1].isprintable():
        return None
    if any(char not in _FAMILY_LEGACY_ALLOWED_CHARS for char in text):
        return None
    if not any(char.isalnum() for char in text):
        return None
    if "=" in text:
        return None
    return text


def _parse_origin_storage_family_legacy_table(
    block_start: int,
    block: bytes,
    *,
    max_rows: int,
    index: int,
) -> OpjuColumnTable | None:
    if not _is_family_formula_marker(block):
        return None

    segments = block[4:].split(_FAMILY_BINARY_LEGACY_SEGMENT_MARKER)
    if len(segments) >= 2:
        segments = segments[1:]

    rows: list[list[str]] = []
    for segment in segments:
        for raw_row in segment.split(b"\x00"):
            value = _decode_family_legacy_token(raw_row)
            if value is None:
                continue
            rows.append([value])

    if len(rows) < _FAMILY_BINARY_LEGACY_MIN_ROWS:
        return None
    if max_rows <= 0:
        return None

    if max_rows < len(rows):
        rows = rows[:max_rows]

    return OpjuColumnTable(
        name=f"origin_storage_family_{block_start:08x}_{index:02d}",
        label="OriginStorageBinaryFamilyLegacy",
        offset=block_start,
        length=len(block),
        rows=rows,
    )


def _parse_origin_storage_family_formula_table(
    block_start: int,
    block: bytes,
    *,
    max_rows: int,
    index: int,
) -> OpjuColumnTable | None:
    if not _is_family_formula_marker(block):
        return None

    formulas: list[str] = []
    for part in block.split(b"\x00"):
        formula = _decode_family_formula_token(part)
        if formula is None:
            continue
        formulas.append(formula)

    if len(formulas) < _FAMILY_BINARY_FORMULA_MIN_ROWS:
        return None
    if max_rows <= 0:
        return None

    if max_rows < len(formulas):
        formulas = formulas[:max_rows]

    return OpjuColumnTable(
        name=f"origin_storage_family_{block_start:08x}_{index:02d}",
        label="OriginStorageBinaryFamilyFormula",
        offset=block_start,
        length=len(block),
        rows=[[formula] for formula in formulas],
    )


def _iter_opju_origin_storage_blocks(
    data: bytes,
    *,
    include_decoded: bool,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
    analyses: tuple[OpjuAnalyzedCandidate, ...] | None = None,
) -> Iterable[tuple[int, bytes]]:
    if analyses is not None:
        seen: set[tuple[int, int]] = set()
        for analysis in analyses:
            lowered = analysis.payload.lower()
            if b"<originstorage" not in lowered:
                continue
            if analysis.source_start < 0:
                continue
            span = (analysis.source_start, analysis.source_end)
            if span in seen:
                continue
            seen.add(span)
            yield analysis.source_start, analysis.payload
        return

    seen: set[tuple[int, int]] = set()
    for block_start, block in _iter_candidate_blocks(
        data,
        include_decoded=include_decoded,
        candidates=candidates,
    ):
        if not block.startswith(b"<OriginStorage"):
            continue
        if block_start < 0:
            continue
        span = (block_start, block_start + len(block))
        if span in seen:
            continue
        seen.add(span)
        yield block_start, block


def _iter_column_table_spans(block: bytes) -> Iterable[tuple[int, int]]:
    lowered = block.lower()
    cursor = 0
    while True:
        start = lowered.find(_COLUMN_TABLE_OPEN, cursor)
        if start < 0:
            return

        open_end = block.find(b">", start + len(_COLUMN_TABLE_OPEN))
        if open_end < 0:
            cursor = start + len(_COLUMN_TABLE_OPEN)
            continue

        close = lowered.find(_COLUMN_TABLE_CLOSE, open_end)
        if close < 0:
            cursor = open_end + 1
            continue

        close_end = close + len(_COLUMN_TABLE_CLOSE)
        yield (start, close_end)
        cursor = close_end


def _iter_attributes(open_tag: str) -> tuple[tuple[str, str], ...]:
    if " " not in open_tag:
        return ()

    _, _, remainder = open_tag.partition(" ")
    remainder = remainder.strip().rstrip(">")
    attributes: list[tuple[str, str]] = []
    i = 0
    n = len(remainder)
    while i < n:
        while i < n and remainder[i].isspace():
            i += 1
        if i >= n:
            break

        key_start = i
        while i < n and remainder[i] not in {" ", "="}:
            i += 1
        key = remainder[key_start:i].strip()
        if not key:
            while i < n and remainder[i] != "=":
                i += 1
        else:
            while i < n and remainder[i].isspace():
                i += 1
            if i >= n or remainder[i] != "=":
                break
            i += 1
            while i < n and remainder[i].isspace():
                i += 1
            if i >= n:
                break

            quote = remainder[i]
            if quote not in {'"', "'"}:
                break
            i += 1
            value_start = i
            while i < n and remainder[i] != quote:
                i += 1
            value = remainder[value_start:i]
            attributes.append((key, value))
            if i >= n:
                break
            i += 1

    return tuple(attributes)


def _extract_open_tag_attr_value(open_tag: bytes, key: str) -> str | None:
    text = open_tag.decode("utf-8", errors="replace")
    target = key.lower()
    for attr_name, value in _iter_attributes(text):
        if attr_name.lower() == target:
            return value or None
    if fallback := _extract_escaped_attr(text, key):
        return fallback
    return None


def _parse_column_tables_in_block(
    block_start: int, block: bytes, *, max_tables: int, max_rows: int
) -> list[OpjuColumnTable]:
    """Parse `<ColumnTable>` records from a block and return parser records."""
    tables: list[OpjuColumnTable] = []
    if not block:
        return tables

    for start, close_end in _iter_column_table_spans(block):
        if len(tables) >= max_tables:
            break
        if close_end <= start:
            continue

        open_end = block.find(b">", start + len(_COLUMN_TABLE_OPEN))
        if open_end < 0 or open_end >= close_end:
            continue

        open_tag = block[start : open_end + 1]
        name = _extract_open_tag_attr_value(open_tag, "Name")
        if not name:
            continue
        label = _extract_open_tag_attr_value(open_tag, "Label")

        body_bytes = block[open_end + 1 : close_end - len(_COLUMN_TABLE_CLOSE)]
        if not body_bytes:
            continue

        rows: list[list[str]] = []
        if b"\x00" in body_bytes:
            parsed_rows = _decode_binary_column_rows(body_bytes, max_rows=max_rows)
            if parsed_rows is None:
                continue
            rows = parsed_rows
        else:
            body_text = body_bytes.decode("utf-8", errors="replace")
            for raw_line in body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                row = _decode_opju_column_row(raw_line)
                if row is None:
                    continue
                rows.append(row)
                if len(rows) >= max_rows:
                    break
        if not rows:
            continue

        tables.append(
            OpjuColumnTable(
                name=name,
                label=label,
                offset=block_start + start,
                length=close_end - start,
                rows=rows,
            )
        )

    return tables


def _parse_strict_origin_storage_family_table(
    block_start: int,
    block: bytes,
    *,
    max_rows: int,
    index: int,
) -> OpjuColumnTable | None:
    if not block:
        return None

    lower = block.lower()
    if b"<originstorage" not in lower:
        return None

    close_tag = lower.find(b"</originstorage>")
    if close_tag < 0:
        return None
    close_tag += len(b"</originstorage>")
    payload = block[:close_tag].decode("utf-8", errors="replace")

    result = payload.lower().find("<results")
    if result < 0:
        return None

    row_count = _extract_family_row_count(payload[result:])
    if row_count <= 0:
        return None

    values_by_tag: list[tuple[str, list[str]]] = []
    for tag in _STRICT_FAMILY_TAGS:
        values = _extract_blob_array_values(payload, tag, max_rows=max_rows)
        if values is not None:
            values_by_tag.append((tag, values))

    if len(values_by_tag) != len(_STRICT_FAMILY_TAGS):
        return None
    min_values = min(len(values) for _, values in values_by_tag)
    if min_values <= 0:
        return None

    row_count = min(row_count, min_values)
    if row_count <= 0 or row_count > max_rows:
        return None

    table_rows: list[list[str]] = []
    for row_index in range(row_count):
        row = [str(row_index + 1)]
        for _, values in values_by_tag:
            row.append(values[row_index])
        table_rows.append(row)

    if not table_rows:
        return None

    return OpjuColumnTable(
        name=f"origin_storage_family_{block_start:08x}_{index:02d}",
        label="OriginStorageBinaryFamily",
        offset=block_start,
        length=close_tag,
        rows=table_rows,
    )


def _parse_generic_origin_storage_family_table(
    block_start: int,
    block: bytes,
    *,
    max_rows: int,
    index: int,
) -> OpjuColumnTable | None:
    if not block:
        return None

    lower = block.lower()
    if b"<originstorage" not in lower:
        return None

    close_tag = lower.find(b"</originstorage>")
    if close_tag < 0:
        return None
    close_tag += len(b"</originstorage>")

    payload = block[:close_tag].decode("utf-8", errors="replace")

    values_by_tag = _iter_blob_array_values(payload, max_rows=max_rows)
    if len(values_by_tag) < 2:
        return None

    row_count = _extract_family_row_count(payload)
    min_values = min(len(values) for _, values in values_by_tag)
    if min_values <= 0:
        return None

    if row_count <= 0:
        row_count = min_values
    else:
        row_count = min(row_count, min_values)

    if row_count <= 0 or row_count > max_rows:
        return None

    table_rows: list[list[str]] = []
    for row_index in range(row_count):
        row = [str(row_index + 1)]
        for _, values in values_by_tag:
            if row_index >= len(values):
                break
            row.append(values[row_index])
        if len(row) < 2:
            continue
        table_rows.append(row)

    if not table_rows:
        return None

    return OpjuColumnTable(
        name=f"origin_storage_family_{block_start:08x}_{index:02d}",
        label="OriginStorageBinaryFamily",
        offset=block_start,
        length=close_tag,
        rows=table_rows,
    )


def parse_opju_origin_storage_family_tables(
    data: bytes,
    *,
    max_tables: int = 16,
    max_rows: int = 256,
    include_decoded: bool = False,
    include_family_binary: bool = False,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
    analyses: tuple[OpjuAnalyzedCandidate, ...] | None = None,
) -> list[OpjuColumnTable]:
    if max_tables <= 0 or max_rows <= 0 or not data.startswith(MAGIC_OPJU):
        return []

    if analyses is not None:
        blocks = [
            (analysis.source_start, analysis.payload)
            for analysis in analyses
            if b"<originstorage" in analysis.normalized_payload.lower()
            or (include_family_binary and _has_family_formula_marker(analysis.payload))
        ]
    elif candidates is not None:
        blocks = [
            (candidate.source_start, candidate.payload)
            for candidate in candidates
            if b"<originstorage" in candidate.payload.lower()
            or (include_family_binary and _has_family_formula_marker(candidate.payload))
        ]
    else:
        blocks = []
        if include_decoded:
            for candidate in opju_regions.iter_origin_storage_candidates(
                data,
                include_decoded=include_decoded,
                include_family_binary=include_family_binary,
            ):
                blocks.append((candidate.source_start, candidate.payload))

    if not blocks:
        return []

    tables: list[OpjuColumnTable] = []
    seen: set[tuple[int, int, int]] = set()
    for block_start, payload in blocks:
        payload_key = (block_start, len(payload), 0)
        if payload_key in seen:
            continue
        seen.add(payload_key)
        if len(tables) >= max_tables:
            break
        table = _parse_strict_origin_storage_family_table(
            block_start,
            payload,
            max_rows=max_rows,
            index=len(tables),
        )
        if table is None:
            table = _parse_generic_origin_storage_family_table(
                block_start,
                payload,
                max_rows=max_rows,
                index=len(tables),
            )
        if table is None and include_family_binary:
            table = _parse_origin_storage_family_formula_table(
                block_start,
                payload,
                max_rows=max_rows,
                index=len(tables),
            )
        if table is None and include_family_binary:
            table = _parse_origin_storage_family_legacy_table(
                block_start,
                payload,
                max_rows=max_rows,
                index=len(tables),
            )
        if table is not None:
            tables.append(table)
            continue

        if include_family_binary:
            marker_payload_offsets = tuple(sorted(_iter_family_formula_payload_offsets(payload)))
            for marker_index, marker_offset in enumerate(marker_payload_offsets):
                if len(tables) >= max_tables:
                    break

                next_offset = (
                    marker_payload_offsets[marker_index + 1]
                    if marker_index + 1 < len(marker_payload_offsets)
                    else len(payload)
                )
                marker_payload = payload[marker_offset:next_offset]
                if not marker_payload:
                    continue

                marker_key = (
                    block_start + marker_offset,
                    len(marker_payload),
                    marker_offset,
                )
                if marker_key in seen:
                    continue
                seen.add(marker_key)

                table = _parse_origin_storage_family_formula_table(
                    block_start + marker_offset,
                    marker_payload,
                    max_rows=max_rows,
                    index=len(tables),
                )
                if table is None:
                    table = _parse_origin_storage_family_legacy_table(
                        block_start + marker_offset,
                        marker_payload,
                        max_rows=max_rows,
                        index=len(tables),
                    )

                if table is not None:
                    tables.append(table)
    return tables


from ._tables.columns import parse_opju_column_tables  # noqa: E402, F401
