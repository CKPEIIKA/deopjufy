from tests.cli.contracts.misc._test_cli_contracts_extract_misc_common import *  # noqa: F403


def test_support_class_treats_table_scan_partial_as_heuristic_reconnaissance() -> None:
    items = [
        {
            "kind": "table_scan",
            "name": "numeric_tables",
            "status": "partial",
            "confidence": 0.4,
            "discovery_type": "heuristic_scan",
            "heuristic": True,
        },
        {
            "kind": "worksheet",
            "name": "Sheet1",
            "status": "extracted",
            "confidence": 0.9,
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_table_scan_skipped_when_disabled_as_heuristic_reconnaissance() -> None:
    items = [
        {
            "kind": "table_scan",
            "name": "numeric_tables",
            "status": "skipped",
            "confidence": 0.4,
            "discovery_type": "heuristic_scan",
            "heuristic": True,
            "error": "table_scan_disabled_by_scan_profile",
        },
        {
            "kind": "worksheet",
            "name": "Sheet1",
            "status": "extracted",
            "confidence": 0.9,
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_graph_preview_absence_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "graph",
            "name": "Layer1",
            "status": "unsupported",
            "error": "no_graph_previews",
            "discovery_type": "parser_window",
            "heuristic": False,
        },
        {
            "kind": "graph_preview",
            "name": "Layer1",
            "status": "unsupported",
            "error": "no_embedded_image_block",
            "discovery_type": "parser_window",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_origin_storage_report_absence_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "origin_storage_report",
            "name": "origin_storage_reports",
            "status": "unsupported",
            "error": "no_origin_storage_reports",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_missing_matrix_collection_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "matrix",
            "name": "matrix_collection",
            "status": "unsupported",
            "error": "no_matrix_objects",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_tree_style_worksheet_placeholders_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "partial",
            "error": "no_extracted_table_rows",
            "source_object_path": "Book1/Book1",
            "discovery_type": "parser_window",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Sheet1",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_missing_function_collection_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "function",
            "name": "function_collection",
            "status": "unsupported",
            "error": "no_function_objects",
            "discovery_type": "heuristic_object_scan",
            "heuristic": True,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opju_origin_storage_report_absence_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "origin_storage_report",
            "name": "origin_storage_reports",
            "status": "partial",
            "error": "no_origin_storage_reports",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opju", "ok", items=items) == "parser"


def test_support_class_treats_opju_object_discovery_worksheet_partials_as_nonblocking() -> None:
    items = [
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "partial",
            "discovery_type": "object_discovery",
            "heuristic": True,
            "source_object_path": "Book1/Book1_A",
        },
        {
            "kind": "origin_object",
            "name": "opju_container",
            "status": "extracted",
            "discovery_type": "opj_boundary",
            "heuristic": False,
            "error": None,
        },
    ]

    assert command_support._support_class("opju", "ok", items=items) == "parser"


def test_support_class_treats_opj_excel_collection_absence_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "excel",
            "name": "excel_collection",
            "status": "unsupported",
            "error": "no_excel_objects",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_excel_collection_empty_rows_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "excel",
            "name": "excel_collection",
            "status": "unsupported",
            "error": "no_extracted_table_rows",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_opj_note_collection_absence_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "note",
            "name": "note_collection",
            "status": "unsupported",
            "error": "no_note_objects",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_target_exists_skips_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "discovery_type": "parser_window",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "skipped",
            "error": "target_exists",
            "discovery_type": "parser_window",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_support_class_treats_text_extraction_excluded_raw_dumps_as_scoped_nonblocking_gap() -> None:
    items = [
        {
            "kind": "raw_dump",
            "name": "offset:123456_length:256",
            "status": "skipped",
            "error": "excluded_by_text_extraction",
            "discovery_type": "unknown_gap",
            "heuristic": True,
        },
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]

    assert command_support._support_class("opj", "ok", items=items) == "parser"


def test_refresh_status_lock_scopes_tree_matrix_and_worksheet_reference_gaps() -> None:
    lock_path = REPO_ROOT / "tests" / "fixtures" / "ref-extract-status-lock.json"
    lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))

    for path in [
        "refs/github/Ropj/inst/tree.opj",
        "refs/ropj/src/Ropj/inst/tree.opj",
    ]:
        record = next(entry for entry in lock_payload["records"] if entry["path"] == path)

        assert record["partial_items"] == 0
        assert record["unsupported_items"] == 0
        assert not any(
            entry["kind"] == "matrix" and entry["status"] == "partial" and entry["error"] == "no_extracted_table_rows"
            for entry in record["artifact_histogram"]
        )
        assert not any(
            entry["kind"] == "worksheet"
            and entry["status"] == "unsupported"
            and entry["error"] == "no_extracted_table_rows"
            for entry in record["artifact_histogram"]
        )


def test_refresh_status_lock_scopes_opj_no_excel_no_note_as_nonblocking_evidence() -> None:
    lock_path = REPO_ROOT / "tests" / "fixtures" / "ref-extract-status-lock.json"
    lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))

    for path in [
        "refs/github/Ropj/inst/test.opj",
        "refs/github/Ropj/inst/tree.opj",
        "refs/ropj/src/Ropj/inst/test.opj",
        "refs/ropj/src/Ropj/inst/tree.opj",
    ]:
        record = next(entry for entry in lock_payload["records"] if entry["path"] == path)
        assert not any(
            entry["kind"] == "excel" and entry["status"] == "unsupported" and entry["error"] == "no_excel_objects"
            for entry in record["artifact_histogram"]
        )


