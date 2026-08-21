"""Decode bounded typed column payloads used by CPYUA files."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

_NUMERIC_COLUMN_PAYLOAD_PREFIX = b"\x0a\x05"
_VARUINT_COLUMN_PAYLOAD_PREFIX = b"\x0a\x04"
_FULL_MASK = (1 << 64) - 1
_FPC_PREDICTOR_BITS = 12
_OBSERVED_ONE_RUN = b"\x1a\xf0\x3f"
_ORIGIN_MISSING_BITS = struct.unpack("<Q", struct.pack("<d", -1.23456789e-300))[0]
_COMPACT_SCALAR_BYTES = {0x1A: 2, 0x23: 3, 0x3E: 6, 0x47: 7, 0x50: 8}


@dataclass(frozen=True)
class OpjuColumnPayload:
    """An exact CPYUA column payload decoded to typed cells and trailing blanks."""

    encoding: str
    row_capacity: int
    stored_value_count: int
    missing_count: int
    trailing_missing_count: int
    repeated_prefix_count: int
    first_control_byte: int | None
    values: tuple[float | int | str | None, ...]
    value_bits: tuple[str | None, ...]
    cell_kinds: tuple[str, ...]


@dataclass
class _FpcState:
    fcm: list[int]
    dfcm: list[int]
    table_mask: int
    fcm_hash: int = 0
    dfcm_hash: int = 0
    last_value: int = 0
    fcm_prediction: int = 0
    dfcm_prediction: int = 0

    def decode(self, code: int, residual: int) -> int:
        prediction = self.dfcm_prediction if code & 0x08 else self.fcm_prediction
        value = residual ^ prediction
        self.fcm[self.fcm_hash] = value
        self.fcm_hash = ((self.fcm_hash << 6) ^ (value >> 48)) & self.table_mask
        self.fcm_prediction = self.fcm[self.fcm_hash]
        stride = (value - self.last_value) & _FULL_MASK
        self.dfcm[self.dfcm_hash] = stride
        self.dfcm_hash = ((self.dfcm_hash << 2) ^ (stride >> 40)) & self.table_mask
        self.dfcm_prediction = (value + self.dfcm[self.dfcm_hash]) & _FULL_MASK
        self.last_value = value
        return value


def _stored_byte_count(code: int) -> int:
    byte_code = code & 0x07
    return byte_code + (byte_code >> 2)


def _decode_varuint(payload: bytes, offset: int) -> tuple[int, int] | None:
    """Decode the unsigned base-128 integers used by column framing."""
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(payload):
            return None
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    return None


def _encode_varuint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_row_and_stored_count(payload: bytes) -> tuple[int, int, int] | None:
    row_field = _decode_varuint(payload, len(_NUMERIC_COLUMN_PAYLOAD_PREFIX))
    if row_field is None:
        return None
    row_capacity, offset = row_field
    if payload[offset : offset + 2] != b"\xff\xff":
        return None
    stored_field = _decode_varuint(payload, offset + 2)
    if stored_field is None:
        return None
    stored_count, offset = stored_field
    if stored_count > row_capacity:
        return None
    return row_capacity, stored_count, offset


def _decode_fpc_stream(payload: bytes, offset: int, count: int) -> tuple[tuple[int, ...], int] | None:
    table_size = 1 << _FPC_PREDICTOR_BITS
    state = _FpcState(fcm=[0] * table_size, dfcm=[0] * table_size, table_mask=table_size - 1)
    values: list[int] = []
    while len(values) < count:
        if offset >= len(payload):
            return None
        control = payload[offset]
        offset += 1
        for code in (control & 0x0F, control >> 4):
            if len(values) == count:
                break
            stored_bytes = _stored_byte_count(code)
            end = offset + stored_bytes
            if end > len(payload):
                return None
            residual = int.from_bytes(payload[offset:end], "little")
            values.append(state.decode(code, residual))
            offset = end
    return tuple(values), offset


def _trailing_missing_count(payload: bytes, offset: int, expected: int) -> int | None:
    tail = payload[offset:]
    if expected == 0:
        return 0 if tail == b"\xce" else None
    expected_tail = b"\xff\xff" + _encode_varuint(expected) + b"\x01" + _encode_varuint(2 * expected) + b"\0\xce"
    return expected if tail == expected_tail else None


def _decoded_payload(
    *,
    encoding: str,
    row_capacity: int,
    repeated_prefix_count: int,
    value_bits: tuple[int, ...],
    trailing_missing_count: int,
    first_control_byte: int | None,
) -> OpjuColumnPayload:
    bits_with_blanks: tuple[int | None, ...] = (*value_bits, *((None,) * trailing_missing_count))
    values = tuple(
        None if bits is None else struct.unpack("<d", bits.to_bytes(8, "little"))[0] for bits in bits_with_blanks
    )
    bit_strings = tuple(None if bits is None else f"{bits:016x}" for bits in bits_with_blanks)
    return OpjuColumnPayload(
        encoding=encoding,
        row_capacity=row_capacity,
        stored_value_count=len(value_bits),
        missing_count=trailing_missing_count,
        trailing_missing_count=trailing_missing_count,
        repeated_prefix_count=repeated_prefix_count,
        first_control_byte=first_control_byte,
        values=values,
        value_bits=bit_strings,
        cell_kinds=tuple("missing" if bits is None else "float64" for bits in bits_with_blanks),
    )


def _decoded_cells(
    *,
    encoding: str,
    value_bits: tuple[int | None, ...],
    repeated_prefix_count: int = 0,
    first_control_byte: int | None = None,
) -> OpjuColumnPayload:
    values = tuple(None if bits is None else struct.unpack("<d", bits.to_bytes(8, "little"))[0] for bits in value_bits)
    bit_strings = tuple(None if bits is None else f"{bits:016x}" for bits in value_bits)
    trailing_missing_count = 0
    for bits in reversed(value_bits):
        if bits is not None:
            break
        trailing_missing_count += 1
    return OpjuColumnPayload(
        encoding=encoding,
        row_capacity=len(value_bits),
        stored_value_count=sum(bits is not None for bits in value_bits),
        missing_count=sum(bits is None for bits in value_bits),
        trailing_missing_count=trailing_missing_count,
        repeated_prefix_count=repeated_prefix_count,
        first_control_byte=first_control_byte,
        values=values,
        value_bits=bit_strings,
        cell_kinds=tuple("missing" if bits is None else "float64" for bits in value_bits),
    )


def _decode_empty(payload: bytes) -> OpjuColumnPayload | None:
    singleton = payload == b"\x0a\x05\x01\x01\x00\x00\xce"
    if singleton:
        row_capacity = 1
    else:
        header = _decode_row_and_stored_count(payload)
        if header is None:
            return None
        row_capacity, stored_count, offset = header
        marker_field = _decode_varuint(payload, offset)
        if marker_field is None:
            return None
        marker, offset = marker_field
        doubled_field = _decode_varuint(payload, offset)
        if doubled_field is None:
            return None
        doubled_count, offset = doubled_field
        if stored_count != row_capacity or marker != 1 or doubled_count != 2 * row_capacity:
            return None
        if payload[offset:] != b"\0\xce":
            return None
    return _decoded_payload(
        encoding="empty",
        row_capacity=row_capacity,
        repeated_prefix_count=0,
        value_bits=(),
        trailing_missing_count=row_capacity,
        first_control_byte=None,
    )


def _decode_direct_fpc(payload: bytes) -> OpjuColumnPayload | None:
    header = _decode_row_and_stored_count(payload)
    if header is None:
        return None
    row_capacity, stored_count, offset = header
    if offset >= len(payload) or payload[offset] != 0:
        return None
    literal_field = _decode_varuint(payload, offset + 1)
    if literal_field is None:
        return None
    literal_marker, offset = literal_field
    if stored_count == 0 or literal_marker != 2 * stored_count - 1:
        return None
    if offset >= len(payload) or payload[offset] != _FPC_PREDICTOR_BITS:
        return None
    first_control_offset = offset + 1
    decoded = _decode_fpc_stream(payload, first_control_offset, stored_count)
    if decoded is None:
        return None
    value_bits, offset = decoded
    missing_count = _trailing_missing_count(payload, offset, row_capacity - stored_count)
    if missing_count is None:
        return None
    return _decoded_payload(
        encoding="fpc-fcm-dfcm",
        row_capacity=row_capacity,
        repeated_prefix_count=0,
        value_bits=value_bits,
        trailing_missing_count=missing_count,
        first_control_byte=payload[first_control_offset],
    )


def _decode_constant_prefix_fpc(payload: bytes) -> OpjuColumnPayload | None:
    header = _decode_row_and_stored_count(payload)
    if header is None:
        return None
    row_capacity, stored_count, offset = header
    if offset >= len(payload) or payload[offset] != 0:
        return None
    repeated_field = _decode_varuint(payload, offset + 1)
    if repeated_field is None:
        return None
    repeated_marker, offset = repeated_field
    if repeated_marker == 0 or repeated_marker & 1 or payload[offset : offset + 3] != _OBSERVED_ONE_RUN:
        return None
    literal_field = _decode_varuint(payload, offset + 3)
    if literal_field is None:
        return None
    literal_marker, offset = literal_field
    repeated_count = repeated_marker // 2
    literal_count = (literal_marker + 1) // 2
    if literal_marker & 1 == 0 or repeated_count + literal_count != stored_count:
        return None
    if offset >= len(payload) or payload[offset] != _FPC_PREDICTOR_BITS:
        return None
    first_control_offset = offset + 1
    decoded = _decode_fpc_stream(payload, first_control_offset, literal_count)
    if decoded is None:
        return None
    literal_bits, offset = decoded
    missing_count = _trailing_missing_count(payload, offset, row_capacity - stored_count)
    if missing_count is None:
        return None
    one_bits = struct.unpack("<Q", struct.pack("<d", 1.0))[0]
    return _decoded_payload(
        encoding="constant-one-prefix-fpc-fcm-dfcm",
        row_capacity=row_capacity,
        repeated_prefix_count=repeated_count,
        value_bits=(*((one_bits,) * repeated_count), *literal_bits),
        trailing_missing_count=missing_count,
        first_control_byte=payload[first_control_offset],
    )


def _decode_compact_scalar(payload: bytes, offset: int) -> tuple[int | None, int] | None:
    if offset >= len(payload):
        return None
    code = payload[offset]
    if code == 0x65:
        return None, offset + 1
    if code == 0x64:
        return 0, offset + 1
    stored_bytes = _COMPACT_SCALAR_BYTES.get(code)
    if stored_bytes is None:
        return None
    end = offset + 1 + stored_bytes
    if end > len(payload):
        return None
    raw_value = int.from_bytes(payload[offset + 1 : end], "little")
    if stored_bytes < 8:
        raw_value <<= (8 - stored_bytes) * 8
    return raw_value, end


def _decode_missing_run(payload: bytes, offset: int, count: int) -> int | None:
    if payload[offset : offset + 2] != b"\xff\xff":
        return None
    run_field = _decode_varuint(payload, offset + 2)
    if run_field is None:
        return None
    run_count, offset = run_field
    kind_field = _decode_varuint(payload, offset)
    if kind_field is None:
        return None
    run_kind, offset = kind_field
    doubled_field = _decode_varuint(payload, offset)
    if doubled_field is None:
        return None
    doubled_count, offset = doubled_field
    if run_count != count or run_kind != 1 or doubled_count != 2 * count:
        return None
    if payload[offset : offset + 1] != b"\0":
        return None
    return offset + 1


def _decode_plain_scalars(payload: bytes) -> OpjuColumnPayload | None:
    row_field = _decode_varuint(payload, len(_NUMERIC_COLUMN_PAYLOAD_PREFIX))
    if row_field is None:
        return None
    row_capacity, offset = row_field
    if payload[offset : offset + 2] != b"\0\0":
        return None
    offset += 2
    values: list[int | None] = []
    while len(values) < row_capacity:
        if payload[offset : offset + 2] == b"\xff\xff":
            missing_count = row_capacity - len(values)
            offset = _decode_missing_run(payload, offset, missing_count) or -1
            if offset < 0:
                return None
            values.extend([None] * missing_count)
            break
        scalar = _decode_compact_scalar(payload, offset)
        if scalar is None:
            return None
        scalar_bits, offset = scalar
        values.append(scalar_bits)
        if len(values) < row_capacity and payload[offset : offset + 2] == b"\0\0":
            offset += 2
    if payload[offset:] != b"\xce":
        return None
    return _decoded_cells(encoding="compact-double-sequence", value_bits=tuple(values))


def _decode_numeric_segments(payload: bytes, offset: int, count: int) -> tuple[tuple[int | None, ...], int] | None:
    values: list[int | None] = []
    while len(values) < count:
        marker_field = _decode_varuint(payload, offset)
        if marker_field is None:
            return None
        marker, offset = marker_field
        if marker == 0:
            return None
        if marker & 1:
            literal_count = (marker + 1) // 2
            if offset >= len(payload) or payload[offset] != _FPC_PREDICTOR_BITS:
                return None
            decoded = _decode_fpc_stream(payload, offset + 1, literal_count)
            if decoded is None:
                return None
            literal_bits, offset = decoded
            values.extend(None if bits == _ORIGIN_MISSING_BITS else bits for bits in literal_bits)
        else:
            repeated_count = marker // 2
            scalar = _decode_compact_scalar(payload, offset)
            if scalar is None:
                return None
            scalar_bits, offset = scalar
            values.extend([scalar_bits] * repeated_count)
        if len(values) > count:
            return None
    return tuple(values), offset


def _decode_segmented_fpc(payload: bytes) -> OpjuColumnPayload | None:
    row_field = _decode_varuint(payload, len(_NUMERIC_COLUMN_PAYLOAD_PREFIX))
    if row_field is None:
        return None
    row_capacity, offset = row_field
    values: list[int | None] = []
    while len(values) < row_capacity:
        if payload[offset : offset + 3] == b"\x01\0\0":
            values.append(None)
            offset += 3
            continue
        if payload[offset : offset + 2] != b"\xff\xff":
            return None
        run_field = _decode_varuint(payload, offset + 2)
        if run_field is None:
            return None
        run_count, offset = run_field
        kind_field = _decode_varuint(payload, offset)
        if kind_field is None or run_count == 0 or len(values) + run_count > row_capacity:
            return None
        run_kind, offset = kind_field
        if run_kind == 0:
            decoded = _decode_numeric_segments(payload, offset, run_count)
            if decoded is None:
                return None
            run_values, offset = decoded
            values.extend(run_values)
            continue
        if run_kind != 1:
            return None
        doubled_field = _decode_varuint(payload, offset)
        if doubled_field is None:
            return None
        doubled_count, offset = doubled_field
        if doubled_count != 2 * run_count or payload[offset : offset + 1] != b"\0":
            return None
        values.extend([None] * run_count)
        offset += 1
    if payload[offset:] != b"\xce":
        return None
    return _decoded_cells(
        encoding="segmented-fpc-fcm-dfcm",
        value_bits=tuple(values),
    )


def _decoded_non_float_cells(
    *,
    encoding: str,
    values: tuple[int | str | None, ...],
    present_kind: str,
) -> OpjuColumnPayload:
    trailing_missing_count = 0
    for value in reversed(values):
        if value is not None:
            break
        trailing_missing_count += 1
    return OpjuColumnPayload(
        encoding=encoding,
        row_capacity=len(values),
        stored_value_count=sum(value is not None for value in values),
        missing_count=sum(value is None for value in values),
        trailing_missing_count=trailing_missing_count,
        repeated_prefix_count=0,
        first_control_byte=None,
        values=values,
        value_bits=(None,) * len(values),
        cell_kinds=tuple("missing" if value is None else present_kind for value in values),
    )


def _decode_utf8_sequence(payload: bytes) -> OpjuColumnPayload | None:
    row_field = _decode_varuint(payload, len(_NUMERIC_COLUMN_PAYLOAD_PREFIX))
    if row_field is None:
        return None
    row_capacity, offset = row_field
    if payload[offset : offset + 2] != b"\xff\xff":
        return None
    run_field = _decode_varuint(payload, offset + 2)
    if run_field is None:
        return None
    run_count, offset = run_field
    kind_field = _decode_varuint(payload, offset)
    if kind_field is None:
        return None
    run_kind, offset = kind_field
    literal_field = _decode_varuint(payload, offset)
    if literal_field is None:
        return None
    literal_marker, offset = literal_field
    if run_count != row_capacity or run_kind != 1 or literal_marker & 1 == 0:
        return None
    literal_count = (literal_marker + 1) // 2
    if literal_count > row_capacity:
        return None
    values: list[int | str | None] = []
    for _ in range(literal_count):
        length_field = _decode_varuint(payload, offset)
        if length_field is None:
            return None
        length, offset = length_field
        end = offset + length
        if end > len(payload):
            return None
        try:
            values.append(payload[offset:end].decode("utf-8"))
        except UnicodeDecodeError:
            return None
        offset = end
    missing_count = row_capacity - literal_count
    doubled_field = _decode_varuint(payload, offset)
    if doubled_field is None:
        return None
    doubled_count, offset = doubled_field
    if doubled_count != 2 * missing_count or payload[offset:] != b"\0\xce":
        return None
    values.extend([None] * missing_count)
    return _decoded_non_float_cells(
        encoding="utf8-string-sequence",
        values=tuple(values),
        present_kind="utf8",
    )


def _decode_varuint_sequence(payload: bytes) -> OpjuColumnPayload | None:
    row_field = _decode_varuint(payload, len(_VARUINT_COLUMN_PAYLOAD_PREFIX))
    if row_field is None:
        return None
    row_capacity, offset = row_field
    if payload[offset : offset + 2] != b"\xff\xff":
        return None
    run_field = _decode_varuint(payload, offset + 2)
    if run_field is None:
        return None
    run_count, offset = run_field
    kind_field = _decode_varuint(payload, offset)
    if kind_field is None:
        return None
    run_kind, offset = kind_field
    literal_field = _decode_varuint(payload, offset)
    if literal_field is None:
        return None
    literal_marker, offset = literal_field
    if run_count != row_capacity or run_kind != 1 or literal_marker & 1 == 0:
        return None
    literal_count = (literal_marker + 1) // 2
    if literal_count > row_capacity:
        return None
    values: list[int | str | None] = []
    for _ in range(literal_count):
        value_field = _decode_varuint(payload, offset)
        if value_field is None:
            return None
        value, offset = value_field
        values.append(value)
    missing_count = row_capacity - literal_count
    if missing_count:
        doubled_field = _decode_varuint(payload, offset)
        if doubled_field is None:
            return None
        doubled_count, offset = doubled_field
        if doubled_count != 2 * missing_count or payload[offset:] != b"\0\xce":
            return None
        values.extend([None] * missing_count)
    elif payload[offset:] != b"\xce":
        return None
    return _decoded_non_float_cells(
        encoding="unsigned-varint-sequence",
        values=tuple(values),
        present_kind="unsigned_integer",
    )


def decode_opju_column_payload(payload: bytes) -> OpjuColumnPayload | None:
    """Decode a confirmed CPYUA numeric, text, integer, or empty column payload.

    ``None`` means the bytes do not match one of the exact layouts implemented
    here. The function never fabricates values for an unrecognized variant.
    """
    if len(payload) < 3:
        return None
    if payload.startswith(_VARUINT_COLUMN_PAYLOAD_PREFIX):
        return _decode_varuint_sequence(payload)
    if not payload.startswith(_NUMERIC_COLUMN_PAYLOAD_PREFIX):
        return None
    decoded = (
        _decode_empty(payload)
        or _decode_direct_fpc(payload)
        or _decode_constant_prefix_fpc(payload)
        or _decode_segmented_fpc(payload)
        or _decode_plain_scalars(payload)
        or _decode_utf8_sequence(payload)
    )
    if decoded is None:
        return None
    if any(isinstance(value, float) and not math.isfinite(value) for value in decoded.values):
        return None
    return decoded


def opju_column_payload_semantic_status(payload: OpjuColumnPayload) -> str:
    """Return the stable machine status for a decoded column payload."""
    if payload.encoding == "empty":
        return "decoded_empty_column"
    if payload.encoding == "utf8-string-sequence":
        return "decoded_utf8_values"
    if payload.encoding == "unsigned-varint-sequence":
        return "decoded_unsigned_varints"
    return "decoded_numeric_values"


__all__ = ["OpjuColumnPayload", "decode_opju_column_payload", "opju_column_payload_semantic_status"]
