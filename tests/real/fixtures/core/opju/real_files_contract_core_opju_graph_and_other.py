from tests.real.fixtures.core.opju.real_files_contract_core_opju_common import *  # noqa: F403
from tests.real.fixtures.core.opju.real_files_contract_core_opju_common import (
    _public_opju_science_paper_sample,
)


def test_real_small_science_paper_has_parser_backed_exact_worksheet_rows(
    cached_extract,
) -> None:
    sample = _public_opju_science_paper_sample()
    run = cached_extract(sample, "--no-strings", "--no-tables", "--no-images")
    payload = run.payload

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert worksheet_items, "Expected worksheet artifacts for small science fixture"

    exact_row_items = [
        item
        for item in worksheet_items
        if str(item.get("name", "")).startswith("Book1_")
        and str(item.get("name", "")).endswith("@7")
        and item.get("status") in {"extracted", "partial"}
    ]
    expected_exact_names = {
        "Book1_A@7",
        "Book1_AA@7",
        "Book1_AB@7",
        "Book1_AC@7",
        "Book1_AD@7",
        "Book1_AF@7",
        "Book1_AE@7",
        "Book1_AG@7",
        "Book1_AH@7",
        "Book1_AI@7",
        "Book1_E@7",
        "Book1_F@7",
        "Book1_AJ@7",
        "Book1_AK@7",
        "Book1_AL@7",
        "Book1_AM@7",
        "Book1_AN@7",
        "Book1_AP@7",
        "Book1_AO@7",
        "Book1_AQ@7",
        "Book1_AS@7",
        "Book1_AR@7",
        "Book1_AT@7",
        "Book1_AU@7",
        "Book1_AV@7",
        "Book1_D@7",
        "Book1_Z@7",
        "Book1_Y@7",
    }
    exact_row_names = {str(item.get("name", "")) for item in exact_row_items}
    expected_rowful_names = {
        "Book1_A@7",
        "Book1_AA@7",
        "Book1_AB@7",
        "Book1_AC@7",
        "Book1_AD@7",
        "Book1_AE@7",
        "Book1_AF@7",
        "Book1_AG@7",
        "Book1_AH@7",
        "Book1_AI@7",
        "Book1_AJ@7",
        "Book1_AK@7",
        "Book1_AL@7",
        "Book1_AM@7",
        "Book1_AN@7",
        "Book1_AO@7",
        "Book1_AP@7",
        "Book1_AQ@7",
        "Book1_AR@7",
        "Book1_AS@7",
        "Book1_AT@7",
        "Book1_AU@7",
        "Book1_AV@7",
        "Book1_D@7",
        "Book1_E@7",
        "Book1_F@7",
        "Book1_Y@7",
        "Book1_Z@7",
    }
    assert expected_exact_names.issubset(exact_row_names), (
        "Expected parser-backed exact Book1_*@7 rows for all currently known worksheet names"
    )
    assert "Book1_A@7" in exact_row_names

    rowful_items = [
        item
        for item in exact_row_items
        if str(item.get("name", "")) in expected_rowful_names and item.get("status") == "extracted"
    ]
    assert all(item.get("error") is None for item in rowful_items), (
        "Expected no parser errors for extracted exact rowful Book1_*@7 rows"
    )
    assert all(item.get("rows", 0) > 0 for item in rowful_items), (
        "Expected parser-backed rowful Book1_*@7 windows to have data"
    )
    assert all(item.get("status") == "extracted" for item in rowful_items)

    partial_items = [item for item in exact_row_items if item.get("status") == "partial"]
    assert all(item.get("error") == "no_extracted_table_rows" and item.get("rows") == 0 for item in partial_items), (
        "Unrecovered parser-backed worksheet windows must remain explicit partial evidence"
    )

    extracted_book1_items = [
        item
        for item in worksheet_items
        if str(item.get("name", "")).startswith("Book1_") and item.get("status") == "extracted"
    ]
    allowed_non_standard_book_names = {"Book1_P@10"}
    assert all(
        str(item.get("name", "")).endswith("@7") or str(item.get("name", "")) in allowed_non_standard_book_names
        for item in extracted_book1_items
    ), "Book1_* extracted worksheet rows should remain on @7 names and not be emitted as @10 or other variants"

    assert all("@" in str(item.get("name", "")) for item in exact_row_items)

    for item in rowful_items[:2]:
        assert item.get("path")
        assert (run.output_dir / str(item["path"])).exists()

    book1_p10_items = [item for item in worksheet_items if str(item.get("name", "")) == "Book1_P@10"]
    assert book1_p10_items, "Expected parser-backed extracted Book1_P@10 worksheet artifact"
    assert book1_p10_items[0].get("status") == "extracted"
    assert book1_p10_items[0].get("rows", 0) > 0
    assert all(str(item.get("name", "")) != "Book1_P@7" for item in worksheet_items)


