"""Build parser-owned worksheets from decoded OPJU column descriptors."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import OpjuColumnDescriptor

_DATASET_NAME_RE = re.compile(r"(?P<workbook>[A-Za-z][A-Za-z0-9_.-]*)_(?P<column>[A-Z]+)(?:@(?P<sheet>[1-9][0-9]*))?")
_DISPLAY_NAME_RE = re.compile(rb"([A-Z]{1,3})\x88\x01\x09")
_COLUMN_METADATA_MARKERS = ((b"\x10\x80\x03", 3), (b"\x10\x01\x00\x00", 4))
_COLUMN_LABEL_RE = re.compile(rb"[\x99\x9a]\x01\x00\x0a")
_SYSTEM_MARKER = b"\x0bSYSTEM\x03\x00\x8e\x02\x01"
_STORAGE_CELL_REFERENCE_MARKER = b"_Storage_Cell_Ref_Data_"
_STRING_PROPERTY_SET_MARKER = b"#_MSER_STRINGS_PSET"
_SYSTEM_TEXT_FIELDS = {
    "long_name": b"\xa6\x02\x03",
    "units": b"\xa8\x02\x03",
    "comment": b"\xaa\x02\x03",
    "display_name": b"\xb0\x02\x03",
    "workbook": b"\xc8\x02\x03",
    "workbook_long_name": b"\xca\x02\x03",
    "sheet_long_name": b"\xcc\x02\x03",
}


@dataclass(frozen=True)
class OpjuColumnMetadata:
    """Column metadata bound by an explicit one-based descriptor ordinal."""

    descriptor_ordinal: int
    display_name: str | None = None
    designation: str | None = None
    long_name: str | None = None
    units: str | None = None
    comment: str | None = None
    formula: str | None = None
    workbook: str | None = None
    workbook_long_name: str | None = None
    sheet_long_name: str | None = None
    source_ranges: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class _ColumnMetadataCandidate:
    start: int
    ordinal: int
    display_name: str
    designation: str
    display_end: int


@dataclass(frozen=True)
class OpjuColumnIdentity:
    """Ownership encoded directly by an OPJU dataset name."""

    dataset_name: str
    workbook: str
    sheet_index: int
    column_name: str
    column_index: int


@dataclass(frozen=True)
class OpjuDescriptorColumn:
    """One decoded column and its exact source descriptor."""

    identity: OpjuColumnIdentity
    descriptor: OpjuColumnDescriptor
    display_index: int
    metadata: OpjuColumnMetadata | None = None

    @property
    def display_name(self) -> str:
        if self.metadata is not None and self.metadata.display_name is not None:
            return self.metadata.display_name
        return _column_name(self.display_index)

    @property
    def long_name(self) -> str | None:
        return self.metadata.long_name if self.metadata is not None else None

    @property
    def units(self) -> str | None:
        return self.metadata.units if self.metadata is not None else None

    @property
    def designation(self) -> str | None:
        return self.metadata.designation if self.metadata is not None else None

    @property
    def formula(self) -> str | None:
        return self.metadata.formula if self.metadata is not None else None

    @property
    def value_type(self) -> str:
        payload = self.descriptor.decoded_payload
        if payload is None:
            return "unsupported"
        kinds = set(payload.cell_kinds) - {"missing"}
        if not kinds:
            return "empty"
        if kinds == {"float64"}:
            return "numeric"
        if kinds == {"utf8"}:
            return "text"
        if kinds == {"unsigned_integer"}:
            return "unsigned_integer"
        return "mixed"


@dataclass(frozen=True)
class OpjuDescriptorTable:
    """A complete worksheet assembled from contiguous A..N dataset columns."""

    workbook: str
    sheet_index: int
    columns: tuple[OpjuDescriptorColumn, ...]

    @property
    def name(self) -> str:
        return f"{self.workbook}/Sheet{self.sheet_index}"

    @property
    def row_count(self) -> int:
        return max(
            (
                column.descriptor.decoded_payload.row_capacity
                for column in self.columns
                if column.descriptor.decoded_payload
            ),
            default=0,
        )

    @property
    def source_ranges(self) -> list[dict[str, int]]:
        return [
            {"start": column.descriptor.start_offset, "end": column.descriptor.end_offset} for column in self.columns
        ]

    def text_rows(self) -> list[list[str]]:
        """Return rectangular rows using empty fields only for explicit missing cells."""
        rows: list[list[str]] = []
        for row_index in range(self.row_count):
            row: list[str] = []
            for column in self.columns:
                payload = column.descriptor.decoded_payload
                value = payload.values[row_index] if payload is not None and row_index < len(payload.values) else None
                row.append("" if value is None else str(value))
            rows.append(row)
        return rows

    @property
    def has_values(self) -> bool:
        return any(
            kind != "missing"
            for column in self.columns
            if column.descriptor.decoded_payload is not None
            for kind in column.descriptor.decoded_payload.cell_kinds
        )


def _column_index(name: str) -> int:
    index = 0
    for character in name:
        index = index * 26 + ord(character) - ord("A") + 1
    return index


def _column_name(index: int) -> str:
    characters: list[str] = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        characters.append(chr(ord("A") + remainder))
    return "".join(reversed(characters))


def _decode_varuint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(data):
            return None
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    return None


def _decode_utf8_field(raw: bytes) -> str | None:
    if not raw or b"\0" in raw:
        return None
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(character) < 32 and character not in "\t\r\n" for character in value):
        return None
    return value


def _metadata_candidates(data: bytes, descriptor_count: int) -> tuple[_ColumnMetadataCandidate, ...]:
    candidates: list[_ColumnMetadataCandidate] = []
    for marker, ordinal_width in _COLUMN_METADATA_MARKERS:
        for match in re.finditer(re.escape(marker), data):
            ordinal_start = match.start() + ordinal_width
            ordinal_end = ordinal_start + 2
            if ordinal_end > len(data):
                continue
            ordinal = int.from_bytes(data[ordinal_start:ordinal_end], "little")
            if not 1 <= ordinal <= descriptor_count:
                continue
            display_match = _DISPLAY_NAME_RE.search(data, ordinal_end, min(len(data), ordinal_end + 48))
            if display_match is None:
                continue
            designation_start = display_match.end()
            designation_end = min(len(data), designation_start + 24)
            designation_frame = re.search(rb"\x21([\x51\x61])", data[designation_start:designation_end])
            if designation_frame is None:
                continue
            candidates.append(
                _ColumnMetadataCandidate(
                    start=match.start(),
                    ordinal=ordinal,
                    display_name=display_match.group(1).decode("ascii"),
                    designation="X" if designation_frame.group(1) == b"Q" else "Y",
                    display_end=display_match.end(),
                )
            )
    return tuple(sorted(candidates, key=lambda candidate: candidate.start))


def _column_label(data: bytes, candidate: _ColumnMetadataCandidate, end: int) -> tuple[str | None, int]:
    label_match = _COLUMN_LABEL_RE.search(data, candidate.display_end, end)
    if label_match is None:
        return None, candidate.display_end
    outer_length_offset = label_match.end()
    if outer_length_offset >= end:
        return None, candidate.display_end
    outer_length = data[outer_length_offset]
    if outer_length == 0:
        return None, outer_length_offset + 1
    inner_length_offset = outer_length_offset + 1
    if inner_length_offset >= end:
        return None, candidate.display_end
    inner_length = data[inner_length_offset]
    value_start = inner_length_offset + 1
    value_end = value_start + inner_length
    if outer_length != inner_length + 1 or inner_length < 1 or value_end > end:
        return None, candidate.display_end
    raw = data[value_start:value_end]
    if raw[-1:] != b"\0":
        return None, candidate.display_end
    return _decode_utf8_field(raw[:-1]), value_end


def _bounded_post_descriptor_envelope(data: bytes, descriptor: OpjuColumnDescriptor) -> tuple[bytes, int] | None:
    start = descriptor.payload_end
    if start >= len(data) or data[start] != 0xFA:
        return None
    decoded_length = _decode_varuint(data, start + 1)
    if decoded_length is None:
        return None
    length, version_offset = decoded_length
    if version_offset >= len(data) or data[version_offset] != 1:
        return None
    body_start = version_offset + 1
    body_end = body_start + length
    if body_end > len(data):
        return None
    return data[body_start:body_end], body_end


def opju_column_post_payload_range(
    data: bytes,
    descriptor: OpjuColumnDescriptor,
) -> tuple[int, int] | None:
    """Return the exact bounded envelope immediately owned by a descriptor."""
    envelope = _bounded_post_descriptor_envelope(data, descriptor)
    if envelope is None:
        return None
    _body, envelope_end = envelope
    return descriptor.payload_end, envelope_end


def _system_text_field(body: bytes, marker: bytes) -> str | None:
    offset = body.find(marker)
    if offset < 0:
        return None
    decoded_length = _decode_varuint(body, offset + len(marker))
    if decoded_length is None:
        return None
    length, value_start = decoded_length
    value_end = value_start + length
    if value_end > len(body):
        return None
    return _decode_utf8_field(body[value_start:value_end])


def _system_fields(body: bytes) -> dict[str, str]:
    if _SYSTEM_MARKER not in body:
        return {}
    fields: dict[str, str] = {}
    for name, marker in _SYSTEM_TEXT_FIELDS.items():
        value = _system_text_field(body, marker)
        if value is not None:
            fields[name] = value
    return fields


def _cell_formula(body: bytes) -> str | None:
    if _STORAGE_CELL_REFERENCE_MARKER not in body:
        return None
    marker_offset = body.find(_STRING_PROPERTY_SET_MARKER)
    header_start = marker_offset + len(_STRING_PROPERTY_SET_MARKER)
    if marker_offset < 0 or body[header_start : header_start + 2] != b"\x05\x01":
        return None
    record_length = int.from_bytes(body[header_start + 2 : header_start + 4], "little")
    payload_length = int.from_bytes(body[header_start + 4 : header_start + 8], "little")
    payload_start = header_start + 8
    payload_end = payload_start + payload_length
    if record_length != payload_length + 3 or payload_length < 23 or payload_end > len(body):
        return None
    payload = body[payload_start:payload_end]
    text_length = int.from_bytes(payload[15:19], "little")
    text_count = int.from_bytes(payload[19:23], "little")
    text_end = 23 + text_length
    if text_count != 1 or text_length < 2 or text_end > len(payload) or any(payload[text_end:]):
        return None
    raw = payload[23:text_end]
    if raw[-1:] != b"\0":
        return None
    formula = _decode_utf8_field(raw[:-1])
    return formula if formula is not None and formula.startswith("=") else None


def iter_opju_column_metadata(
    data: bytes,
    descriptors: tuple[OpjuColumnDescriptor, ...],
) -> tuple[OpjuColumnMetadata, ...]:
    """Decode metadata records with ordinal or exact post-descriptor ownership."""
    candidates = _metadata_candidates(data, len(descriptors))
    ordinal_counts = Counter(candidate.ordinal for candidate in candidates)
    duplicate_ordinals = {ordinal for ordinal, count in ordinal_counts.items() if count > 1}
    fields_by_ordinal: dict[int, dict[str, str]] = {}
    ranges_by_ordinal: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        if candidate.ordinal in duplicate_ordinals:
            continue
        record_end = min(
            candidates[index + 1].start if index + 1 < len(candidates) else len(data),
            candidate.start + 256,
        )
        long_name, semantic_end = _column_label(data, candidate, record_end)
        fields = fields_by_ordinal.setdefault(candidate.ordinal, {})
        fields.update(display_name=candidate.display_name, designation=candidate.designation)
        if long_name is not None:
            fields["long_name"] = long_name
        ranges_by_ordinal[candidate.ordinal].append((candidate.start, semantic_end))

    for ordinal, descriptor in enumerate(descriptors, start=1):
        envelope = _bounded_post_descriptor_envelope(data, descriptor)
        if envelope is None:
            continue
        body, envelope_end = envelope
        system_fields = _system_fields(body)
        formula = _cell_formula(body)
        if not system_fields and formula is None:
            continue
        fields = fields_by_ordinal.setdefault(ordinal, {})
        for name, value in system_fields.items():
            fields.setdefault(name, value)
        if formula is not None:
            fields["formula"] = formula
        ranges_by_ordinal[ordinal].append((descriptor.payload_end, envelope_end))

    return tuple(
        OpjuColumnMetadata(
            descriptor_ordinal=ordinal,
            source_ranges=tuple(ranges_by_ordinal[ordinal]),
            **fields,
        )
        for ordinal, fields in sorted(fields_by_ordinal.items())
    )


def parse_opju_column_identity(dataset_name: str) -> OpjuColumnIdentity | None:
    """Parse ``Workbook_COLUMN@SHEET`` without proximity or scan evidence."""
    match = _DATASET_NAME_RE.fullmatch(dataset_name)
    if match is None:
        return None
    column_name = match.group("column")
    return OpjuColumnIdentity(
        dataset_name=dataset_name,
        workbook=match.group("workbook"),
        sheet_index=int(match.group("sheet") or 1),
        column_name=column_name,
        column_index=_column_index(column_name),
    )


def group_opju_column_descriptors(
    descriptors: tuple[OpjuColumnDescriptor, ...],
    metadata: tuple[OpjuColumnMetadata, ...] = (),
) -> tuple[OpjuDescriptorTable, ...]:
    """Return only complete, uniquely owned, contiguous descriptor tables."""
    metadata_by_ordinal = {item.descriptor_ordinal: item for item in metadata}
    grouped: dict[tuple[str, int], list[OpjuDescriptorColumn]] = defaultdict(list)
    rejected_groups: set[tuple[str, int]] = set()
    for ordinal, descriptor in enumerate(descriptors, start=1):
        identity = parse_opju_column_identity(descriptor.name)
        if identity is None:
            continue
        key = (identity.workbook, identity.sheet_index)
        if descriptor.decoded_payload is None:
            rejected_groups.add(key)
            continue
        grouped[key].append(
            OpjuDescriptorColumn(
                identity=identity,
                descriptor=descriptor,
                display_index=0,
                metadata=metadata_by_ordinal.get(ordinal),
            )
        )

    tables: list[OpjuDescriptorTable] = []
    for key, columns in grouped.items():
        if key in rejected_groups:
            continue
        indices = sorted(column.identity.column_index for column in columns)
        if indices != list(range(1, len(columns) + 1)):
            continue
        if len(set(indices)) != len(indices):
            continue
        logical_columns = sorted(columns, key=lambda column: column.identity.column_index)
        display_columns = tuple(
            OpjuDescriptorColumn(
                identity=column.identity,
                descriptor=column.descriptor,
                display_index=display_index,
                metadata=column.metadata,
            )
            for display_index, column in enumerate(logical_columns, start=1)
        )
        tables.append(OpjuDescriptorTable(workbook=key[0], sheet_index=key[1], columns=display_columns))
    return tuple(sorted(tables, key=lambda table: (table.workbook.casefold(), table.workbook, table.sheet_index)))


__all__ = [
    "OpjuColumnIdentity",
    "OpjuColumnMetadata",
    "OpjuDescriptorColumn",
    "OpjuDescriptorTable",
    "group_opju_column_descriptors",
    "iter_opju_column_metadata",
    "opju_column_post_payload_range",
    "parse_opju_column_identity",
]
