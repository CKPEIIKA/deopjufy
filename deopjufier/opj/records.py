"""Low-level OPJ record parsing and shared data structures."""

from __future__ import annotations

import re
import struct
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from .stream import OpjStreamError

_WalkElementMetadataValue = int | float | str | None | tuple[int, int] | tuple[int, ...]

MAGIC_OPJ = b"CPYA"
MAGIC_OPJU = b"CPYUA"
OPJ_HEADER_MARKER = (MAGIC_OPJ, MAGIC_OPJU)
OPJ_PARAMETERS_MAX_RECORDS = 128
OPJ_PARAMETERS_SCAN_WINDOW = 4 * 1024 * 1024
OPJ_NOTES_MAX_BLOCKS = 32
OPJ_NOTES_MAX_CHARS = 1200
OPJ_NOTE_SECTION_NAMES = (
    "Results",
    "ResultsLog",
    "Notes",
    "Note",
)

_DELIM = b"\n"
_OPJ_NOTE_SECTION_PATTERN = re.compile(rb"\n([A-Za-z][A-Za-z0-9_]{1,64})\x00")
_OPJ_NOTE_SECTION_END_MARKER = b"\r\n\r\n\x00\n"
_OPJ_NOTE_SECTION_ALT_END_MARKER = b"\x00\n"
_OPJ_DATA_SECTION_HEADER_SIZES = (123, 147)
_OPJ_FUNCTION_PAYLOAD_PATTERN = re.compile(
    r"<(?P<tag>[A-Za-z_][A-Za-z0-9_]*)\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
_OPJ_FUNCTION_FORMULA_TAGS = (
    "formula",
    "functionlist",
    "oy",
    "ix",
    "iy",
    "xfname",
    "functionname",
    "xfunctionname",
    "nlfitxfname",
)
_OPJ_FUNCTION_RANGE_ATTR_TAGS: tuple[tuple[str, str], ...] = (
    ("xrangefrom", "xrangeto"),
    ("yrangefrom", "yrangeto"),
    ("rowrangefrom", "rowrangeto"),
)
_OPJ_DATASET_NAME_OFFSET = 0x58
_OPJ_DATASET_NAME_SIZE = 25
_OPJ_EMPTY_VALUE = -1.23456789e-300
_OPJ_DATA_SECTION_CACHE_SIZE = 4
_OPJ_DATA_SECTION_CACHE: OrderedDict[tuple[int, int, int | None], list[OpjDataSection]] = OrderedDict()


@dataclass(frozen=True)
class OpjSignature:
    magic: str
    file_version: str
    build: int
    origin_version: float | None = None

    def to_dict(self) -> dict[str, int | float | str]:
        payload: dict[str, int | float | str] = {
            "magic": self.magic,
            "file_version": self.file_version,
            "build": self.build,
        }
        if self.origin_version is not None:
            payload["origin_version"] = self.origin_version
        return payload


@dataclass(frozen=True)
class OpjDataSection:
    offset: int
    length: int
    name: str
    data_type: int
    data_type2: int
    total_rows: int
    first_row: int
    last_row: int
    value_size: int
    data_type_u: int
    data_type3: int
    values: list[object | None]
    mask_offset: int | None = None
    mask: bytes = b""


class _WalkElement(Protocol):
    kind: str
    start_offset: int
    end_offset: int
    metadata: dict[str, _WalkElementMetadataValue]


@dataclass(frozen=True)
class OpjParameter:
    name: str
    value: float
    offset: int
    total_length: int


@dataclass(frozen=True)
class OpjNoteSection:
    name: str
    text: str
    offset: int
    length: int


@dataclass(frozen=True)
class OpjObjectBoundary:
    kind: str
    name: str
    source_object_path: str
    start_offset: int
    end_offset: int
    length: int
    confidence: float
    parser_rule: str
    label: str | None = None


@dataclass(frozen=True)
class OpjColumnMetadata:
    """Semantic column header decoded from a worksheet layer curve."""

    name: str
    sheet_index: int
    designation: str | None = None
    long_name: str | None = None
    units: str | None = None
    value_type: str | None = None
    value_type_specification: int | None = None
    significant_digits: int | None = None
    decimal_places: int | None = None
    width: int | None = None
    comment: str | None = None
    formula: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"name": self.name, "sheet_index": self.sheet_index}
        for key, value in (
            ("designation", self.designation),
            ("long_name", self.long_name),
            ("units", self.units),
            ("value_type", self.value_type),
            ("value_type_specification", self.value_type_specification),
            ("significant_digits", self.significant_digits),
            ("decimal_places", self.decimal_places),
            ("width", self.width),
            ("comment", self.comment),
            ("formula", self.formula),
        ):
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class OpjWorksheetMetadata:
    name: str
    label: str | None = None
    long_name: str | None = None
    comments: str | None = None
    formulas: list[str] = field(default_factory=list)
    column_types: list[str] = field(default_factory=list)
    display_hints: list[str] = field(default_factory=list)
    units: str | None = None
    formula_rows: tuple[int, int] | None = None
    column_labels: list[str] = field(default_factory=list)
    object_id: int | None = None
    hidden: bool | None = None
    state: str | None = None
    creation_time: int | None = None
    modification_time: int | None = None
    columns: list[OpjColumnMetadata] = field(default_factory=list)
    metadata_status: str | None = None
    unresolved_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.label is not None:
            payload["label"] = self.label
        if self.long_name:
            payload["long_name"] = self.long_name
        if self.comments:
            payload["comments"] = self.comments
        if self.formulas:
            payload["formulas"] = self.formulas
        if self.column_types:
            payload["column_types"] = self.column_types
        if self.display_hints:
            payload["display_hints"] = self.display_hints
        if self.units:
            payload["units"] = self.units
        if self.formula_rows is not None:
            payload["formula_rows"] = self.formula_rows
        if self.column_labels:
            payload["column_labels"] = self.column_labels
        if self.object_id is not None:
            payload["object_id"] = self.object_id
        if self.hidden is not None:
            payload["hidden"] = self.hidden
        if self.state:
            payload["state"] = self.state
        if self.creation_time is not None:
            payload["creation_time"] = self.creation_time
        if self.modification_time is not None:
            payload["modification_time"] = self.modification_time
        if self.columns:
            payload["columns"] = [column.to_dict() for column in self.columns]
        if self.metadata_status:
            payload["metadata_status"] = self.metadata_status
        if self.unresolved_fields:
            payload["unresolved_fields"] = self.unresolved_fields
        return payload


