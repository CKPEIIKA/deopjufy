"""Worksheet and matrix metadata recovery for OPJ files."""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass

from .records import (
    OPJ_PARAMETERS_SCAN_WINDOW,
    OpjColumnMetadata,
    OpjDataSection,
    OpjMatrixMetadata,
    OpjMatrixSheetMetadata,
    OpjWorksheetMetadata,
    _decode_opj_text,
    _is_plausible_opj_data_name,
    _read_opj_payload,
    _read_opj_size,
    is_opj_signature,
)
from .structures.semantics import OpjWindowMetadata, parse_opj_window_metadata


def _iter_opj_data_sections(data: bytes, *, max_sections: int | None = None) -> list[OpjDataSection]:
    from . import iter_opj_data_sections as exported_iter_opj_data_sections

    if max_sections is None:
        return list(exported_iter_opj_data_sections(data))
    return list(exported_iter_opj_data_sections(data, max_sections=max_sections))


_OPJ_WORKSHEET_METADATA_SPLIT = re.compile(r"[\x00\r\n]+")
_OPJ_WORKSHEET_COMMENT_KEYS = {"comment", "comments"}
_OPJ_WORKSHEET_FORMULA_KEYS = {"formula", "formulas"}
_OPJ_WINDOW_HEADER_MIN_SIZE = 0xC3 + 1
_OPJ_WINDOW_HEADER_MAX_SIZE = 16 * 1024
_OPJ_WINDOW_NAME_OFFSET = 0x02
_OPJ_WINDOW_NAME_SIZE = 25
_OPJ_WINDOW_NAME_MIN_SIZE = _OPJ_WINDOW_NAME_OFFSET + _OPJ_WINDOW_NAME_SIZE
_OPJ_WINDOW_LABEL_OFFSET = 0xC3
_OPJ_WINDOW_STATE_OFFSET = 0x32
_OPJ_WINDOW_STATE_MINIMIZED = 0x01
_OPJ_WINDOW_STATE_MAXIMIZED = 0x02
_OPJ_WINDOW_HIDDEN_OFFSET = 0x69
_OPJ_WINDOW_HIDDEN_MASK = 0x08
_OPJ_WINDOW_TIMESTAMP_OFFSET = 0x73
_OPJ_UNIT_VALUE_MAX_LENGTH = 80
_OpjLengthBlock = tuple[int, int, bytes]


@dataclass
class _OpjWindowMetadata:
    label: str | None = None
    object_id: int | None = None
    hidden: bool | None = None
    state: str | None = None
    creation_time: int | None = None
    modification_time: int | None = None


