"""Split: inspect payload and determinism contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests.cli.contracts.listing._test_cli_contracts import (  # noqa: F401
    test_inspect_counts_include_origin_object_inventory,
    test_inspect_empty_opj_file_marks_empty,
    test_inspect_failure_payload_stays_schema_stable,
    test_inspect_includes_compact_parser_evidence_counts,
    test_inspect_includes_opju_raw_dump_crosswalk_summary,
    test_inspect_includes_tool_metadata,
    test_inspect_missing_file_still_emits_json,
    test_inspect_opju_without_parser_backed_artifacts_is_unknown,
    test_inspect_parser_error_reports_error_status,
    test_inspect_payload_is_deterministic_for_same_input,
    test_inspect_recognized_file_reports_status_and_counts,
    test_inspect_reports_magic_format_hints_for_extension_mismatch,
    test_inspect_reports_parser_backed_and_heuristic_counts_separately,
    test_inspect_support_class_for_opj,
    test_inspect_synthetic_binary_opju_without_parser_records_is_unknown,
    test_inspect_unsupported_binary_with_embedded_signatures_still_reports_zero_counts,
    test_inspect_unsupported_file_type_returns_code_three,
    test_list_failure_payload_stays_schema_stable,
    test_list_missing_file_still_emits_json,
    test_list_payload_includes_status,
    test_list_payload_is_deterministic_for_same_input,
    test_list_unsupported_file_with_signature_stays_empty,
    test_rejects_backend_argument,
    test_signature_scan_not_repeated_for_supported_commands,
)