@dataclass(frozen=True)
class OpjMatrixSheetMetadata:
    """Semantic shape and coordinate metadata for one matrix sheet."""

    name: str
    sheet_index: int
    shape: tuple[int, int] | None = None
    width: int | None = None
    view: str | None = None
    formula: str | None = None
    coordinates: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"name": self.name, "sheet_index": self.sheet_index}
        for key, value in (
            ("shape", self.shape),
            ("width", self.width),
            ("view", self.view),
            ("formula", self.formula),
            ("coordinates", self.coordinates),
        ):
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class OpjMatrixMetadata:
    name: str
    long_name: str | None = None
    shape: tuple[int, int] | None = None
    data_type: int | None = None
    row_start: int | None = None
    row_end: int | None = None
    section_count: int | None = None
    active_sheet: int | None = None
    header_view: str | None = None
    sheets: list[OpjMatrixSheetMetadata] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.long_name:
            payload["long_name"] = self.long_name
        if self.shape is not None:
            payload["shape"] = self.shape
        if self.data_type is not None:
            payload["data_type"] = self.data_type
        if self.row_start is not None:
            payload["row_start"] = self.row_start
        if self.row_end is not None:
            payload["row_end"] = self.row_end
        if self.section_count is not None:
            payload["section_count"] = self.section_count
        if self.active_sheet is not None:
            payload["active_sheet"] = self.active_sheet
        if self.header_view is not None:
            payload["header_view"] = self.header_view
        if self.sheets:
            payload["sheets"] = [sheet.to_dict() for sheet in self.sheets]
        return payload


@dataclass(frozen=True)
class OpjFunctionMetadata:
    name: str
    formula: str | None = None
    function_range: tuple[str, str] | None = None
    total_points: int | None = None
    function_type: str | None = None

    def to_dict(self) -> dict[str, int | tuple[str, str] | str]:
        payload: dict[str, int | tuple[str, str] | str] = {"name": self.name}
        if self.formula:
            payload["formula"] = self.formula
        if self.function_range is not None:
            payload["range"] = self.function_range
        if self.total_points is not None:
            payload["total_points"] = self.total_points
        if self.function_type is not None:
            payload["function_type"] = self.function_type
        return payload


