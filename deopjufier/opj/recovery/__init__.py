"""Parser-owned OPJ tabular recovery helpers."""

from __future__ import annotations

import re

from deopjufier.discovery import ParserBackedDiscoveryRecord
from deopjufier.opj.boundaries import parse_opj_boundaries
from deopjufier.opj.columns import (
    OpjColumnInfo,
    get_column_info_and_data,
    group_columns_by_spreadsheet,
    group_columns_by_workbook_sheet,
)
from deopjufier.opj.metadata import (
    _resolve_opj_matrix_name,
    _resolve_opj_worksheet_name,
    parse_opj_matrix_metadata,
    parse_opj_worksheet_metadata,
)
from deopjufier.opj.records import (
    OPJ_NOTES_MAX_BLOCKS,
    OPJ_NOTES_MAX_CHARS,
    OpjDataSection,
    OpjMatrixMetadata,
    OpjNoteSection,
    OpjWorksheetMetadata,
    iter_opj_data_sections,
    parse_opj_note_sections,
)


def _expand_worksheet_names(names: set[str]) -> set[str]:
    expanded: set[str] = set(names)
    for name in names:
        if "@" in name:
            expanded.add(name.split("@", 1)[0])

        base = name.split("@", 1)[0]
        if "_" in base:
            expanded.add(base.split("_", 1)[0])

    return expanded


def _coalesced_worksheet_roots(names: set[str]) -> set[str]:
    roots: set[str] = set()
    for name in names:
        normalized = name.split("@", 1)[0]
        if "_" in normalized:
            normalized = normalized.split("_", 1)[0]
        if normalized:
            roots.add(normalized)
    return roots


def _matrix_alias_names(name: str) -> set[str]:
    if not name:
        return set()

    aliases: set[str] = set()
    head = name.split("@", 1)[0]
    if "/" in head:
        head = head.split("/")[-1]
    if not head:
        return aliases

    if head.startswith("PdM") and len(head) > 3:
        stripped = head[3:]
        if stripped:
            aliases.add(stripped)
            if not stripped.startswith("M"):
                aliases.add(f"M{stripped}")
            if stripped.startswith("Sheet"):
                if m := re.search(r"(\d+)$", stripped):
                    aliases.add(f"MBook{m.group(1)}")

    if head.startswith("MSheet") or (head.startswith("M") and not head.startswith("MBook")):
        if m := re.search(r"(\d+)$", head):
            aliases.add(f"MBook{m.group(1)}")

    if head.startswith("M") and not head.startswith("MBook") and head[1:].isdigit():
        aliases.add(f"MBook{head[1:]}")

    return aliases


def _expand_matrix_names(names: set[str]) -> set[str]:
    expanded = _expand_worksheet_names(names)
    for name in names:
        expanded.update(_matrix_alias_names(name))
    return expanded


def _stringify_opj_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _transpose_opj_columns(columns: list[OpjColumnInfo]) -> tuple[list[list[str]], tuple[int, int]]:
    max_rows = max((column.row_count for column in columns), default=0)
    rows = [
        [_stringify_opj_value(column.rows[row_index]) if row_index < column.row_count else "" for column in columns]
        for row_index in range(max_rows)
    ]
    return rows, (max_rows, len(columns))


