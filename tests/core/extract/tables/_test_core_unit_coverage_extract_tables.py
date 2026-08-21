"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from deopjufier.discovery import _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
from deopjufier.extract import (
    extract_books,
    extract_excel,
    extract_graph_previews,
    extract_matrices,
)
from deopjufier.extract.object_tables_helpers import (
    _dedupe_partial_tabular_items_with_extracted_names,
)
from deopjufier.inventory import (
    OpjWorksheetMetadata,
    OriginObject,
    discover_origin_objects,
)
from deopjufier.manifest import ManifestItem
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


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _build_opj_global_header() -> bytes:
    return _u32(4) + b"\n" + b"HEAD" + b"\n" + _u32(0) + b"\n"


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
    payload = b"CPYA 6.0 552#\n" + _build_opj_global_header()
    for index, (name, values) in enumerate(sections):
        payload += _opj_matrix_data_section_payload(name, values)
        if index + 1 < len(sections):
            payload += b"\x00\x00\x00\x00\n"
    payload += _u32(0) + b"\n"
    return payload


def test_extract_matrices_does_not_emit_unsupported_collection_for_opju_without_parser_rows(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "no_parser_matrix.opju"
    sample.write_bytes(b"OPJU fixture payload")
    manifest = _make_manifest(sample)

    objects = [
        OriginObject(
            offset=0,
            name="MatrixA",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="Matrix/MatrixA",
            parser_confirmed=False,
        )
    ]
    out_dir = tmp_path / "out"

    count = extract_matrices(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
        allow_parser_recovery=True,
    )

    assert count == 0
    assert not any(item.kind == "matrix" and str(item.name).endswith("_collection") for item in manifest.items)


def test_extract_matrices_marks_missing_opj_matrix_objects_as_unsupported_collection(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "no_matrix.opj"
    sample.write_bytes(b"Book1_A\n1 2 3\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "matrices"

    count = extract_matrices(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=[],
    )

    assert count == 0
    matrix_item = next(item for item in manifest.items if item.kind == "matrix" and item.name == "matrix_collection")
    assert matrix_item.status == "unsupported"
    assert matrix_item.error == "no_matrix_objects"
    assert matrix_item.discovery_type == "parser_backed_hint"
    assert matrix_item.heuristic is False


def test_extract_excel_marks_missing_opj_excel_objects_as_unsupported_collection(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "no_excel.opj"
    sample.write_bytes(b"Graph1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "excel"

    count = extract_excel(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=[],
    )

    assert count == 0
    excel_item = next(item for item in manifest.items if item.kind == "excel" and item.name == "excel_collection")
    assert excel_item.status == "unsupported"
    assert excel_item.error == "no_excel_objects"
    assert excel_item.discovery_type == "parser_backed_hint"
    assert excel_item.heuristic is False


def test_extract_graph_previews_marks_no_graph_objects_as_unsupported_collection(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "no_graph_objects.opj"
    sample.write_bytes(b"Graphless fixture\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "graphs"

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
    )

    assert count == 0
    graph_item = next(item for item in manifest.items if item.kind == "graph" and item.name == "graph_collection")
    assert graph_item.status == "unsupported"
    assert graph_item.error == "no_graph_objects"
    assert graph_item.discovery_type == "parser_backed_hint"
    assert graph_item.heuristic is False
    assert not any(item.kind == "graph_preview" and str(item.name).endswith("_collection") for item in manifest.items)


def test_extract_books_recover_rows_and_columns_from_opj_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_worksheet_metadata.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\0Book1_A\0something")

    def fail_scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        raise AssertionError("numeric scan should be skipped when parser metadata is available")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {"Book1_A": [["1"], ["2"]]},
            {"Book1_A": (10, 1)},
            {
                "Book1_A": OpjWorksheetMetadata(
                    name="Book1_A",
                    long_name="Book1_A",
                    label="Book1_A",
                    object_id=0,
                    hidden=False,
                    state="normal",
                    creation_time=123,
                    modification_time=456,
                    formula_rows=(1, 2),
                    units="V",
                    comments="Worksheet notes",
                    formulas=["y = a*x + b"],
                )
            },
        ),
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
            length=8,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]
    out_dir = tmp_path / "out"
    extracted_count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
        allow_parser_recovery=True,
    )

    assert extracted_count == 1
    assert manifest.items[0].rows == 10
    assert manifest.items[0].columns == 1
    assert manifest.items[0].heuristic is False
    output = out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.csv"
    assert output.exists()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0] == "col_1"
    assert lines[1:] == ["1", "2"]


def test_extract_books_scans_when_opju_parser_backed_rows_are_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_backed_empty_rows.opju"
    sample.write_bytes(b"1,2,3\n4,5,6\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {"Book1_A": []}, {"Book1_A": (0, 0)}, {"Book1_A"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [
            (1, 1, 0, ["1", "2", "3"]),
            (1, 2, 6, ["4", "5", "6"]),
        ]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

    extracted_count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
    )

    assert scan_calls
    assert extracted_count == 1
    worksheet_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A")
    assert worksheet_item.status == "extracted"
    assert worksheet_item.error is None
    output = out_dir / "books" / "Book" / "Book1_A" / "book_Book1_A.csv"
    assert output.exists()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == ["col_1,col_2,col_3", "1,2,3", "4,5,6"]


def test_extract_books_uses_parser_recovered_workbook_rows_for_worksheet_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_backed_root_window.opju"
    sample.write_bytes(b"1,2\n3,4\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"

    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        ),
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return (
            {
                "Book1": [["1", "2"], ["3", "4"]],
            },
            {"Book1": (2, 2)},
            {"Book1"},
        )

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )

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
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet"]
    assert len(worksheet_items) == 1
    worksheet_item = worksheet_items[0]
    assert worksheet_item.name == "Book1_A"
    assert worksheet_item.status == "extracted"
    assert worksheet_item.error is None

    output = out_dir / "books" / "Book" / "Book1_A" / "book_Book1_A.csv"
    assert output.exists()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == ["col_1,col_2", "1,2", "3,4"]


