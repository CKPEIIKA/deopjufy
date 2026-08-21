"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import cast

import pytest

from deopjufier.extract import (
    extract_books,
    extract_excel,
    extract_origin_storage_reports,
)
from deopjufier.extract.object_tables_extract import _filter_meaningful_recovered_rows
from deopjufier.extract.object_tables_extract_filters import _is_parser_recovered_row_meaningful
from deopjufier.extract.object_tables_extract_tables._core import _extract_tabular_objects
from deopjufier.inventory import (
    OpjObjectBoundary,
    OriginObject,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
)
from deopjufier.opju.recovery_helpers_tokens import _infer_parser_backed_worksheet_names
from tests.core.basics.opj_parse._test_core_unit_coverage_basics_opj_parse import (
    _build_opj_global_header,
    _build_opj_walk_window,
    _u32,
)
from tests.test_core_unit_coverage_utils import _make_manifest

_VALID_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    + b"\x90wS\xde"
    + b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x17"
    + b"8U"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_VALID_JPEG_1X1 = (
    b"\xff\xd8"
    + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    + b"\x01\x02"
    + b"\xff\xd9"
)


def _discover_objects(path: Path) -> list[OriginObject]:
    return discover_origin_objects(path)


def _opj_matrix_data_section_payload(
    name: str,
    values: list[float],
    *,
    value_size: int = 8,
    data_type: int = 0,
) -> bytes:
    header = bytearray(123)
    name_bytes = f"{name}\x00".encode("ascii")
    header[0x58 : 0x58 + len(name_bytes)] = name_bytes[:25]
    header[0x16:0x18] = data_type.to_bytes(2, "little")
    header[0x18] = 0
    header[0x19:0x1D] = len(values).to_bytes(4, "little")
    header[0x1D:0x21] = (1).to_bytes(4, "little")
    header[0x21:0x25] = len(values).to_bytes(4, "little")
    header[0x3D] = value_size
    header[0x3F] = 0
    header[0x71:0x73] = (0).to_bytes(2, "little")

    payload = b"".join(struct.pack("<d", float(value)) for value in values)
    return (
        struct.pack("<I", len(header))
        + b"\n"
        + bytes(header)
        + b"\n"
        + struct.pack("<I", len(payload))
        + b"\n"
        + payload
        + b"\n"
    )


def _build_opj_matrix_payload_file(
    sections: list[tuple[str, list[float]]],
) -> bytes:
    payload = b"CPYA 6.0 552#\n"
    for index, (name, values) in enumerate(sections):
        payload += _opj_matrix_data_section_payload(name, values)
        if index + 1 < len(sections):
            payload += b"\x00\x00\x00\x00\n"
    return payload


