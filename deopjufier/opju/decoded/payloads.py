"""Bounded classifiers for exact LZ4-decoded OPJU payload families."""

from __future__ import annotations

import hashlib
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MSER_STRINGS_PSET_MAGIC = 0x11111177
STYLE_HOLDER_SOURCE_INFO_MAGIC = 0x11111172
STYLE_HOLDER_SUBRECORD_MAGIC = 0x1111116D
STORAGE_CELL_REF_TYPE = 0x00000702
STORAGE_CELL_REF_SENTINEL = -999

_STYLE_DESCRIPTOR_SEMANTICS = {
    (1, 0): (
        "primary_plot_dataset_reference",
        "corpus_medium",
        "repeats the Y-source identity beside explicit X/Y binding descriptors",
    ),
    (2, 2): (
        "y_source_column_reference",
        "corpus_high",
        "selects the Y source in cross-serialization differential comparisons",
    ),
    (2, 1): (
        "x_source_column_reference",
        "corpus_high",
        "selects the X source in cross-serialization differential comparisons",
    ),
}


class OpjuPayloadError(ValueError):
    """Raised when a recognized decoded payload violates its byte grammar."""


@dataclass(frozen=True)
class OpjuDecodedPayload:
    """One decoded payload classification and its bounded structured fields."""

    family: str
    fields: dict[str, object]
    completeness: str
    verification: str

    @property
    def known(self) -> bool:
        return self.family not in {"unknown", "origin_storage_xml_invalid", "recognized_payload_invalid"}

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "completeness": self.completeness,
            "verification": self.verification,
            **self.fields,
        }


@dataclass
class _Cursor:
    data: bytes
    offset: int = 0

    def take(self, length: int) -> bytes:
        end = self.offset + length
        if length < 0 or end > len(self.data):
            raise OpjuPayloadError("decoded payload field exceeds its bounded record")
        payload = self.data[self.offset : end]
        self.offset = end
        return payload

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.take(8))[0]

    def u32s(self, count: int) -> list[int]:
        return [self.u32() for _ in range(count)]

    def f64s(self, count: int) -> list[float]:
        return [self.f64() for _ in range(count)]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise OpjuPayloadError(f"u32 at offset {offset} exceeds the decoded payload")
    return struct.unpack_from("<I", data, offset)[0]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_all(data: bytes, needle: bytes, *, start: int = 0, end: int | None = None) -> list[int]:
    positions: list[int] = []
    cursor = start
    stop = len(data) if end is None else end
    while (position := data.find(needle, cursor, stop)) >= 0:
        positions.append(position)
        cursor = position + 1
    return positions


