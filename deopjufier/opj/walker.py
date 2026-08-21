"""Sequential OPJ walk helpers and walk-event records."""

from __future__ import annotations

import string
import struct
from dataclasses import dataclass, field

from .records import (
    _decode_name,
    _decode_opj_text,
    _parse_opj_data_header,
    parse_opj_signature,
)
from .stream import OpjStream, OpjStreamError

_WalkMetadataValue = int | float | str | None | tuple[int, int] | tuple[int, ...]
_OPJ_WINDOW_LABEL_OFFSET = 0xC3
_OPJ_WINDOW_STATE_OFFSET = 0x32
_OPJ_WINDOW_HIDDEN_OFFSET = 0x69
_OPJ_WINDOW_STATE_MINIMIZED = 0x01
_OPJ_WINDOW_STATE_MAXIMIZED = 0x02
_OPJ_WINDOW_TITLE_LABEL = 0x01
_OPJ_WINDOW_TITLE_NAME = 0x02


@dataclass(frozen=True)
class OpjWalkElement:
    """Deterministic element emitted by a sequential OPJ walk."""

    kind: str
    start_offset: int
    end_offset: int
    name: str | None = None
    metadata: dict[str, _WalkMetadataValue] = field(default_factory=dict)


def _read_object_size_or_raise(cursor: OpjStream, *, tolerate: bool, start_fallback: int) -> int | None:
    try:
        return cursor.read_object_size()
    except OpjStreamError:
        if tolerate:
            cursor.seek(start_fallback)
            return None
        raise


def _decode_name_from_object(payload: bytes, offset: int, size: int) -> str | None:
    if offset < 0 or size <= 0 or offset + size > len(payload):
        return None
    return _decode_name(payload[offset : offset + size].split(b"\x00", 1)[0])


def _clean_ascii_text(value: str | None) -> str:
    """Normalize note label/window name text for deterministic naming."""
    if value is None:
        return ""

    text = value.split("\x00", 1)[0].strip()
    return "".join(char for char in text if char in string.printable and char not in {"\r", "\n", "\t"}).strip()


def _decode_note_label(note_label: bytes | None) -> str:
    if not note_label:
        return ""
    return _clean_ascii_text(note_label.decode("utf-8", errors="replace"))


def _resolve_note_name(note_header: bytes, note_label: bytes | None) -> str:
    label_name = _decode_note_label(note_label)
    if label_name:
        return label_name

    return _decode_name_from_object(note_header, 0, 25) or "note"


def _decode_julian_timestamp(payload: bytes, offset: int) -> int | None:
    if offset < 0 or offset + 8 > len(payload):
        return None
    value = struct.unpack_from("<d", payload, offset)[0]
    if not 2_350_000 <= value <= 2_500_000:
        return None
    timestamp = int((value - 2_440_587) * 86_400.0 + 0.5)
    return timestamp if timestamp >= 0 else None


def _decode_rect_u32_as_i16(payload: bytes, offset: int = 0) -> tuple[int, int, int, int] | None:
    if offset < 0 or offset + 16 > len(payload):
        return None
    values = struct.unpack_from("<IIII", payload, offset)
    converted = tuple(struct.unpack("<h", (value & 0xFFFF).to_bytes(2, "little"))[0] for value in values)
    return converted[0], converted[1], converted[2], converted[3]