def recover_worksheet_metadata_from_opj_sections(
    data: bytes,
    object_names: set[str],
    *,
    parse_metadata: bool = True,
    metadata_by_name: dict[str, OpjWorksheetMetadata] | None = None,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    dict[str, OpjWorksheetMetadata],
]:
    """Recover parser-backed worksheet rows, shapes, and metadata by section names."""
    recovered_rows_by_name: dict[str, list[list[str]]] = {}
    recovered_dimensions_by_name: dict[str, tuple[int, int]] = {}
    recovered_metadata_by_name: dict[str, OpjWorksheetMetadata] = {}

    if not object_names:
        return recovered_rows_by_name, recovered_dimensions_by_name, recovered_metadata_by_name

    worksheet_names = _expand_worksheet_names(set(object_names))
    if metadata_by_name is not None:
        recovered_metadata_by_name = dict(metadata_by_name)
    elif parse_metadata:
        metadata_names = _coalesced_worksheet_roots(worksheet_names)
        recovered_metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names=metadata_names)

    section_rows_by_sheet: dict[str, list[list[str]]] = {}
    sheet_row_counts: dict[str, int] = {}
    parsed_columns = []

    for section in iter_opj_data_sections(data, max_sections=None):
        worksheet_name = _resolve_opj_worksheet_name(section.name, worksheet_names)
        if worksheet_name is None:
            continue

        column_info = get_column_info_and_data(section)
        parsed_columns.append((worksheet_name, column_info))

    for worksheet_name, columns in group_columns_by_spreadsheet(
        [column_info for _, column_info in parsed_columns]
    ).items():
        # Keep current behavior: resolve worksheet candidates can collapse multiple
        # aliases and still emit to parser-backed worksheet namespaces.
        matched_name = _resolve_opj_worksheet_name(worksheet_name, worksheet_names)
        target_name = matched_name or worksheet_name

        section_rows_by_sheet[target_name] = []
        for column_info in columns:
            section_rows_by_sheet[target_name].append([_stringify_opj_value(value) for value in column_info.rows])

        sheet_row_counts[target_name] = max(
            sheet_row_counts.get(target_name, 0),
            max((column.row_count for column in columns), default=0),
        )

    for worksheet_name, columns in section_rows_by_sheet.items():
        max_rows = sheet_row_counts.get(worksheet_name, 0)
        if not columns:
            continue

        row_width = len(columns)
        sheet_rows: list[list[str]] = []
        for row_index in range(max_rows):
            sheet_rows.append(
                [
                    columns[column_index][row_index] if row_index < len(columns[column_index]) else ""
                    for column_index in range(row_width)
                ]
            )

        recovered_rows_by_name[worksheet_name] = sheet_rows
        recovered_dimensions_by_name[worksheet_name] = (max_rows, row_width)

    return recovered_rows_by_name, recovered_dimensions_by_name, recovered_metadata_by_name


def recover_excel_sheets_from_opj_sections(
    data: bytes,
    object_names: set[str],
    *,
    metadata_by_name: dict[str, OpjWorksheetMetadata] | None = None,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    dict[str, OpjWorksheetMetadata],
    list[ParserBackedDiscoveryRecord],
]:
    """Recover multi-sheet OPJ workbook columns as distinct Excel sheets."""
    columns = [get_column_info_and_data(section) for section in iter_opj_data_sections(data, max_sections=None)]
    grouped = group_columns_by_workbook_sheet([column for column in columns if column.column_name])
    requested_names = {name.split("/", 1)[0] for name in object_names}

    sheet_counts: dict[str, int] = {}
    for workbook_name, sheet_index in grouped:
        sheet_counts[workbook_name] = max(sheet_counts.get(workbook_name, 0), sheet_index)
    excel_names = {name for name, count in sheet_counts.items() if count > 1 and name in requested_names}
    workbook_metadata = (
        parse_opj_worksheet_metadata(data, worksheet_names=excel_names)
        if metadata_by_name is None
        else metadata_by_name
    )

    rows_by_name: dict[str, list[list[str]]] = {}
    dimensions_by_name: dict[str, tuple[int, int]] = {}
    metadata_by_name: dict[str, OpjWorksheetMetadata] = {}
    records: list[ParserBackedDiscoveryRecord] = []
    for (workbook_name, sheet_index), sheet_columns in grouped.items():
        if workbook_name not in excel_names:
            continue
        sheet_name = f"{workbook_name}/Sheet{sheet_index}"
        rows, dimensions = _transpose_opj_columns(sheet_columns)
        rows_by_name[sheet_name] = rows
        dimensions_by_name[sheet_name] = dimensions
        parsed_metadata = workbook_metadata.get(workbook_name)
        exact_columns = (
            [column for column in parsed_metadata.columns if column.sheet_index == sheet_index]
            if parsed_metadata is not None
            else []
        )
        metadata_by_name[sheet_name] = OpjWorksheetMetadata(
            name=sheet_name,
            long_name=f"Sheet{sheet_index}",
            column_labels=[column.name for column in exact_columns] or [column.column_name for column in sheet_columns],
            column_types=[column.value_type or "unknown" for column in exact_columns]
            or [column.value_type for column in sheet_columns],
            formulas=[column.formula for column in exact_columns if column.formula],
            object_id=parsed_metadata.object_id if parsed_metadata is not None else None,
            hidden=parsed_metadata.hidden if parsed_metadata is not None else None,
            state=parsed_metadata.state if parsed_metadata is not None else None,
            creation_time=parsed_metadata.creation_time if parsed_metadata is not None else None,
            modification_time=parsed_metadata.modification_time if parsed_metadata is not None else None,
            columns=exact_columns,
        )
        start = min(column.source_offset for column in sheet_columns)
        end = max(column.source_offset + column.source_length for column in sheet_columns)
        records.append(
            ParserBackedDiscoveryRecord(
                offset=start,
                name=sheet_name,
                length=max(1, end - start),
                object_kind="excel",
                source_object_path=sheet_name,
                parser_rule="opj_excel_sheet_data_sections",
                parser_confidence=0.94,
            )
        )

    return rows_by_name, dimensions_by_name, metadata_by_name, records