def test_extract_books_uses_parser_backed_opju_worksheet_names(tmp_path: Path) -> None:
    sample = tmp_path / "books_parser_names.opju"
    sample.write_bytes(
        b'CPYUA 4.3318 0\x00<ColumnTable Name="Book A">1</ColumnTable><ColumnTable Name="Book A">2</ColumnTable>'
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [obj for obj in _discover_objects(sample) if obj.object_kind == "worksheet" and obj.parser_confirmed]
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert count == 2
    worksheet_paths = {item.path for item in manifest.items if item.kind == "worksheet" and item.path is not None}
    assert (out_dir / "books" / "Book" / "Book_A" / "book_Book_A.csv").exists()
    assert (out_dir / "books" / "Book" / "Book_A__2" / "book_Book_A__2.csv").exists()
    assert worksheet_paths == {
        "books/Book/Book_A/book_Book_A.csv",
        "books/Book/Book_A__2/book_Book_A__2.csv",
    }


def test_extract_origin_storage_reports_uses_parser_backed_names(tmp_path: Path) -> None:
    sample = tmp_path / "reports.opju"
    sample.write_bytes(
        b"CPYUA 4.3318 0\x00"
        b'<OriginStorage Label="Report / One"><Notes>one</Notes></OriginStorage>'
        b'<OriginStorage Label="Report / One"><Notes>two</Notes></OriginStorage>'
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_origin_storage_reports(
        sample,
        out_dir,
        manifest,
        force=True,
    )

    assert count == 2
    report_items = [
        item
        for item in manifest.items
        if item.kind == "origin_storage_report" and item.path is not None and item.path.endswith(".txt")
    ]
    assert [item.name for item in report_items] == [
        "Report___One",
        "Report___One__2",
    ]
    report_path_item = report_items[0]
    assert report_path_item.path is not None
    report_path = Path(report_path_item.path)
    assert (out_dir / "origin_storage_reports" / "Report___One.txt").exists()
    assert (out_dir / "origin_storage_reports" / "Report___One__2.txt").exists()
    assert (out_dir / report_path).exists()
    assert (out_dir / "origin_storage_reports" / "Report___One.json").exists()
    assert (out_dir / "origin_storage_reports" / "Report___One__2.json").exists()
    json_items = [
        item
        for item in manifest.items
        if item.kind == "origin_storage_report_json" and item.path is not None and item.path.endswith(".json")
    ]
    assert len(json_items) == 2


def test_extract_origin_storage_reports_skips_locked_report_artifacts_without_force(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "reports_locked.opju"
    sample.write_bytes(b'CPYUA 4.3318 0\x00<OriginStorage Label="Report / One"><Notes>one</Notes></OriginStorage>')

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    report_root = out_dir / "origin_storage_reports"
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "origin_storage_reports.json").write_text("{}\n", encoding="utf-8")
    (report_root / "origin_storage_reports_summary.txt").write_text("old\n", encoding="utf-8")
    (report_root / "Report___One.txt").write_text("old\n", encoding="utf-8")

    count = extract_origin_storage_reports(
        sample,
        out_dir,
        manifest,
        force=False,
    )

    assert count == 0
    collection_item = next(
        item
        for item in manifest.items
        if item.kind == "origin_storage_report" and item.name == "origin_storage_reports"
    )
    assert collection_item.status == "skipped"
    assert collection_item.error == "target_exists"
    assert collection_item.path == "origin_storage_reports/origin_storage_reports.json"
    report_item = next(
        item for item in manifest.items if item.kind == "origin_storage_report" and item.name == "Report___One"
    )
    assert report_item.status == "skipped"
    assert report_item.path == "origin_storage_reports/Report___One.txt"
    summary_item = next(item for item in manifest.items if item.kind == "origin_storage_report_summary")
    assert summary_item.status == "skipped"


def test_extract_books_creates_books_directory_and_rows(tmp_path: Path) -> None:
    sample = tmp_path / "books.opju"
    sample.write_bytes(
        b"CPYUA 4.3318 113\n"
        b'<ColumnTable Name="Book3_B" Label="August">'
        b"18.3\n13.3\n16.5\n12.6\n9.5\n13.6\n8.1\n8.9\n10.0\n8.3\n7.9\n8.1\n13.4\n"
        b"</ColumnTable>"
        b'<ColumnTable Name="Book3_C" Label="November">'
        b"12.7\n11.1\n15.3\n12.7\n10.5\n15.6\n11.2\n14.2\n16.3\n15.5\n19.9\n20.4\n36.8\n"
        b"</ColumnTable>"
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=2,
        objects=_discover_objects(sample),
    )

    assert count == 2
    assert manifest.items
    assert manifest.items[0].kind == "worksheet"
    assert {item.name for item in manifest.items} == {"Book3_B", "Book3_C"}
    assert manifest.items[0].status == "extracted"
    august = out_dir / "books" / "Book" / "Book3_B" / "book_Book3_B.csv"
    november = out_dir / "books" / "Book" / "Book3_C" / "book_Book3_C.csv"
    assert august.exists()
    assert november.exists()
    assert "18.3" in august.read_text(encoding="utf-8")
    assert "36.8" in november.read_text(encoding="utf-8")
    assert manifest.items[0].heuristic is False


def test_extract_books_emits_empty_sheet_with_header_when_no_rows(tmp_path: Path) -> None:
    sample = tmp_path / "books_empty.opju"
    sample.write_bytes(b"Book3_Empty")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=_discover_objects(sample),
    )

    assert count == 0
    assert len(manifest.items) == 1
    assert manifest.items[0].status == "partial"
    assert not (out_dir / "books" / "Book" / "Book3_Empty" / "book_Book3_Empty.csv").exists()


def test_extract_books_does_not_numeric_scan_for_parser_boundary_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"Book1_A\n1 2\n3 4\n"
    sample = tmp_path / "boundary_book.opj"
    sample.write_bytes(payload)

    boundary = OpjObjectBoundary(
        kind="worksheet",
        name="Book1_A",
        source_object_path="Book/Book1_A",
        start_offset=0,
        end_offset=len(payload),
        length=len(payload),
        confidence=0.9,
        parser_rule="test",
    )
    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        lambda *_args, **_kwargs: [boundary],
    )

    def fail_scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        raise AssertionError("numeric scan should not run for parser-backed worksheet windows")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.scan_numeric_tables_from_bytes",
        fail_scan,
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=[
            OriginObject(
                offset=0,
                name="Book1_A",
                length=sample.stat().st_size,
                object_kind="worksheet",
                source_object_path="Book/Book1_A",
            )
        ],
        allow_parser_recovery=True,
    )

    assert count == 0
    assert manifest.items
    item = manifest.items[0]
    assert item.status == "partial"
    assert item.heuristic is False
    assert item.discovery_type == "parser_window"
    assert item.path is None
    assert not out_dir.joinpath("books", "Book1", "Book1", "book_Book1.csv").exists()