def _decode_blob_name(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def _decode_window_title_mode(payload: bytes) -> str | None:
    if len(payload) <= _OPJ_WINDOW_HIDDEN_OFFSET:
        return None

    title_mask = payload[_OPJ_WINDOW_HIDDEN_OFFSET]
    if title_mask & _OPJ_WINDOW_TITLE_LABEL:
        return "label"
    if title_mask & _OPJ_WINDOW_TITLE_NAME:
        return "name"
    return "both"


def _decode_window_state(payload: bytes) -> str | None:
    if len(payload) <= _OPJ_WINDOW_STATE_OFFSET:
        return None
    state = payload[_OPJ_WINDOW_STATE_OFFSET]
    if state & _OPJ_WINDOW_STATE_MINIMIZED:
        return "minimized"
    if state & _OPJ_WINDOW_STATE_MAXIMIZED:
        return "maximized"
    return "normal"


def _decode_window_label(payload: bytes) -> str | None:
    if len(payload) <= _OPJ_WINDOW_LABEL_OFFSET:
        return None
    label = _decode_opj_text(payload[_OPJ_WINDOW_LABEL_OFFSET:]).strip()
    if not label:
        return None
    label = label.split("@${", 1)[0].strip()
    return label or None


def _read_line(cursor: OpjStream, *, tolerate: bool) -> bytes:
    line_start = cursor.offset
    if line_start >= len(cursor.data):
        if tolerate:
            return b""
        raise OpjStreamError("unterminated text line", offset=line_start)

    line_end = cursor.data.find(b"\n", line_start)
    if line_end < 0:
        if tolerate:
            cursor.seek(len(cursor.data))
            return b""
        raise OpjStreamError("unterminated text line", offset=line_start)

    cursor.seek(line_end + 1)
    return cursor.data[line_start:line_end]


def _read_u32_le(payload: bytes) -> int | None:
    if len(payload) < 4:
        return None
    return int.from_bytes(payload[:4], "little")


def _read_u16_le(payload: bytes, offset: int) -> int | None:
    if offset < 0 or offset + 2 > len(payload):
        return None
    return int.from_bytes(payload[offset : offset + 2], "little")


def _read_f64_le(payload: bytes, offset: int) -> float | None:
    if offset < 0 or offset + 8 > len(payload):
        return None
    return struct.unpack_from("<d", payload, offset)[0]


def _read_i16_rect(payload: bytes, offset: int) -> tuple[int, int, int, int] | None:
    if offset < 0 or offset + 8 > len(payload):
        return None
    return struct.unpack_from("<hhhh", payload, offset)


def _read_or_skip_object(
    cursor: OpjStream, *, size: int, tolerate: bool, allow_zero_payload: bool = False
) -> bytes | None:
    if size == 0:
        return b""

    try:
        return cursor.read_object(size)
    except OpjStreamError:
        if tolerate:
            return None
        raise


def _walk_curve_list(
    cursor: OpjStream,
    *,
    tolerate: bool,
    window_name: str,
    layer_index: int,
    elements: list[OpjWalkElement],
) -> int:
    count = 0
    while True:
        curve_header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if curve_header_size is None or curve_header_size == 0:
            return count

        start = cursor.offset - 5
        curve_header = _read_or_skip_object(cursor, size=curve_header_size, tolerate=tolerate)
        if curve_header is None:
            return count

        cursor.seek(start + 5 + curve_header_size + 1)
        curve_data_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if curve_data_size is None:
            return count
        curve_data_offset = cursor.offset
        curve_data = _read_or_skip_object(cursor, size=curve_data_size, tolerate=tolerate, allow_zero_payload=True)
        if curve_data is None:
            return count

        curve_name = _decode_name_from_object(curve_header, 0x12, 41) or f"curve_{count + 1}"
        elements.append(
            OpjWalkElement(
                kind="curve",
                start_offset=start,
                end_offset=cursor.offset,
                name=curve_name,
                metadata={
                    "window_name": window_name,
                    "layer_index": layer_index,
                    "curve_index": count,
                    "header_size": curve_header_size,
                    "data_offset": curve_data_offset,
                    "data_size": curve_data_size,
                    "data_id": _read_u16_le(curve_header, 0x04),
                    "x_data_id": _read_u16_le(curve_header, 0x23),
                    "z_data_id": _read_u16_le(curve_header, 0x4D),
                    "designation_code": curve_header[0x11] if len(curve_header) > 0x11 else None,
                    "format_code": curve_header[0x1E] if len(curve_header) > 0x1E else None,
                    "digits_code": curve_header[0x1F] if len(curve_header) > 0x1F else None,
                    "width_raw": _read_u16_le(curve_header, 0x4A),
                    "hidden": len(curve_header) > 0x26 and curve_header[0x26] == 33,
                    "plot_type": curve_header[0x4C] if len(curve_header) > 0x4C else None,
                    "comment": _decode_blob_name(curve_data),
                },
            )
        )
        count += 1


def _walk_axis_parameter_list(
    cursor: OpjStream,
    axis: int,
    *,
    tolerate: bool,
    window_name: str,
    layer_index: int,
    elements: list[OpjWalkElement],
) -> int:
    count = 0
    while True:
        block_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if block_size is None or block_size == 0:
            return count

        start = cursor.offset - 5
        payload = _read_or_skip_object(cursor, size=block_size, tolerate=tolerate)
        if payload is None:
            return count
        elements.append(
            OpjWalkElement(
                kind="axis_parameter",
                start_offset=start,
                end_offset=cursor.offset,
                name=f"{window_name}/layer_{layer_index + 1}/axis_{axis}_{count + 1}",
                metadata={
                    "window_name": window_name,
                    "layer_index": layer_index,
                    "axis": axis,
                    "parameter_index": count,
                    "data_size": block_size,
                    "color": payload[0x0F] if len(payload) > 0x0F else None,
                    "style": payload[0x12] if len(payload) > 0x12 else None,
                    "width_raw": _read_u16_le(payload, 0x15),
                    "format_code": payload[0x25] if len(payload) > 0x25 else None,
                    "flags": payload[0x26] if len(payload) > 0x26 else None,
                },
            )
        )
        count += 1


def _walk_axis_break_list(
    cursor: OpjStream,
    *,
    tolerate: bool,
    window_name: str,
    layer_index: int,
    elements: list[OpjWalkElement],
) -> int:
    count = 0
    while True:
        break_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if break_size is None or break_size == 0:
            return count

        start = cursor.offset - 5
        payload = _read_or_skip_object(cursor, size=break_size, tolerate=tolerate)
        if payload is None:
            return count
        elements.append(
            OpjWalkElement(
                kind="axis_break",
                start_offset=start,
                end_offset=cursor.offset,
                name=f"{window_name}/layer_{layer_index + 1}/break_{count + 1}",
                metadata={
                    "window_name": window_name,
                    "layer_index": layer_index,
                    "break_index": count,
                    "axis": payload[0x02] if len(payload) > 0x02 else None,
                    "from": _read_f64_le(payload, 0x0B),
                    "to": _read_f64_le(payload, 0x13),
                    "increment_after": _read_f64_le(payload, 0x1B),
                    "position": _read_f64_le(payload, 0x23),
                    "log10": len(payload) > 0x2B and payload[0x2B] == 1,
                    "minor_ticks_after": payload[0x2C] if len(payload) > 0x2C else None,
                },
            )
        )
        count += 1


def _walk_annotation_list(
    cursor: OpjStream,
    *,
    tolerate: bool,
    window_name: str,
    layer_index: int,
    elements: list[OpjWalkElement],
) -> int:
    annotation_count = 0
    while True:
        ane_header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if ane_header_size is None or ane_header_size == 0:
            return annotation_count

        ane_header_start = cursor.offset - 5
        ane_header = _read_or_skip_object(cursor, size=ane_header_size, tolerate=tolerate)
        if ane_header is None:
            return annotation_count

        cursor.seek(ane_header_start + 5 + ane_header_size + 1)
        ane_data_1_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if ane_data_1_size is None:
            return annotation_count
        ane_data_1_offset = cursor.offset
        ane_data_1 = _read_or_skip_object(cursor, size=ane_data_1_size, tolerate=tolerate)
        if ane_data_1 is None:
            return annotation_count

        ane_data_2_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if ane_data_2_size is None:
            return annotation_count

        if ane_data_1_size in {0x5E, 0x0A} and ane_data_2_size == 4:
            _walk_annotation_list(
                cursor,
                tolerate=tolerate,
                window_name=window_name,
                layer_index=layer_index,
                elements=elements,
            )
            ane_data_2 = b""
            ane_data_2_offset = cursor.offset
        else:
            ane_data_2_offset = cursor.offset
            ane_data_2 = _read_or_skip_object(cursor, size=ane_data_2_size, tolerate=tolerate)
            if ane_data_2 is None:
                return annotation_count

        ane_data_3_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if ane_data_3_size is None:
            return annotation_count
        ane_data_3_offset = cursor.offset
        if _read_or_skip_object(cursor, size=ane_data_3_size, tolerate=tolerate) is None:
            return annotation_count

        annotation_name = _decode_name_from_object(ane_header, 0x46, 41) or f"annotation_{annotation_count + 1}"
        elements.append(
            OpjWalkElement(
                kind="annotation",
                start_offset=ane_header_start,
                end_offset=cursor.offset,
                name=annotation_name,
                metadata={
                    "window_name": window_name,
                    "layer_index": layer_index,
                    "annotation_index": annotation_count,
                    "annotation_kind": ane_header[0x02] if len(ane_header) > 0x02 else None,
                    "client_rect": _read_i16_rect(ane_header, 0x03),
                    "attach": ane_header[0x28] if len(ane_header) > 0x28 else None,
                    "border": ane_header[0x29] if len(ane_header) > 0x29 else None,
                    "data_1_offset": ane_data_1_offset,
                    "data_1_size": ane_data_1_size,
                    "data_1_text": _decode_blob_name(ane_data_1),
                    "data_2_offset": ane_data_2_offset,
                    "data_2_size": ane_data_2_size,
                    "data_2_text": _decode_blob_name(ane_data_2),
                    "data_3_offset": ane_data_3_offset,
                    "data_3_size": ane_data_3_size,
                },
            )
        )
        annotation_count += 1


def _walk_window_layer(
    cursor: OpjStream,
    *,
    tolerate: bool,
    window_name: str,
    layer_index: int,
    elements: list[OpjWalkElement],
) -> bool:
    layer_header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if layer_header_size is None or layer_header_size == 0:
        return False

    layer_header_start = cursor.offset - 5
    layer_header = _read_or_skip_object(cursor, size=layer_header_size, tolerate=tolerate)
    if layer_header is None:
        return False
    cursor.seek(layer_header_start + 5 + layer_header_size + 1)

    # annotation blocks
    annotation_count = _walk_annotation_list(
        cursor,
        tolerate=tolerate,
        window_name=window_name,
        layer_index=layer_index,
        elements=elements,
    )
    # curve blocks
    curve_count = _walk_curve_list(
        cursor,
        tolerate=tolerate,
        window_name=window_name,
        layer_index=layer_index,
        elements=elements,
    )
    # axis breaks
    axis_break_count = _walk_axis_break_list(
        cursor,
        tolerate=tolerate,
        window_name=window_name,
        layer_index=layer_index,
        elements=elements,
    )
    # axis breaks/params: in the C++ flow it includes three axis-parameter loops.
    axis_parameter_counts = tuple(
        _walk_axis_parameter_list(
            cursor,
            axis=axis,
            tolerate=tolerate,
            window_name=window_name,
            layer_index=layer_index,
            elements=elements,
        )
        for axis in (1, 2, 3)
    )

    layer_name = _decode_name_from_object(layer_header, 0xD2, 32) or f"layer_{layer_index + 1}"
    elements.append(
        OpjWalkElement(
            kind="layer",
            start_offset=layer_header_start,
            end_offset=cursor.offset,
            name=layer_name,
            metadata={
                "window_name": window_name,
                "layer_index": layer_index,
                "header_size": layer_header_size,
                "x_min": _read_f64_le(layer_header, 0x0F),
                "x_max": _read_f64_le(layer_header, 0x17),
                "x_step": _read_f64_le(layer_header, 0x1F),
                "x_major_ticks": layer_header[0x2B] if len(layer_header) > 0x2B else None,
                "x_minor_ticks": layer_header[0x37] if len(layer_header) > 0x37 else None,
                "x_scale": layer_header[0x38] if len(layer_header) > 0x38 else None,
                "y_min": _read_f64_le(layer_header, 0x3A),
                "y_max": _read_f64_le(layer_header, 0x42),
                "y_step": _read_f64_le(layer_header, 0x4A),
                "y_major_ticks": layer_header[0x56] if len(layer_header) > 0x56 else None,
                "y_minor_ticks": layer_header[0x62] if len(layer_header) > 0x62 else None,
                "y_scale": layer_header[0x63] if len(layer_header) > 0x63 else None,
                "client_rect": _read_i16_rect(layer_header, 0x71),
                "matrix_width": _read_u16_le(layer_header, 0x27),
                "matrix_columns": _read_u16_le(layer_header, 0x2B),
                "matrix_rows": _read_u16_le(layer_header, 0x52),
                "matrix_view_code": layer_header[0x71] if len(layer_header) > 0x71 else None,
                "annotations": annotation_count,
                "curves": curve_count,
                "axis_breaks": axis_break_count,
                "axis_parameters": axis_parameter_counts,
            },
        )
    )

    return True


def _walk_window_layers(
    cursor: OpjStream,
    *,
    tolerate: bool,
    window_name: str,
    elements: list[OpjWalkElement],
) -> int:
    layer_count = 0
    while _walk_window_layer(
        cursor,
        tolerate=tolerate,
        window_name=window_name,
        layer_index=layer_count,
        elements=elements,
    ):
        layer_count += 1
    return layer_count


def _walk_data_sets(cursor: OpjStream, *, tolerate: bool) -> list[OpjWalkElement]:
    elements: list[OpjWalkElement] = []
    while True:
        header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if header_size is None or header_size == 0:
            return elements

        dataset_start = cursor.offset - 5
        header_payload = _read_or_skip_object(cursor, size=header_size, tolerate=tolerate)
        if header_payload is None:
            return elements

        data_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if data_size is None:
            return elements
        data_offset = cursor.offset
        data_payload = _read_or_skip_object(
            cursor,
            size=data_size,
            tolerate=tolerate,
            allow_zero_payload=True,
        )
        if data_payload is None:
            return elements

        mask_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if mask_size is None:
            return elements
        mask_offset = cursor.offset
        if _read_or_skip_object(cursor, size=mask_size, tolerate=tolerate, allow_zero_payload=True) is None:
            return elements

        parsed = _parse_opj_data_header(header_payload)
        if parsed is None:
            name = "dataset"
            data_type = total_rows = value_size = first_row = last_row = data_type_u = data_type2 = 0
            data_type3 = 0
        else:
            name = str(parsed.get("name", "dataset"))
            data_type = int(parsed.get("data_type", 0))
            total_rows = int(parsed.get("total_rows", 0))
            first_row = int(parsed.get("first_row", 0))
            last_row = int(parsed.get("last_row", 0))
            value_size = int(parsed.get("value_size", 0))
            data_type_u = int(parsed.get("data_type_u", 0))
            data_type2 = int(parsed.get("data_type2", 0))
            data_type3 = int(parsed.get("data_type3", 0))

        elements.append(
            OpjWalkElement(
                kind="dataset",
                start_offset=dataset_start,
                end_offset=cursor.offset,
                name=name,
                metadata={
                    "header_size": header_size,
                    "header_offset": dataset_start + 5,
                    "data_size": data_size,
                    "data_offset": data_offset,
                    "mask_size": mask_size,
                    "mask_offset": mask_offset,
                    "data_type": data_type,
                    "data_type2": data_type2,
                    "total_rows": total_rows,
                    "first_row": first_row,
                    "last_row": last_row,
                    "value_size": value_size,
                    "data_type_u": data_type_u,
                    "data_type3": data_type3,
                },
            )
        )


def _walk_windows(cursor: OpjStream, *, tolerate: bool) -> list[OpjWalkElement]:
    elements: list[OpjWalkElement] = []
    window_index = 0
    while True:
        header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if header_size is None or header_size == 0:
            return elements

        window_header_start = cursor.offset - 5
        window_header = _read_or_skip_object(cursor, size=header_size, tolerate=tolerate)
        if window_header is None:
            return elements

        name = _decode_name_from_object(window_header, 0x02, 25)
        window_label = _decode_window_label(window_header)
        window_title_mode = _decode_window_title_mode(window_header)
        window_state = _decode_window_state(window_header)
        window_hidden = None
        if len(window_header) > _OPJ_WINDOW_HIDDEN_OFFSET:
            window_hidden = bool(window_header[_OPJ_WINDOW_HIDDEN_OFFSET] & 0x08)
        child_elements: list[OpjWalkElement] = []
        layer_count = _walk_window_layers(
            cursor,
            tolerate=tolerate,
            window_name=name or "window",
            elements=child_elements,
        )
        elements.append(
            OpjWalkElement(
                kind="window",
                start_offset=window_header_start,
                end_offset=cursor.offset,
                name=name or "window",
                metadata={
                    "object_id": window_index,
                    "header_size": header_size,
                    "frame_rect": _read_i16_rect(window_header, 0x1B),
                    "width": _read_u16_le(window_header, 0x23),
                    "height": _read_u16_le(window_header, 0x25),
                    "active_sheet": window_header[0x29] if len(window_header) > 0x29 else None,
                    "window_label": window_label,
                    "window_title_mode": window_title_mode,
                    "window_state": window_state,
                    "window_hidden": window_hidden,
                    "creation_time": _decode_julian_timestamp(window_header, 0x73),
                    "modification_time": _decode_julian_timestamp(window_header, 0x7B),
                    "matrix_header": (
                        "xy"
                        if len(window_header) > 0x87 and window_header[0x87] == 194
                        else "column_row"
                        if len(window_header) > 0x87
                        else None
                    ),
                    "connect_missing_data": (bool(window_header[0x38] & 0x40) if len(window_header) > 0x38 else None),
                    "template_name": _decode_name_from_object(window_header, 0x45, 20),
                    "layers": layer_count,
                },
            )
        )
        elements.extend(child_elements)
        window_index += 1


def _walk_parameters(cursor: OpjStream, *, tolerate: bool) -> list[OpjWalkElement]:
    elements: list[OpjWalkElement] = []
    while cursor.offset < len(cursor.data):
        parameter_start = cursor.offset
        raw_name = _read_line(cursor, tolerate=tolerate)
        if not raw_name:
            if cursor.offset >= len(cursor.data):
                return elements
            eof_mark = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
            if eof_mark != 0 and tolerate is False:
                raise OpjStreamError("wrong parameter list terminator", offset=cursor.offset)
            return elements

        if raw_name.startswith(b"\x00"):
            eof_mark = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
            if eof_mark != 0 and tolerate is False:
                raise OpjStreamError("wrong parameter list terminator", offset=cursor.offset)
            return elements

        if cursor.offset + 9 > len(cursor.data):
            if tolerate:
                return elements
            raise OpjStreamError("truncated parameter value", offset=cursor.offset)
        value = struct.unpack("<d", cursor.read(8))[0]
        delimiter = cursor.read_byte()
        if delimiter != b"\n":
            if tolerate:
                return elements
            raise OpjStreamError("wrong parameter delimiter", offset=cursor.offset - 1)

        try:
            name = raw_name.decode("ascii").strip()
        except UnicodeDecodeError:
            name = raw_name.decode("ascii", errors="replace").strip()

        elements.append(
            OpjWalkElement(
                kind="parameter",
                start_offset=parameter_start,
                end_offset=cursor.offset,
                name=name or None,
                metadata={"value": value},
            )
        )
    return elements


def _walk_notes(cursor: OpjStream, *, tolerate: bool) -> list[OpjWalkElement]:
    elements: list[OpjWalkElement] = []
    while True:
        note_header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if note_header_size is None or note_header_size == 0:
            return elements

        note_start = cursor.offset - 5
        note_header = _read_or_skip_object(cursor, size=note_header_size, tolerate=tolerate)
        if note_header is None:
            return elements

        note_label_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if note_label_size is None:
            return elements
        note_label_start = cursor.offset
        note_label = _read_or_skip_object(
            cursor,
            size=note_label_size,
            tolerate=tolerate,
            allow_zero_payload=True,
        )
        if note_label is None:
            return elements

        note_contents_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if note_contents_size is None:
            return elements
        note_contents_start = cursor.offset
        note_contents = _read_or_skip_object(
            cursor,
            size=note_contents_size,
            tolerate=tolerate,
            allow_zero_payload=True,
        )
        if note_contents is None:
            return elements

        note_name = _resolve_note_name(note_header, note_label)
        frame_rect = _decode_rect_u32_as_i16(note_header)
        is_results_log = frame_rect is not None and (frame_rect[2] == 0 or frame_rect[3] == 0)
        state_flag = note_header[0x18] if len(note_header) > 0x18 else None
        label_length = _read_u32_le(note_header[0x3C:0x40]) if len(note_header) >= 0x40 else None
        embedded_label = ""
        text_offset = note_contents_start
        if note_contents is not None and label_length is not None and 1 < label_length <= len(note_contents):
            embedded_label = _decode_blob_name(note_contents[:label_length])
            text_offset += label_length
        elements.append(
            OpjWalkElement(
                kind="note",
                start_offset=note_start,
                end_offset=cursor.offset,
                name=note_name,
                metadata={
                    "label_size": note_label_size,
                    "contents_size": note_contents_size,
                    "note_label_start": note_label_start,
                    "note_contents_start": note_contents_start,
                    "label": _decode_note_label(note_label) if note_label is not None else "",
                    "embedded_label": embedded_label,
                    "text_offset": text_offset,
                    "frame_rect": frame_rect,
                    "state": ("minimized" if state_flag == 0x07 else "maximized" if state_flag == 0x0B else "normal"),
                    "hidden": bool(state_flag & 0x40) if state_flag is not None else None,
                    "title_mode": (
                        "label"
                        if len(note_header) > 0x38 and note_header[0x38] == 0x01
                        else "name"
                        if len(note_header) > 0x38 and note_header[0x38] == 0x02
                        else "both"
                    ),
                    "creation_time": _decode_julian_timestamp(note_header, 0x20),
                    "modification_time": _decode_julian_timestamp(note_header, 0x28),
                    "results_log": is_results_log,
                },
            )
        )


def _walk_global_header(cursor: OpjStream, *, tolerate: bool) -> list[OpjWalkElement]:
    global_start = cursor.offset
    header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if header_size is None:
        return []
    if _read_or_skip_object(cursor, size=header_size, tolerate=tolerate) is None:
        return []

    header_end_mark = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if header_end_mark is None:
        return []
    if header_end_mark != 0 and not tolerate:
        raise OpjStreamError("wrong global header end mark", offset=cursor.offset - 4)

    return [
        OpjWalkElement(
            kind="global_header",
            start_offset=global_start,
            end_offset=cursor.offset,
            name="global_header",
            metadata={"header_size": header_size, "end_mark": header_end_mark},
        )
    ]


def walk_opj_file(data: bytes, *, tolerant: bool = True) -> list[OpjWalkElement]:
    """Walk OPJ bytes in liborigin object order and return high-level objects."""
    from .structures.walker_tail import _walk_attachments, _walk_project_tree

    signature = parse_opj_signature(data)
    if signature is None or signature.magic != "CPYA":
        raise OpjStreamError("not an OPJ file")

    line_end = data.find(b"\n")
    if line_end < 0:
        raise OpjStreamError("invalid OPJ signature line")
    cursor = OpjStream(data)
    cursor.seek(line_end + 1)
    elements: list[OpjWalkElement] = []

    # Global header is mandatory for OPJ container structure.
    elements.extend(_walk_global_header(cursor, tolerate=tolerant))
    if cursor.at_eof:
        return elements

    elements.extend(_walk_data_sets(cursor, tolerate=tolerant))
    if cursor.at_eof:
        return elements

    elements.extend(_walk_windows(cursor, tolerate=tolerant))
    if cursor.at_eof:
        return elements

    elements.extend(_walk_parameters(cursor, tolerate=tolerant))
    if cursor.at_eof:
        return elements

    # Notes are optional and only attempted when data remains.
    if cursor.offset < len(cursor.data):
        elements.extend(_walk_notes(cursor, tolerate=tolerant))

    # Project tree and attachment lists are optional additions introduced later.
    if cursor.offset < len(cursor.data):
        try:
            windows_by_id = {
                index: element.name or f"window_{index}"
                for index, element in enumerate(item for item in elements if item.kind == "window")
            }
            notes_by_id = {
                index: element.name or f"note_{index}"
                for index, element in enumerate(
                    item for item in elements if item.kind == "note" and not item.metadata.get("results_log")
                )
            }
            elements.extend(
                _walk_project_tree(
                    cursor,
                    tolerate=tolerant,
                    windows_by_id=windows_by_id,
                    notes_by_id=notes_by_id,
                )
            )
        except OpjStreamError:
            if not tolerant:
                raise

    if cursor.offset < len(cursor.data):
        elements.extend(_walk_attachments(cursor, tolerate=tolerant))
    return elements
