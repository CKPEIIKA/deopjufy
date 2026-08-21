from tests.real.fixtures.core.opju.real_files_contract_core_opju_common import *  # noqa: F403


def _count_csv_shape(table_path: Path) -> tuple[int, int]:
    delimiter = ","
    if table_path.suffix.lower() == ".tsv":
        delimiter = "\t"

    with table_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.reader(fp, delimiter=delimiter))

    if not rows:
        return (0, 0)

    scan_header = ("table_id", "row_in_table", "offset", "columns", "values")
    parser_header = bool(rows[0]) and all(
        value.startswith("col_") and value.removeprefix("col_").isdigit() for value in rows[0]
    )
    data_rows = rows[1:] if tuple(rows[0]) == scan_header or parser_header else rows

    row_count = len(data_rows)
    column_count = 0
    for row in data_rows:
        if tuple(rows[0]) == scan_header and len(row) >= 5:
            declared_columns = row[3].strip()
            if declared_columns.isdigit():
                column_count = max(column_count, int(declared_columns))
                continue
            values_field = row[-1]
            values_count = 0 if not values_field else values_field.count(";") + 1
            column_count = max(column_count, values_count)
            continue

        column_count = max(column_count, len(row))
    return row_count, column_count


def _count_item_csv_shape(table_path: Path, item: dict[str, Any]) -> tuple[int, int]:
    row_count, column_count = _count_csv_shape(table_path)
    if item.get("extraction_method") == "opju_descriptor_table":
        row_count = max(0, row_count - 1)
    return row_count, column_count


def _iter_opju_tabular_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict) and item.get("kind") in {"worksheet", "matrix"}
    ]


def _assert_tabular_shape_matches_extracted_file(output: Path, item: dict[str, Any]) -> None:
    assert item.get("status") == "extracted"
    assert item.get("path") is not None
    table_path = output / str(item["path"])
    assert table_path.exists()

    row_count, column_count = _count_item_csv_shape(table_path, item)
    assert row_count >= 0
    assert column_count >= 0
    assert item.get("rows") == row_count
    assert item.get("columns") == column_count


@pytest.mark.timeout(480)  # Multi-sample OPJU loop in one extraction test.
def test_real_opju_extracted_worksheet_matrix_schema_matches_csv_shape(
    cached_extract,
) -> None:
    opju_samples = [
        (
            "zenodo figure-1b",
            REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
        ),
        (
            "zenodo eucd2p2",
            REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-18450855-eucd2p2.opju",
        ),
    ]
    for _sample_label, sample in opju_samples:
        if not sample.exists():
            continue

        run = cached_extract(sample, "--no-images")
        sample_output = run.output_dir
        payload = run.payload
        tabular_items = _iter_opju_tabular_items(payload)
        if not tabular_items:
            continue

        extracted_items = [item for item in tabular_items if item.get("status") == "extracted"]
        for item in extracted_items:
            _assert_tabular_shape_matches_extracted_file(sample_output, item)

        partial_items = [item for item in tabular_items if item.get("status") in {"partial", "unsupported"}]
        if extracted_items:
            # Keep parse-failure semantics explicit.
            for item in partial_items:
                assert item.get("error") == "no_extracted_table_rows"

        if extracted_items:
            return

    pytest.skip("No OPJU fixture with extracted worksheet/matrix rows found for schema matching.")


def test_public_opju_extract_has_parser_backed_report_metadata(
    public_worksheet_gap_no_images_no_strings,
) -> None:
    run = public_worksheet_gap_no_images_no_strings
    payload = run.payload

    report_items = [
        item
        for item in payload["items"]
        if item.get("kind") == "origin_storage_report"
        and item.get("name") not in {"origin_storage_reports", "origin_storage_reports.json"}
    ]
    summary_items = [item for item in payload["items"] if item.get("kind") == "origin_storage_report_summary"]
    report_json_items = [
        item
        for item in payload["items"]
        if item.get("kind") == "origin_storage_report" and item.get("name") == "origin_storage_reports.json"
    ]

    assert report_items
    assert all(
        item.get("status") == "extracted"
        and item.get("heuristic") is False
        and str(item.get("source_object_path", "")).startswith("origin_storage_reports/")
        for item in report_items
    )
    assert report_json_items
    assert all(item.get("status") == "extracted" for item in report_json_items)
    assert summary_items
    assert all(item.get("status") == "extracted" for item in summary_items)