def parse_opj_worksheet_metadata(
    data: bytes,
    *,
    worksheet_names: set[str] | None = None,
    parsed_window_metadata: list[OpjWindowMetadata] | None = None,
) -> dict[str, OpjWorksheetMetadata]:
    if not is_opj_signature(data):
        return {}

    filtered_names = worksheet_names or set()
    metadata_by_name: dict[str, OpjWorksheetMetadata] = {}
    column_labels_by_name: dict[str, list[str]] = {}
    formula_rows_by_name: dict[str, tuple[int, int]] = {}
    column_metadata_by_name: dict[str, dict[str, tuple[str, str]]] = {}
    sections = _iter_opj_data_sections(data)
    if not sections:
        return {}

    target_names = filtered_names if filtered_names else {section.name for section in sections}
    parsed_windows = parse_opj_window_metadata(data) if parsed_window_metadata is None else parsed_window_metadata
    windows_by_name = {window.name: window for window in parsed_windows}
    if target_names:
        length_blocks = _iter_opj_length_blocks(
            data,
            scan_window=OPJ_PARAMETERS_SCAN_WINDOW,
            max_payload_size=_OPJ_WINDOW_HEADER_MAX_SIZE,
        )
        long_names_by_sheet = _recover_opj_worksheet_long_names(data, target_names, blocks=length_blocks)
        units_by_sheet = _recover_opj_worksheet_units(data, target_names, blocks=length_blocks)
        comments_by_sheet = _recover_opj_worksheet_comments(data, target_names, blocks=length_blocks)
        formulas_by_sheet = _recover_opj_worksheet_formulas(data, target_names, blocks=length_blocks)
        window_metadata_by_sheet = _recover_opj_worksheet_window_metadata(
            data,
            target_names,
            blocks=length_blocks,
        )
    else:
        long_names_by_sheet = {}
        units_by_sheet = {}
        comments_by_sheet = {}
        formulas_by_sheet = {}
        window_metadata_by_sheet = {}

    for section in sections:
        worksheet_name = _resolve_opj_worksheet_name(section.name, target_names)
        if worksheet_name is None:
            continue

        if section.last_row > 0 and section.last_row >= section.first_row:
            formula_rows = (section.first_row, section.last_row)
            existing = formula_rows_by_name.get(worksheet_name)
            if existing is None:
                formula_rows_by_name[worksheet_name] = formula_rows
            else:
                formula_rows_by_name[worksheet_name] = (
                    min(existing[0], formula_rows[0]),
                    max(existing[1], formula_rows[1]),
                )

        if worksheet_name != section.name:
            suffix = section.name.removeprefix(worksheet_name)
            if suffix.startswith("_"):
                label = suffix[1:]
                if label:
                    labels = column_labels_by_name.setdefault(worksheet_name, [])
                    if label not in labels:
                        labels.append(label)
                    worksheet_columns = column_metadata_by_name.setdefault(worksheet_name, {})
                    if label not in worksheet_columns:
                        worksheet_columns[label] = (
                            _infer_opj_worksheet_column_type(section),
                            _infer_opj_worksheet_column_display_hint(section),
                        )

    for worksheet_name in target_names if target_names else metadata_by_name.keys():
        if worksheet_name not in metadata_by_name and formula_rows_by_name.get(worksheet_name) is None:
            continue
        parsed_window = windows_by_name.get(worksheet_name)
        window_metadata = window_metadata_by_sheet.get(worksheet_name) or _OpjWindowMetadata()
        exact_columns = _worksheet_columns_from_window(parsed_window)
        exact_formulas = [column.formula for column in exact_columns if column.formula]
        metadata_by_name[worksheet_name] = OpjWorksheetMetadata(
            name=worksheet_name,
            label=parsed_window.label if parsed_window is not None else window_metadata.label,
            long_name=long_names_by_sheet.get(worksheet_name, worksheet_name),
            comments=comments_by_sheet.get(worksheet_name),
            formulas=exact_formulas or formulas_by_sheet.get(worksheet_name, []),
            column_types=(
                [column.value_type or "unknown" for column in exact_columns]
                or [value[0] for value in column_metadata_by_name.get(worksheet_name, {}).values()]
            ),
            display_hints=[value[1] for value in column_metadata_by_name.get(worksheet_name, {}).values()],
            units=units_by_sheet.get(worksheet_name),
            formula_rows=formula_rows_by_name.get(worksheet_name),
            column_labels=[column.name for column in exact_columns] or column_labels_by_name.get(worksheet_name, []),
            object_id=parsed_window.object_id if parsed_window is not None else window_metadata.object_id,
            hidden=parsed_window.hidden if parsed_window is not None else window_metadata.hidden,
            state=parsed_window.state if parsed_window is not None else window_metadata.state,
            creation_time=(parsed_window.creation_time if parsed_window is not None else window_metadata.creation_time),
            modification_time=(
                parsed_window.modification_time if parsed_window is not None else window_metadata.modification_time
            ),
            columns=exact_columns,
        )
    return metadata_by_name


