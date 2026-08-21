"""Split: OPJ parsing unit coverage tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.core.basics.common._test_core_unit_coverage_basics import (  # noqa: F401
    test_parse_binary_opj_project_tree_preserves_nested_paths_and_object_ids,
    test_parse_opj_boundaries_includes_excel_attachment_parent_when_available,
    test_parse_opj_boundaries_includes_excel_payloads,
    test_parse_opj_boundaries_includes_layer_graph_names,
    test_parse_opj_boundaries_infers_tree_paths_from_references,
    test_parse_opj_boundaries_preserves_overlapping_spans_and_exact_duplicates,
    test_parse_opj_boundaries_uses_parsed_tree_ownership,
    test_parse_opj_function_metadata_decodes_native_dataset_header,
    test_parse_opj_function_metadata_recovers_formula_range_and_points,
    test_parse_opj_function_metadata_recovers_range_aliases,
    test_parse_opj_function_metadata_recovers_range_attributes,
    test_parse_opj_function_metadata_recovers_xf_name_formula,
    test_parse_opj_function_metadata_returns_none_without_known_fields,
    test_parse_opj_function_payload_extracts_tag_payload,
    test_parse_opj_matrix_metadata_recovers_dimensions,
    test_parse_opj_matrix_metadata_recovers_multicolumn_dimensions,
    test_parse_opj_note_metadata_keeps_results_log_and_exact_text_ranges,
    test_parse_opj_note_sections_recovers_results_blocks,
    test_parse_opj_parameters_parses_expected_records,
    test_parse_opj_tree_nodes_extracts_folder_records,
    test_parse_opj_tree_ownership_links_parses_bracket_references,
    test_parse_opj_tree_ownership_links_prefers_tree_blocks_when_present,
    test_parse_opj_worksheet_metadata_recovers_column_labels,
    test_parse_opj_worksheet_metadata_recovers_column_types_and_display_hints,
    test_parse_opj_worksheet_metadata_recovers_comments,
    test_parse_opj_worksheet_metadata_recovers_formula_rows,
    test_parse_opj_worksheet_metadata_recovers_formulas,
    test_parse_opj_worksheet_metadata_recovers_units,
    test_parse_opj_worksheet_metadata_recovers_window_long_name,
    test_parse_opj_worksheet_metadata_recovers_window_object_fields,
    test_parse_opju_origin_storage_reports_extracts_report_metadata,
    test_parse_real_opj_column_headers_recovers_designations_formats_and_formulas,
    test_parse_real_opj_matrix_layer_recovers_true_shape_and_view,
)