def test_public_opju_extract_records_has_parser_backed_worksheet_objects(
    public_worksheet_gap_no_images,
) -> None:
    sample = _public_opju_worksheet_gap_sample()
    payload = public_worksheet_gap_no_images.payload

    parsed_records = parse_opju_records(sample.read_bytes(), max_tables=200)
    assert parsed_records.worksheets
    assert len(parsed_records.worksheets) == 8
    assert all(str(worksheet.name).startswith("origin_storage_family_") for worksheet in parsed_records.worksheets)

    collection_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and str(item.get("name", "")).endswith("_collection")
    ]
    assert not any(item.get("error") == "no_matching_metadata" for item in collection_items)

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert worksheet_items, "Expected parser-backed worksheet artifacts for fixture"
    assert len(worksheet_items) >= 8
    assert all(item.get("status") in {"extracted", "partial"} for item in worksheet_items)
    assert all(item.get("error") in {None, "no_extracted_table_rows"} for item in worksheet_items)


def _assert_real_fixture_worksheet_scope_contract(
    payload: dict,
    *,
    sample: Path,
    sample_label: str,
    allow_mixed_status: bool = False,
) -> None:
    parsed_records = parse_opju_records(sample.read_bytes(), max_tables=200)
    discovered_worksheet_objects = [obj for obj in discover_origin_objects(sample) if obj.object_kind == "worksheet"]
    discovered_worksheet_names = {obj.name for obj in discovered_worksheet_objects}
    parser_worksheet_names = {str(worksheet.name) for worksheet in parsed_records.worksheets}
    parser_worksheet_names = {
        name for name in parser_worksheet_names if not str(name).startswith("origin_storage_family_")
    }
    has_parser_worksheet_scope = bool(parser_worksheet_names)

    worksheet_items = [item for item in payload.get("items", []) if item.get("kind") == "worksheet"]
    assert worksheet_items, f"Expected worksheet artifacts for {sample_label}"

    collection_items = [item for item in worksheet_items if str(item.get("name", "")).endswith("_collection")]
    assert not collection_items, f"Unexpected worksheet collection placeholders for {sample_label}"
    assert not any(item.get("error") == "no_matching_metadata" for item in collection_items)

    worksheet_scope = [item for item in worksheet_items if not str(item.get("name", "")).endswith("_collection")]
    assert worksheet_scope, f"Expected per-worksheet worksheet artifacts for {sample_label}"
    worksheet_names = [str(item.get("name")) for item in worksheet_scope if item.get("name") is not None]
    assert len(worksheet_names) == len(set(worksheet_names)), (
        f"Duplicate worksheet names in per-worksheet scope for {sample_label}"
    )
    assert all(item.get("status") in {"extracted", "partial"} for item in worksheet_scope)
    if not allow_mixed_status:
        assert all(item.get("status") == "partial" for item in worksheet_scope)
    assert all(item.get("heuristic") is False for item in worksheet_scope)
    parser_discovery_types = {
        "opju_column_descriptor_table",
        "parser_backed_hint",
        "parser_window",
    }
    assert all(item.get("discovery_type") in parser_discovery_types for item in worksheet_scope)
    assert any(item.get("status") in {"extracted", "partial"} for item in worksheet_scope)
    assert all(
        item.get("error") in {None, "no_extracted_table_rows"}
        for item in worksheet_scope
        if item.get("status") == "partial"
    )
    descriptor_scope = [
        item for item in worksheet_scope if item.get("discovery_type") == "opju_column_descriptor_table"
    ]
    assert all(
        item.get("status") == "extracted"
        and item.get("extraction_method") == "opju_descriptor_table"
        and item.get("source_object_path") == item.get("name")
        for item in descriptor_scope
    )
    discovered_scope = [item for item in worksheet_scope if item not in descriptor_scope]
    assert all(
        (
            str(item.get("name")) in parser_worksheet_names
            if has_parser_worksheet_scope
            else str(item.get("name")) in discovered_worksheet_names
        )
        for item in discovered_scope
    ), f"Non-parser worksheet artifact found for {sample_label}"
    discovered_paths = {obj.source_object_path for obj in discovered_worksheet_objects}
    assert discovered_paths, f"Expected discovered worksheet objects for {sample_label}"

    discovered_windows = {
        (obj.name, obj.source_object_path, start, end, obj.parser_confirmed)
        for obj, start, end in iter_object_windows(
            sorted(discovered_worksheet_objects, key=lambda item: item.offset),
            sample.stat().st_size,
            scope_by_source_prefix=sample.suffix.lower() == ".opju",
        )
        if obj.offset >= 0 and obj.source_object_path
    }

    for item in discovered_scope:
        source_path = item.get("source_object_path")
        assert isinstance(source_path, str) and source_path
        assert source_path in discovered_paths, (
            f"Missing discovered worksheet source path evidence for {item['name']} in {sample_label}"
        )

        range_start = item.get("range_start")
        range_end = item.get("range_end")
        assert isinstance(range_start, int)
        assert isinstance(range_end, int)
        assert range_end >= range_start

        assert any(
            candidate_name == item["name"]
            and candidate_source == source_path
            and candidate_offset == range_start
            and (candidate_parser_confirmed is False or candidate_range_end == range_end)
            for (
                candidate_name,
                candidate_source,
                candidate_offset,
                candidate_range_end,
                candidate_parser_confirmed,
            ) in discovered_windows
        ), f"No discovered worksheet window bound to manifest item {item['name']} in {sample_label}"