def _worksheet_columns_from_window(window: OpjWindowMetadata | None) -> list[OpjColumnMetadata]:
    if window is None:
        return []
    formulas = {
        (annotation.layer_index, annotation.name): annotation.data_1_text
        for annotation in window.annotations
        if annotation.data_1_text and not annotation.name.startswith("__")
    }
    return [
        OpjColumnMetadata(
            name=curve.name,
            sheet_index=curve.layer_index + 1,
            designation=curve.designation,
            value_type=curve.value_type,
            value_type_specification=curve.value_type_specification,
            significant_digits=curve.significant_digits,
            decimal_places=curve.decimal_places,
            width=curve.width,
            comment=curve.comment,
            formula=formulas.get((curve.layer_index, curve.name)),
        )
        for curve in window.curves
    ]


def _infer_opj_worksheet_column_type(section: OpjDataSection) -> str:
    values = [value for value in section.values if value is not None]
    if not values:
        return "text" if section.data_type & 0x100 else "numeric"
    has_text = any(isinstance(value, str) for value in values)
    has_number = any(isinstance(value, (int, float)) for value in values)
    if has_text and has_number:
        return "mixed"
    if has_text:
        return "text"
    if has_number:
        return "numeric"
    return "text" if section.data_type & 0x100 else "unknown"


def _infer_opj_worksheet_column_display_hint(section: OpjDataSection) -> str:
    if section.value_size <= 0:
        return "unknown"
    if section.value_size >= 9:
        if section.data_type & 0x100 and any(isinstance(value, str) for value in section.values if value is not None):
            return "text"
        return "numeric_mixed" if section.data_type & 0x800 else "float64"
    if section.value_size == 8:
        return "numeric_or_text_8" if section.data_type & 0x100 else "float64"
    if section.value_size == 4:
        return "int32" if section.data_type & 0x800 else "float32"
    if section.value_size == 2:
        return "int16"
    if section.value_size == 1:
        return "int8"
    return f"byte_{section.value_size}"


def _iter_metadata_tokens(payload: bytes) -> list[str]:
    try:
        decoded = payload.decode("ascii", errors="replace")
    except Exception:
        return []
    return [token.strip() for token in _OPJ_WORKSHEET_METADATA_SPLIT.split(decoded) if token.strip()]


def _is_probable_opj_metadata_value(value: str, *, max_length: int = 240) -> bool:
    text = value.strip()
    return bool(
        text
        and len(text) <= max_length
        and text.lower() not in {"null", "none", "na", "n/a"}
        and not any(ord(ch) < 32 or ord(ch) >= 127 for ch in text)
    )


def _extract_opj_worksheet_metadata_kv(
    tokens: list[str], *, target_names: set[str], value_keys: set[str]
) -> list[tuple[str, str, str]]:
    if not tokens or not target_names:
        return []

    normalized_targets = {name.lower() for name in target_names}
    key_results: list[tuple[str, str, str]] = []
    for index, token in enumerate(tokens):
        token = token.strip()
        if not token:
            continue

        worksheet_name: str | None = None
        key: str | None = None
        value_index = index + 2

        if token in target_names or token.lower() in normalized_targets:
            key_candidate = tokens[index + 1].strip().lower() if index + 1 < len(tokens) else ""
            if key_candidate in value_keys:
                worksheet_name = next(name for name in target_names if name.lower() == token.lower())
                key = key_candidate
        else:
            prefix, separator, maybe_key = token.rpartition(" ")
            if (
                separator
                and maybe_key.lower() in value_keys
                and (prefix in target_names or prefix.lower() in normalized_targets)
            ):
                worksheet_name = next(name for name in target_names if name.lower() == prefix.lower())
                key = maybe_key.lower()
                value_index = index + 1

        if key and worksheet_name and value_index < len(tokens):
            value = tokens[value_index].strip()
            if _is_probable_opj_metadata_value(value):
                key_results.append((worksheet_name, key, value))
    return key_results


