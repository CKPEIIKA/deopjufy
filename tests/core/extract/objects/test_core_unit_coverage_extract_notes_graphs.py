"""Split: notes/graph/function/table/raw extraction unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.core.extract.tables._test_core_unit_coverage_extract import (  # noqa: F401
    test_extract_functions_creates_function_directory_and_text,
    test_extract_functions_exports_parser_backed_function_payload,
    test_extract_functions_exports_parser_backed_opju_function_region,
    test_extract_functions_records_function_metadata_when_present,
    test_extract_functions_without_objects_no_parser_recovery,
    test_extract_graph_previews_does_not_resort_blocks_per_object,
    test_extract_graph_previews_emits_malformed_preview_item,
    test_extract_graph_previews_emits_parser_backed_jpeg_preview_object_item,
    test_extract_graph_previews_emits_parser_backed_preview_object_item,
    test_extract_graph_previews_expands_parser_window_for_parser_duplicates,
    test_extract_graph_previews_marks_invalid_jpeg_as_malformed_preview,
    test_extract_graph_previews_marks_no_graph_objects_as_unsupported_collection,
    test_extract_graph_previews_marks_parser_backed_graph_metadata,
    test_extract_graph_previews_marks_parser_backed_missing_preview_as_unavailable,
    test_extract_graph_previews_records_partial_without_embedded_block,
    test_extract_graph_previews_recovers_unsupported_jpeg_with_eoi,
    test_extract_graph_previews_skips_oversized_malformed_jpeg_salvage,
    test_extract_graph_previews_treats_layer_objects_as_graph_output,
    test_extract_graph_previews_uses_embedded_image_block,
    test_extract_notes_creates_note_files,
    test_extract_notes_emits_parser_backed_opju_note_payloads,
    test_extract_notes_emits_parser_notes_without_discovered_note_objects,
    test_extract_notes_extracts_heuristic_opju_notes,
    test_extract_notes_formats_markdown_and_html_when_detected,
    test_extract_notes_marks_no_parser_notes_as_unsupported_for_opju,
    test_extract_notes_records_note_payload_type,
    test_extract_notes_trim_neighboring_object_markers,
    test_extract_notes_uses_parser_note_sections_without_bleed,
    test_extract_raw_blocks_empty_file_records_partial,
    test_extract_raw_blocks_records_relative_manifest_paths,
    test_extract_raw_blocks_skips_locked_output,
    test_extract_tables_csv_and_json_formats,
    test_extract_tables_marks_skipped_when_output_locked,
    test_extract_tables_unknown_output_format_falls_back_to_json,
)