def test_extract_books_scans_when_opju_parser_backed_hint_is_present_without_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_backed_hint_without_rows.opju"
    sample.write_bytes(b"7,8\n9,10\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {}, {}, {"Book1_A"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [(1, 1, 0, ["7", "8"]), (1, 2, 4, ["9", "10"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

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

    assert scan_calls
    assert count == 1
    worksheet_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A")
    assert worksheet_item.status == "extracted"
    assert worksheet_item.rows == 2
    assert worksheet_item.columns == 2


def test_extract_books_scans_all_opju_duplicate_worksheet_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_duplicate_worksheet_windows.opju"
    sample.write_bytes(b"1\n2\n3\n4\n" * 4)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Sheet1",
            length=4,
            object_kind="worksheet",
            source_object_path="Sheet/Sheet1",
        ),
        OriginObject(
            offset=8,
            name="Sheet1",
            length=6,
            object_kind="worksheet",
            source_object_path="Sheet/Sheet1__2",
        ),
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {"Sheet1": []}, {"Sheet1": (0, 0)}, {"Sheet1"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [
            (1, 1, 8, ["first"]),
            (1, 2, 9, ["second"]),
        ]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
        file_data=sample.read_bytes(),
    )

    assert scan_calls == [1]
    assert count == 1
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet" and item.name == "Sheet1"]
    assert len(worksheet_items) == 1
    extracted = worksheet_items[0]
    assert extracted.status == "extracted"
    assert extracted.path == "books/Sheet/Sheet1__2/book_Sheet1.csv"
    assert extracted.rows == 2


def test_dedupe_partial_worksheet_items_drops_zero_row_duplicates_when_extracted_exists(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "opju_manifest_dedupe.opju"
    sample.write_bytes(b"OPJU fixture payload")
    manifest = _make_manifest(sample)

    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Sheet4",
            status="partial",
            confidence=0.4,
            discovery_type="parser_window",
            heuristic=False,
            path=None,
            source_object_path="Sheet/Sheet4",
            rows=0,
            columns=0,
            error="no_extracted_table_rows",
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Sheet4",
            status="extracted",
            confidence=0.85,
            discovery_type="parser_window",
            heuristic=False,
            path="books/Sheet/Sheet4__2/book_Sheet4.csv",
            source_object_path="Sheet/Sheet4__2",
            rows=3,
            columns=2,
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Sheet3",
            status="partial",
            confidence=0.4,
            discovery_type="parser_window",
            heuristic=False,
            path=None,
            source_object_path="Sheet/Sheet3",
            rows=0,
            columns=0,
            error="no_extracted_table_rows",
        )
    )

    _dedupe_partial_tabular_items_with_extracted_names(
        manifest,
        manifest_item_kind="worksheet",
        collection_name="book",
    )

    remaining_sheet4 = [item for item in manifest.items if item.kind == "worksheet" and item.name == "Sheet4"]
    assert len(remaining_sheet4) == 1
    assert remaining_sheet4[0].status == "extracted"
    assert any(
        item
        for item in manifest.items
        if item.kind == "worksheet" and item.name == "Sheet3" and item.error == "no_extracted_table_rows"
    )


def test_dedupe_partial_worksheet_items_collapses_pathless_suffixed_duplicates(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "opju_manifest_dedupe_pathless.opju"
    sample.write_bytes(b"OPJU fixture payload")
    manifest = _make_manifest(sample)

    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Sheet4",
            status="partial",
            confidence=0.4,
            discovery_type="parser_window",
            heuristic=False,
            path=None,
            source_object_path="Book/Sheet4",
            rows=0,
            columns=0,
            error="no_extracted_table_rows",
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Sheet4",
            status="partial",
            confidence=0.4,
            discovery_type="parser_window",
            heuristic=False,
            path=None,
            source_object_path="Book/Sheet4__2",
            rows=0,
            columns=0,
            error="no_extracted_table_rows",
        )
    )

    _dedupe_partial_tabular_items_with_extracted_names(
        manifest,
        manifest_item_kind="worksheet",
        collection_name="book",
    )

    remaining = [item for item in manifest.items if item.kind == "worksheet" and item.name == "Sheet4"]
    assert len(remaining) == 1