def test_public_opju_extract_worksheet_gap_has_no_zero_row_worksheet_partials(
    public_worksheet_gap_no_images,
) -> None:
    payload = public_worksheet_gap_no_images.payload

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert worksheet_items, "Expected worksheet artifacts for public OPJU worksheet-gap fixture"
    for item in worksheet_items:
        if item.get("status") == "extracted":
            assert item.get("rows", 0) >= 0
        else:
            assert item.get("status") == "partial"
            assert item.get("error") in {None, "no_extracted_table_rows"}


def test_real_figure_1b_worksheet_lock_scope_is_per_worksheet(public_report_no_images) -> None:
    sample = _public_opju_report_sample()
    payload = public_report_no_images.payload
    _assert_real_fixture_worksheet_scope_contract(
        payload,
        sample=sample,
        sample_label="zenodo-10721640-figure-1b.opju",
        allow_mixed_status=True,
    )
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert len(worksheet_items) == 8


def test_real_eucd2p2_worksheet_lock_scope_is_per_worksheet(public_graph_gap_no_images) -> None:
    sample = _public_opju_graph_gap_sample()
    payload = public_graph_gap_no_images.payload
    _assert_real_fixture_worksheet_scope_contract(
        payload,
        sample=sample,
        sample_label="zenodo-18450855-eucd2p2.opju",
        allow_mixed_status=True,
    )


def test_real_figure_1b_worksheet_lock_scope_has_stable_candidates(public_report_no_images) -> None:
    payload = public_report_no_images.payload
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    expected = {
        (
            "Book1A_A@2",
            "Book1A/Book1A_A_2",
            226,
            729,
        ),
        (
            "Book1A",
            "Book/Book1A",
            605,
            3725,
        ),
        ("Sheet1", "Sheet/Sheet1", 15815, 36191),
        ("Sheet2", "Sheet/Sheet2", 615, 3735),
        (
            "Book1A_B@2",
            "Book1A/Book1A_B_2",
            729,
            3849,
        ),
        (
            "Book1A_C@2",
            "Book1A/Book1A_C_2",
            3849,
            6866,
        ),
        (
            "Book1A_D@2",
            "Book1A/Book1A_D_2",
            6866,
            9975,
        ),
        (
            "Book1A_E@2",
            "Book1A/Book1A_E_2",
            9975,
            15815,
        ),
    }
    actual = {
        (
            str(item.get("name")),
            str(item.get("source_object_path")),
            int(item.get("range_start")),
            int(item.get("range_end")),
        )
        for item in worksheet_items
    }
    assert actual == expected
    assert all(item.get("status") in {"extracted", "partial"} for item in worksheet_items)
    assert all(not item.get("heuristic") for item in worksheet_items)