def test_extract_excel_marks_parser_backed_excel_objects(tmp_path: Path) -> None:
    sample = tmp_path / "excel_parser_window.opj"
    sample.write_bytes(
        b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + _build_opj_walk_window("Book1.xlsx")
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=discover_origin_objects(sample, collect_heuristics=False),
    )

    assert count == 0
    assert manifest.items
    item = manifest.items[0]
    assert item.kind == "excel"
    assert item.name == "Book1.xlsx"
    assert item.status == "partial"
    assert item.discovery_type == "parser_window"
    assert item.heuristic is False
    assert item.path is None
    assert not (out_dir / "excel" / "Book" / "Book1.xlsx" / "excel_Book1.xlsx.csv").exists()


def test_extract_excel_from_parser_backed_opju_attachment_hint(tmp_path: Path) -> None:
    payload = b"<OriginStorage><Path>[H:\\Temp\\Project\\__E_Book1.xlsx]</Path></OriginStorage>"
    sample = tmp_path / "opju_attachment.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00" + payload)
    sample_bytes = sample.read_bytes()

    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(b"CPYUA 4.3318 0\x00"),
            name="__E_Book1.xlsx",
            length=len(payload),
            object_kind="excel",
            source_object_path="Excel/__E_Book1.xlsx",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.89,
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=cast(list[OriginObject], objects),
        file_data=sample_bytes,
    )

    assert count == 1
    item = manifest.items[0]
    assert item.kind == "origin_storage_region"
    assert item.name == "__E_Book1.xlsx"
    assert item.discovery_type == "parser_window"
    assert item.heuristic is False
    assert item.status == "partial"
    assert item.object_kind == "origin_storage_attachment"
    assert item.error == "advertised_spreadsheet_signature_mismatch"
    assert item.path == "attachments/Excel/__E_Book1.xlsx/E_Book1.originstorage.bin"
    assert (out_dir / item.path).read_bytes() == payload
    assert not (out_dir / "excel" / "Excel" / "__E_Book1.xlsx" / "excel_E_Book1.xlsx.csv").exists()


def test_extract_excel_recovers_external_workbook_reference_without_claiming_embedded_payload(
    tmp_path: Path,
) -> None:
    reference = "[R1C1:R2C2] [C:\\Fixtures\\[measurements.xlsx]Sheet1 [Excel] 1 2"
    encoded_reference = reference.encode()
    payload = b"\x81\x00\n" + encoded_reference + b"\x00\x92"
    header = b"CPYUA 4.3318 0\x00"
    sample = tmp_path / "opju_external_workbook.opju"
    sample.write_bytes(header + payload)
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(header),
            name="__E_measurements.xlsx",
            length=len(payload),
            object_kind="excel",
            source_object_path="Excel/__E_measurements.xlsx",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.89,
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=cast(list[OriginObject], objects),
        file_data=sample.read_bytes(),
    )

    assert count == 2
    link = next(item for item in manifest.items if item.kind == "external_workbook_link")
    assert link.status == "extracted"
    assert link.verification == "exact"
    assert link.completeness == "complete"
    assert link.embedded_payload is False
    assert (link.range_start, link.range_end) == (
        len(header) + 3,
        len(header) + 3 + len(encoded_reference),
    )
    link_payload = json.loads((out_dir / Path(link.path or "")).read_text(encoding="utf-8"))
    assert link_payload == {
        "advertised_filename": "__E_measurements.xlsx",
        "embedded_payload": False,
        "reference": reference,
        "source_range": {"end": link.range_end, "start": link.range_start},
        "workbook_path": "[C:\\Fixtures\\[measurements.xlsx]",
    }
    source = next(item for item in manifest.items if item.kind == "origin_storage_region")
    assert source.status == "partial"
    assert source.error == "external_workbook_reference_source_preserved"
    assert source.embedded_payload is False
    assert (out_dir / Path(source.path or "")).read_bytes() == payload