def test_refresh_status_lock_scopes_zenodo_opju_note_gaps_as_nonblocking_evidence() -> None:
    lock_path = REPO_ROOT / "tests" / "fixtures" / "ref-extract-status-lock.json"
    lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))

    expected_unsupported = {
        "refs/public/zenodo/zenodo-10721640-figure-1b.opju": 0,
        "refs/public/zenodo/zenodo-18450855-eucd2p2.opju": 0,
        "refs/public/zenodo/zenodo-19549171-small-science-paper.opju": 0,
    }
    for path, unsupported_count in expected_unsupported.items():
        record = next(entry for entry in lock_payload["records"] if entry["path"] == path)

        assert record["unsupported_items"] == unsupported_count
        assert not any(
            entry["kind"] == "note" and entry["status"] == "unsupported" and entry["error"] == "no_note_objects"
            for entry in record["artifact_histogram"]
        )


def test_refresh_status_lock_scopes_zenodo_opju_report_gap_as_nonblocking_evidence() -> None:
    lock_path = REPO_ROOT / "tests" / "fixtures" / "ref-extract-status-lock.json"
    lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))

    expected_unsupported = {
        "refs/public/zenodo/zenodo-10721640-figure-1b.opju": 0,
        "refs/public/zenodo/zenodo-18450855-eucd2p2.opju": 0,
        "refs/public/zenodo/zenodo-19549171-small-science-paper.opju": 0,
    }
    for path, unsupported_count in expected_unsupported.items():
        record = next(entry for entry in lock_payload["records"] if entry["path"] == path)

        assert record["unsupported_items"] == unsupported_count
        assert not any(
            entry["kind"] == "origin_storage_report"
            and entry["status"] == "unsupported"
            and entry["error"] in {"no_origin_storage_reports", "no_origin_storage_report_summary"}
            for entry in record["artifact_histogram"]
        )


def test_support_scope_marks_supported_items_with_scoped_gaps_as_partial() -> None:
    items = [
        {
            "kind": "worksheet",
            "name": "Book1_A",
            "status": "partial",
            "error": "no_extracted_table_rows",
            "source_object_path": "Book1/Book1_A",
            "discovery_type": "object_discovery",
            "heuristic": False,
        },
        {
            "kind": "worksheet",
            "name": "Sheet1",
            "status": "extracted",
            "discovery_type": "parser_backed_hint",
            "heuristic": False,
        },
    ]
    coverage_scope, verification = command_support._support_scope(
        "opju",
        "ok",
        items=items,
    )

    assert coverage_scope == "partial"
    assert verification == "unverified"
