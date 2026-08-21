"""Regression tests for the synthetic CPYUA fixture."""

from __future__ import annotations

from pathlib import Path

from deopjufier.detect import detect_file
from deopjufier.extract import extract_books, extract_images, extract_origin_storage_reports
from deopjufier.inventory import discover_origin_objects
from tests.test_core_unit_coverage_utils import _make_manifest, _resolve_synthetic_fixture

SYNTHETIC_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua.opju")
SYNTHETIC_BINARY_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua-binary.opju")


def test_synthetic_cpyua_fixture_is_local_and_valid_shape() -> None:
    assert SYNTHETIC_FIXTURE.exists()
    data = SYNTHETIC_FIXTURE.read_bytes()

    assert data.startswith(b"CPYUA")
    assert b'<ColumnTable Name="Book3_B"' in data
    assert b"<OriginStorage" in data
    assert data.count(b"\x89PNG\r\n\x1a\n") == 2


def test_synthetic_cpyua_detect_and_parse() -> None:
    detected = detect_file(SYNTHETIC_FIXTURE)
    assert detected.detected_type == "opju"
    assert detected.reason == "extension"
    assert detected.magic_type == "opju"

    objects = discover_origin_objects(SYNTHETIC_FIXTURE)
    book_objects = [obj for obj in objects if obj.name == "Book3_B"]
    assert book_objects, "synthetic fixture should expose a worksheet object marker"
    assert book_objects[0].parser_confirmed is True
    assert book_objects[0].source_object_path == "Book/Book3_B"
    assert book_objects[0].object_kind == "worksheet"


def test_synthetic_cpyua_extracts_worksheet_from_parser_marker(tmp_path: Path) -> None:
    out_dir = tmp_path / "extract"
    manifest = _make_manifest(SYNTHETIC_FIXTURE)
    objects = [
        obj
        for obj in discover_origin_objects(SYNTHETIC_FIXTURE)
        if obj.object_kind == "worksheet" and obj.parser_confirmed
    ]
    count = extract_books(
        SYNTHETIC_FIXTURE,
        out_dir,
        manifest,
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert count >= 1
    worksheet_paths = {item.path for item in manifest.items if item.kind == "worksheet"}
    assert any((path or "").endswith("/book_Book3_B.csv") for path in worksheet_paths)
    item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book3_B")
    assert item.rows == 5
    assert item.columns == 1
    assert item.discovery_method == "parser_window"
    assert item.extraction_method == "parser_window"
    assert item.completeness == "complete"
    assert item.source_ranges == [{"start": item.range_start, "end": item.range_end}]


def test_synthetic_cpyua_binary_tables_extract_to_stable_rows(tmp_path: Path) -> None:
    out_dir = tmp_path / "extract_binary"
    manifest = _make_manifest(SYNTHETIC_BINARY_FIXTURE)
    objects = [
        obj
        for obj in discover_origin_objects(SYNTHETIC_BINARY_FIXTURE)
        if obj.object_kind == "worksheet" and obj.parser_confirmed
    ]
    count = extract_books(
        SYNTHETIC_BINARY_FIXTURE,
        out_dir,
        manifest,
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert count == 2
    august = out_dir / "books" / "Book" / "Book3_B" / "book_Book3_B.csv"
    november = out_dir / "books" / "Book" / "Book3_C" / "book_Book3_C.csv"
    assert august.exists()
    assert november.exists()
    august_text = august.read_text(encoding="utf-8")
    november_text = november.read_text(encoding="utf-8")
    assert "18.3" in august_text
    assert "13.4" in august_text
    assert "12.7" in november_text
    assert "36.8" in november_text
    assert len([line for line in august_text.splitlines() if line.strip()]) == 14
    assert len([line for line in november_text.splitlines() if line.strip()]) == 14
    august_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book3_B")
    november_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book3_C")
    assert august_item.rows == 13
    assert august_item.columns == 1
    assert november_item.rows == 13
    assert november_item.columns == 1
    assert august_item.discovery_method == "parser_window"
    assert november_item.discovery_method == "parser_window"
    assert august_item.extraction_method == "parser_window"
    assert november_item.extraction_method == "parser_window"
    assert august_item.completeness == "complete"
    assert november_item.completeness == "complete"
    assert august_item.source_ranges is not None
    assert august_item.source_ranges == [{"start": august_item.range_start, "end": august_item.range_end}]
    assert november_item.source_ranges is not None and november_item.source_ranges == [
        {"start": november_item.range_start, "end": november_item.range_end}
    ]


def test_synthetic_cpyua_extracts_origin_storage_and_both_png_variants(tmp_path: Path) -> None:
    out_dir = tmp_path / "extract"
    manifest = _make_manifest(SYNTHETIC_FIXTURE)
    count = extract_origin_storage_reports(SYNTHETIC_FIXTURE, out_dir, manifest, force=True)

    assert count == 1
    report_items = [
        item
        for item in manifest.items
        if item.kind == "origin_storage_report" and item.path is not None and item.path.endswith(".txt")
    ]
    assert len(report_items) == 1
    report_path_item = report_items[0]
    assert report_path_item.path is not None
    report_path = Path(report_path_item.path)
    assert (out_dir / report_path).exists()

    images_manifest = _make_manifest(SYNTHETIC_FIXTURE)
    images_ok = extract_images(
        SYNTHETIC_FIXTURE,
        out_dir / "images",
        images_manifest,
        force=True,
    )

    assert images_ok is False
    assert not any(item.status == "extracted" for item in images_manifest.items)
    assert any(item.status == "partial" for item in images_manifest.items)
    assert any(item.error for item in images_manifest.items if item.status == "partial")
