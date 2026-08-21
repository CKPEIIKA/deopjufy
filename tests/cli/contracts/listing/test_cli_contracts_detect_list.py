"""Split: detect/list contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.cli.contracts.listing._test_cli_contracts import (  # noqa: F401
    test_detect_magic_magic_falls_back_for_unknown_extension,
    test_detect_magic_prefers_jpeg_magic_over_other_known,
    test_detect_magic_prefers_opj_magic_for_unknown_extension,
    test_detect_magic_prefers_opju_magic_for_unknown_extension,
    test_detect_prefers_extension_over_magic_signature,
    test_detect_unknown_returns_unknown,
    test_list_can_include_raw_gaps_as_items,
    test_list_distinguishes_opju_parser_structural_object_kinds,
    test_list_distinguishes_parser_backed_and_heuristic_objects,
    test_list_empty_opj_file_is_marked_empty,
    test_list_includes_opju_raw_dump_crosswalk_for_parser_backed_records,
    test_list_opj_heuristic_limit_exhaustive_override,
    test_list_opju_bounded_heuristic_items_default_and_exhaustive_override,
    test_list_opju_heuristic_note_function_excel_graph_are_parser_gated,
    test_list_opju_parser_items_are_included_in_default_output,
    test_list_outputs_items_sorted_by_offset_for_opju_file,
    test_list_reports_origin_objects_in_discovery,
    test_list_supported_file_with_no_items_is_unsupported,
    test_list_unsupported_file_type_is_supported_shape,
    test_list_uses_stable_parser_backed_opju_naming_for_duplicates,
)
