"""Real-opju contract tests for real targets in repository."""

# ruff: noqa: F401

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from deopjufier.blocks import GIF_SIGS, JPEG_SIG, PNG_SIG
from deopjufier.cli import main
from deopjufier.discovery_windows import iter_object_windows
from deopjufier.inventory import discover_origin_objects, parse_opju_records
from deopjufier.opju import (
    OPJU_REGION_KIND_FOLDER_DIRECTORY,
    OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE,
    OPJU_REGION_KIND_PAGE_DIRECTORY,
)
from deopjufier.opju import regions as opju_regions
from deopjufier.session import ExtractionSession
from tests.real.fixtures.core.real_files_contract_core import (
    _assert_unsupported_collection,
    _public_opju_graph_gap_sample,
    _public_opju_jpg_attachment_sample,
    _public_opju_pdf_attachment_sample,
    _public_opju_report_sample,
    _public_opju_worksheet_gap_sample,
    _run_extract_manifest,
    _synthetic_opju_docx_attachment_fixture,
    _synthetic_opju_pdf_attachment_fixture,
)
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))


def _has_image_signature(payload: bytes) -> bool:
    return any(payload.startswith(signature) for signature in (PNG_SIG, JPEG_SIG, *GIF_SIGS))


def _assert_graph_preview_miss_has_no_embedded_image_bytes(
    sample: Path,
    payload: dict[str, Any],
    graph_name: str,
) -> None:
    misses = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "graph_preview"
        and item.get("name") == graph_name
        and item.get("status") == "skipped"
        and item.get("error") == "no_embedded_image_block"
    ]
    assert misses, f"Expected graph_preview miss for {graph_name}"

    file_bytes = sample.read_bytes()
    for item in misses:
        range_start = item.get("range_start")
        range_end = item.get("range_end")
        assert isinstance(range_start, int)
        assert isinstance(range_end, int)
        assert 0 <= range_start <= range_end <= len(file_bytes)

        window = file_bytes[range_start:range_end]
        assert not _has_image_signature(window)


@pytest.fixture(scope="module")
def public_worksheet_gap_no_images(cached_extract):
    return cached_extract(_public_opju_worksheet_gap_sample(), "--no-images")


@pytest.fixture(scope="module")
def public_report_no_images(cached_extract):
    return cached_extract(_public_opju_report_sample(), "--no-images")


@pytest.fixture(scope="module")
def public_worksheet_gap_no_images_no_strings(cached_extract):
    return cached_extract(_public_opju_worksheet_gap_sample(), "--no-images", "--no-strings")


@pytest.fixture(scope="module")
def public_worksheet_gap_fail_on_partial(cached_extract):
    return cached_extract(
        _public_opju_worksheet_gap_sample(),
        "--fail-on-partial",
        "--no-images",
        "--no-strings",
    )


@pytest.fixture(scope="module")
def public_graph_gap_default(cached_extract):
    return cached_extract(_public_opju_graph_gap_sample())


@pytest.fixture(scope="module")
def public_graph_gap_no_images(cached_extract):
    return cached_extract(_public_opju_graph_gap_sample(), "--no-images")


@pytest.fixture(scope="module")
def public_graph_gap_no_images_no_strings(cached_extract):
    return cached_extract(_public_opju_graph_gap_sample(), "--no-images", "--no-strings")


@pytest.fixture(scope="module")
def public_jpg_attachment_default(cached_extract):
    return cached_extract(_public_opju_jpg_attachment_sample())


def _copied_manifest_payload(
    target_output: Path,
    run: Any,
) -> dict[str, Any]:
    if target_output.exists():
        shutil.rmtree(target_output)
    shutil.copytree(run.output_dir, target_output)
    manifest_path = target_output / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _opjureport_txt_contents(output: Path, payload: dict[str, Any]) -> dict[str, str]:
    report_payload: dict[str, str] = {}
    for item in payload.get("items", []):
        if item.get("kind") != "origin_storage_report":
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str):
            continue
        report_path = output / path_value
        if report_path.suffix.lower() != ".txt":
            continue
        report_payload[str(item["name"])] = report_path.read_text(encoding="utf-8", errors="replace")
    return report_payload


@pytest.mark.timeout(240)
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


__all__ = [name for name in list(globals()) if not (name.startswith("__") and name.endswith("__"))]


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

    row_count, column_count = _count_csv_shape(table_path)
    assert row_count >= 0
    assert column_count >= 0
    assert item.get("rows") == row_count
    assert item.get("columns") == column_count


@pytest.mark.timeout(480)  # Multi-sample OPJU loop in one extraction test.
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


def _public_opju_science_paper_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-19549171-small-science-paper.opju"
    if sample.exists():
        return sample

    pytest.skip("Local public OPJU small science fixture is not available in this checkout.")


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


__all__ = [name for name in globals() if not name.startswith("__")]