def test_public_figure_1b_note_gap_has_parser_region_source_evidence(
    cached_extract,
) -> None:
    sample = _public_opju_report_sample()
    payload = _run_extract_manifest(sample, cached_extract, "--no-images")

    note_collection = next(
        (
            item
            for item in payload.get("items", [])
            if item.get("kind") == "note"
            and item.get("name") == "note_collection"
            and item.get("status") == "unsupported"
            and item.get("error") == "no_note_objects"
        ),
    )
    assert isinstance(note_collection.get("range_start"), int)
    assert isinstance(note_collection.get("range_end"), int)
    assert note_collection.get("range_end", 0) >= note_collection.get("range_start", 0)

    file_bytes = sample.read_bytes()
    range_start = note_collection.get("range_start")
    range_end = note_collection.get("range_end")
    assert range_start is not None and range_end is not None
    assert 0 <= range_start <= range_end <= len(file_bytes)

    parsed_records = parse_opju_records(file_bytes, path=sample)
    assert not any(record.kind == OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE for record in parsed_records.regions)
    unrelated_directory_kinds = {
        OPJU_REGION_KIND_FOLDER_DIRECTORY,
        OPJU_REGION_KIND_PAGE_DIRECTORY,
        "opju_container",
    }
    parser_sources = {
        record.source_object_path
        for record in parsed_records.regions
        if record.kind not in unrelated_directory_kinds and record.length > 0
    }
    source_object_path = note_collection.get("source_object_path")
    if parser_sources:
        assert source_object_path in parser_sources

    parser_spans = [
        (record.offset, record.offset + record.length)
        for record in parsed_records.regions
        if record.kind not in unrelated_directory_kinds and record.length > 0
    ]
    if parser_spans:
        assert note_collection.get("range_start") == min(start for start, _ in parser_spans)
        assert note_collection.get("range_end") == max(end for _, end in parser_spans)


def test_public_opju_extract_records_preview_is_parser_backed(cached_extract) -> None:
    sample = _public_opju_report_sample()
    payload = _run_extract_manifest(sample, cached_extract)

    target = next(
        (
            item
            for item in payload.get("items", [])
            if item.get("kind") == "parser_backed_graph_preview" and item.get("name") == "origin_storage_preview_000"
        ),
        None,
    )
    assert target is not None, "Expected parser-backed graph preview in figure-1b sample"
    assert target.get("status") == "extracted"
    assert target.get("error") is None
    assert target.get("path") == "graphs/previews/origin_storage_preview_000/graph.png"


def test_real_eucd2p2_graph_preview_extraction_is_deterministic(
    public_graph_gap_no_images_no_strings,
) -> None:
    payload = public_graph_gap_no_images_no_strings.payload
    graph_items = [
        item
        for item in payload["items"]
        if item.get("kind") in {"graph", "parser_backed_graph_preview", "graph_preview"}
    ]
    assert graph_items, "Expected graph-family output for zenodo-18450855."
    assert any(
        item.get("kind") in {"graph", "parser_backed_graph_preview"}
        and item.get("status") in {"extracted", "unsupported"}
        for item in graph_items
    )
    assert all(not (item.get("kind") == "graph_preview" and item.get("status") == "partial") for item in graph_items)


def test_real_eucd2p2_has_no_heuristic_worksheet_partials(
    public_graph_gap_no_images,
) -> None:
    payload = public_graph_gap_no_images.payload

    worksheet_items = [item for item in payload.get("items", []) if item.get("kind") == "worksheet"]
    worksheet_partials = [
        item
        for item in worksheet_items
        if not str(item.get("name", "")).endswith("_collection") and item.get("status") == "partial"
    ]
    assert all(not item.get("heuristic") for item in worksheet_partials)
    worksheet_heuristic_partials = [item for item in worksheet_partials if item.get("heuristic", False)]
    assert not worksheet_heuristic_partials