def recover_matrix_metadata_from_opj_sections(
    data: bytes,
    object_names: set[str],
    *,
    parse_metadata: bool = True,
    metadata_by_name: dict[str, OpjMatrixMetadata] | None = None,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    dict[str, OpjMatrixMetadata],
]:
    """Recover parser-backed matrix rows, shapes, and metadata by section names."""
    recovered_rows_by_name: dict[str, list[list[str]]] = {}
    recovered_dimensions_by_name: dict[str, tuple[int, int]] = {}
    recovered_metadata_by_name: dict[str, OpjMatrixMetadata] = {}

    if not object_names:
        return recovered_rows_by_name, recovered_dimensions_by_name, recovered_metadata_by_name

    matrix_names = _expand_matrix_names(set(object_names))
    if metadata_by_name is not None:
        recovered_metadata_by_name = dict(metadata_by_name)
    elif parse_metadata:
        recovered_metadata_by_name = parse_opj_matrix_metadata(data, matrix_names=matrix_names)

    sections = iter_opj_data_sections(data)
    sections_by_matrix: dict[str, list[OpjDataSection]] = {}
    for section in sections:
        matrix_name = _resolve_opj_matrix_name(section.name, matrix_names)
        if matrix_name is None:
            continue
        sections_by_matrix.setdefault(matrix_name, []).append(section)

    for matrix_name, section_group in sections_by_matrix.items():
        section_group.sort(key=lambda section: section.offset)
        available_row_count = max((len(section.values) for section in section_group), default=0)
        metadata = recovered_metadata_by_name.get(matrix_name)
        exact_shape = metadata.shape if metadata is not None else None
        if (
            exact_shape is not None
            and len(section_group) == 1
            and exact_shape[0] > 0
            and exact_shape[1] > 0
            and exact_shape[0] * exact_shape[1] <= len(section_group[0].values)
        ):
            matrix_values = section_group[0].values
            rows = [
                [
                    _stringify_opj_value(value)
                    for value in matrix_values[row_index * exact_shape[1] : (row_index + 1) * exact_shape[1]]
                ]
                for row_index in range(exact_shape[0])
            ]
            dimensions = exact_shape
        else:
            rows = [
                [
                    _stringify_opj_value(section.values[row_index]) if row_index < len(section.values) else ""
                    for section in section_group
                ]
                for row_index in range(available_row_count)
            ]
            dimensions = (available_row_count, len(section_group))

        recovered_rows_by_name[matrix_name] = rows
        recovered_dimensions_by_name[matrix_name] = dimensions
        if metadata is not None:
            recovered_metadata_by_name[matrix_name] = OpjMatrixMetadata(
                name=metadata.name,
                long_name=metadata.long_name,
                shape=metadata.shape or dimensions,
                data_type=metadata.data_type,
                row_start=metadata.row_start,
                row_end=metadata.row_end,
                section_count=metadata.section_count,
                active_sheet=metadata.active_sheet,
                header_view=metadata.header_view,
                sheets=metadata.sheets,
            )

    return recovered_rows_by_name, recovered_dimensions_by_name, recovered_metadata_by_name


def recover_parser_function_records(
    data: bytes,
) -> list[ParserBackedDiscoveryRecord]:
    """Return parser-backed function records from OPJ boundaries.

    Kept parser-owned so object extraction layers can focus on emission policy.
    """
    if not data:
        return []

    return [
        ParserBackedDiscoveryRecord(
            offset=boundary.start_offset,
            name=boundary.name,
            length=max(1, boundary.length),
            object_kind=boundary.kind,
            source_object_path=boundary.source_object_path,
            parser_rule=boundary.parser_rule,
            parser_confidence=boundary.confidence,
        )
        for boundary in parse_opj_boundaries(data)
        if boundary.kind == "function"
    ]


def recover_opj_note_sections(
    data: bytes,
    *,
    max_sections: int = OPJ_NOTES_MAX_BLOCKS,
    max_chars: int = OPJ_NOTES_MAX_CHARS,
) -> dict[tuple[int, str], tuple[int, str]]:
    """Return OPJ note sections as parser-backed location-indexed regions."""
    if not data:
        return {}

    sections: list[OpjNoteSection] = parse_opj_note_sections(
        data,
        max_sections=max_sections,
        max_chars=max_chars,
    )
    return {(section.offset, section.name): (section.length, section.text) for section in sections if section.text}
