"""Unit-level coverage tests for matrix and excel extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.extract import (
    extract_books,
    extract_excel,
    extract_matrices,
)
from deopjufier.inventory import (
    OpjMatrixMetadata,
    OriginObject,
    discover_origin_objects,
)
from deopjufier.opj import OpjDataSection
from tests.core.extract.tables._test_core_unit_coverage_extract_tables import (
    _build_opj_matrix_payload_file,
    _discover_objects,
)
from tests.test_core_unit_coverage_utils import _make_manifest


def test_extract_matrices_creates_matrices_directory_and_rows(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "matrices.opj"
    sample.write_bytes(b"MatrixA" + b"\n1 2 3\n4 5 6\n" + b"Graph1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_matrices(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=2,
        objects=discover_origin_objects(sample),
    )

    assert count == 1
    assert manifest.items
    assert manifest.items[0].kind == "matrix"
    assert manifest.items[0].name == "MatrixA"
    assert manifest.items[0].status == "extracted"
    assert (out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix.csv").exists()


def test_extract_books_uses_decoded_payload_length_not_active_row_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_payload_rows.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n")
    monkeypatch.setattr(
        "deopjufier.opj.recovery.iter_opj_data_sections",
        lambda *_args, **_kwargs: [
            OpjDataSection(
                offset=0,
                length=0,
                name="Book1_A",
                data_type=0,
                data_type2=0,
                total_rows=5,
                first_row=1,
                last_row=2,
                value_size=8,
                data_type_u=0,
                data_type3=0,
                values=[1.0, 2.0, 3.0, 4.0, 5.0],
            )
        ],
    )
    monkeypatch.setattr(
        "deopjufier.opj.recovery.parse_opj_worksheet_metadata",
        lambda *_args, **_kwargs: {},
    )
    manifest = _make_manifest(sample)
    objects = [OriginObject(0, "Book1", sample.stat().st_size, "worksheet", "Book/Book1")]
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
    item = next(item for item in manifest.items if item.kind == "worksheet")
    assert item.rows == 5
    output = out_dir / str(item.path)
    assert output.read_text(encoding="utf-8").splitlines() == [
        "col_1",
        "1.0",
        "2.0",
        "3.0",
        "4.0",
        "5.0",
    ]


def test_extract_matrices_recover_rows_and_columns_from_opj_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_matrix_metadata.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\0MatrixA\0something")

    def fail_scan(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, list[str]]]:
        raise AssertionError("numeric scan should be skipped when parser metadata is available")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_matrix_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {"MatrixA": [["1.0"], ["2.0"]]},
            {"MatrixA": (10, 1)},
            {
                "MatrixA": OpjMatrixMetadata(
                    name="MatrixA",
                    long_name="MatrixA",
                    shape=(10, 1),
                    data_type=0,
                    row_start=7,
                    row_end=16,
                    section_count=1,
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
            name="MatrixA",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="Matrix/MatrixA",
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

    assert count == 1
    assert manifest.items[0].rows == 10
    assert manifest.items[0].columns == 1
    assert manifest.items[0].heuristic is False
    output = out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix_MatrixA.csv"
    assert output.exists()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0] == "col_1"
    assert lines[1:] == ["1.0", "2.0"]


def test_extract_matrices_writes_matrix_metadata_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "opj_matrix_metadata_sidecar.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\0MatrixA\0something")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_matrix_metadata_from_opj_sections",
        lambda *_args, **_kwargs: (
            {"MatrixA": [["1.0"], ["2.0"]]},
            {"MatrixA": (2, 1)},
            {
                "MatrixA": OpjMatrixMetadata(
                    name="MatrixA",
                    long_name="MatrixA",
                    shape=(2, 1),
                    data_type=0,
                    row_start=1,
                    row_end=2,
                    section_count=1,
                )
            },
        ),
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="MatrixA",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="Matrix/MatrixA",
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

    assert count == 1
    metadata_path = out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix_MatrixA.metadata.json"
    table_path = out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix_MatrixA.csv"
    assert metadata_path.exists()
    assert table_path.exists()

    sidecar_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert sidecar_payload == {
        "long_name": "MatrixA",
        "shape": [2, 1],
        "data_type": 0,
        "row_start": 1,
        "row_end": 2,
        "section_count": 1,
    }

    metadata_items = [item for item in manifest.items if item.kind == "matrix_metadata"]
    assert len(metadata_items) == 1
    assert metadata_items[0].name == "MatrixA_metadata"
    assert metadata_items[0].status == "extracted"
    assert metadata_items[0].path == "matrices/Matrix/MatrixA/matrix_MatrixA.metadata.json"
    assert metadata_items[0].source_object_path == "Matrix/MatrixA"


def test_extract_matrices_resolves_collision_suffix_names_for_parser_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_matrix_collision_name.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\0MatrixA\0something")

    def fake_recover_matrix_records(
        _file_data: bytes,
        _matrix_names: set[str],
    ) -> tuple[
        dict[str, list[list[str]]],
        dict[str, tuple[int, int]],
        dict[str, OpjMatrixMetadata],
    ]:
        return (
            {
                "MatrixA": [["1.0"], ["2.0"], ["3.0"]],
            },
            {
                "MatrixA": (3, 1),
            },
            {
                "MatrixA": OpjMatrixMetadata(
                    name="MatrixA",
                    long_name="MatrixA",
                    shape=(3, 1),
                    data_type=0,
                    row_start=1,
                    row_end=3,
                    section_count=1,
                )
            },
        )

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_matrix_metadata_from_opj_sections",
        fake_recover_matrix_records,
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="MatrixA__2",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="Matrix/MatrixA__2",
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

    assert count == 1
    assert manifest.items[0].kind == "matrix"
    assert manifest.items[0].name == "MatrixA__2"
    assert manifest.items[0].status == "extracted"
    assert manifest.items[0].heuristic is False
    assert manifest.items[0].rows == 3
    assert manifest.items[0].columns == 1
    output = out_dir / "matrices" / "Matrix" / "MatrixA__2" / "matrix_MatrixA__2.csv"
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0] == "col_1"
    assert lines[1:] == ["1.0", "2.0", "3.0"]
    metadata_path = out_dir / "matrices" / "Matrix" / "MatrixA__2" / "matrix_MatrixA__2.metadata.json"
    assert metadata_path.exists()
    metadata_items = [item for item in manifest.items if item.kind == "matrix_metadata"]
    assert len(metadata_items) == 1
    assert metadata_items[0].name == "MatrixA__2_metadata"
    assert metadata_items[0].status == "extracted"
    assert metadata_items[0].path == "matrices/Matrix/MatrixA__2/matrix_MatrixA__2.metadata.json"
    assert metadata_items[0].source_object_path == "Matrix/MatrixA__2"
    sidecar_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert sidecar_payload["shape"] == [3, 1]


def test_extract_matrices_recovers_concrete_matrix_payload_from_opj_sections(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "opj_matrix_payload.opj"
    sample.write_bytes(
        _build_opj_matrix_payload_file(
            [
                ("MatrixA_A", [1.0, 2.0, 3.0]),
                ("MatrixA_B", [10.0, 20.0, 30.0]),
            ]
        )
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="MatrixA",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="Matrix/MatrixA",
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

    assert count == 1
    assert manifest.items[0].kind == "matrix"
    assert manifest.items[0].status == "extracted"
    assert manifest.items[0].rows == 3
    assert manifest.items[0].columns == 2
    assert manifest.items[0].heuristic is False

    output = out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix_MatrixA.csv"
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0] == "col_1,col_2"
    assert lines[1:] == [
        "1.0,10.0",
        "2.0,20.0",
        "3.0,30.0",
    ]


def test_extract_matrices_uses_opju_matrix_prefix_for_synthetic_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "synthetic_matrix.opju"
    sample.write_bytes(b"OPJU synthetic matrix payload")

    def recover_matrix_rows(
        *_args: object, **_kwargs: object
    ) -> tuple[
        dict[str, list[list[str]]],
        dict[str, tuple[int, int]],
        set[str],
    ]:
        return {"MatrixA": [["1.0"], ["2.0"]]}, {"MatrixA": (2, 1)}, {"MatrixA"}

    monkeypatch.setattr(
        "deopjufier.extract.object_tables_extract_tables._public._recover_opju_matrix_rows_compat",
        recover_matrix_rows,
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_matrices(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
    )

    assert count == 1
    matrix_item = next(item for item in manifest.items if item.kind == "matrix" and item.name == "MatrixA")
    assert matrix_item.source_object_path == "Matrix/MatrixA"
    assert (out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix_MatrixA.csv").exists()


def test_extract_matrices_resolves_matrix_window_alias_to_parser_matrix_root(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "opj_matrix_alias_payload.opj"
    sample.write_bytes(_build_opj_matrix_payload_file([("MBook1", [1.0, 2.0, 3.0])]))

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="MSheet1",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="MSheet/MSheet1",
        ),
        OriginObject(
            offset=0,
            name="PdMSheet1",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="PdM/PdMSheet1",
        ),
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

    assert count == 2
    matrix_items = [item for item in manifest.items if item.kind == "matrix" and not item.name.endswith("_collection")]
    assert matrix_items
    for item in matrix_items:
        assert item.status == "extracted"
        assert item.rows == 3
        assert item.columns == 1
        assert item.heuristic is False


def test_extract_matrices_parser_backed_no_rows_reports_partial_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opj_matrix_parser_partial.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n" + b"\\0MatrixA\\0payload")

    monkeypatch.setattr(
        "deopjufier.extract.object_tables.recover_matrix_metadata_from_opj_sections",
        lambda *_args: (
            {"MatrixA": []},
            {},
            {},
        ),
    )

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="MatrixA",
            length=sample.stat().st_size,
            object_kind="matrix",
            source_object_path="Matrix/MatrixA",
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
    assert manifest.items
    item = next(item for item in manifest.items if item.kind == "matrix" and item.name == "MatrixA")
    assert item.status == "partial"
    assert item.error == "no_extracted_table_rows"
    assert item.heuristic is False
    assert item.discovery_type == "parser_window"
    output = out_dir / "matrices" / "Matrix" / "MatrixA" / "matrix_MatrixA.csv"
    assert item.path is None
    assert not output.exists()


def test_extract_excel_creates_excel_directory_and_rows(tmp_path: Path) -> None:
    sample = tmp_path / "excel.opj"
    sample.write_bytes(b"ExcelA" + b"\n1 2 3\n4 5 6\n" + b"Graph1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_excel(
        sample,
        out_dir,
        manifest,
        output_format="csv",
        force=True,
        table_min_rows=1,
        table_min_columns=2,
        objects=_discover_objects(sample),
    )

    assert count == 1
    assert manifest.items
    assert manifest.items[0].kind in {"excel", "attachment"}
    assert manifest.items[0].name == "ExcelA"
    assert manifest.items[0].status == "extracted"
    output_path = Path(manifest.items[0].path or "")
    assert output_path.name == "excel.csv"
    assert (out_dir / output_path).exists()


def test_extract_excel_recovers_distinct_opj_workbook_sheets(tmp_path: Path) -> None:
    sample = tmp_path / "multi_sheet.opj"
    sample.write_bytes(
        _build_opj_matrix_payload_file(
            [
                ("Book1_A", [1.0, 2.0]),
                ("Book1_B", [10.0, 20.0]),
                ("Book1_A@2", [3.0, 4.0]),
                ("Book1_B@2", [30.0, 40.0]),
            ]
        )
    )
    objects = [
        OriginObject(
            offset=0,
            name="Book1",
            length=sample.stat().st_size,
            object_kind="excel",
            source_object_path="Book1",
            parser_confirmed=True,
        )
    ]

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
        objects=objects,
        allow_parser_recovery=True,
    )

    assert count == 2
    excel_items = [item for item in manifest.items if item.kind == "excel"]
    assert [(item.name, item.rows, item.columns) for item in excel_items] == [
        ("Book1/Sheet1", 2, 2),
        ("Book1/Sheet2", 2, 2),
    ]
    rows_by_sheet = {
        item.name: (out_dir / str(item.path)).read_text(encoding="utf-8").splitlines() for item in excel_items
    }
    assert rows_by_sheet == {
        "Book1/Sheet1": ["A,B", "1.0,10.0", "2.0,20.0"],
        "Book1/Sheet2": ["A,B", "3.0,30.0", "4.0,40.0"],
    }
