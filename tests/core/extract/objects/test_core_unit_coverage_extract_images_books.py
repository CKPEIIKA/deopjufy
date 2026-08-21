"""Split: image/string/book/matrix extraction unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.core.extract.tables._test_core_unit_coverage_extract import (  # noqa: F401
    test_extract_books_counts_parser_backed_worksheet_hints_without_rows,
    test_extract_books_creates_books_directory_and_rows,
    test_extract_books_does_not_numeric_scan_for_parser_boundary_window,
    test_extract_books_emits_empty_sheet_with_header_when_no_rows,
    test_extract_books_groups_book_prefix_sources_into_workbook_directories_for_opj,
    test_extract_books_records_relative_manifest_paths,
    test_extract_books_recover_rows_and_columns_from_opj_metadata,
    test_extract_books_recovers_column_semantics_from_opj_sections,
    test_extract_books_supports_xlsx_format_with_openpyxl_stub,
    test_extract_books_uses_parser_backed_opju_worksheet_names,
    test_extract_books_uses_parser_backed_rows_without_numeric_scan,
    test_extract_books_writes_worksheet_metadata_sidecar,
    test_extract_excel_from_parser_backed_opju_attachment_hint,
    test_extract_excel_marks_parser_backed_excel_objects,
    test_extract_images_emits_manifest_records,
    test_extract_images_marks_malformed_png_as_partial,
    test_extract_images_marks_skipped_when_output_exists,
    test_extract_images_reads_only_by_ranges_when_file_data_not_provided,
    test_extract_images_uses_parser_owned_window_metadata,
    test_extract_matrices_does_not_emit_unsupported_collection_for_opju_without_parser_rows,
    test_extract_non_xlsx_parser_backed_opju_attachment_hint,
    test_extract_origin_inventory_writes_metadata_file,
    test_extract_origin_storage_reports_skips_locked_report_artifacts_without_force,
    test_extract_origin_storage_reports_uses_parser_backed_names,
    test_extract_origin_storage_reports_writes_manifest_files,
    test_extract_strings_marks_partial_when_no_data,
    test_extract_strings_uses_streaming_scan_not_read_bytes,
    test_extract_strings_writes_file_and_records_status,
    test_graph_preview_blocks_are_excluded_from_generic_image_exports,
    test_infer_parser_backed_worksheet_names_keeps_multiple_workbook_matches,
    test_infer_parser_backed_worksheet_names_normalizes_report_tokens,
)