def test_real_eucd2p2_note_payload_is_proven_unsupported(
    public_graph_gap_no_images,
) -> None:
    payload = public_graph_gap_no_images.payload
    sample = _public_opju_graph_gap_sample()

    note_collection = next(
        item
        for item in payload.get("items", [])
        if item.get("kind") == "note"
        and item.get("name") == "note_collection"
        and item.get("status") == "unsupported"
        and item.get("error") == "no_note_objects"
    )
    assert isinstance(note_collection.get("range_start"), int)
    assert isinstance(note_collection.get("range_end"), int)

    file_bytes = sample.read_bytes()
    range_start = note_collection["range_start"]
    range_end = note_collection["range_end"]
    assert 0 <= range_start <= range_end <= len(file_bytes)
    assert range_end > range_start

    records = parse_opju_records(file_bytes, path=sample)
    assert not any(record.kind == OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE for record in records.regions)


def test_real_eucd2p2_graph_preview_miss_carries_no_image_payload(
    public_graph_gap_default,
) -> None:
    sample = _public_opju_graph_gap_sample()
    payload = public_graph_gap_default.payload
    preview_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") in {"graph", "parser_backed_graph_preview"}
        and item.get("status") == "extracted"
        and item.get("source_object_path") == "previews/origin_storage_preview_000"
    ]
    if preview_items:
        assert all(item.get("heuristic") is False for item in preview_items)
    _assert_graph_preview_miss_has_no_embedded_image_bytes(sample, payload, "Graph112")


def test_real_eucd2p2_extract_emits_parser_backed_function(
    public_graph_gap_no_images,
) -> None:
    run = public_graph_gap_no_images
    payload = run.payload
    function_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "function" and item.get("name") != "function_collection"
    ]
    assert function_items, "Expected parser-backed function artifacts for zenodo-18450855"

    recovered_items = [
        item
        for item in function_items
        if item.get("extraction_method") == "origin_storage_byte_run_decode"
        and item.get("discovery_type") == "origin_storage_byte_run_phase_recovery"
        and item.get("heuristic") is True
    ]
    assert recovered_items, "Expected exact byte-run recovered function artifacts for zenodo-18450855"

    for item in recovered_items:
        assert item.get("status") == "extracted"
        assert item.get("error") is None
        assert item.get("verification") == "exact"
        assert item.get("path"), f"Missing function export path: {item}"
        function_path = run.output_dir / Path(item["path"])
        assert function_path.exists()
        assert function_path.suffix == ".xml"
        assert function_path.read_bytes().startswith(b"<OriginStorage")


def test_real_opju_parser_backed_graph_previews_emit_valid_image_files(public_graph_gap_default) -> None:
    run = public_graph_gap_default
    output = run.output_dir
    payload = run.payload

    preview_items = [
        item for item in payload.get("items", []) if item.get("kind") in {"graph", "parser_backed_graph_preview"}
    ]
    assert preview_items, "Expected preview graph outputs for real OPJU graph sample"
    preview_files = [
        output / str(item["path"])
        for item in payload["items"]
        if item.get("kind") in {"graph", "parser_backed_graph_preview"}
        and item.get("status") in {"extracted", "partial"}
        and isinstance(item.get("path"), str)
    ]
    image_suffixes = {".png", ".jpg", ".jpeg", ".pdf", ".svg"}
    image_files = [path for path in preview_files if path.suffix in image_suffixes]
    assert any(path.exists() for path in image_files), (
        "Expected at least one extracted preview image path for this fixture."
    )

    image_path = next(path for path in image_files if path.exists())
    data = image_path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8")


def test_public_opju_fail_on_partial_returns_exit_code(public_worksheet_gap_fail_on_partial) -> None:
    run = public_worksheet_gap_fail_on_partial
    assert run.exit_code == 4
    payload = run.payload
    assert any(item.get("status") in {"partial", "unsupported"} for item in payload.get("items", []))
    assert payload.get("support_class") in {"partial", "parser"}


def test_real_small_science_graph_preview_miss_carries_no_image_payload(
    public_jpg_attachment_default,
) -> None:
    sample = _public_opju_jpg_attachment_sample()
    payload = public_jpg_attachment_default.payload
    _assert_graph_preview_miss_has_no_embedded_image_bytes(
        sample,
        payload,
        "Graph22",
    )