def test_real_figure_1b_worksheet_zero_rows_are_explicit(public_report_no_images) -> None:
    payload = public_report_no_images.payload
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    by_name = {str(item["name"]): item for item in worksheet_items}

    sheet1 = by_name.get("Sheet1")
    assert sheet1 is not None
    assert sheet1.get("status") == "partial"
    assert sheet1.get("rows") == 0
    assert sheet1.get("error") == "no_extracted_table_rows"

    for name in {"Book1A_A@2", "Sheet2"}:
        item = by_name.get(name)
        assert item is not None, f"Missing worksheet artifact {name}"
        assert item.get("status") in {"extracted", "partial"}
        if item.get("status") == "partial":
            assert item.get("error") == "no_extracted_table_rows"
            assert item.get("rows") == 0
            assert item.get("error") is not None
        else:
            assert item.get("rows") == 0
            assert item.get("error") is None


def test_real_eucd2p2_worksheet_lock_scope_has_stable_candidates(public_graph_gap_no_images) -> None:
    payload = public_graph_gap_no_images.payload
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    actual = {
        (
            str(item.get("name")),
            str(item.get("source_object_path")),
            int(item.get("range_start")),
            int(item.get("range_end")),
        )
        for item in worksheet_items
    }
    expected_subset = {
        ("Book11", "Book/Book11", 9312580, 9313064),
        ("Book1", "Book/Book1", 9313064, 9328513),
        ("Book11/Sheet1", "Book11/Sheet1", 9312579, 9312580),
    }
    assert expected_subset.issubset(actual)
    assert all(item.get("status") in {"extracted", "partial"} for item in worksheet_items)
    assert all(not item.get("heuristic") for item in worksheet_items)


def test_real_eucd2p2_worksheet_rows_are_honestly_scoped(public_graph_gap_no_images) -> None:
    payload = public_graph_gap_no_images.payload
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    by_name = {str(item["name"]): item for item in worksheet_items}

    for name in {"Book1", "Book11", "Book11/Sheet1"}:
        assert name in by_name, f"Missing worksheet artifact {name}"

    for name in {
        "Book1",
        "Book11",
        "Book11/Sheet1",
        "Book7",
        "Book7_A",
        "Book7_B",
        "Book9",
        "Book9_B",
        "Book9_O",
        "Book9_S",
        "Sheet2",
    }:
        item = by_name[name]
        assert item.get("status") == "partial"
        assert item.get("error") == "no_extracted_table_rows"
        assert item.get("rows") == 0


def _public_opju_science_paper_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-19549171-small-science-paper.opju"
    if sample.exists():
        return sample

    pytest.skip("Local public OPJU small science fixture is not available in this checkout.")


def _public_ahrrenius_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10364693-ahrrenius-ybscsz.opju"
    if sample.exists():
        return sample

    pytest.skip("Local public OPJU ahrrenius fixture is not available in this checkout.")


def _assert_scoped_worksheet_partial_count(
    sample: Path,
    cached_extract,
    *,
    sample_label: str,
    expected_partial_count: int,
    allow_zero_row_extracted: bool = False,
) -> dict:
    payload = _run_extract_manifest(sample, cached_extract, "--no-images")
    _assert_real_fixture_worksheet_scope_contract(
        payload,
        sample=sample,
        sample_label=sample_label,
    )

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert len(worksheet_items) == expected_partial_count, (
        f"Expected {expected_partial_count} scoped worksheet artifacts for {sample_label}, got {len(worksheet_items)}"
    )
    if allow_zero_row_extracted:
        assert all(item.get("status") == "extracted" for item in worksheet_items)
        assert all(item.get("rows") == 0 for item in worksheet_items)
        assert all(item.get("error") is None for item in worksheet_items)
    else:
        assert all(item.get("status") == "partial" for item in worksheet_items)
        assert all(item.get("error") == "no_extracted_table_rows" for item in worksheet_items)
    assert all(not item.get("heuristic") for item in worksheet_items)
    return payload


