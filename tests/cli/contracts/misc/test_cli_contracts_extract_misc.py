"""Split: extract command and misc CLI contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.cli.contracts.misc._test_cli_contracts import (  # noqa: F401
    test_build_parser_accepts_all_supported_commands,
    test_cli_main_rejects_missing_command,
    test_cli_main_rejects_missing_file_argument,
    test_dump_block_out_of_range_is_corrupted_error,
    test_dump_block_zero_length_emits_empty_payload,
    test_extract_force_keeps_unsupported_collection_markers_with_existing_outputs,
    test_extract_marks_partial_for_malformed_preview_payload,
    test_extract_parser_error_reports_corrupted_exit,
    test_extract_parser_error_reports_opju_originstorage_truncation,
    test_extract_rejects_unrecognized_input_without_manifest,
    test_extract_without_file_data_inputs_does_not_load_full_bytes,
    test_help_message_has_ascii_mascot_and_examples,
    test_inspect_parser_error_reports_truncated_opj_boundary,
    test_list_parser_error_reports_error_status,
    test_list_parser_error_reports_truncated_opju_region,
    test_list_payload_marks_unsupported,
    test_sanitize_name_replaces_unsafe_characters,
    test_sanitize_name_returns_default_for_empty_value,
    test_strings_ascii_respects_min_length,
    test_strings_invalid_encoding_is_rejected_by_cli_parser,
    test_strings_large_split_multibyte_input_stays_deterministic,
    test_strings_utf16_mode_outputs_decoded_text,
)