def test_verified_empty_descriptor_table_is_a_complete_extracted_object(tmp_path: Path) -> None:
    header = b"CPYUA 4.3318 0\x00"
    sample = tmp_path / "empty_descriptor.opju"
    sample.write_bytes(header + b"descriptor")
    obj = ParserBackedDiscoveryRecord(
        offset=len(header),
        name="BookEmpty",
        length=len(b"descriptor"),
        object_kind="worksheet",
        source_object_path="BookEmpty",
        parser_rule="opju_column_descriptor_table",
        parser_confidence=0.99,
    )
    manifest = _make_manifest(sample)

    count = _extract_tabular_objects(
        sample,
        tmp_path / "out",
        manifest,
        object_kind="worksheet",
        manifest_item_kind="worksheet",
        collection_path="books",
        collection_name="book",
        missing_error="no_worksheet_objects",
        filename_base="book",
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], [obj]),
        allow_parser_recovery=True,
        allow_heuristic_scan=False,
        recovered_rows_by_name={"BookEmpty": []},
        recovered_dimensions_by_name={"BookEmpty": (0, 0)},
        verified_parser_table_names={"BookEmpty"},
        recovered_source_ranges_by_name={
            "BookEmpty": [{"start": len(header), "end": len(header) + len(b"descriptor")}]
        },
        emit_unsupported_collection=False,
    )

    assert count == 1
    item = next(item for item in manifest.items if item.kind == "worksheet")
    assert item.status == "extracted"
    assert item.verification == "exact"
    assert item.completeness == "complete"
    assert item.content_class == "empty"
    assert (item.rows, item.columns, item.path, item.error) == (0, 0, None, None)


def test_extract_non_xlsx_parser_backed_opju_attachment_hint(tmp_path: Path) -> None:
    payload = b"<OriginStorage><Path>[D:\\Temp\\Notes\\summary.pdf]</Path></OriginStorage>"
    sample = tmp_path / "opju_non_xlsx_attachment.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00" + payload)
    sample_bytes = sample.read_bytes()

    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(b"CPYUA 4.3318 0\x00"),
            name="summary.pdf",
            length=len(payload),
            object_kind="excel",
            source_object_path="Excel/summary.pdf",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.89,
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=cast(list[OriginObject], objects),
        file_data=sample_bytes,
    )

    assert count == 0
    item = manifest.items[0]
    assert item.kind == "attachment"
    assert item.name == "summary.pdf"
    assert item.discovery_type == "parser_window"
    assert item.heuristic is False
    assert item.status == "partial"
    assert item.rows == 0
    assert item.error == "no_extracted_table_rows"
    assert item.path is None
    assert not (out_dir / "attachments" / "Excel" / "summary.pdf" / "excel_summary.pdf.csv").exists()


