"""Split: core unit basics for detect/manifest/session helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.core.basics.common._test_core_unit_coverage_basics import (  # noqa: F401
    test_classify_object_kind_covers_reference_object_types,
    test_derive_source_path_and_unique_pathing,
    test_detect_extension_mismatch_still_records_magic_type,
    test_detect_file_extension_is_case_insensitive,
    test_detect_file_magic_samples,
    test_detect_file_opj_extension_stays_opj,
    test_detect_file_opju_extension_stays_opju,
    test_detect_file_unknown_magic_only,
    test_discover_origin_objects_falls_back_to_heuristics_when_parser_boundaries_empty,
    test_discover_origin_objects_falls_back_to_origin_project_for_headered_opj,
    test_discover_origin_objects_from_bracketed_references,
    test_discover_origin_objects_from_name_tokens,
    test_discover_origin_objects_keeps_parser_backed_source_paths,
    test_discover_origin_objects_large_opj_scans_tokens_across_chunks,
    test_discover_origin_objects_large_opj_uses_parser_boundaries_for_streaming_mode,
    test_discover_origin_objects_large_opj_uses_streaming,
    test_discover_origin_objects_large_opju_with_column_table_uses_parser_records,
    test_discover_origin_objects_medium_opj_uses_parser_boundaries,
    test_dump_range_read_past_end_and_negative_offsets,
    test_extraction_session_caches_file_data,
    test_extraction_session_caches_list_items,
    test_extraction_session_caches_objects_and_tables,
    test_find_all_blocks_filters_types,
    test_find_all_blocks_rejects_unknown_filter_types,
    test_find_image_blocks_captures_gif_heuristic,
    test_find_image_blocks_excludes_malformed_jpeg_spans,
    test_find_image_blocks_includes_malformed_jpeg_when_requested,
    test_find_image_blocks_includes_malformed_png_candidates,
    test_iter_file_chunks_respects_chunk_size,
    test_iter_object_windows_prefers_parser_confirmed_boundaries,
    test_list_items_marks_object_kind_for_origin_objects,
    test_list_items_matches_block_inventory,
    test_make_manifest_and_write_has_stable_payload,
    test_manifest_items_are_stably_sorted_before_write,
    test_manifest_schema_is_strict_and_status_is_valid,
    test_manifest_write_uses_lf_line_endings,
    test_merge_parser_and_heuristic_records_prefers_parser_confirmed_objects,
    test_merge_parser_and_heuristic_records_prefers_parser_objects_on_overlap,
    test_origin_object_collision_paths_are_stabilized,
    test_parse_helpers_cover_edge_cases,
    test_parse_helpers_cover_opj_payload_boundaries,
    test_read_cached_bytes_uses_stat_keyed_cache,
    test_sanitize_name_keeps_safe_and_replaces_unsafe,
    test_session_list_items_can_include_raw_gaps,
    test_sha256_file_uses_stat_keyed_cache,
    test_unique_path_avoids_case_insensitive_collision,
)
