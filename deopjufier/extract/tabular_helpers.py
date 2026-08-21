"""Helpers for extracting tabular payloads."""

from __future__ import annotations

import csv
from pathlib import Path

_SEMICOLON_ESCAPE = "%3B"


def _pack_row_values(values: list[str]) -> str:
    """Pack row values for legacy provenance CSV using a semicolon payload.

    The probe payload uses ``;`` as a fixed column separator inside a packed
    string. Literal semicolons in cell values therefore must be escaped so that
    unpacking stays deterministic on load.
    """
    return ";".join(value.replace(";", _SEMICOLON_ESCAPE) for value in values)


def book_rows_for_range(
    rows: list[tuple[int, int, int, list[str]]], start: int, end: int
) -> list[tuple[int, int, int, list[str]]]:
    """Return rows whose byte offsets are inside the [start, end) interval."""
    return [row for row in rows if start <= row[2] < end]


def write_book_csv(
    target: Path,
    rows: list[tuple[int, int, int, list[str]]],
    delimiter: str,
    *,
    headers: list[str] | None = None,
) -> int:
    """Write tabular rows to a CSV/TSV-style output and return row count."""
    with target.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp, delimiter=delimiter, lineterminator="\n")
        if headers:
            writer.writerow(headers)
            for _table_id, _row_in_table, _offset, values in rows:
                writer.writerow(values)
            return len(rows)

        writer.writerow(["table_id", "row_in_table", "offset", "columns", "values"])
        for table_id, row_in_table, offset, values in rows:
            writer.writerow([table_id, row_in_table, offset, len(values), _pack_row_values(values)])
    return len(rows)


def write_book_xlsx(
    target: Path,
    rows: list[tuple[int, int, int, list[str]]],
    *,
    headers: list[str] | None = None,
) -> int:
    """Write tabular rows to XLSX and return row count."""
    try:
        workbook_module = __import__("openpyxl", fromlist=["Workbook"])
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("No module named 'openpyxl'", name="openpyxl") from exc

    workbook = workbook_module.Workbook()
    worksheet = workbook.active
    worksheet.title = "Book"
    if headers:
        worksheet.append(headers)
        for _, _, _, values in rows:
            worksheet.append(values)
        workbook.save(target)
        return len(rows)

    worksheet.append(["table_id", "row_in_table", "offset", "columns", "values"])
    for table_id, row_in_table, offset, values in rows:
        worksheet.append([table_id, row_in_table, offset, len(values), _pack_row_values(values)])
    workbook.save(target)
    return len(rows)
