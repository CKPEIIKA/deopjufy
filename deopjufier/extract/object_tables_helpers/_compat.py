"""Compatibility wrappers for parser backend APIs."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

from deopjufier.inventory import (
    MAGIC_OPJ,
    OriginObject,
    discover_origin_objects,
)
from deopjufier.opj import (
    OpjMatrixMetadata,
    OpjWorksheetMetadata,
)


def _object_tables_module() -> ModuleType:
    return importlib.import_module("deopjufier.extract.object_tables")


def scan_numeric_tables_from_bytes(
    data: bytes,
    *,
    min_rows: int,
    min_columns: int,
    start: int = 0,
    end: int | None = None,
    **_kwargs: object,
) -> list[tuple[int, int, int, list[str]]]:
    """Scan one byte window and retain source-file offsets in the result."""

    window_start = max(start, 0)
    window_end = len(data) if end is None else min(max(end, window_start), len(data))
    rows = _object_tables_module().scan_numeric_tables_from_bytes(
        data[window_start:window_end],
        min_rows=min_rows,
        min_columns=min_columns,
    )
    return [(table_id, row_in_table, window_start + offset, values) for table_id, row_in_table, offset, values in rows]


def _write_book_xlsx(
    target: Path,
    rows: list[tuple[int, int, int, list[str]]],
    headers: list[str] | None = None,
) -> int:
    writer = _object_tables_module()._write_book_xlsx
    try:
        return writer(target, rows, headers=headers)
    except TypeError:
        return writer(target, rows)


def _recover_worksheet_records_compat(
    data: bytes,
    worksheet_names: set[str],
    parse_metadata: bool,
    metadata_by_name: dict[str, OpjWorksheetMetadata] | None = None,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    dict[str, OpjWorksheetMetadata],
]:
    parser_api = _object_tables_module()
    parser_func = parser_api.recover_worksheet_metadata_from_opj_sections
    try:
        return parser_func(
            data,
            worksheet_names,
            parse_metadata=parse_metadata,
            metadata_by_name=metadata_by_name,
        )
    except TypeError:
        try:
            return parser_func(data, worksheet_names, parse_metadata=parse_metadata)
        except TypeError:
            return parser_func(data, worksheet_names)


def _recover_opju_worksheet_rows_compat(
    data: bytes,
    *,
    worksheet_names: set[str],
    path: Path,
    worksheet_objects: list[OriginObject] | None = None,
    max_tables: int = 200,
    include_family_binary: bool = True,
    include_descriptor_tables: bool = True,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    set[str],
]:
    parser_api = _object_tables_module()
    parser_func = parser_api.recover_worksheet_rows_from_opju
    try:
        return parser_func(
            data,
            worksheet_names=worksheet_names,
            path=path,
            worksheet_objects=worksheet_objects,
            max_tables=max_tables,
            include_family_binary=include_family_binary,
            include_descriptor_tables=include_descriptor_tables,
        )
    except TypeError:
        try:
            return parser_func(data, worksheet_names=worksheet_names, path=path)
        except TypeError:
            return parser_func(data, worksheet_names=worksheet_names)


def _recover_opju_matrix_rows_compat(
    data: bytes,
    *,
    matrix_names: set[str],
    path: Path,
    max_tables: int = 200,
    include_family_binary: bool = True,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    set[str],
]:
    parser_api = _object_tables_module()
    parser_func = parser_api.recover_matrix_rows_from_opju
    try:
        return parser_func(
            data,
            matrix_names=matrix_names,
            path=path,
            max_tables=max_tables,
            include_family_binary=include_family_binary,
        )
    except TypeError:
        return parser_func(data, matrix_names=matrix_names, path=path)


def _recover_opju_worksheet_metadata_compat(
    data: bytes,
    *,
    worksheet_names: set[str] | None = None,
    path: Path | None = None,
    include_descriptor_tables: bool = True,
) -> dict[str, OpjWorksheetMetadata]:
    parser_api = _object_tables_module()
    parser_func = parser_api.recover_worksheet_metadata_from_opju
    try:
        return parser_func(
            data,
            worksheet_names=worksheet_names,
            path=path,
            include_descriptor_tables=include_descriptor_tables,
        )
    except TypeError:
        if worksheet_names is None:
            return parser_func(data)
        return parser_func(data, worksheet_names)


def _recover_matrix_records_compat(
    data: bytes,
    matrix_names: set[str],
    parse_metadata: bool,
    metadata_by_name: dict[str, OpjMatrixMetadata] | None = None,
) -> tuple[
    dict[str, list[list[str]]],
    dict[str, tuple[int, int]],
    dict[str, OpjMatrixMetadata],
]:
    parser_api = _object_tables_module()
    parser_func = parser_api.recover_matrix_metadata_from_opj_sections
    try:
        return parser_func(
            data,
            matrix_names,
            parse_metadata=parse_metadata,
            metadata_by_name=metadata_by_name,
        )
    except TypeError:
        try:
            return parser_func(data, matrix_names, parse_metadata=parse_metadata)
        except TypeError:
            return parser_func(data, matrix_names)


def _discover_worksheet_names_for_recovery(input_path: Path) -> set[str]:
    try:
        return {
            obj.name
            for obj in discover_origin_objects(
                input_path,
                allowed_kinds=frozenset({"worksheet"}),
            )
            if obj.object_kind == "worksheet"
        }
    except Exception:
        return set()


def _is_opju_file(file_data: bytes | None, input_path: Path) -> bool:
    suffix = input_path.suffix.lower()
    if suffix == ".opju":
        return True
    if suffix == ".opj":
        return False

    if file_data is not None:
        return not file_data.startswith(MAGIC_OPJ)
    return not input_path.read_bytes()[: len(MAGIC_OPJ)].startswith(MAGIC_OPJ)


__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
