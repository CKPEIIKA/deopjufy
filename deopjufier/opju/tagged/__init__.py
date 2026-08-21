"""Bounded OPJU tagged-binary envelopes and explicit string fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from .column_payloads import OpjuColumnPayload, decode_opju_column_payload

_TAGGED_FAMILY_SIGNATURES = (
    ("tagged_header_27_01", bytes.fromhex("27 01 6c c0 11 01 06 80")),
    ("tagged_86_01", bytes.fromhex("86 01 02 80 01 18 80 01")),
    ("tagged_00_04_8c", bytes.fromhex("00 04 8c 01 33 c0 11 01")),
    ("tagged_00_00_10", bytes.fromhex("00 00 10 00 00 01 95 04")),
)
_COLUMN_NAME_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_@-]{1,63}")
_LEGACY_COLUMN_NAME_RE = re.compile(rb"(?:N2N|O2O)_[A-Z](?:@\d+)?")
_COLUMN_ROW_PREFIX = b"\x18\x18" + b"\0" * 7
_COLUMN_SYSTEM_PRELUDE_MARKER = b"\x01\x0bSYSTEM"


@dataclass(frozen=True)
class OpjuTaggedString:
    """An explicitly length-framed, NUL-terminated UTF-8 field."""

    offset: int
    length: int
    tag_code: int
    value: str


@dataclass(frozen=True)
class OpjuTaggedScalar:
    """An exact ``FIELD c0 11 SIZE DESCRIPTOR VALUE`` wire frame."""

    offset: int
    end_offset: int
    field_code: int
    declared_size: int
    descriptor_hex: str
    value_width: int
    value_hex: str
    little_endian_unsigned: int | None


@dataclass(frozen=True)
class OpjuTaggedEnvelope:
    """An exact binary envelope between already bounded OPJU records."""

    family: str
    start_offset: int
    end_offset: int
    sha256: str
    strings: tuple[OpjuTaggedString, ...]
    scalars: tuple[OpjuTaggedScalar, ...]
    semantic_status: str


@dataclass(frozen=True)
class OpjuColumnDescriptor:
    """A bounded OPJU column record with an explicitly sized stored payload."""

    name: str
    start_offset: int
    end_offset: int
    name_offset: int
    stored_payload_length_offset: int
    stored_payload_length: int
    payload_prelude: str
    payload_offset: int
    payload_end: int
    header_signature: str
    row_capacity: int | None
    stored_value_count: int | None
    first_control_byte: int | None
    first_value: float | int | str | None
    decoded_payload: OpjuColumnPayload | None


def _merged_ranges(ranges: list[tuple[int, int]], file_size: int) -> list[tuple[int, int]]:
    bounded = sorted((max(0, start), min(end, file_size)) for start, end in ranges if end > start)
    merged: list[tuple[int, int]] = []
    for start, end in bounded:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _gap_ranges(ranges: list[tuple[int, int]], file_size: int) -> list[tuple[int, int]]:
    merged = _merged_ranges(ranges, file_size)
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < file_size:
        gaps.append((cursor, file_size))
    return gaps


def _family(payload: bytes) -> str | None:
    for family, signature in _TAGGED_FAMILY_SIGNATURES:
        if payload.startswith(signature):
            return family
    if payload.startswith(b"\xfa") and _COLUMN_SYSTEM_PRELUDE_MARKER in payload[:64]:
        return "tagged_system_prelude"
    if payload.startswith(b"</") and payload.endswith(b">") and all(_is_text_byte(value) for value in payload):
        return "xml_close_fragment"
    if (
        payload.startswith(b"</")
        and payload.endswith(b">")
        and 0x7F in payload
        and all(_is_text_byte(value) or value == 0x7F for value in payload)
    ):
        return "malformed_xml_close_fragment"
    return None


def _semantic_status(family: str) -> str:
    if family == "xml_close_fragment":
        return "decoded_xml_framing"
    if family == "malformed_xml_close_fragment":
        return "corrupt_xml_framing_preserved"
    return "fields_partial"


def _is_text_byte(value: int) -> bool:
    return value in {9, 10, 13} or 32 <= value < 127


def iter_tagged_strings(payload: bytes, *, source_start: int = 0) -> tuple[OpjuTaggedString, ...]:
    """Return exact short-string fields using the observed ``LEN 80 TAG DATA`` rule."""
    strings: list[OpjuTaggedString] = []
    for offset in range(max(0, len(payload) - 3)):
        length = payload[offset]
        if length < 2 or payload[offset + 1] != 0x80:
            continue
        data_start = offset + 3
        data_end = data_start + length
        if data_end > len(payload):
            continue
        raw_value = payload[data_start:data_end]
        if raw_value[-1:] != b"\0" or not all(_is_text_byte(value) for value in raw_value[:-1]):
            continue
        try:
            value = raw_value[:-1].decode("utf-8")
        except UnicodeDecodeError:
            continue
        strings.append(
            OpjuTaggedString(
                offset=source_start + data_start,
                length=length,
                tag_code=payload[offset + 2],
                value=value,
            )
        )
    return tuple(strings)


def iter_tagged_scalars(payload: bytes, *, source_start: int = 0) -> tuple[OpjuTaggedScalar, ...]:
    """Return exact scalar wire frames using their self-bounding size byte."""
    scalars: list[OpjuTaggedScalar] = []
    marker = b"\xc0\x11"
    offset = 0
    while (marker_offset := payload.find(marker, offset)) >= 0:
        offset = marker_offset + len(marker)
        if marker_offset == 0 or offset >= len(payload):
            continue
        declared_size = payload[offset]
        frame_end = offset + declared_size
        if frame_end > len(payload):
            continue
        framed = payload[offset + 1 : frame_end]
        if declared_size == 1:
            descriptor = b""
            value = b""
        elif declared_size == 3 and framed == b"\0\0":
            descriptor = framed
            value = b""
        elif declared_size == 4 and framed == b"\x02\0\x01":
            descriptor = framed
            value = b""
        elif declared_size in {5, 6, 9, 13, 21} and framed[2:4] == b"\x01\0":
            descriptor = framed[:4]
            value = framed[4:]
        else:
            continue
        scalars.append(
            OpjuTaggedScalar(
                offset=source_start + marker_offset - 1,
                end_offset=source_start + frame_end,
                field_code=payload[marker_offset - 1],
                declared_size=declared_size,
                descriptor_hex=descriptor.hex(" "),
                value_width=len(value),
                value_hex=value.hex(" "),
                little_endian_unsigned=int.from_bytes(value, "little") if value else None,
            )
        )
    return tuple(scalars)


def iter_opju_tagged_envelopes(
    data: bytes,
    bounded_ranges: list[tuple[int, int]],
) -> tuple[OpjuTaggedEnvelope, ...]:
    """Decode recognized tagged envelopes from exact gaps between bounded records.

    A gap is promoted only when its first bytes match a family signature observed
    repeatedly in both private and public OPJU fixtures. Contents without an
    explicit field rule remain bytes inside the bounded envelope.
    """
    envelopes: list[OpjuTaggedEnvelope] = []
    for start, end in _gap_ranges(bounded_ranges, len(data)):
        payload = data[start:end]
        family = _family(payload)
        if family is None:
            continue
        envelopes.append(
            OpjuTaggedEnvelope(
                family=family,
                start_offset=start,
                end_offset=end,
                sha256=sha256(payload).hexdigest(),
                strings=iter_tagged_strings(payload, source_start=start),
                scalars=iter_tagged_scalars(payload, source_start=start),
                semantic_status=_semantic_status(family),
            )
        )
    return tuple(envelopes)


def _column_name_match(data: bytes, prefix_offset: int) -> re.Match[bytes] | None:
    search_start = max(0, prefix_offset - 80)
    matches: list[re.Match[bytes]] = []
    for pattern in (_COLUMN_NAME_RE, _LEGACY_COLUMN_NAME_RE):
        for match in pattern.finditer(data, search_start, prefix_offset):
            framed = match.start() > 0 and data[match.start() - 1] == len(match.group())
            legacy = _LEGACY_COLUMN_NAME_RE.fullmatch(match.group()) is not None
            if (framed or legacy) and prefix_offset - match.end() <= 16:
                matches.append(match)
    return max(matches, key=lambda item: (item.end(), item.start()), default=None)


def iter_opju_column_descriptors(data: bytes) -> tuple[OpjuColumnDescriptor, ...]:
    """Decode ASCII column names and their explicitly sized stored payloads."""
    descriptors: list[OpjuColumnDescriptor] = []
    previous_payload_end: int | None = None
    for prefix_match in re.finditer(re.escape(_COLUMN_ROW_PREFIX), data):
        prefix_offset = prefix_match.start()
        name_match = _column_name_match(data, prefix_offset)
        if name_match is None:
            continue
        stored_length_offset = prefix_match.end()
        stored_length_end = stored_length_offset + 8
        payload_offset = stored_length_end + 8
        if payload_offset > len(data):
            continue
        stored_payload_length = int.from_bytes(data[stored_length_offset:stored_length_end], "little")
        payload_end = payload_offset + stored_payload_length
        if not 0 < stored_payload_length <= 10_000_000 or payload_end > len(data):
            continue
        start_offset = (
            name_match.start() - 1
            if name_match.start() > 0 and data[name_match.start() - 1] == len(name_match.group())
            else name_match.start()
        )
        if previous_payload_end is not None:
            gap_length = name_match.start() - previous_payload_end
            gap = data[previous_payload_end : name_match.start()]
            short_continuation = 0 <= gap_length <= 64
            system_prelude = (
                0 < gap_length <= 512 and gap.startswith(b"\xfa") and _COLUMN_SYSTEM_PRELUDE_MARKER in gap[:64]
            )
            if short_continuation or system_prelude:
                start_offset = previous_payload_end
        payload = data[payload_offset:payload_end]
        decoded_payload = decode_opju_column_payload(payload)
        row_capacity = decoded_payload.row_capacity if decoded_payload is not None else None
        stored_value_count = decoded_payload.stored_value_count if decoded_payload is not None else None
        first_control_byte = decoded_payload.first_control_byte if decoded_payload is not None else None
        first_value = None
        if decoded_payload is not None:
            first_value = next((value for value in decoded_payload.values if value is not None), None)
        descriptors.append(
            OpjuColumnDescriptor(
                name=name_match.group().decode("ascii"),
                start_offset=start_offset,
                end_offset=payload_end,
                name_offset=name_match.start(),
                stored_payload_length_offset=stored_length_offset,
                stored_payload_length=stored_payload_length,
                payload_prelude=data[stored_length_end:payload_offset].hex(" "),
                payload_offset=payload_offset,
                payload_end=payload_end,
                header_signature=data[name_match.end() : stored_length_offset].hex(" "),
                row_capacity=row_capacity,
                stored_value_count=stored_value_count,
                first_control_byte=first_control_byte,
                first_value=first_value,
                decoded_payload=decoded_payload,
            )
        )
        previous_payload_end = payload_end
    return tuple(descriptors)


__all__ = [
    "OpjuColumnDescriptor",
    "OpjuTaggedEnvelope",
    "OpjuTaggedScalar",
    "OpjuTaggedString",
    "iter_opju_column_descriptors",
    "iter_opju_tagged_envelopes",
    "iter_tagged_scalars",
    "iter_tagged_strings",
]


from .tables import (  # noqa: E402
    OpjuColumnIdentity,
    OpjuColumnMetadata,
    OpjuDescriptorColumn,
    OpjuDescriptorTable,
    group_opju_column_descriptors,
    iter_opju_column_metadata,
    opju_column_post_payload_range,
    parse_opju_column_identity,
)

__all__ += [
    "OpjuColumnIdentity",
    "OpjuColumnMetadata",
    "OpjuDescriptorColumn",
    "OpjuDescriptorTable",
    "group_opju_column_descriptors",
    "iter_opju_column_metadata",
    "opju_column_post_payload_range",
    "parse_opju_column_identity",
]