def _recover_opj_worksheet_comments(
    data: bytes,
    worksheet_names: set[str] | None = None,
    *,
    blocks: list[_OpjLengthBlock] | None = None,
) -> dict[str, str]:
    if not is_opj_signature(data):
        return {}
    target_names = worksheet_names or set()
    if not target_names:
        return {}

    comments_by_name: dict[str, str] = {}
    length_blocks = (
        blocks
        if blocks is not None
        else _iter_opj_length_blocks(
            data,
            scan_window=OPJ_PARAMETERS_SCAN_WINDOW,
            max_payload_size=_OPJ_WINDOW_HEADER_MAX_SIZE,
        )
    )
    for _block_start, _block_end, payload in length_blocks:
        for worksheet_name, _key, value in _extract_opj_worksheet_metadata_kv(
            _iter_metadata_tokens(payload), target_names=target_names, value_keys=_OPJ_WORKSHEET_COMMENT_KEYS
        ):
            comments_by_name.setdefault(worksheet_name, value)
    return comments_by_name


def _recover_opj_worksheet_formulas(
    data: bytes,
    worksheet_names: set[str] | None = None,
    *,
    blocks: list[_OpjLengthBlock] | None = None,
) -> dict[str, list[str]]:
    if not is_opj_signature(data):
        return {}
    target_names = worksheet_names or set()
    if not target_names:
        return {}

    formulas_by_name: dict[str, list[str]] = {}
    length_blocks = (
        blocks
        if blocks is not None
        else _iter_opj_length_blocks(
            data,
            scan_window=OPJ_PARAMETERS_SCAN_WINDOW,
            max_payload_size=_OPJ_WINDOW_HEADER_MAX_SIZE,
        )
    )
    for _block_start, _block_end, payload in length_blocks:
        for worksheet_name, _key, value in _extract_opj_worksheet_metadata_kv(
            _iter_metadata_tokens(payload), target_names=target_names, value_keys=_OPJ_WORKSHEET_FORMULA_KEYS
        ):
            formula_list = formulas_by_name.setdefault(worksheet_name, [])
            if value not in formula_list:
                formula_list.append(value)
    return formulas_by_name


def _resolve_opj_worksheet_name(section_name: str, worksheet_names: set[str]) -> str | None:
    at_split = section_name.split("@", 1)[0]
    if at_split != section_name and "_" in at_split:
        worksheet_root = at_split.split("_", 1)[0]
        if worksheet_root in worksheet_names:
            return worksheet_root
    if at_split != section_name and at_split in worksheet_names:
        return at_split
    if "_" in section_name:
        worksheet_root = section_name.split("_", 1)[0]
        if worksheet_root in worksheet_names:
            return worksheet_root
    if "_" in at_split:
        worksheet_root = at_split.split("_", 1)[0]
        if worksheet_root in worksheet_names:
            return worksheet_root
    if section_name in worksheet_names:
        return section_name

    candidates: list[str] = []
    for name in worksheet_names:
        if section_name.startswith(f"{name}_") or section_name.startswith(f"{name}@"):
            candidates.append(name)
    if not candidates:
        return None
    candidates.sort(key=len)
    return candidates[0]


def _resolve_opj_matrix_name(section_name: str, matrix_names: set[str]) -> str | None:
    at_split = section_name.split("@", 1)[0]
    if at_split != section_name and "_" in at_split:
        matrix_root = at_split.split("_", 1)[0]
        if matrix_root in matrix_names:
            return matrix_root
    if at_split != section_name and at_split in matrix_names:
        return at_split
    if "_" in section_name:
        matrix_root = section_name.split("_", 1)[0]
        if matrix_root in matrix_names:
            return matrix_root
    if "_" in at_split:
        matrix_root = at_split.split("_", 1)[0]
        if matrix_root in matrix_names:
            return matrix_root
    if section_name in matrix_names:
        return section_name
    candidates: list[str] = []
    for name in matrix_names:
        if section_name.startswith(f"{name}_") or section_name.startswith(f"{name}@"):
            candidates.append(name)
    if not candidates:
        return None
    candidates.sort(key=len)
    return candidates[0]


