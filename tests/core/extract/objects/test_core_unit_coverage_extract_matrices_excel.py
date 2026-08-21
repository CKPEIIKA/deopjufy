"""Split: matrix and Excel extraction unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.core.extract.tables._test_core_unit_coverage_extract import (  # noqa: F401
    test_extract_books_skips_numeric_scan_for_large_file_without_parser_rows,
    test_extract_excel_creates_excel_directory_and_rows,
    test_extract_excel_marks_missing_opj_excel_objects_as_unsupported_collection,
    test_extract_matrices_creates_matrices_directory_and_rows,
    test_extract_matrices_marks_missing_opj_matrix_objects_as_unsupported_collection,
    test_extract_matrices_recover_rows_and_columns_from_opj_metadata,
    test_extract_matrices_recovers_concrete_matrix_payload_from_opj_sections,
    test_extract_matrices_resolves_collision_suffix_names_for_parser_metadata,
    test_extract_matrices_writes_matrix_metadata_sidecar,
)
