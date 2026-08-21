"""Large-worksheet and metadata extraction regression tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deopjufier.discovery import _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
from deopjufier.extract import extract_books
from deopjufier.inventory import OpjWorksheetMetadata, OriginObject, discover_origin_objects
from tests.test_core_unit_coverage_utils import _make_manifest


def _discover_objects(path: Path) -> list[OriginObject]:
    return discover_origin_objects(path)


def test_extract_books_keeps_opju_parser_backed_sheet_partial_when_single_cell_scan_is_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_parser_backed_single_cell_noise.opju"
    sample.write_bytes(b"1,2\n3,4\n")
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [OriginObject(0, "Sheet1", sample.stat().st_size, "worksheet", source_object_path="Sheet/Sheet1")]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {"Sheet1": []}, {"Sheet1": (0, 0)}, {"Sheet1"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [(1, 1, 0, ["7"])]

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat", recover_rows
    )
    monkeypatch.setattr("deopjufier.extract.object_tables_extract_tables._core.scan_numeric_tables_from_bytes", scan)
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
    assert count == 0
    worksheet_item = manifest.items[0]
    assert worksheet_item.kind == "worksheet"
    assert worksheet_item.name == "Sheet1"
    assert worksheet_item.status == "partial"
    assert worksheet_item.error == "no_extracted_table_rows"
    assert worksheet_item.rows == 0
    assert worksheet_item.heuristic is False


def test_extract_books_scans_large_opju_worksheet_without_hints_when_other_rows_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"10,11\n12,13\n"
    sample = tmp_path / "opju_parser_backed_large_without_hints.opju"
    sample.write_bytes(payload + b"0" * (max(0, _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES - len(payload) + 1)))

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=16,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        ),
        OriginObject(
            offset=16,
            name="Book2_B",
            length=sample.stat().st_size - 16,
            object_kind="worksheet",
            source_object_path="Book/Book2_B",
        ),
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {"Book1_A": [["10", "11"]]}, {"Book1_A": (1, 2)}, {"Book1_A"}

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [(1, 1, 0, ["10", "11"]), (2, 1, 16, ["12", "13"])]

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
    assert count == 2
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet" and item.status == "extracted"]
    assert {item.name for item in worksheet_items} == {"Book1_A", "Book2_B"}
    assert next(item for item in worksheet_items if item.name == "Book2_B").rows == 1
    output = out_dir / "books" / "Book" / "Book2_B" / "book.csv"
    assert output.exists()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == [
        "table_id,row_in_table,offset,columns,values",
        "2,1,16,2,12;13",
    ]


def test_extract_books_scans_large_opju_worksheet_for_parser_confirmed_no_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"10,11\n12,13\n"
    sample = tmp_path / "opju_parser_backed_large_no_hints.opju"
    sample.write_bytes(payload + b"0" * (max(0, _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES - len(payload) + 1)))

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=16,
            object_kind="worksheet",
            parser_confirmed=True,
            source_object_path="Book/Book1_A",
        ),
        OriginObject(
            offset=16,
            name="Book2_B",
            length=sample.stat().st_size - 16,
            object_kind="worksheet",
            parser_confirmed=True,
            source_object_path="Book/Book2_B",
        ),
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {}, {}, set()

    def scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        return [
            (1, 1, 0, ["10", "11"]),
            (2, 1, 16, ["12", "13"]),
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
    )

    assert scan_calls
    assert count == 2
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet" and item.status == "extracted"]
    assert {item.name for item in worksheet_items} == {"Book1_A", "Book2_B"}
    assert all(item.rows == 1 for item in worksheet_items)


def test_extract_books_scans_large_opju_worksheet_with_discovered_names_no_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"10,11\n12,13\n"
    sample = tmp_path / "opju_discovered_name_no_hints.opju"
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
        return {}, {}, set()

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


def test_extract_books_scans_opju_worksheet_with_parser_hint_plus_parser_confirmed_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"10,11\n12,13\n"
    sample = tmp_path / "opju_parser_backed_large_mix.opju"
    sample.write_bytes(payload + b"0" * (max(0, _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES - len(payload) + 1)))

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    scan_calls: list[int] = []
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=16,
            object_kind="worksheet",
            parser_confirmed=True,
            source_object_path="Book/Book1_A",
        ),
        OriginObject(
            offset=16,
            name="Book2_B",
            length=sample.stat().st_size - 16,
            object_kind="worksheet",
            parser_confirmed=True,
            source_object_path="Book/Book2_B",
        ),
    ]

    def recover_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
        return {"Book1_A": [["10", "11"]]}, {"Book1_A": (1, 2)}, {"Book1_A"}

    def scan(*_args: object, start: int = 0, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        scan_calls.append(1)
        if start == 16:
            return [(1, 1, 16, ["12", "13"])]
        return [
            (1, 1, 0, ["10", "11"]),
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
    )

    assert scan_calls
    assert count == 2
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet" and item.status == "extracted"]
    assert {item.name for item in worksheet_items} == {"Book1_A", "Book2_B"}
    assert all(item.rows == 1 for item in worksheet_items)


def test_extract_books_transposes_opj_data_sections_into_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "opj_multi_column.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n")

    from deopjufier.opj import OpjDataSection

    monkeypatch.setattr(
        "deopjufier.opj.recovery.iter_opj_data_sections",
        lambda *_args, **_kwargs: [
            OpjDataSection(
                offset=0,
                length=0,
                name="Book1_A",
                data_type=0,
                data_type2=0,
                total_rows=2,
                first_row=1,
                last_row=2,
                value_size=8,
                data_type_u=0,
                data_type3=0,
                values=[1.1, 2.2],
            ),
            OpjDataSection(
                offset=0,
                length=0,
                name="Book1_B",
                data_type=0,
                data_type2=0,
                total_rows=2,
                first_row=1,
                last_row=2,
                value_size=8,
                data_type_u=0,
                data_type3=0,
                values=[10.0, 20.0],
            ),
        ],
    )
    monkeypatch.setattr(
        "deopjufier.opj.recovery.parse_opj_worksheet_metadata",
        lambda *_args, **_kwargs: {},
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book/Book1",
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
        allow_parser_recovery=True,
    )

    assert count == 1
    output = out_dir / "books" / "Book1" / "Book1" / "book_Book1.csv"
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines == [
        "col_1,col_2",
        "1.1,10.0",
        "2.2,20.0",
    ]
    rows_item = next(item for item in manifest.items if item.kind == "worksheet" and item.name == "Book1")
    assert rows_item.rows == 2
    assert rows_item.columns == 2


def test_extract_books_collapses_parser_backed_worksheet_columns_into_single_workbook_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_multi_sheet_column_names.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n")

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=10,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        ),
        OriginObject(
            offset=0,
            name="Book1_B",
            length=10,
            object_kind="worksheet",
            source_object_path="Book/Book1_B",
        ),
    ]
    metadata = OpjWorksheetMetadata(
        name="Book1",
        long_name="Book1",
        formula_rows=(1, 2),
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables._parser_window_lookup",
        lambda *_args, **_kwargs: {"Book1", "Book1_A", "Book1_B"},
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {"Book1": [["1", "10"], ["2", "20"]]},
            {"Book1": (2, 2)},
            {"Book1": metadata},
        ),
    )

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
        allow_parser_recovery=True,
    )

    assert count == 1
    outputs = sorted((out_dir / "books").rglob("book_Book1*.csv"))
    assert outputs == [out_dir / "books" / "Book1" / "Book1" / "book_Book1.csv"]
    worksheet_items = [item for item in manifest.items if item.kind == "worksheet"]
    assert [item.name for item in worksheet_items] == ["Book1"]
    lines = [line for line in outputs[0].read_text(encoding="utf-8").splitlines() if line]
    assert lines == ["col_1,col_2", "1,10", "2,20"]


def test_extract_books_keeps_distinct_worksheet_workbooks_when_root_names_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_multiple_worksheets.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n")

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=10,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
        ),
        OriginObject(
            offset=0,
            name="Book1_B",
            length=10,
            object_kind="worksheet",
            source_object_path="Book/Book1_B",
        ),
        OriginObject(
            offset=0,
            name="Book2_A",
            length=10,
            object_kind="worksheet",
            source_object_path="Book/Book2_A",
        ),
        OriginObject(
            offset=0,
            name="Book2_B",
            length=10,
            object_kind="worksheet",
            source_object_path="Book/Book2_B",
        ),
    ]

    metadata1 = OpjWorksheetMetadata(
        name="Book1",
        long_name="Book1",
        column_labels=["A", "B"],
        formula_rows=(1, 2),
    )
    metadata2 = OpjWorksheetMetadata(
        name="Book2",
        long_name="Book2",
        column_labels=["A", "B"],
        formula_rows=(1, 2),
    )

    monkeypatch.setattr(
        "deopjufier.extract.object_tables._parser_window_lookup",
        lambda *_args, **_kwargs: {
            "Book1",
            "Book1_A",
            "Book1_B",
            "Book2",
            "Book2_A",
            "Book2_B",
        },
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {"Book1": [["1", "10"], ["2", "20"]], "Book2": [["3", "30"], ["4", "40"]]},
            {"Book1": (2, 2), "Book2": (2, 2)},
            {"Book1": metadata1, "Book2": metadata2},
        ),
    )

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
        allow_parser_recovery=True,
    )

    assert count == 2
    outputs = sorted((out_dir / "books").rglob("book_Book*.csv"))
    assert outputs == [
        out_dir / "books" / "Book1" / "Book1" / "book_Book1.csv",
        out_dir / "books" / "Book2" / "Book2" / "book_Book2.csv",
    ]
    worksheet_names = [
        item.name for item in manifest.items if item.kind == "worksheet" and not str(item.name).endswith("_collection")
    ]
    assert worksheet_names == ["Book1", "Book2"]


def test_extract_books_writes_worksheet_metadata_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "opj_worksheet_metadata_sidecar.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\0Book1_A\0notes")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {"Book1_A": [["1.0"], ["2.0"]]},
            {"Book1_A": (2, 1)},
            {
                "Book1_A": OpjWorksheetMetadata(
                    name="Book1_A",
                    label="Book1_A",
                    object_id=0,
                    hidden=False,
                    state="normal",
                    creation_time=123,
                    modification_time=456,
                    long_name="Book1_A",
                    formula_rows=(1, 2),
                    units="V",
                    comments="Worksheet notes",
                    formulas=["y = a*x + b"],
                )
            },
        ),
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
        allow_parser_recovery=True,
    )

    assert count == 1
    metadata_path = out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.metadata.json"
    table_path = out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.csv"
    assert metadata_path.exists()
    assert table_path.exists()

    sidecar_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert sidecar_payload == {
        "label": "Book1_A",
        "object_id": 0,
        "hidden": False,
        "state": "normal",
        "creation_time": 123,
        "modification_time": 456,
        "formula_rows": [1, 2],
        "long_name": "Book1_A",
        "comments": "Worksheet notes",
        "formulas": ["y = a*x + b"],
        "units": "V",
    }

    metadata_items = [item for item in manifest.items if item.kind == "worksheet_metadata"]
    assert len(metadata_items) == 1
    assert metadata_items[0].name == "Book1_A_metadata"
    assert metadata_items[0].status == "extracted"
    assert metadata_items[0].path == "books/Book1/Book1_A/book_Book1_A.metadata.json"
    assert metadata_items[0].source_object_path == "Book1/Book1_A"


def test_extract_books_recovers_worksheet_metadata_from_opju_metadata_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_worksheet_metadata.opju"
    sample.write_bytes(b"OPJU fixture payload")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        lambda *_args, **_kwargs: (
            {"Book1_A": [["1", "2"], ["3", "4"]]},
            {"Book1_A": (2, 2)},
            {"Book1_A"},
        ),
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_metadata_compat",
        lambda *_args, **_kwargs: {
            "Book1_A": OpjWorksheetMetadata(
                name="Book1_A",
                label="Book1_A",
                long_name="Book1_A",
                units="V",
            )
        },
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book1/Book1_A",
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
        allow_parser_recovery=True,
    )

    assert count == 1
    metadata_items = [item for item in manifest.items if item.kind == "worksheet_metadata"]
    assert len(metadata_items) == 1
    assert metadata_items[0].name == "Book1_A_metadata"
    assert metadata_items[0].status == "extracted"
    assert metadata_items[0].path == "books/Book1/Book1_A/book_Book1_A.metadata.json"

    metadata_path = out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload == {
        "label": "Book1_A",
        "long_name": "Book1_A",
        "units": "V",
    }


def test_extract_books_does_not_emit_worksheet_metadata_without_opju_parser_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_worksheet_metadata_no_recovery.opju"
    sample.write_bytes(b"OPJU fixture payload")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_rows_compat",
        lambda *_args, **_kwargs: (
            {"Book1_A": [["1", "2"]]},
            {"Book1_A": (1, 2)},
            {"Book1_A"},
        ),
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_worksheet_metadata_compat",
        lambda *_args, **_kwargs: {
            "Book1_A": OpjWorksheetMetadata(
                name="Book1_A",
                label="Book1_A",
                long_name="Book1_A",
                units="V",
            )
        },
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
            object_kind="worksheet",
            source_object_path="Book1/Book1_A",
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
    metadata_items = [item for item in manifest.items if item.kind == "worksheet_metadata"]
    assert metadata_items == []
    assert not (out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.metadata.json").exists()


def test_extract_books_recovers_column_semantics_from_opj_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_worksheet_column_semantics.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\0Book1_A\0")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_worksheet_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {},
            {},
            {
                "Book1_A": OpjWorksheetMetadata(
                    name="Book1_A",
                    column_labels=["X", "Y"],
                    column_types=["numeric", "text"],
                    display_hints=["float64", "text"],
                )
            },
        ),
    )
    monkeypatch.setattr(
        "deopjufier.extract.object_tables.scan_numeric_tables_from_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("numeric scan should be skipped when parser metadata is available")
        ),
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
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
        allow_parser_recovery=True,
    )

    assert count == 0
    assert manifest.items[0].kind == "worksheet"
    assert manifest.items[0].name == "Book1_A"
    assert manifest.items[0].heuristic is False
    assert manifest.items[0].rows == 1
    assert manifest.items[0].columns == 2

    metadata_items = [item for item in manifest.items if item.kind == "worksheet_metadata"]
    assert len(metadata_items) == 1
    metadata_path = out_dir / "books" / "Book1" / "Book1_A" / "book_Book1_A.metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["column_labels"] == ["X", "Y"]
    assert payload["column_types"] == ["numeric", "text"]
    assert payload["display_hints"] == ["float64", "text"]


def test_extract_books_supports_xlsx_format_with_openpyxl_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeWorksheet:
        def append(self, row: list[object]) -> None:
            pass

    class _FakeWorkbook:
        def __init__(self) -> None:
            self.active = _FakeWorksheet()

        def save(self, target: Path | str) -> None:
            Path(target).write_text("xlsx", encoding="utf-8")

    fake_openpyxl = SimpleNamespace(Workbook=lambda: _FakeWorkbook())
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)

    sample = tmp_path / "books_xlsx.opj"
    sample.write_bytes(b"Book1_A\n1 2 3\n4 5 6\nGraph1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="xlsx",
        force=True,
        table_min_rows=1,
        table_min_columns=2,
        objects=_discover_objects(sample),
    )

    assert count == 1
    assert manifest.items[0].name == "Book1_A"
    assert manifest.items[0].status == "extracted"
    assert (out_dir / "books" / "Book1" / "Book1_A" / "book.xlsx").exists()


def test_extract_books_records_relative_manifest_paths(tmp_path: Path) -> None:
    sample = tmp_path / "books_rel.opj"
    sample.write_bytes(b"Book1_A\n1 2 3\n4 5 6\nGraph1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    extracted_count = extract_books(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=2,
        objects=_discover_objects(sample),
    )
    assert extracted_count >= 1
    assert manifest.items
    paths = [Path(item.path or "") for item in manifest.items if item.path]
    assert all(not item_path.is_absolute() for item_path in paths)
    assert (out_dir / "books" / "Book1" / "Book1_A" / "book.csv").exists()


def test_extract_books_skips_numeric_scan_for_large_file_without_parser_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"Book1_A\n1 2 3\n4 5 6\n"
    sample = tmp_path / "large_books.opj"
    sample.write_bytes(payload + b"0" * (max(0, _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES - len(payload) + 1)))

    def fail_scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        raise AssertionError("numeric scan should be skipped for large non-parser inputs")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.scan_numeric_tables_from_bytes",
        fail_scan,
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Book1_A",
            length=sample.stat().st_size,
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

    assert count == 0
    item = manifest.items[0]
    assert item.status == "partial"
    assert item.rows == 0
    assert item.columns == 0
    assert item.heuristic is True
    assert item.path is None
    assert not (out_dir / "books" / "Book1" / "Book1_A" / "book.csv").exists()


from tests.core.extract.tables._test_core_unit_coverage_extract_tables_matrix_excel import *  # noqa: E402,F403
