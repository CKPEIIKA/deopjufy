"""Targeted parity checks for audited public OPJU figure fixtures."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from deopjufier.inventory import parse_opju_records
from deopjufier.opju import OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW
from tests.real.contracts.parity._audited_family_parity_data import (
    _LOW_RECOVERY_OPJU_FIGURES,
    _LOW_RECOVERY_OPJU_NO_EMBEDDED_IMAGE_PREVIEWS,
    _LOW_RECOVERY_OPJU_NO_NOTE_OBJECTS,
    _LOW_RECOVERY_OPJU_PREVIEW_COUNTS,
    _LOW_RECOVERY_OPJU_TABLE_SCAN_COUNTS,
    _LOW_RECOVERY_OPJU_WORKSHEET_NAMES,
    _PUBLIC_OPJU_FIGURE_FIXTURES,
    _PUBLIC_OPJU_FIGURE_MIN_FUNCTION_COUNTS,
    _PUBLIC_OPJU_FIGURE_PREVIEW_NAMES,
    _PUBLIC_OPJU_FIGURE_VALUE_GOLDENS,
    REPO_ROOT,
    _assert_worksheet_rows_match_expectation,
    _extract_table_row_values,
    _has_image_signature,
)


@pytest.mark.parametrize(
    ("fixture_rel", "expected_rows"),
    [(fixture_rel, expected_rows) for fixture_rel, expected_rows in _PUBLIC_OPJU_FIGURE_FIXTURES.items()],
)
def test_real_audited_public_opju_figure_worksheet_rows_are_explicit(
    fixture_rel: str,
    expected_rows: dict[str, int],
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    worksheet_items = {
        str(item.get("name")): item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    }
    assert worksheet_items, f"Expected worksheet artifacts for {fixture_rel}"
    assert all(item.get("heuristic") is False for item in worksheet_items.values())
    assert all(item.get("status") in {"extracted", "partial"} for item in worksheet_items.values())

    _assert_worksheet_rows_match_expectation(sample, worksheet_items, expected_rows=expected_rows)

    if expected_rows:
        zero_rows = {name: item for name, item in worksheet_items.items() if name not in expected_rows}
        assert all(
            item.get("status") == "partial" and item.get("error") == "no_extracted_table_rows" and item.get("rows") == 0
            for item in zero_rows.values()
        )
    else:
        assert all(
            item.get("status") == "partial" and item.get("error") == "no_extracted_table_rows" and item.get("rows") == 0
            for item in worksheet_items.values()
        )


@pytest.mark.parametrize("fixture_rel", _LOW_RECOVERY_OPJU_FIGURES)
def test_real_audited_public_opju_figure_low_recoverability_profiles_are_shape_only(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload
    assert payload.get("support_class") == "partial"
    parser_warning_codes = {
        entry.get("code") for entry in payload.get("parser_warnings", ()) if isinstance(entry, dict)
    }
    assert parser_warning_codes.issubset({"no-raw-blocks", "no-text-regions"})

    worksheet_items = {
        str(item.get("name")): item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    }
    assert worksheet_items
    assert all(
        item.get("status") == "partial"
        and item.get("error") == "no_extracted_table_rows"
        and item.get("rows") == 0
        and item.get("heuristic") is False
        for item in worksheet_items.values()
    )

    table_scan_items = [item for item in payload.get("items", []) if item.get("kind") == "table_scan"]
    assert table_scan_items
    assert all(
        item.get("source_object_path") == "numeric_tables"
        and item.get("heuristic") is True
        and item.get("status") in {"partial", "extracted"}
        for item in table_scan_items
    )
    assert len(table_scan_items) == _LOW_RECOVERY_OPJU_TABLE_SCAN_COUNTS[fixture_rel]

    for item in table_scan_items:
        table_path = item.get("path")
        if table_path is None:
            continue
        extracted_path = run.output_dir / str(table_path)
        assert extracted_path.exists()
        assert extracted_path.suffix == ".csv"


@pytest.mark.parametrize("fixture_rel", _LOW_RECOVERY_OPJU_FIGURES)
def test_real_audited_public_opju_figure_low_recoverability_function_payloads_are_parser_backed(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    function_items = [
        item
        for item in payload.get("items", ())
        if item.get("kind") == "function" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert function_items, f"Expected function artifacts for {fixture_rel}"

    for item in function_items:
        assert item.get("status") == "extracted"
        assert item.get("heuristic") is False
        assert item.get("error") is None
        rows = item.get("rows")
        assert isinstance(rows, int)
        assert rows >= 1
        assert item.get("discovery_type") == "parser_window"
        assert (confidence := item.get("confidence")) is not None
        assert confidence >= 0.8
        name = item.get("name")
        path_value = item.get("path")
        source_object_path = item.get("source_object_path")

        assert isinstance(name, str) and name.startswith("origin_storage_function_")
        assert isinstance(path_value, str)
        assert isinstance(source_object_path, str)
        assert source_object_path.startswith("origin_storage/origin_storage_function_")
        function_path = run.output_dir / Path(path_value)
        assert function_path.exists()
        expected_path = Path("functions") / source_object_path / "function.txt"
        assert function_path.relative_to(run.output_dir).as_posix() == expected_path.as_posix()
        function_payload = function_path.read_text(encoding="utf-8")
        assert function_payload.startswith("<OriginStorage")


@pytest.mark.parametrize(
    ("fixture_rel", "expected_min_functions"),
    [(fixture_rel, expected) for fixture_rel, expected in _PUBLIC_OPJU_FIGURE_MIN_FUNCTION_COUNTS.items()],
)
def test_real_audited_public_opju_figure_functions_are_parser_backed(
    fixture_rel: str,
    expected_min_functions: int,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    function_items = [
        item
        for item in payload.get("items", ())
        if item.get("kind") == "function" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert len(function_items) >= expected_min_functions

    for item in function_items:
        name = item.get("name")
        path_value = item.get("path")
        source_object_path = item.get("source_object_path")

        assert isinstance(name, str) and name.startswith("origin_storage_function_")
        assert isinstance(path_value, str)
        assert isinstance(source_object_path, str)
        assert source_object_path.startswith("origin_storage/origin_storage_function_")

        function_path = run.output_dir / Path(path_value)
        assert function_path.exists()
        if item.get("extraction_method") == "origin_storage_byte_run_decode":
            assert item.get("status") == "extracted"
            assert item.get("error") is None
            assert item.get("heuristic") is True
            assert item.get("discovery_type") == "origin_storage_byte_run_phase_recovery"
            assert item.get("verification") == "exact"
            assert item.get("payload_family") == "origin_storage_xml"
            assert function_path.suffix == ".xml"
            assert function_path.read_bytes().startswith(b"<OriginStorage")
        elif item.get("status") == "partial":
            assert item.get("heuristic") is False
            assert item.get("discovery_type") == "parser_window"
            assert item.get("error") == "non_lossless_function_text"
            assert (item.get("replacement_character_count", 0) + item.get("control_character_count", 0)) > 0
            expected_path = Path("functions") / source_object_path / "function.raw.bin"
            assert function_path.relative_to(run.output_dir).as_posix() == expected_path.as_posix()
            assert function_path.read_bytes().startswith(b"<OriginStorage")
        else:
            assert item.get("heuristic") is False
            assert item.get("discovery_type") == "parser_window"
            assert item.get("status") == "extracted"
            assert item.get("error") is None
            expected_path = Path("functions") / source_object_path / "function.txt"
            assert function_path.relative_to(run.output_dir).as_posix() == expected_path.as_posix()
            function_payload = function_path.read_text(encoding="utf-8", errors="strict")
            assert function_payload.startswith("<OriginStorage")
            assert not any(
                char not in "\n\r\t" and (ord(char) < 0x20 or ord(char) == 0x7F) for char in function_payload
            )


@pytest.mark.parametrize(
    ("fixture_rel", "expected_names"),
    [(fixture_rel, expected_names) for fixture_rel, expected_names in _LOW_RECOVERY_OPJU_WORKSHEET_NAMES.items()],
)
def test_real_audited_public_opju_figure_low_recoverability_worksheet_name_set_is_stable(
    fixture_rel: str,
    expected_names: tuple[str, ...],
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}

    worksheet_names = sorted(
        {
            str(item.get("name"))
            for item in run.payload.get("items", ())
            if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
        }
    )
    assert worksheet_names == sorted(expected_names)
    assert len(worksheet_names) == len(expected_names)


@pytest.mark.parametrize(
    ("fixture_rel", "expected_graph", "expected_graph_preview", "expected_parser_backed"),
    [
        (fixture_rel, expected_graph, expected_graph_preview, expected_parser_backed)
        for fixture_rel, (expected_graph, expected_graph_preview, expected_parser_backed) in (
            _LOW_RECOVERY_OPJU_PREVIEW_COUNTS.items()
        )
    ],
)
def test_real_audited_public_opju_figure_low_recoverability_preview_profile_is_stable(
    fixture_rel: str,
    expected_graph: int,
    expected_graph_preview: int,
    expected_parser_backed: int,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    counts = Counter(
        item.get("kind")
        for item in payload.get("items", [])
        if isinstance(item, dict) and item.get("kind") in {"graph", "graph_preview", "parser_backed_graph_preview"}
    )
    assert counts["graph"] == expected_graph
    assert counts["graph_preview"] == expected_graph_preview
    assert counts["parser_backed_graph_preview"] == expected_parser_backed

    table_scan_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "table_scan" and item.get("status") == "partial"
    ]
    assert table_scan_items


@pytest.mark.parametrize("fixture_rel", _LOW_RECOVERY_OPJU_FIGURES)
def test_real_audited_public_opju_figure_low_recoverability_graph_gaps_are_explicit(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    expected_gap_names = _LOW_RECOVERY_OPJU_NO_EMBEDDED_IMAGE_PREVIEWS[fixture_rel]
    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    no_embedded_preview_items = [
        item
        for item in payload.get("items", ())
        if item.get("kind") == "graph_preview"
        and item.get("status") == "skipped"
        and item.get("error") == "no_embedded_image_block"
    ]
    actual_gap_names = {str(item.get("name")) for item in no_embedded_preview_items}
    assert actual_gap_names == expected_gap_names

    for name in expected_gap_names:
        gap_graph_items = [
            item
            for item in payload.get("items", ())
            if item.get("kind") == "graph"
            and str(item.get("name")) == name
            and item.get("status") == "partial"
            and item.get("error") in {"graph_definition_partial", "graph_definition_unverified"}
        ]
        assert gap_graph_items, f"Expected graph preview gap evidence for {name} in {fixture_rel}"
        for item in gap_graph_items:
            item_start = item.get("range_start")
            item_end = item.get("range_end")
            assert item.get("path")
            assert isinstance(item_start, int) and isinstance(item_end, int)
            assert 0 <= item_start <= item_end
            source_object_path = item.get("source_object_path")
            assert isinstance(source_object_path, str) and source_object_path

    graph_gap_items = [
        item
        for item in payload.get("items", ())
        if item.get("kind") == "graph"
        and item.get("status") == "partial"
        and item.get("error") in {"graph_definition_partial", "graph_definition_unverified"}
    ]

    for item in no_embedded_preview_items:
        start = item.get("range_start")
        end = item.get("range_end")
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str) and source_object_path
        assert item.get("path") is None
        assert item.get("status") == "skipped"
        assert isinstance(start, int) and isinstance(end, int)
        assert 0 <= start <= end
        matching_graph_items = [
            gap_graph
            for gap_graph in graph_gap_items
            if str(gap_graph.get("name")) == str(item.get("name"))
            and gap_graph.get("source_object_path") == source_object_path
        ]
        assert matching_graph_items, (
            f"Expected graph miss item for preview miss {item.get('name')}::{source_object_path} in {fixture_rel}"
        )
        for gap_graph in matching_graph_items:
            graph_start = gap_graph.get("range_start")
            graph_end = gap_graph.get("range_end")
            assert isinstance(graph_start, int) and isinstance(graph_end, int)
            assert 0 <= graph_start <= graph_end
            assert not (graph_end < start or graph_start > end)


@pytest.mark.parametrize("fixture_rel", _LOW_RECOVERY_OPJU_FIGURES)
def test_real_audited_public_opju_figure_low_recoverability_note_gaps_are_explicit(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    expected_note_gap = _LOW_RECOVERY_OPJU_NO_NOTE_OBJECTS[fixture_rel]
    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    note_collection = [
        item
        for item in payload.get("items", ())
        if item.get("kind") == "note" and item.get("name") == "note_collection"
    ]
    if expected_note_gap:
        assert note_collection, f"Expected note collection gap in {fixture_rel}"
        assert all(
            item.get("status") == "unsupported" and item.get("error") == "no_note_objects" for item in note_collection
        )
        assert all(item.get("source_object_path") == "previews/origin_storage_preview_000" for item in note_collection)
        assert all(
            isinstance(item.get("range_start"), int) and isinstance(item.get("range_end"), int)
            for item in note_collection
        )
        assert all(isinstance(item.get("path"), str) for item in note_collection)
    else:
        assert not note_collection, f"Expected no note collection gap in {fixture_rel}"


@pytest.mark.parametrize("fixture_rel", tuple(_PUBLIC_OPJU_FIGURE_FIXTURES))
def test_real_audited_public_opju_figure_previews_are_parser_backed(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample)
    assert run.exit_code in {0, 4}
    payload = run.payload
    output = run.output_dir

    preview_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") in {"graph_preview", "parser_backed_graph_preview"}
        and not str(item.get("name", "")).endswith("_collection")
    ]
    assert preview_items, f"Expected preview artifacts for {fixture_rel}"

    parser_backed_previews = [item for item in preview_items if item.get("kind") == "parser_backed_graph_preview"]
    assert parser_backed_previews, f"Expected parser-backed preview for {fixture_rel}"

    preview_sources = {
        str(item.get("source_object_path"))
        for item in parser_backed_previews
        if item.get("status") == "extracted" and isinstance(item.get("source_object_path"), str)
    }
    assert preview_sources, f"Expected parser-backed preview source for {fixture_rel}"
    assert all("origin_storage_preview_000" in source for source in preview_sources)
    for source in preview_sources:
        assert source.startswith("previews/")

    for item in parser_backed_previews:
        assert item.get("status") == "extracted"
        assert item.get("error") is None
        assert item.get("heuristic") is False
        assert item.get("discovery_type") == "parser_window"
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str)
        assert source_object_path.startswith("previews/")
        assert "origin_storage_preview_000" in source_object_path

        assert item.get("path"), f"Expected preview path for {fixture_rel}"
        path_value = str(item["path"])
        preview_path = output / path_value
        assert preview_path.exists()

        parsed_path = preview_path.relative_to(output).as_posix()
        expected_prefix = Path("graphs") / source_object_path
        assert parsed_path.startswith(expected_prefix.as_posix() + "/")
        assert Path(parsed_path).name.startswith("graph")
        assert preview_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg"}
        preview_data = preview_path.read_bytes()
        if preview_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
            assert _has_image_signature(preview_data)
        elif preview_path.suffix.lower() == ".svg":
            assert preview_data.startswith(b"<") or _has_image_signature(preview_data)

    parsed_records = parse_opju_records(sample.read_bytes(), max_tables=200)
    parser_preview_sources = {
        str(region.source_object_path)
        for region in parsed_records.regions
        if region.kind == OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW and region.source_object_path
    }
    assert parser_preview_sources, f"No parser preview regions found for {fixture_rel}"
    for source in preview_sources:
        assert source in parser_preview_sources


@pytest.mark.parametrize(
    ("fixture_rel", "expected_rows"),
    [(fixture_rel, expected_rows) for fixture_rel, expected_rows in _PUBLIC_OPJU_FIGURE_VALUE_GOLDENS.items()],
)
def test_real_audited_public_opju_figure_value_golden_rows_are_stable(
    fixture_rel: str,
    expected_rows: dict[str, dict[int, list[str]]],
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    output = run.output_dir
    manifest_items = run.payload.get("items", [])

    worksheet_items: dict[str, dict[str, Any]] = {
        str(item.get("name")): item
        for item in manifest_items
        if isinstance(item, dict) and item.get("kind") == "worksheet"
    }

    for worksheet_name, rows in expected_rows.items():
        item = worksheet_items.get(worksheet_name)
        assert isinstance(item, dict), f"Missing worksheet item {worksheet_name} in {fixture_rel}"
        assert item.get("status") == "extracted"
        path_value = item.get("path")
        assert isinstance(path_value, str), f"Expected path for worksheet {worksheet_name} in {fixture_rel}"
        table_path = output / path_value
        assert table_path.exists()
        for row_in_table, expected_values in rows.items():
            actual_values = _extract_table_row_values(table_path, row_in_table=row_in_table)
            assert actual_values == expected_values, (
                f"Worksheet row mismatch for {fixture_rel}::{worksheet_name}@{row_in_table}"
            )


@pytest.mark.parametrize("fixture_rel", tuple(_PUBLIC_OPJU_FIGURE_FIXTURES))
def test_real_audited_public_opju_figure_parser_backed_preview_identity_is_stable(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample)
    assert run.exit_code in {0, 4}
    payload = run.payload

    parser_backed_previews = [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict)
        and item.get("kind") == "parser_backed_graph_preview"
        and item.get("status") == "extracted"
    ]
    assert parser_backed_previews, f"Expected parser-backed preview for {fixture_rel}"
    names = sorted({str(item.get("name")) for item in parser_backed_previews})
    assert names == ["origin_storage_preview_000"]


@pytest.mark.parametrize(
    ("fixture_rel", "expected_preview_names"),
    [
        (fixture_rel, expected_preview_names)
        for fixture_rel, expected_preview_names in _PUBLIC_OPJU_FIGURE_PREVIEW_NAMES.items()
    ],
)
def test_real_audited_public_opju_figure_graph_preview_names_are_stable(
    fixture_rel: str,
    expected_preview_names: list[str],
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    preview_names = sorted(
        {
            str(item.get("name"))
            for item in payload.get("items", [])
            if isinstance(item, dict)
            and item.get("kind") in {"graph_preview", "parser_backed_graph_preview"}
            and not str(item.get("name", "")).endswith("_collection")
            and item.get("status") in {"extracted", "skipped"}
        }
    )
    assert preview_names == sorted(expected_preview_names)


@pytest.mark.parametrize("fixture_rel", tuple(_PUBLIC_OPJU_FIGURE_FIXTURES))
def test_real_audited_public_opju_figure_graph_paths_are_deterministic(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample)
    assert run.exit_code in {0, 4}
    payload = run.payload

    output = run.output_dir
    graph_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict)
        and item.get("kind") == "graph"
        and not str(item.get("name", "")).endswith("_collection")
    ]
    assert graph_items, f"Expected non-collection graph artifacts for {fixture_rel}"

    for item in graph_items:
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str) and source_object_path
        path_value = item.get("path")

        if path_value is None:
            assert item.get("status") in {"unsupported", "partial", "skipped", "failed"}
            continue

        path = output / str(path_value)
        assert path.is_relative_to(output)
        rel_path = path.relative_to(output).as_posix()
        assert rel_path.startswith(f"graphs/{source_object_path}/")
        assert Path(rel_path).name == "graph.metadata.json"
        assert path.exists()


@pytest.mark.parametrize("fixture_rel", tuple(_PUBLIC_OPJU_FIGURE_FIXTURES))
def test_real_audited_public_opju_figure_data_object_paths_are_deterministic(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload
    output = run.output_dir

    kind_to_root = {
        "worksheet": Path("books"),
        "matrix": Path("matrices"),
        "note": Path("notes"),
    }
    for item in payload.get("items", ()):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in kind_to_root:
            continue

        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str) and source_object_path
        if str(item.get("name", "")).endswith("_collection"):
            continue

        path_value = item.get("path")
        if path_value is None:
            assert item.get("status") in {"unsupported", "partial", "skipped", "failed"}
            continue

        path = output / str(path_value)
        assert path.is_relative_to(output)
        rel_path = path.relative_to(output).as_posix()
        assert rel_path.startswith(f"{kind_to_root[kind]}/{source_object_path}/")
        filename = Path(rel_path).name
        if kind == "worksheet":
            assert filename == "book.csv" or (filename.startswith("book_") and filename.endswith(".csv"))
        elif kind == "matrix":
            assert filename == "matrix.csv" or (filename.startswith("matrix_") and filename.endswith(".csv"))
        else:
            assert filename == "note.txt"
        if item.get("status") == "extracted":
            assert path.exists()


@pytest.mark.parametrize("fixture_rel", tuple(_PUBLIC_OPJU_FIGURE_FIXTURES))
def test_real_audited_public_opju_figure_origin_storage_report_paths_are_deterministic(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload
    output = run.output_dir

    report_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "origin_storage_report"
    ]
    report_json_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "origin_storage_report_json"
    ]
    summary_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "origin_storage_report_summary"
    ]
    if not (report_items or report_json_items or summary_items):
        return

    for item in report_items:
        name = item.get("name")
        path_value = item.get("path")
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str) and source_object_path

        assert isinstance(name, str)
        if name in {"origin_storage_reports", "origin_storage_reports.json"}:
            if path_value is None:
                assert item.get("status") in {"unsupported", "partial", "skipped", "failed"}
                continue
            assert isinstance(path_value, str)
            assert path_value in {
                "origin_storage_reports",
                "origin_storage_reports/origin_storage_reports.json",
            }
            assert source_object_path == "origin_storage_reports"
            report_path = output / str(path_value)
            assert report_path.is_relative_to(output)
            rel_report_path = report_path.relative_to(output).as_posix()
            assert rel_report_path in {
                "origin_storage_reports",
                "origin_storage_reports/origin_storage_reports.json",
            }
            if item.get("status") == "extracted":
                assert report_path.exists()
            continue

        if path_value is None:
            assert item.get("status") in {"unsupported", "partial", "skipped", "failed"}
            continue
        assert isinstance(path_value, str)
        report_path = output / str(path_value)
        assert report_path.is_relative_to(output)
        rel_report_path = report_path.relative_to(output).as_posix()
        assert rel_report_path.startswith("origin_storage_reports/")
        assert source_object_path.startswith("origin_storage_reports/")
        assert rel_report_path.endswith(".txt")
        assert report_path.name.endswith(".txt")
        if item.get("status") == "extracted":
            assert report_path.exists()

    for item in report_json_items:
        source_object_path = item.get("source_object_path")
        path_value = item.get("path")
        assert isinstance(source_object_path, str) and source_object_path
        assert source_object_path.startswith("origin_storage_reports/")
        assert path_value is not None
        assert isinstance(path_value, str)
        report_path = output / str(path_value)
        assert report_path.is_relative_to(output)
        rel_report_path = report_path.relative_to(output).as_posix()
        assert rel_report_path.startswith("origin_storage_reports/")
        assert rel_report_path.endswith(".json")
        if item.get("status") == "extracted":
            assert report_path.exists()

    for item in summary_items:
        path_value = item.get("path")
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str)
        assert source_object_path == "origin_storage_reports"
        assert path_value is not None
        assert isinstance(path_value, str)
        summary_path = output / str(path_value)
        assert summary_path.is_relative_to(output)
        assert (
            summary_path.relative_to(output).as_posix() == "origin_storage_reports/origin_storage_reports_summary.txt"
        )
        if item.get("status") == "extracted":
            assert summary_path.exists()
