"""Column-oriented OPJ recovery helpers."""

from __future__ import annotations

from deopjufier.opj import OpjDataSection
from deopjufier.opj.columns import (
    OpjColumnInfo,
    get_column_info_and_data,
    group_columns_by_spreadsheet,
    group_columns_by_workbook_sheet,
    split_opj_dataset_name,
    spreadsheet_name_from_dataset_name,
)


def test_spreadsheet_name_from_dataset_name() -> None:
    assert spreadsheet_name_from_dataset_name("Book1_A") == "Book1"
    assert spreadsheet_name_from_dataset_name("Book2") == "Book2"
    assert spreadsheet_name_from_dataset_name("Book3_A@v1") == "Book3"
    assert spreadsheet_name_from_dataset_name("Book_With_Name_A@2") == "Book_With_Name"


def test_split_opj_dataset_name_preserves_workbook_and_sheet_identity() -> None:
    assert split_opj_dataset_name("Book1_A") == ("Book1", "A", 1)
    assert split_opj_dataset_name("Book1_B@2") == ("Book1", "B", 2)
    assert split_opj_dataset_name("Book_With_Name_C@12") == ("Book_With_Name", "C", 12)
    assert split_opj_dataset_name("TestM") == ("TestM", "", 1)


def test_get_column_info_and_data_infers_type_and_rows() -> None:
    section = OpjDataSection(
        offset=0,
        length=0,
        name="Book1_A",
        data_type=0x100,
        data_type2=0,
        total_rows=3,
        first_row=2,
        last_row=4,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1, "x", None],
    )

    info = get_column_info_and_data(section)
    assert isinstance(info, OpjColumnInfo)
    assert info.dataset_name == "Book1_A"
    assert info.workbook_name == "Book1"
    assert info.column_name == "A"
    assert info.sheet_index == 1
    assert info.value_type == "text_mixed"
    assert info.value_size == 8
    assert info.first_row == 2
    assert info.last_row == 4
    assert info.declared_row_count == 3
    assert info.rows == [1, "x", None]


def test_group_columns_by_spreadsheet_collapses_sheet_aliases() -> None:
    columns = [
        get_column_info_and_data(
            OpjDataSection(
                offset=0,
                length=0,
                name="Book1_A",
                data_type=0,
                data_type2=0,
                total_rows=2,
                first_row=1,
                last_row=2,
                value_size=8,
                data_type_u=0,
                data_type3=0,
                values=["1", "2"],
            )
        ),
        get_column_info_and_data(
            OpjDataSection(
                offset=0,
                length=0,
                name="Book1_B",
                data_type=0,
                data_type2=0,
                total_rows=2,
                first_row=1,
                last_row=2,
                value_size=8,
                data_type_u=0,
                data_type3=0,
                values=["3", "4"],
            )
        ),
        get_column_info_and_data(
            OpjDataSection(
                offset=0,
                length=0,
                name="Sheet2",
                data_type=0,
                data_type2=0,
                total_rows=2,
                first_row=1,
                last_row=2,
                value_size=8,
                data_type_u=0,
                data_type3=0,
                values=[5, 6],
            )
        ),
    ]

    grouped = group_columns_by_spreadsheet(columns)
    assert list(grouped.keys()) == ["Book1", "Sheet2"]
    assert [column.dataset_name for column in grouped["Book1"]] == ["Book1_A", "Book1_B"]
    assert [column.dataset_name for column in grouped["Sheet2"]] == ["Sheet2"]


def test_group_columns_by_workbook_sheet_keeps_sheet_indices_separate() -> None:
    sections = [
        OpjDataSection(0, 10, "Book1_A", 0, 0, 1, 0, 1, 8, 0, 0, [1.0]),
        OpjDataSection(10, 10, "Book1_B", 0, 0, 1, 0, 1, 8, 0, 0, [2.0]),
        OpjDataSection(20, 10, "Book1_A@2", 0, 0, 1, 0, 1, 8, 0, 0, [3.0]),
    ]

    grouped = group_columns_by_workbook_sheet([get_column_info_and_data(section) for section in sections])

    assert list(grouped) == [("Book1", 1), ("Book1", 2)]
    assert [column.column_name for column in grouped[("Book1", 1)]] == ["A", "B"]
    assert [column.column_name for column in grouped[("Book1", 2)]] == ["A"]