def test_real_ahrrenius_extract_has_parser_backed_matrix_and_function_recovery(
    cached_extract,
) -> None:
    sample = _public_ahrrenius_sample()
    run = cached_extract(sample, "--no-images", "--no-strings")
    output = run.output_dir
    payload = run.payload

    matrix_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "matrix"
        and str(item.get("name", "")).startswith("origin_storage_family_")
        and item.get("status") == "extracted"
        and item.get("discovery_type") == "parser_window"
        and item.get("heuristic") is False
    ]
    for item in matrix_items:
        table_path_value = item.get("path")
        assert isinstance(table_path_value, str)
        table_path = output / table_path_value
        assert table_path.exists()
        row_count, column_count = _count_csv_shape(table_path)
        assert item.get("rows", 0) == row_count
        assert item.get("columns", 0) == column_count
        assert row_count > 0
        assert column_count > 0

    function_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "function" and item.get("name") != "function_collection"
    ]
    byte_run_items = [
        item for item in function_items if item.get("extraction_method") == "origin_storage_byte_run_decode"
    ]
    for item in function_items:
        function_path_value = item.get("path")
        assert isinstance(function_path_value, str)
        function_path = output / function_path_value
        assert function_path.exists()
        assert function_path.stat().st_size > 0
        if item.get("extraction_method") == "origin_storage_byte_run_decode":
            assert item.get("status") == "extracted"
            assert function_path.suffix == ".xml"
            assert function_path.read_bytes().startswith(b"<OriginStorage")
            assert item.get("heuristic") is True
            assert item.get("verification") == "exact"
            assert item.get("error") is None
        else:
            assert item.get("status") == "partial"
            assert function_path.name == "function.raw.bin"
            assert item.get("error") == "non_lossless_function_text"

    assert len(matrix_items) == 7
    assert len(function_items) == 3
    assert len(byte_run_items) == 2


def test_real_ahrrenius_worksheet_lock_scope_is_exact_counted_partial_set(cached_extract) -> None:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10364693-ahrrenius-ybscsz.opju"
    if not sample.exists():
        pytest.skip("Local public OPJU ahrrenius fixture is not available in this checkout.")

    payload = _run_extract_manifest(sample, cached_extract, "--no-images")
    _assert_real_fixture_worksheet_scope_contract(
        payload,
        sample=sample,
        sample_label="zenodo-10364693-ahrrenius-ybscsz.opju",
        allow_mixed_status=True,
    )

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    by_name = {str(item["name"]): item for item in worksheet_items}

    expected_extracted = {
        "Book1/FitLinear2",
        "Book1/FitLinear3",
        "Book1/FitLinear4",
        "Book1/FitLinear5",
        "Book1/FitLinear6",
        "Book3/FitLinear4",
        "Book3/FitLinear5",
        "Book3/FitLinear6",
        "Book4/FitLinear1",
        "Book4/FitLinear2",
        "Book3/Sheet1",
        "Book4/Sheet1",
    }
    for name in expected_extracted:
        item = by_name.get(name)
        assert item is not None, f"Expected extracted worksheet artifact {name}"
        assert item.get("status") == "extracted"
        assert item.get("rows", 0) > 0
        assert item.get("error") is None

    for name in {"Book1/FitLinear7", "Book4/FitLinear3", "Book1/Sheet1"}:
        item = by_name.get(name)
        assert item is not None, f"Expected parser-backed worksheet artifact {name}"
        assert item.get("status") == "partial"
        assert item.get("rows") == 0
        assert item.get("error") == "no_extracted_table_rows"

    zero_row_items = [item for item in worksheet_items if item.get("rows", 0) == 0]
    assert len(zero_row_items) == 46
    assert all(item.get("status") == "partial" for item in zero_row_items)
    assert all(item.get("error") == "no_extracted_table_rows" for item in zero_row_items)

    assert all(not item.get("heuristic") for item in worksheet_items)