def _is_probable_opj_unit_value(value: str) -> bool:
    value = value.strip()
    if not value or len(value) > _OPJ_UNIT_VALUE_MAX_LENGTH:
        return False
    if (
        not all(32 <= ord(ch) < 127 for ch in value)
        or all(ch == "." for ch in value)
        or any(ch in value for ch in "\x00\r\n")
    ):
        return False
    if any(ch in value for ch in "_@") and value.count(" ") == 0:
        return True
    if len(value) <= 2:
        return True
    return any(ch.isalpha() for ch in value)


def _recover_opj_worksheet_units(
    data: bytes,
    worksheet_names: set[str] | None = None,
    *,
    blocks: list[_OpjLengthBlock] | None = None,
) -> dict[str, str]:
    if not is_opj_signature(data):
        return {}
    target_names = worksheet_names or set()
    if not target_names:
        return {}

    unit_by_name: dict[str, str] = {}
    split_pattern = re.compile(r"[\x00\r\n]+")
    length_blocks = (
        blocks
        if blocks is not None
        else _iter_opj_length_blocks(
            data,
            scan_window=OPJ_PARAMETERS_SCAN_WINDOW,
            max_payload_size=_OPJ_WINDOW_HEADER_MAX_SIZE,
        )
    )
    for _block_start, _block_end, payload in length_blocks:
        try:
            decoded = payload.decode("ascii", errors="replace")
        except Exception:
            continue

        tokens = [token.strip() for token in split_pattern.split(decoded) if token and token.strip()]
        if len(tokens) < 2:
            continue
        lower_target_names = {name.lower() for name in target_names}
        candidate_positions = [index for index, token in enumerate(tokens) if token.lower() in lower_target_names]
        for start in candidate_positions:
            worksheet_name = tokens[start]
            if worksheet_name not in target_names:
                continue

            index = start + 1
            while index + 1 < len(tokens):
                key = tokens[index].strip().lower()
                value = tokens[index + 1].strip()
                if key == "units" and _is_probable_opj_unit_value(value):
                    unit_by_name[worksheet_name] = value
                    index += 2
                    continue
                index += 1
    return unit_by_name


def _recover_opj_worksheet_long_names(
    data: bytes,
    worksheet_names: set[str] | None = None,
    *,
    blocks: list[_OpjLengthBlock] | None = None,
) -> dict[str, str]:
    if not is_opj_signature(data):
        return {}
    target_names = worksheet_names or set()
    if not target_names:
        return {}

    recovered: dict[str, str] = {}
    length_blocks = (
        blocks
        if blocks is not None
        else _iter_opj_length_blocks(
            data,
            scan_window=OPJ_PARAMETERS_SCAN_WINDOW,
            max_payload_size=_OPJ_WINDOW_HEADER_MAX_SIZE,
        )
    )
    for start, end, payload in length_blocks:
        if not (start < end and len(payload) >= _OPJ_WINDOW_HEADER_MIN_SIZE):
            continue
        name = _decode_opj_text(
            payload[_OPJ_WINDOW_NAME_OFFSET : _OPJ_WINDOW_NAME_OFFSET + _OPJ_WINDOW_NAME_SIZE]
        ).strip()
        if not name or name not in target_names or not _is_plausible_opj_data_name(name):
            continue
        label = _decode_opj_text(payload[_OPJ_WINDOW_LABEL_OFFSET:])
        if not label:
            continue
        label = label.split("@${", 1)[0].strip()
        if label and label != name:
            recovered.setdefault(name, label)
        if len(recovered) >= len(target_names):
            break
    return recovered


def _decode_opj_window_state(flag: int) -> str:
    if flag & _OPJ_WINDOW_STATE_MINIMIZED:
        return "minimized"
    if flag & _OPJ_WINDOW_STATE_MAXIMIZED:
        return "maximized"
    return "normal"


def _decode_opj_window_timestamp(raw_value: float) -> int | None:
    if not math.isfinite(raw_value) or not 2_350_000 <= raw_value <= 2_500_000:
        return None
    timestamp = int((raw_value - 2440587) * 86400.0 + 0.5)
    return None if timestamp < 0 else timestamp