def test_extract_non_xlsx_opj_attachment_hint(tmp_path: Path) -> None:
    sample = tmp_path / "opj_non_xlsx_attachment.opj"
    sample.write_bytes(b"Graph1\\n")
    sample_bytes = sample.read_bytes()

    objects = [
        OriginObject(
            offset=0,
            name="Attachment_Report",
            length=len(sample_bytes),
            object_kind="excel",
            source_object_path="object/Attachment_Report",
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=objects,
        file_data=sample_bytes,
    )

    assert count == 0
    item = manifest.items[0]
    assert item.kind == "attachment"
    assert item.name == "Attachment_Report"
    assert item.discovery_type == "heuristic_object_scan"
    assert item.heuristic is True
    assert item.status == "partial"
    assert item.rows == 0
    assert item.error == "no_extracted_table_rows"
    assert item.path is None
    assert not (out_dir / "attachments" / "object" / "Attachment_Report" / "excel.csv").exists()


def test_extract_spreadsheet_like_opj_attachment_is_raw_attachment(tmp_path: Path) -> None:
    sample = tmp_path / "opj_spreadsheet_attachment.opj"
    sample.write_bytes(b"Graph1\\n")
    sample_bytes = sample.read_bytes()

    objects = [
        OriginObject(
            offset=0,
            name="Report.XLS",
            length=len(sample_bytes),
            object_kind="excel",
            source_object_path="Excel/Report.XLS",
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=objects,
        file_data=sample_bytes,
    )

    assert count == 1
    item = manifest.items[0]
    assert item.kind == "attachment"
    assert item.name == "Report.XLS"
    assert item.discovery_type == "heuristic_object_scan"
    assert item.heuristic is True
    assert item.status == "extracted"
    assert item.rows == 0
    assert item.columns == 0
    assert item.error is None
    attachment_path = Path(item.path or "")
    assert attachment_path.as_posix() == "attachments/Excel/Report.XLS/Report.XLS"
    assert (out_dir / attachment_path).exists()


def test_extract_known_non_tabular_opj_attachment_hint_as_raw_attachment(tmp_path: Path) -> None:
    sample = tmp_path / "opj_non_tabular_attachment.opj"
    sample.write_bytes(b"Graph1\n")
    sample_bytes = sample.read_bytes()

    objects = [
        OriginObject(
            offset=0,
            name="Excel",
            length=len(sample_bytes),
            object_kind="excel",
            source_object_path="object/Excel",
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=objects,
        file_data=sample_bytes,
    )

    assert count == 1
    item = manifest.items[0]
    assert item.kind == "attachment"
    assert item.name == "Excel"
    assert item.discovery_type == "heuristic_object_scan"
    assert item.heuristic is True
    assert item.status == "extracted"
    assert item.rows == 0
    assert item.columns == 0
    assert item.error is None
    attachment_path = Path(item.path or "")
    assert attachment_path.as_posix() == "attachments/object/Excel/Excel"
    assert (out_dir / attachment_path).exists()


def test_extract_books_groups_book_prefix_sources_into_workbook_directories_for_opj(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "book_grouping.opj"
    sample.write_bytes(b"CPYA 6.0 123\n")

    def fake_scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        return [(1, 1, 0, ["1"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.scan_numeric_tables_from_bytes",
        fake_scan,
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=11,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert count == 1
    assert (out_dir / "books" / "Book1" / "Book1_A" / "book.csv").exists()


def test_extract_books_uses_parser_backed_rows_without_numeric_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "parsed_rows.opj"
    sample.write_bytes(b"Book1_A data")

    def fake_recover_rows(
        _file_data: bytes, worksheet_names: set[str] | None = None
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        assert worksheet_names is not None
        return {"Book1_A": [["1", "2"], ["3", "4"]]}, {"Book1_A": (2, 2)}, set()

    def fail_scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        raise AssertionError("numeric scan should not run when parsed records are available")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_rows_from_opju",
        fake_recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables.scan_numeric_tables_from_bytes",
        fail_scan,
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=9,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert count == 1
    output = out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.csv"
    assert output.exists()
    assert manifest.items[0].heuristic is False


def test_extract_books_counts_parser_backed_worksheet_hints_without_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "hinted_rows.opju"
    sample.write_bytes(b"OPJU fixture payload")
    scan_calls: list[int] = []

    def fake_recover_rows(
        _file_data: bytes, worksheet_names: set[str] | None = None
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        assert worksheet_names is not None
        assert "Book1_A" in worksheet_names
        return {}, {}, {"Book1_A"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return []

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_rows_from_opju",
        fake_recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables.scan_numeric_tables_from_bytes",
        scan,
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=17,
            object_kind="worksheet",
            source_object_path="object/Book1_A",
        )
    ]
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert count == 0
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A"]
    assert len(worksheet_items) == 1
    assert worksheet_items[0].status == "partial"
    assert worksheet_items[0].error == "no_extracted_table_rows"
    assert scan_calls == [1]


def test_infer_parser_backed_worksheet_names_keeps_multiple_workbook_matches() -> None:
    workbook_tokens = {"Book", "MBook"}
    worksheet_names = {
        "Book_A",
        "Book_B",
        "Book_B__1",
        "MBook_C",
        "Other_X",
    }
    assert _infer_parser_backed_worksheet_names(workbook_tokens, worksheet_names) == {
        "Book_A",
        "Book_B",
        "Book_B__1",
        "MBook_C",
    }


def test_infer_parser_backed_worksheet_names_normalizes_report_tokens() -> None:
    workbook_tokens = {"N2NTIME", "crossO2O2"}
    worksheet_names = {
        "N2N_A",
        "O2O_B",
        "Other_C",
    }
    assert _infer_parser_backed_worksheet_names(workbook_tokens, worksheet_names) == {
        "N2N_A",
        "O2O_B",
    }


def test_filter_meaningful_recovered_rows_preserves_parser_backed_fit_rows() -> None:
    rows_by_name = {
        "Book1/FitLinear1": [
            ["cell://[Book1]FitLinear1!Parameters.Intercept.row_label"],
            ["cell://[Book1]FitLinear1!Parameters.Slope.row_label"],
            ["cell://[Book1]FitLinear1!Parameters.Intercept_2.row_label"],
        ],
        "origin_storage_family_000000_00": [
            ["a"],
            ["a"],
        ],
    }
    dims_by_name = {
        "Book1/FitLinear1": (3, 1),
        "origin_storage_family_000000_00": (2, 1),
    }
    filtered_rows, filtered_dims = _filter_meaningful_recovered_rows(
        rows_by_name,
        dims_by_name,
        parser_backed_worksheet_names={"Book1/FitLinear1"},
    )

    assert filtered_rows["Book1/FitLinear1"] == rows_by_name["Book1/FitLinear1"]
    assert filtered_dims["Book1/FitLinear1"] == (3, 1)
    assert filtered_rows["origin_storage_family_000000_00"] == []
    assert filtered_dims["origin_storage_family_000000_00"] == (0, 0)


def test_filter_meaningful_recovered_rows_keeps_multicolumn_single_row() -> None:
    rows_by_name = {
        "Book1": [["time", "value"]],
        "origin_storage_family_000000_00": [["a"], ["a"]],
    }
    dims_by_name = {
        "Book1": (1, 2),
        "origin_storage_family_000000_00": (2, 1),
    }

    filtered_rows, filtered_dims = _filter_meaningful_recovered_rows(
        rows_by_name,
        dims_by_name,
    )

    assert filtered_rows["Book1"] == rows_by_name["Book1"]
    assert filtered_dims["Book1"] == (1, 2)
    assert filtered_rows["origin_storage_family_000000_00"] == []
    assert filtered_dims["origin_storage_family_000000_00"] == (0, 0)


def test_is_parser_recovered_row_meaningful_rejects_fig3_single_column_garbage() -> None:
    rows = [
        [";C"],
        ["Sheet1*"],
        [">T("],
        ["$qrNh"],
        ["bAV^7"],
        ["Page>"],
        ["#k"],
        ["B33"],
        ["?F"],
        ["e?"],
        ["wP"],
        ["Ws,@LM0"],
        ["ESizeU"],
        ["ZLine"],
        ["SX"],
        ["WH"],
        ["7z"],
    ]
    assert not _is_parser_recovered_row_meaningful(rows)


def test_is_parser_recovered_row_meaningful_rejects_figure_7e_like_noise() -> None:
    rows = [
        [value]
        for value in [
            ",C",
            "aSheet1*",
            "/D",
            "?E",
            "Roncador",
            "?G",
            "/H",
            "?I",
            "?K",
            "nIran",
            "?M",
            "/N",
            "?O",
            "~Merey",
            "?S",
            ">T(",
            "[iXKG0",
            'D"V$I',
            "@.{G<F4",
            "52",
            "9545a",
            "9612",
            "o_Hy",
            "?553T",
            "Sheet1",
        ]
    ]
    assert not _is_parser_recovered_row_meaningful(rows)


def test_is_parser_recovered_row_meaningful_accepts_semicolon_numeric_series() -> None:
    rows = [
        [
            "1;-0.03208982188295166;-0.03208982188295166;-0.03208982188295166;-0.03208982188295166;-0.05359387263568026;-0.03208982188295166",
        ]
    ]
    assert _is_parser_recovered_row_meaningful(rows)