def _decode_utf8(value: bytes, *, field: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OpjuPayloadError(f"{field} is not strict UTF-8") from exc


def parse_mser_strings_pset(data: bytes) -> dict[str, object] | None:
    """Parse the bounded ``0x11111177`` NUL-terminated string property set."""
    if len(data) < 28 or _u32(data, 0) != MSER_STRINGS_PSET_MAGIC:
        return None
    magic, version, flags_or_kind, unknown_0, unknown_1, blob_length, string_count = struct.unpack_from(
        "<IHHIIII", data
    )
    blob_end = 24 + blob_length
    if blob_end + 4 != len(data):
        raise OpjuPayloadError("0x11111177 string blob does not consume the decoded payload")
    blob = data[24:blob_end]
    parts = blob.split(b"\x00")
    if not parts or parts[-1] != b"":
        raise OpjuPayloadError("0x11111177 string blob lacks its final NUL")
    raw_strings = parts[:-1]
    if len(raw_strings) != string_count:
        raise OpjuPayloadError("0x11111177 string count does not match its blob")
    strings: list[str] = []
    string_records: list[dict[str, object]] = []
    decoded_offset = 24
    for index, raw_value in enumerate(raw_strings):
        value = _decode_utf8(raw_value, field="0x11111177 string")
        value_end = decoded_offset + len(raw_value)
        strings.append(value)
        string_records.append(
            {
                "index": index,
                "value": value,
                "decoded_range": {"start": decoded_offset, "end": value_end},
                "nul_offset": value_end,
            }
        )
        decoded_offset = value_end + 1
    return {
        "structural_name": "mser_strings_pset",
        "semantic_alias": "origin_string_property_set",
        "semantic_confidence": "wire_exact",
        "magic": f"0x{magic:08x}",
        "version": version,
        "flags_or_kind": flags_or_kind,
        "unknown_0": unknown_0,
        "unknown_1": unknown_1,
        "blob_byte_length": blob_length,
        "string_count": string_count,
        "strings": strings,
        "string_records": string_records,
        "terminator": _u32(data, blob_end),
    }


def _cell_ref_record(cursor: _Cursor, ordinal: int) -> dict[str, object]:
    payload_size = cursor.u32()
    if payload_size != 16:
        raise OpjuPayloadError("calculation-reference payload size is not 16")
    ref_type = cursor.u32()
    stored_ordinal = cursor.u32()
    sentinel = cursor.i32()
    calculation_uid = cursor.u32()
    terminator = cursor.u32()
    if (
        ref_type != STORAGE_CELL_REF_TYPE
        or stored_ordinal != ordinal
        or sentinel != STORAGE_CELL_REF_SENTINEL
        or terminator != 0
    ):
        raise OpjuPayloadError("calculation-reference invariant mismatch")
    return {
        "payload_size": payload_size,
        "ref_type": f"0x{ref_type:08x}",
        "analysis_result_reference_type_code": f"0x{ref_type:08x}",
        "ordinal": stored_ordinal,
        "analysis_result_slot_ordinal": stored_ordinal,
        "sentinel": sentinel,
        "unresolved_or_not_applicable_index_sentinel": sentinel,
        "calculation_uid": calculation_uid,
        "source_analysis_operation_uid": calculation_uid,
        "record_terminator": terminator,
    }


def parse_storage_cell_refs(data: bytes) -> dict[str, object] | None:
    """Parse the exact calculation-reference array observed in decoded records."""
    if len(data) < 12 or _u32(data, 0) != 0:
        return None
    count = _u32(data, 4)
    if count == 0 or count > 1024 or len(data) != 12 + count * 24:
        return None
    cursor = _Cursor(data, 8)
    try:
        records = [_cell_ref_record(cursor, ordinal) for ordinal in range(count)]
        array_terminator = cursor.u32()
    except OpjuPayloadError:
        return None
    if cursor.offset != len(data) or array_terminator != 0:
        return None
    return {
        "structural_name": "storage_cell_ref_data",
        "semantic_alias": "analysis_result_reference_array",
        "semantic_confidence": "corpus_high",
        "leading_zero": 0,
        "count": count,
        "records": records,
        "array_terminator": array_terminator,
    }


def _typed_descriptor(cursor: _Cursor, index: int) -> dict[str, object]:
    offset = cursor.offset
    words = cursor.u32s(10)
    typed_code = words[4]
    code_unit = typed_code & 0xFFFF
    character_hint = chr(code_unit) if 0x20 <= code_unit <= 0x7E else None
    semantics = _STYLE_DESCRIPTOR_SEMANTICS.get((words[0], words[1]))
    return {
        "index": index,
        "offset": offset,
        "length": 40,
        "words": words,
        "observed_role_word": words[0],
        "observed_subrole_word": words[1],
        "observed_column_ordinal": words[2],
        "column_ordinal_zero_based": words[2],
        "sentinel": words[3],
        "sentinel_interpretation": "unbounded_or_unspecified_index" if words[3] == 0x7FFFFFFF else "unknown",
        "typed_code": f"0x{typed_code:08x}",
        "typed_code_prefix": typed_code >> 16,
        "code_unit": code_unit,
        "character_hint": character_hint,
        "dataset_short_name_hint": character_hint,
        "semantic_role": semantics[0] if semantics else None,
        "semantic_alias": semantics[0] if semantics else None,
        "semantic_confidence": semantics[1] if semantics else None,
        "semantic_basis": semantics[2] if semantics else None,
        "reserved_words": words[5:],
    }


def _style_name(cursor: _Cursor) -> tuple[int, str]:
    offset = cursor.offset
    nul = cursor.data.find(b"\x00", offset)
    if nul < 0:
        raise OpjuPayloadError("style-holder sheet name lacks its final NUL")
    value = _decode_utf8(cursor.take(nul - offset), field="style-holder sheet name")
    cursor.take(1)
    return offset, value


def _style_tail(cursor: _Cursor) -> dict[str, object]:
    return {
        "u32_0": cursor.u32(),
        "u8_0": cursor.u8(),
        "u32_1": cursor.u32(),
        "u16_0": cursor.u16(),
        "u32_values": cursor.u32s(4),
        "f64_values": cursor.f64s(4),
    }


def _style_source_range(sheet_name: str, descriptors: list[dict[str, object]]) -> dict[str, object]:
    by_role = {
        descriptor["semantic_role"]: descriptor for descriptor in descriptors if descriptor["semantic_role"] is not None
    }
    x_descriptor = by_role.get("x_source_column_reference")
    y_descriptor = by_role.get("y_source_column_reference")
    return {
        "worksheet": sheet_name,
        "x_column_ordinal_zero_based": x_descriptor["column_ordinal_zero_based"] if x_descriptor else None,
        "x_column_short_name": x_descriptor["dataset_short_name_hint"] if x_descriptor else None,
        "y_column_ordinal_zero_based": y_descriptor["column_ordinal_zero_based"] if y_descriptor else None,
        "y_column_short_name": y_descriptor["dataset_short_name_hint"] if y_descriptor else None,
        "binding_semantics": "persistent style-holder source slot; not necessarily a current curve",
    }


def _parse_style_subrecord(data: bytes, index: int) -> dict[str, object]:
    cursor = _Cursor(data)
    if cursor.u32() != STYLE_HOLDER_SUBRECORD_MAGIC:
        raise OpjuPayloadError("style-holder child magic mismatch")
    version = cursor.u16()
    flags_or_kind = cursor.u16()
    record_index = cursor.u32()
    preamble_words = cursor.u32s(7)
    descriptor_count = cursor.u32()
    if descriptor_count == 0 or descriptor_count > 1024:
        raise OpjuPayloadError("style-holder descriptor count is implausible")
    descriptors = [_typed_descriptor(cursor, descriptor_index) for descriptor_index in range(descriptor_count)]
    pre_name_words = cursor.u32s(3)
    pre_name_byte = cursor.u8()
    sheet_name_offset, sheet_name = _style_name(cursor)
    post_name_words = cursor.u32s(4)
    opaque_blob_offset = cursor.offset
    opaque_blob = cursor.take(post_name_words[3])
    tail = _style_tail(cursor)
    if cursor.offset != len(data):
        raise OpjuPayloadError("style-holder child has unconsumed bytes")
    return {
        "index": index,
        "semantic_name": "data_plot_style_holder_source_slot_v1",
        "length": len(data),
        "sha256": _sha256(data),
        "magic": f"0x{STYLE_HOLDER_SUBRECORD_MAGIC:08x}",
        "version": version,
        "flags_or_kind": flags_or_kind,
        "record_index": record_index,
        "slot_index_zero_based": record_index,
        "record_index_alias": "style_holder_plot_slot_index_zero_based",
        "record_index_confidence": "high",
        "preamble_words": preamble_words,
        "descriptor_count": descriptor_count,
        "reference_descriptors": descriptors,
        "pre_name_words": pre_name_words,
        "pre_name_byte": pre_name_byte,
        "sheet_name_offset": sheet_name_offset,
        "sheet_name": sheet_name,
        "source_range": _style_source_range(sheet_name, descriptors),
        "post_name_words": post_name_words,
        "opaque_blob_offset": opaque_blob_offset,
        "opaque_blob_length": len(opaque_blob),
        "opaque_blob_hex": opaque_blob.hex(),
        "tail": tail,
        "semantic_status": (
            "source-slot and X/Y descriptor roles have differential evidence; "
            "neutral preamble, tail, flag, and blob names remain provisional"
        ),
    }


def parse_style_holder_source_info(data: bytes) -> dict[str, object] | None:
    """Parse the bounded ``0x11111172`` style-holder source record."""
    if len(data) < 24 or _u32(data, 0) != STYLE_HOLDER_SOURCE_INFO_MAGIC:
        return None
    subrecord_count = _u32(data, 12)
    if subrecord_count == 0 or subrecord_count > 1024 or _u32(data, len(data) - 4) != 0:
        raise OpjuPayloadError("style-holder parent framing is invalid")
    child_magic = struct.pack("<I", STYLE_HOLDER_SUBRECORD_MAGIC)
    starts = _find_all(data, child_magic, start=16, end=len(data) - 4)
    if len(starts) != subrecord_count or starts[0] != 16:
        raise OpjuPayloadError("style-holder child boundaries do not match the declared count")
    payload_end = len(data) - 4
    ends = [*starts[1:], payload_end]
    subrecords = [
        _parse_style_subrecord(data[start:end], index)
        for index, (start, end) in enumerate(zip(starts, ends, strict=True))
    ]
    for record, start, end in zip(subrecords, starts, ends, strict=True):
        record["offset"] = start
        record["end"] = end
    return {
        "semantic_name": "data_plot_style_holder_source_info_v1",
        "structural_name": "data_plot_style_holder_source_info",
        "semantic_alias": "data_plot_style_prototype_source_binding",
        "object_role": "persistent graph-layer data-plot style-holder source metadata",
        "semantic_confidence": "corpus_high",
        "semantic_basis": "cross-serialization differential against independently parsed legacy project structure",
        "magic": f"0x{STYLE_HOLDER_SOURCE_INFO_MAGIC:08x}",
        "header_word_1": f"0x{_u32(data, 4):08x}",
        "header_word_2": f"0x{_u32(data, 8):08x}",
        "subrecord_count": subrecord_count,
        "subrecords": subrecords,
        "source_slots": [record["source_range"] for record in subrecords],
        "outer_terminator": 0,
        "semantic_status": (
            "object role and source-slot bindings have differential evidence; exact private names for neutral scalar "
            "fields remain unknown"
        ),
    }


def _classify_origin_storage_xml(data: bytes) -> OpjuDecodedPayload | None:
    if not data.startswith(b"<OriginStorage"):
        return None
    nul_terminated = data.endswith(b"\x00")
    xml = data[:-1] if nul_terminated else data
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return OpjuDecodedPayload(
            family="origin_storage_xml_invalid",
            fields={"error": str(exc), "length": len(data), "sha256": _sha256(data)},
            completeness="partial",
            verification="unverified",
        )
    return OpjuDecodedPayload(
        family="origin_storage_xml",
        fields={
            "length": len(data),
            "xml_length": len(xml),
            "nul_terminated": nul_terminated,
            "sha256": _sha256(data),
            "root_attributes": dict(root.attrib),
        },
        completeness="complete",
        verification="exact",
    )


def classify_decoded_payload(data: bytes) -> OpjuDecodedPayload:
    """Classify one exact decoded payload without guessing unknown bytes."""
    if (xml := _classify_origin_storage_xml(data)) is not None:
        return xml
    parsers = (
        ("mser_strings_pset", parse_mser_strings_pset),
        ("storage_cell_ref_data", parse_storage_cell_refs),
        ("style_holder_source_info_v1", parse_style_holder_source_info),
    )
    for family, parser in parsers:
        try:
            fields = parser(data)
        except OpjuPayloadError as exc:
            return OpjuDecodedPayload(
                family="recognized_payload_invalid",
                fields={"candidate_family": family, "error": str(exc), "length": len(data)},
                completeness="partial",
                verification="unverified",
            )
        if fields is not None:
            return OpjuDecodedPayload(
                family=family,
                fields={"length": len(data), "sha256": _sha256(data), **fields},
                completeness="complete",
                verification="exact",
            )
    return OpjuDecodedPayload(
        family="unknown",
        fields={"length": len(data), "sha256": _sha256(data), "prefix_hex": data[:32].hex()},
        completeness="partial",
        verification="unverified",
    )


__all__ = [
    "MSER_STRINGS_PSET_MAGIC",
    "STORAGE_CELL_REF_SENTINEL",
    "STORAGE_CELL_REF_TYPE",
    "STYLE_HOLDER_SOURCE_INFO_MAGIC",
    "STYLE_HOLDER_SUBRECORD_MAGIC",
    "OpjuDecodedPayload",
    "OpjuPayloadError",
    "classify_decoded_payload",
    "parse_mser_strings_pset",
    "parse_storage_cell_refs",
    "parse_style_holder_source_info",
]