def _parse_tag_value(payload: str, tag: str) -> str | None:
    pattern = re.compile(rf"<{tag}\b[^>]*>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL)
    match = pattern.search(payload)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _parse_xml_attribute(tag: str, name: str) -> str | None:
    pattern = re.compile(
        rf"""\b{name}\s*=\s*(
            "((?:[^"\\]|\\.)*)"
            |'((?:[^'\\]|\\.)*)'
        )""",
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    )
    match = pattern.search(tag)
    if not match:
        return None
    value = match.group(2) or match.group(3) or ""
    value = value.strip()
    return value or None


def _clean_function_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _to_function_range(value: str | None) -> str | None:
    if value is None:
        return None
    text = _clean_function_text(value)
    return text if text else None


def _to_int_if_possible(value: str | None) -> int | None:
    if value is None:
        return None
    text = _clean_function_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            numeric = float(text)
        except ValueError:
            return None
        return int(numeric)


def parse_opj_function_metadata(payload: bytes, *, function_name: str) -> OpjFunctionMetadata | None:
    if not payload:
        return None

    native = _parse_native_opj_function_metadata(payload, function_name=function_name)
    if native is not None:
        return native

    text = payload.decode("utf-8", errors="replace").replace("\x00", " ")
    formula = None
    for tag_name in _OPJ_FUNCTION_FORMULA_TAGS:
        formula = _parse_tag_value(text, tag_name)
        if formula is not None:
            break
    formula = _clean_function_text(formula) if formula is not None else None

    start = _to_function_range(
        _parse_tag_value(text, "x1") or _parse_tag_value(text, "range1") or _parse_tag_value(text, "begin")
    )
    end = _to_function_range(
        _parse_tag_value(text, "x2") or _parse_tag_value(text, "range2") or _parse_tag_value(text, "end")
    )
    if start is None or end is None:
        tag_match = re.search(
            r"<(?:range\d*)\b([^>]*)>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if tag_match:
            attrs = tag_match.group(1)
            for from_name, to_name in _OPJ_FUNCTION_RANGE_ATTR_TAGS:
                parsed_start = _parse_xml_attribute(attrs, from_name)
                parsed_end = _parse_xml_attribute(attrs, to_name)
                if parsed_start is not None and parsed_end is not None:
                    start = _to_function_range(parsed_start)
                    end = _to_function_range(parsed_end)
                    break

    function_range: tuple[str, str] | None = None
    if start is not None and end is not None:
        function_range = (start, end)

    total_points = _to_int_if_possible(_parse_tag_value(text, "nx"))
    if total_points is None:
        total_points = _to_int_if_possible(_parse_tag_value(text, "totalpoints"))

    if formula is None and function_range is None and total_points is None:
        return None

    name = function_name.strip() or "Function"
    return OpjFunctionMetadata(
        name=name,
        formula=formula,
        function_range=function_range,
        total_points=total_points,
    )


def _parse_native_opj_function_metadata(payload: bytes, *, function_name: str) -> OpjFunctionMetadata | None:
    header_size_record = _read_opj_size(payload, 0)
    if header_size_record is None:
        return None
    header_size, header_offset = header_size_record
    header_record = _read_opj_payload(payload, header_offset, header_size)
    if header_record is None:
        return None
    header, data_size_offset = header_record
    parsed_header = _parse_opj_data_header(header)
    if parsed_header is None or int(parsed_header["data_type"]) != 0x6081:
        return None
    data_size_record = _read_opj_size(payload, data_size_offset)
    if data_size_record is None:
        return None
    data_size, data_offset = data_size_record
    data_record = _read_opj_payload(payload, data_offset, data_size)
    if data_record is None:
        return None
    formula_payload, _ = data_record
    formula = _decode_opj_text(formula_payload).strip().lower() or None
    total_points = int.from_bytes(header[0x21:0x25], "little") if len(header) >= 0x25 else None
    begin = struct.unpack_from("<d", header, 0x25)[0] if len(header) >= 0x2D else None
    increment = struct.unpack_from("<d", header, 0x2D)[0] if len(header) >= 0x35 else None
    function_range = None
    if begin is not None and increment is not None and total_points is not None and total_points > 0:
        end = begin + increment * (total_points - 1)
        function_range = (format(begin, ".17g"), format(end, ".17g"))
    function_code = int.from_bytes(header[0x0A:0x0C], "little") if len(header) >= 0x0C else None
    return OpjFunctionMetadata(
        name=function_name,
        formula=formula,
        function_range=function_range,
        total_points=total_points,
        function_type="polar" if function_code == 0x1194 else "normal",
    )


def parse_opj_function_payload(payload: bytes) -> str | None:
    """Extract a lightweight, parser-backed function payload from XML-like tags."""
    if not payload:
        return None

    text = payload.decode("utf-8", errors="replace")
    chunks: list[str] = []
    for match in _OPJ_FUNCTION_PAYLOAD_PATTERN.finditer(text):
        body = _clean_function_text(match.group("body"))
        if not body:
            continue
        tag = match.group("tag")
        chunks.append(f"{tag}: {body}")

    if chunks:
        return "\n".join(chunks)

    fallback = _clean_function_text(text)
    return fallback or None


def parse_opj_parameters(
    data: bytes, *, max_records: int = OPJ_PARAMETERS_MAX_RECORDS, scan_window: int = OPJ_PARAMETERS_SCAN_WINDOW
) -> list[OpjParameter]:
    if not is_opj_signature(data):
        return []
    if max_records <= 0 or scan_window <= 0:
        return []
    if scan_window > len(data):
        scan_window = len(data)

    end_scan = scan_window
    start = data.find(_DELIM)
    start = 0 if start < 0 else start + 1

    parameters: list[OpjParameter] = []
    pos = start
    while pos + 10 < end_scan:
        if data[pos] == 0x00:
            if pos + 1 < end_scan and data[pos + 1] == 0x0A:
                break
            pos += 1
            continue
        if data[pos] == 0x0A:
            pos += 1
            continue

        lf = data.find(_DELIM, pos + 1, end_scan)
        if lf < 0:
            break
        name_bytes = data[pos:lf]
        if (
            not name_bytes
            or len(name_bytes) > 64
            or not all(0x21 <= byte <= 0x7E for byte in name_bytes)
            or not (name_bytes[0:1].isalpha() or name_bytes[0:1] in (b"_",))
        ):
            pos = lf + 1
            continue

        value_offset = lf + 1
        if value_offset + 9 > end_scan:
            break
        if data[value_offset + 8] != 0x0A:
            pos = lf + 1
            continue

        value = struct.unpack_from("<d", data, value_offset)[0]
        total_length = (value_offset - pos) + 9
        parameters.append(
            OpjParameter(
                name=name_bytes.decode("ascii", errors="replace"),
                value=value,
                offset=pos,
                total_length=total_length,
            )
        )
        pos = value_offset + 9
        if len(parameters) >= max_records:
            break
    return parameters


def parse_opj_note_sections(
    data: bytes, *, max_sections: int = OPJ_NOTES_MAX_BLOCKS, max_chars: int = OPJ_NOTES_MAX_CHARS
) -> list[OpjNoteSection]:
    if max_sections <= 0 or max_chars <= 0 or not data:
        return []

    if not is_opj_signature(data):
        return []

    opj_walker_module: object | None = None
    imported_walker: object | None = None
    try:
        from . import walker as imported_walker
    except Exception:  # pragma: no cover - defensive import guard
        pass
    else:
        opj_walker_module = imported_walker

    if opj_walker_module is not None:
        matches = []
        try:
            for element in opj_walker_module.walk_opj_file(data, tolerant=True):
                if element.kind != "note":
                    continue
                if len(matches) >= max_sections:
                    break
                label_value = element.metadata.get("label") if isinstance(element.metadata, dict) else None
                if isinstance(label_value, str):
                    label = label_value.split("\x00", 1)[0].strip()
                else:
                    label = ""
                name: str = label or element.name or "note"
                if not name:
                    continue
                if name not in OPJ_NOTE_SECTION_NAMES and not name.lower().startswith("note"):
                    continue

                metadata = element.metadata
                contents_offset = metadata.get("note_contents_start")
                contents_size = metadata.get("contents_size")
                if isinstance(contents_offset, int) and isinstance(contents_size, int):
                    contents_end = contents_offset + contents_size
                    if 0 <= contents_offset <= len(data) and contents_end <= len(data):
                        payload = data[contents_offset:contents_end]
                    else:
                        continue
                else:
                    continue
                while payload and payload[0] <= 0x20:
                    payload = payload[1:]
                if payload and payload[0] == 0x95:
                    payload = payload[1:]
                while payload and payload[0] <= 0x20:
                    payload = payload[1:]

                text = payload.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\x00", "").strip()
                if not text:
                    continue
                if len(text) > max_chars:
                    text = text[: max_chars - 3] + "..."
                matches.append(
                    OpjNoteSection(
                        name=name,
                        text=text,
                        offset=element.start_offset,
                        length=max(0, element.end_offset - element.start_offset),
                    )
                )
        except OpjStreamError:
            matches = []
        if matches:
            return matches

    matches = []
    for match in _OPJ_NOTE_SECTION_PATTERN.finditer(data):
        if len(matches) >= max_sections:
            break
        raw_name = match.group(1)
        if raw_name.decode("ascii", errors="ignore") not in OPJ_NOTE_SECTION_NAMES:
            continue

        content_start = match.end()
        content_end = data.find(_OPJ_NOTE_SECTION_END_MARKER, content_start)
        if content_end < 0:
            content_end = data.find(_OPJ_NOTE_SECTION_ALT_END_MARKER, content_start)
            if content_end < 0:
                continue
            section_length = content_end - match.start() + len(_OPJ_NOTE_SECTION_ALT_END_MARKER)
        else:
            section_length = content_end - match.start() + len(_OPJ_NOTE_SECTION_END_MARKER)

        payload = data[content_start:content_end]
        while payload and payload[0] <= 0x20:
            payload = payload[1:]
        if payload and payload[0] == 0x95:
            payload = payload[1:]
        while payload and payload[0] <= 0x20:
            payload = payload[1:]

        text = payload.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\x00", "").strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        matches.append(
            OpjNoteSection(
                name=raw_name.decode("ascii", errors="replace"),
                text=text,
                offset=match.start(),
                length=section_length,
            )
        )
    return matches


def parse_opj_signature(data: bytes) -> OpjSignature | None:
    if not data.startswith(OPJ_HEADER_MARKER):
        return None
    line_end = data.find(_DELIM)
    if line_end < 0:
        return None

    signature_line = data[:line_end].decode("ascii", errors="ignore").strip()
    parts = signature_line.split()
    magic = parts[0]
    if magic not in (MAGIC_OPJ.decode("ascii"), MAGIC_OPJU.decode("ascii")) or len(parts) < 3:
        return None

    build_text = parts[2].rstrip("#")
    if not build_text.isdigit():
        return None

    origin_version: float | None = None
    header_start = line_end + 1
    header_size_and_pos = _read_opj_size(data, header_start)
    if header_size_and_pos is not None:
        header_size, header_pos = header_size_and_pos
        header_payload = _read_opj_payload(data, header_pos, header_size)
        if header_payload is not None:
            payload = header_payload[0]
            if len(payload) >= 0x23:
                origin_version = struct.unpack_from("<d", payload, 0x1B)[0]

    return OpjSignature(
        magic=parts[0],
        file_version=parts[1],
        build=int(build_text),
        origin_version=origin_version,
    )


def is_opj_signature(data: bytes) -> bool:
    """Return ``True`` only for strict OPJ family files (``CPYA``)."""
    signature = parse_opj_signature(data)
    return signature is not None and signature.magic == "CPYA"


def _decode_name(data: bytes) -> str | None:
    text = data.decode("ascii", errors="ignore").rstrip("\x00")
    text = text.strip(" \t\0\r\n")
    return text or None


def _is_plausible_opj_data_name(name: str) -> bool:
    if not name or len(name) > _OPJ_DATASET_NAME_SIZE:
        return False
    if any(ch.isspace() for ch in name) or name[0].isdigit():
        return False
    return all(ch.isalnum() or ch in "._-@" for ch in name)


def _parse_opj_data_header(payload: bytes) -> dict[str, int | str] | None:
    if len(payload) < 0x73:
        return None

    name = _decode_name(payload[_OPJ_DATASET_NAME_OFFSET : _OPJ_DATASET_NAME_OFFSET + _OPJ_DATASET_NAME_SIZE])
    if not name or not _is_plausible_opj_data_name(name):
        return None

    return {
        "name": name,
        "data_type": int.from_bytes(payload[0x16:0x18], "little"),
        "data_type2": payload[0x18],
        "total_rows": int.from_bytes(payload[0x19:0x1D], "little"),
        "first_row": int.from_bytes(payload[0x1D:0x21], "little"),
        "last_row": int.from_bytes(payload[0x21:0x25], "little"),
        "value_size": payload[0x3D],
        "data_type_u": payload[0x3F],
        "data_type3": int.from_bytes(payload[0x71:0x73], "little"),
    }


def _decode_opj_text(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def _decode_opj_value(
    value_size: int,
    data_type: int,
    data_type_u: int,
    payload: bytes,
) -> object | None:
    if value_size <= 0:
        return None
    if value_size == 1:
        format_code = "<B" if data_type_u == 8 else "<b"
        return struct.unpack_from(format_code, payload[:1].ljust(1, b"\x00"), 0)[0]
    if value_size == 2:
        format_code = "<H" if data_type_u == 8 else "<h"
        return struct.unpack_from(format_code, payload[:2].ljust(2, b"\x00"), 0)[0]
    if value_size == 4:
        if data_type & 0x800:
            format_code = "<I" if data_type_u == 8 else "<i"
            return struct.unpack_from(format_code, payload[:4].ljust(4, b"\x00"), 0)[0]
        value = struct.unpack_from("<f", payload[:4].ljust(4, b"\x00"), 0)[0]
        return None if value == _OPJ_EMPTY_VALUE else value
    if value_size == 8:
        value = struct.unpack_from("<d", payload[:8].ljust(8, b"\x00"), 0)[0]
        return None if value == _OPJ_EMPTY_VALUE else value

    if data_type & 0x100:
        prefix = payload[0] if payload else 0
        if prefix != 1:
            # liborigin uses 1 for text cells; everything else is numeric.
            # For mixed-size records, the payload stores a 2-byte per-cell
            # prefix before the 8-byte numeric value.
            numeric = payload[2:10].ljust(8, b"\x00")
            value = struct.unpack_from("<d", numeric, 0)[0]
            return None if value == _OPJ_EMPTY_VALUE else value
        body = payload[2:value_size] if len(payload) > 2 else b""
        return _decode_opj_text(body)
    return _decode_opj_text(payload[:value_size])


def _decode_opj_values(
    data_type: int,
    data_type_u: int,
    value_size: int,
    total_rows: int,
    payload: bytes,
) -> list[object | None]:
    if value_size <= 0:
        return []

    row_count = min(total_rows, len(payload) // value_size)
    values: list[object | None] = []
    for index in range(row_count):
        start = index * value_size
        values.append(
            _decode_opj_value(
                value_size,
                data_type,
                data_type_u,
                payload[start : start + value_size],
            )
        )
    return values


def _read_opj_size(data: bytes, offset: int) -> tuple[int, int] | None:
    if offset + 5 > len(data):
        return None
    value = int.from_bytes(data[offset : offset + 4], "little")
    offset += 4
    if data[offset : offset + 1] != _DELIM:
        return None
    return value, offset + 1


def _read_opj_payload(data: bytes, offset: int, length: int) -> tuple[bytes, int] | None:
    end = offset + length
    if end > len(data):
        return None
    if length == 0:
        return b"", offset
    if end >= len(data) or data[end : end + 1] != _DELIM:
        return None
    return data[offset:end], end + 1


def _skip_opj_payload(data: bytes, offset: int, length: int) -> int | None:
    if length == 0:
        return offset
    if offset + length > len(data):
        return None
    end = offset + length
    if end >= len(data) or data[end : end + 1] != _DELIM:
        return None
    return end + 1


def _iter_opj_data_sections_uncached(data: bytes, *, max_sections: int | None = None) -> list[OpjDataSection]:
    if not is_opj_signature(data):
        return []

    # Primary path: sequential liborigin-style walk.
    from . import walker as opj_walker

    parse_failed = False
    sections: list[OpjDataSection] = []

    def _collect_sections(walk_elements: Iterable[_WalkElement]) -> tuple[list[OpjDataSection], bool]:
        sections: list[OpjDataSection] = []
        parse_failed = False
        try:
            for element in walk_elements:
                if element.kind != "dataset":
                    continue
                header_size = element.metadata.get("header_size")
                data_size = element.metadata.get("data_size")
                if not isinstance(header_size, int) or not isinstance(data_size, int):
                    continue
                if header_size < 0 or data_size < 0:
                    continue

                header_offset = element.metadata.get("header_offset")
                data_offset = element.metadata.get("data_offset")
                if not isinstance(header_offset, int) or not isinstance(data_offset, int):
                    continue

                header_end = header_offset + header_size
                data_end = data_offset + data_size
                if header_end > len(data) or data_end > len(data):
                    continue

                header_payload = data[header_offset:header_end]
                parsed_header = _parse_opj_data_header(header_payload)
                if parsed_header is None:
                    continue

                data_payload = data[data_offset:data_end]
                values = _decode_opj_values(
                    int(parsed_header["data_type"]),
                    int(parsed_header["data_type_u"]),
                    int(parsed_header["value_size"]),
                    int(parsed_header["total_rows"]),
                    data_payload,
                )
                mask_size = element.metadata.get("mask_size")
                mask_offset = element.metadata.get("mask_offset")
                mask = b""
                if isinstance(mask_size, int) and isinstance(mask_offset, int) and mask_size > 0:
                    mask_end = mask_offset + mask_size
                    if 0 <= mask_offset <= mask_end <= len(data):
                        mask = data[mask_offset:mask_end]
                sections.append(
                    OpjDataSection(
                        offset=element.start_offset,
                        length=max(0, element.end_offset - element.start_offset),
                        name=str(parsed_header["name"]),
                        data_type=int(parsed_header["data_type"]),
                        data_type2=int(parsed_header["data_type2"]),
                        total_rows=int(parsed_header["total_rows"]),
                        first_row=int(parsed_header["first_row"]),
                        last_row=int(parsed_header["last_row"]),
                        value_size=int(parsed_header["value_size"]),
                        data_type_u=int(parsed_header["data_type_u"]),
                        data_type3=int(parsed_header["data_type3"]),
                        values=values,
                        mask_offset=mask_offset if isinstance(mask_offset, int) else None,
                        mask=mask,
                    )
                )
                if max_sections is not None and len(sections) >= max_sections:
                    return sections, parse_failed
        except OpjStreamError:
            parse_failed = True
        return sections, parse_failed

    def _merge_sections(head: list[OpjDataSection], tail: list[OpjDataSection]) -> list[OpjDataSection]:
        by_span: dict[tuple[int, int], OpjDataSection] = {(item.offset, item.length): item for item in head}
        merged = list(head)
        for section in tail:
            key = (section.offset, section.length)
            if key not in by_span:
                by_span[key] = section
                merged.append(section)
        return merged

    try:
        walk_elements = opj_walker.walk_opj_file(data, tolerant=False)
    except OpjStreamError:
        parse_failed = True
    else:
        sections, parse_failed = _collect_sections(walk_elements)
        if sections and not parse_failed:
            return sections

    if parse_failed or not sections:
        try:
            walk_elements = opj_walker.walk_opj_file(data, tolerant=True)
        except OpjStreamError:
            walk_elements = []
        else:
            parse_failed = True
            additional_sections, parse_failed_fallback = _collect_sections(walk_elements)
            if sections:
                sections = _merge_sections(sections, additional_sections)
            else:
                sections = additional_sections
            parse_failed = parse_failed or parse_failed_fallback

    if parse_failed and sections:
        return sections

    if sections:
        return sections
    return sections


def _iter_opj_data_sections_cached(data: bytes, *, max_sections: int | None = None) -> list[OpjDataSection]:
    cache_key = (id(data), len(data), max_sections)
    cached = _OPJ_DATA_SECTION_CACHE.get(cache_key)
    if cached is not None:
        _OPJ_DATA_SECTION_CACHE.move_to_end(cache_key)
        return cached

    sections = _iter_opj_data_sections_uncached(data, max_sections=max_sections)
    _OPJ_DATA_SECTION_CACHE[cache_key] = sections
    while len(_OPJ_DATA_SECTION_CACHE) > _OPJ_DATA_SECTION_CACHE_SIZE:
        _OPJ_DATA_SECTION_CACHE.popitem(last=False)
    return sections


def iter_opj_data_sections(data: bytes, *, max_sections: int | None = None) -> list[OpjDataSection]:
    return [*_iter_opj_data_sections_cached(data, max_sections=max_sections)]