def _recover_opj_worksheet_window_metadata(
    data: bytes,
    worksheet_names: set[str] | None = None,
    *,
    blocks: list[_OpjLengthBlock] | None = None,
) -> dict[str, _OpjWindowMetadata]:
    if not is_opj_signature(data):
        return {}
    target_names = worksheet_names or set()
    if not target_names:
        return {}

    recovered: dict[str, _OpjWindowMetadata] = {}
    next_object_id = 0
    length_blocks = (
        blocks
        if blocks is not None
        else _iter_opj_length_blocks(
            data,
            scan_window=OPJ_PARAMETERS_SCAN_WINDOW,
            max_payload_size=_OPJ_WINDOW_HEADER_MAX_SIZE,
        )
    )
    for _start, _end, payload in length_blocks:
        if len(payload) < _OPJ_WINDOW_NAME_MIN_SIZE:
            continue
        name = _decode_opj_text(
            payload[_OPJ_WINDOW_NAME_OFFSET : _OPJ_WINDOW_NAME_OFFSET + _OPJ_WINDOW_NAME_SIZE]
        ).strip()
        if not name or name not in target_names or not _is_plausible_opj_data_name(name):
            continue

        metadata = recovered.get(name)
        if metadata is None:
            metadata = _OpjWindowMetadata(object_id=next_object_id)
            recovered[name] = metadata
            next_object_id += 1

        if len(payload) > _OPJ_WINDOW_LABEL_OFFSET:
            label = _decode_opj_text(payload[_OPJ_WINDOW_LABEL_OFFSET:])
            if label:
                label = label.split("@${", 1)[0].strip()
                if label and label != name and metadata.label is None:
                    metadata.label = label
        if len(payload) > _OPJ_WINDOW_HIDDEN_OFFSET and metadata.hidden is None:
            metadata.hidden = bool(payload[_OPJ_WINDOW_HIDDEN_OFFSET] & _OPJ_WINDOW_HIDDEN_MASK)
        if len(payload) > _OPJ_WINDOW_STATE_OFFSET and metadata.state is None:
            metadata.state = _decode_opj_window_state(payload[_OPJ_WINDOW_STATE_OFFSET])

        if len(payload) >= _OPJ_WINDOW_TIMESTAMP_OFFSET + 16:
            try:
                creation_raw = struct.unpack_from("<d", payload, _OPJ_WINDOW_TIMESTAMP_OFFSET)[0]
            except (OSError, struct.error):
                creation_raw = None
            try:
                modification_raw = struct.unpack_from("<d", payload, _OPJ_WINDOW_TIMESTAMP_OFFSET + 8)[0]
            except (OSError, struct.error):
                modification_raw = None
            if creation_raw is not None and metadata.creation_time is None:
                metadata.creation_time = _decode_opj_window_timestamp(creation_raw)
            if modification_raw is not None and metadata.modification_time is None:
                metadata.modification_time = _decode_opj_window_timestamp(modification_raw)
    return recovered


def _iter_opj_length_blocks(
    data: bytes, *, scan_window: int = OPJ_PARAMETERS_SCAN_WINDOW, max_payload_size: int = 0
) -> list[tuple[int, int, bytes]]:
    if not is_opj_signature(data):
        return []
    line_end = data.find(b"\n")
    if line_end < 0:
        return []

    scan_limit = line_end + 1 + max(0, scan_window)
    scan_end = min(len(data), scan_limit)
    if max_payload_size <= 0:
        max_payload_size = max(1, OPJ_PARAMETERS_SCAN_WINDOW)

    blocks: list[tuple[int, int, bytes]] = []
    pos = line_end + 1
    while pos < scan_end:
        block_size_and_pos = _read_opj_size(data, pos)
        if block_size_and_pos is None:
            pos += 1
            continue
        block_size, payload_pos = block_size_and_pos
        block_start = pos
        if block_size <= 0 or block_size > max_payload_size:
            pos = payload_pos
            continue
        block = _read_opj_payload(data, payload_pos, block_size)
        if block is None:
            pos += 1
            continue
        payload, payload_end = block
        blocks.append((block_start, payload_end, payload))
        pos = payload_end
    return blocks


