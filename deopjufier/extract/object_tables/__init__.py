"""Tabular extractor facade."""

from pathlib import Path

from deopjufier.extract.discovery_helpers import book_dir as _book_dir
from deopjufier.extract.object_tables_extract_tables import (
    extract_books,
    extract_excel,
    extract_matrices,
)
from deopjufier.extract.object_tables_match import (
    _collapse_worksheet_recovery_names,
)
from deopjufier.extract.object_tables_match import *
from deopjufier.extract.tabular_helpers import write_book_xlsx as _default_write_book_xlsx
from deopjufier.extract.tables import scan_numeric_tables_from_bytes
from deopjufier.opj import (
    recover_excel_sheets_from_opj_sections,
    recover_matrix_metadata_from_opj_sections,
    recover_worksheet_metadata_from_opj_sections,
)
from deopjufier.opju import (
    recover_matrix_rows_from_opju,
    recover_worksheet_metadata_from_opju,
    recover_worksheet_rows_from_opju,
)

__all__ = [name for name in globals() if not name.startswith("_")]


# Default compatibility points for tests and parser monkeypatching.
def _write_book_xlsx(
    target: Path,
    rows: list[tuple[int, int, int, list[str]]],
    headers: list[str] | None = None,
) -> int:
    return _default_write_book_xlsx(target, rows, headers=headers)
