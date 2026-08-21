"""Split: OPJU parsing and helper edge-case unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.core.basics.common._test_core_unit_coverage_basics import (  # noqa: F401
    test_book_dir_normalizes_windows_separators_and_reserved_names,
    test_discover_origin_objects_uses_structural_opju_region_kinds,
    test_find_graph_block_for_object_prefers_valid_candidate_over_invalid,
    test_find_graph_block_for_object_rejects_bad_bounds,
    test_manifest_path_is_relative_when_under_base,
    test_manifest_path_never_returns_absolute_when_outside_base,
    test_parse_opju_column_tables_decodes_binary_payloads,
    test_parse_opju_column_tables_limits_binary_rows_to_max_rows,
    test_parse_opju_column_tables_recovers_explicit_column_rows,
    test_parse_opju_column_tables_rejects_partial_binary_payload_rows,
    test_parse_opju_records_balances_nested_origin_storage_blocks,
    test_parse_opju_records_cache_reuse_for_reports_and_tables,
    test_parse_opju_records_classifies_attachment_regions,
    test_parse_opju_records_classifies_attachment_regions_for_multiple_extensions,
    test_parse_opju_records_classifies_control_byte_split_function_tags,
    test_parse_opju_records_classifies_control_byte_split_note_tags,
    test_parse_opju_records_classifies_expgraph_regions_as_function,
    test_parse_opju_records_classifies_fitcurve_aliases_as_function,
    test_parse_opju_records_classifies_function_without_whole_word_match,
    test_parse_opju_records_classifies_origin_storage_regions_before_deeper_recovery,
    test_parse_opju_records_classifies_xffunction_records_as_function,
    test_parse_opju_records_parses_cpyua_header,
    test_parse_opju_records_returns_typed_empty_for_non_opju_payload,
    test_parse_opju_records_uses_deterministic_parser_backed_naming,
)