def parse_opj_matrix_metadata(
    data: bytes,
    *,
    matrix_names: set[str] | None = None,
    parsed_window_metadata: list[OpjWindowMetadata] | None = None,
) -> dict[str, OpjMatrixMetadata]:
    if not is_opj_signature(data):
        return {}
    sections = _iter_opj_data_sections(data)
    if not sections:
        return {}

    filtered_names = matrix_names or {section.name for section in sections}
    if not filtered_names:
        return {}

    sections_by_matrix: dict[str, list[OpjDataSection]] = {}
    for section in sections:
        matrix_name = _resolve_opj_matrix_name(section.name, filtered_names)
        if matrix_name is not None:
            sections_by_matrix.setdefault(matrix_name, []).append(section)

    parsed_windows = parse_opj_window_metadata(data) if parsed_window_metadata is None else parsed_window_metadata
    windows_by_name = {window.name: window for window in parsed_windows}
    metadata_by_name: dict[str, OpjMatrixMetadata] = {}
    for matrix_name, section_group in sections_by_matrix.items():
        ordered_sections = sorted(section_group, key=lambda section: section.offset)
        row_starts = [section.first_row for section in ordered_sections if section.first_row > 0]
        row_ends = [
            section.last_row
            for section in ordered_sections
            if section.last_row > 0 and section.last_row >= section.first_row
        ]
        row_count = max(
            (section.total_rows if section.total_rows > 0 else len(section.values) for section in section_group),
            default=0,
        )
        parsed_window = windows_by_name.get(matrix_name)
        matrix_sheets = _matrix_sheets_from_window(parsed_window)
        exact_shape = matrix_sheets[0].shape if len(matrix_sheets) == 1 else None
        metadata_by_name[matrix_name] = OpjMatrixMetadata(
            name=matrix_name,
            long_name=parsed_window.label if parsed_window is not None and parsed_window.label else matrix_name,
            shape=exact_shape or (row_count, len(section_group)),
            data_type=section_group[0].data_type,
            row_start=min(row_starts, default=None),
            row_end=max(row_ends, default=None),
            section_count=len(section_group),
            active_sheet=parsed_window.active_sheet if parsed_window is not None else None,
            header_view=parsed_window.matrix_header if parsed_window is not None else None,
            sheets=matrix_sheets,
        )
    return metadata_by_name


def _matrix_sheets_from_window(window: OpjWindowMetadata | None) -> list[OpjMatrixSheetMetadata]:
    if window is None:
        return []
    annotations_by_layer = {
        layer.index: {
            annotation.name: annotation.data_1_text
            for annotation in window.annotations
            if annotation.layer_index == layer.index and annotation.data_1_text
        }
        for layer in window.layers
    }
    sheets: list[OpjMatrixSheetMetadata] = []
    for layer in window.layers:
        annotations = annotations_by_layer[layer.index]
        coordinate_values: list[float] = []
        for key in ("X1", "X2", "Y1", "Y2"):
            try:
                coordinate_values.append(float(annotations[key]))
            except (KeyError, ValueError):
                coordinate_values = []
                break
        coordinates = (
            (
                coordinate_values[0],
                coordinate_values[1],
                coordinate_values[2],
                coordinate_values[3],
            )
            if len(coordinate_values) == 4
            else None
        )
        sheets.append(
            OpjMatrixSheetMetadata(
                name=layer.name,
                sheet_index=layer.index + 1,
                shape=(layer.matrix_rows, layer.matrix_columns)
                if layer.matrix_rows is not None and layer.matrix_columns is not None
                else None,
                width=layer.matrix_width or 8,
                view=layer.matrix_view,
                formula=annotations.get("MV"),
                coordinates=coordinates,
            )
        )
    return sheets