def test_extract_books_relaxes_min_columns_for_opju_parser_backed_worksheet_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_backed_min_columns.opju"
    sample.write_bytes(b"1\n2\n3\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    scan_kwargs: list[dict[str, int]] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {}, {}, {"Book1_A"}

    def scan(
        *_args: object, min_rows: int, min_columns: int, **_kwargs: object
    ) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        scan_kwargs.append({"min_rows": min_rows, "min_columns": min_columns})
        return [
            (1, 1, 0, ["1"]),
            (1, 2, 2, ["2"]),
            (1, 3, 4, ["3"]),
        ]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=2,
        objects=objects,
    )

    assert scan_calls
    assert scan_kwargs[0]["min_columns"] == 1
    assert count == 1
    worksheet_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A")
    assert worksheet_item.status == "extracted"
    assert worksheet_item.rows == 3
    assert worksheet_item.columns == 1
    output = out_dir / "books" / "Book" / "Book1_A" / "book_Book1_A.csv"
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == ["col_1", "1", "2", "3"]


def test_extract_books_scans_opju_worksheet_with_parser_window_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_window_confirmation.opju"
    sample.write_bytes(b"1\n2\n3\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {}, {}, set()

    def parser_windows(*_args: object, **_kwargs: object) -> set[str]:
        return {"Book1_A"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [(1, 1, 0, ["1"]), (1, 2, 2, ["2"]), (1, 3, 4, ["3"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core._parser_window_lookup",
        parser_windows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
        allow_parser_recovery=True,
    )

    assert scan_calls
    assert count == 1
    worksheet_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A")
    assert worksheet_item.status == "extracted"
    assert worksheet_item.rows == 3
    output = out_dir / "books" / "Book" / "Book1_A" / "book_Book1_A.csv"
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == ["col_1", "1", "2", "3"]


def test_extract_books_scans_opju_worksheet_parser_confirmed_without_parser_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_confirmed_window.opju"
    sample.write_bytes(b"1\n2\n3\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            parser_confirmed=True,
            source_object_path="Book/Book1_A",
        )
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {}, {}, set()

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [(1, 1, 0, ["1"]), (1, 2, 2, ["2"]), (1, 3, 4, ["3"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=objects,
        allow_parser_recovery=True,
    )

    assert scan_calls
    assert count == 1
    worksheet_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A")
    assert worksheet_item.status == "extracted"
    assert worksheet_item.rows == 3
    output = out_dir / "books" / "Book" / "Book1_A" / "book_Book1_A.csv"
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == ["col_1", "1", "2", "3"]


def test_extract_books_scans_large_opju_worksheet_hint_records_over_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"10,11\n12,13\n"
    sample = tmp_path / "opju_parser_backed_large_hint.opju"
    sample.write_bytes(payload + b"0" * (max(0, _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES - len(payload) + 1)))

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        )
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {}, {}, {"Book1_A"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [(1, 1, 0, ["10", "11"]), (1, 2, 6, ["12", "13"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

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

    assert scan_calls
    assert count == 1
    worksheet_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1_A")
    assert worksheet_item.status == "extracted"
    assert worksheet_item.rows == 2
    assert worksheet_item.columns == 2


def test_extract_books_keeps_all_opju_worksheet_objects_when_parser_hints_are_over_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"10,11\n12,13\n"
    sample = tmp_path / "opju_parser_backed_noisy_threshold.opju"
    sample.write_bytes(payload + b"0" * (max(0, _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES - len(payload) + 1)))

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    worksheet_objects: list[OriginObject] = []
    for index in range(26):
        worksheet_objects.append(
            OriginObject(
                offset=index * 8,
                name=f"Book{index}",
                length=8,
                object_kind="worksheet",
                source_object_path=f"Book/Book{index}",
            )
        )

    recovered_rows = {"Book0": [["10", "11"]]}
    recovered_dimensions = {"Book0": (1, 2)}
    noisy_hints = {f"Hint{index}" for index in range(26)}

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return recovered_rows, recovered_dimensions, noisy_hints

    def scan(*_args: object, start: int = 0, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        return [(1, 1, start, ["10", "11"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        recover_rows,
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes",
        scan,
    )

    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=1,
        objects=worksheet_objects,
    )

    assert count >= 1

    worksheet_items = [item for item in manifest.items if item.kind == "worksheet"]
    assert len(worksheet_items) == len(worksheet_objects)
    assert any(item.status == "extracted" for item in worksheet_items)
    assert {item.name for item in worksheet_items} == {obj.name for obj in worksheet_objects}
