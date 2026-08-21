"""Column-oriented OPJ dataset helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .records import OpjDataSection


@dataclass(frozen=True)
class OpjColumnInfo:
    """Parsed metadata and row payload for one OPJ dataset/column section."""

    dataset_name: str
    workbook_name: str
    column_name: str
    sheet_index: int
    source_offset: int
    source_length: int
    value_type: str
    value_size: int
    first_row: int
    last_row: int
    rows: list[object | None]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def declared_row_count(self) -> int:
        return max(0, self.last_row - self.first_row + 1)

    @property
    def value_type_category(self) -> str:
        return self.value_type


def _value_type_from_section(section: OpjDataSection) -> str:
    if section.value_size > 8 and section.data_type & 0x100:
        return "text_mixed"
    if section.value_size > 8:
        return "text"
    if section.data_type & 0x800:
        return "unsigned_integer" if section.data_type_u == 8 else "integer"
    return "floating_point"


def get_column_info_and_data(section: OpjDataSection) -> OpjColumnInfo:
    """Convert an OPJ data section into a reusable parser-facing column shape."""
    workbook_name, column_name, sheet_index = split_opj_dataset_name(section.name)
    return OpjColumnInfo(
        dataset_name=section.name,
        workbook_name=workbook_name,
        column_name=column_name,
        sheet_index=sheet_index,
        source_offset=section.offset,
        source_length=section.length,
        value_type=_value_type_from_section(section),
        value_size=section.value_size,
        first_row=section.first_row,
        last_row=section.last_row,
        rows=list(section.values),
    )


def spreadsheet_name_from_dataset_name(dataset_name: str) -> str:
    """Best-effort workbook-like spreadsheet name for a dataset token."""
    workbook_name, _column_name, _sheet_index = split_opj_dataset_name(dataset_name)
    return workbook_name


def split_opj_dataset_name(dataset_name: str) -> tuple[str, str, int]:
    """Return workbook, column label, and one-based sheet index."""
    if "_" not in dataset_name:
        return dataset_name, "", 1

    workbook_name, column_token = dataset_name.rsplit("_", 1)
    column_name = column_token
    sheet_index = 1
    if "@" in column_token:
        possible_column, possible_sheet = column_token.rsplit("@", 1)
        if possible_column and possible_sheet.isdigit() and int(possible_sheet) > 0:
            column_name = possible_column
            sheet_index = int(possible_sheet)
    return workbook_name, column_name, sheet_index


def group_columns_by_spreadsheet(
    columns: list[OpjColumnInfo],
) -> dict[str, list[OpjColumnInfo]]:
    """Group column records by spreadsheet worksheet target."""
    grouped: dict[str, list[OpjColumnInfo]] = {}
    for column in columns:
        worksheet_name = spreadsheet_name_from_dataset_name(column.dataset_name)
        grouped.setdefault(worksheet_name, []).append(column)
    return grouped


def group_columns_by_workbook_sheet(
    columns: list[OpjColumnInfo],
) -> dict[tuple[str, int], list[OpjColumnInfo]]:
    """Group OPJ columns by workbook and one-based sheet index."""
    grouped: dict[tuple[str, int], list[OpjColumnInfo]] = {}
    for column in columns:
        grouped.setdefault((column.workbook_name, column.sheet_index), []).append(column)
    return grouped
