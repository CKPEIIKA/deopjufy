"""Tests for extract payload emission and format behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.blocks import ImageBlock
from deopjufier.cli import main
from deopjufier.extract.raw_regions import RawRegionClassification
from deopjufier.inventory import OriginObject
from tests.test_core_unit_coverage_utils import _resolve_synthetic_fixture

_VALID_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    + b"\x90wS\xde"
    + b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x17"
    + b"8U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_extract_human_profile_omits_unowned_graph_preview_placeholder(tmp_path: Path) -> None:
    sample = tmp_path / "graph.opj"
    sample.write_bytes(b"Graph1" + b"\x00" + _VALID_PNG_1X1)

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    manifest = outdir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert code == 0
    assert all(item.get("kind") not in {"graph", "graph_preview"} for item in payload["items"])
    assert not (outdir / "graphs").exists()


def test_extract_emits_excel_items(tmp_path: Path) -> None:
    sample = tmp_path / "excel.opj"
    sample.write_bytes(b"ExcelA" + b"\n1 2 3\n4 5 6\n" + b"Graph1\n")

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    manifest = outdir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert code == 0
    excel_items = [item for item in payload["items"] if item.get("kind") in {"excel", "attachment"}]
    assert excel_items
    assert any(
        (outdir / item["path"]).exists()
        for item in excel_items
        if item.get("status") == "extracted" and item.get("path")
    )
    assert any(Path(item["path"]).name == "excel.csv" for item in excel_items if item.get("path"))


def test_extract_emits_function_items(tmp_path: Path) -> None:
    sample = tmp_path / "function.opj"
    sample.write_bytes(b"Function1" + b"\n1 2 3\n4 5 6\n" + b"Graph1\n")

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
        ]
    )

    manifest = outdir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert code == 0
    function_items = [item for item in payload["items"] if item.get("kind") == "function"]
    assert function_items
    assert any(
        (outdir / item["path"]).exists()
        for item in function_items
        if item.get("status") == "extracted" and item.get("path")
    )
    assert any("functions" in (outdir / item["path"]).parts for item in function_items if item.get("path"))


def test_extract_marks_mislabeled_attachment_and_non_lossless_function_partial(tmp_path: Path) -> None:
    sample = tmp_path / "mislabeled.opju"
    sample.write_bytes(
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><Path>[C:\\Temp\\__E_Book.xlsx]</Path></OriginStorage>"
        b"<OriginStorage><Operation><xfName>fit\x7f</xfName><Value>1.2\xff3</Value>"
        b"</Operation></OriginStorage>"
    )
    outdir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
        ]
    )

    assert code == 0
    payload = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert {warning["code"] for warning in payload["parser_warnings"]}.issuperset(
        {"spreadsheet-signature-mismatch", "non-lossless-function-text"}
    )
    attachment = next(item for item in payload["items"] if item["kind"] == "origin_storage_region")
    assert attachment["object_kind"] == "origin_storage_attachment"
    assert attachment["path"].endswith(".originstorage.bin")
    assert not attachment["path"].endswith(".xlsx")
    function = next(item for item in payload["items"] if item["kind"] == "function")
    assert function["status"] == "partial"
    assert function["path"].endswith("function.raw.bin")
    assert function["replacement_character_count"] == 1
    assert function["control_character_count"] == 1


def test_extract_map_recovers_exact_analysis_leaf_fields_from_partial_region(tmp_path: Path) -> None:
    equation = b"y = offset + slope*x"
    region = (
        b"<OriginStorage><Operation><xfName>fit\x7f</xfName></Operation>"
        b'<Calculation AnalysisName="LinearFit">'
        b"<Equation>" + equation + b"</Equation><TableID>17</TableID><Value>1.25</Value>"
        b"<Damaged>1.2\xff3</Damaged></Calculation></OriginStorage>"
    )
    source = b"CPYUA 4.3318 0\x00" + region
    sample = tmp_path / "analysis_fields.opju"
    sample.write_bytes(source)
    outdir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--map",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--force",
        ]
    )

    assert code == 0
    records_path = outdir / "analyses/origin_storage_analysis_records.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert set(records[0]) == {"index", "source_object_path", "source_range", "completeness", "fields"}
    fields = {field["tag"]: field for field in records[0]["fields"]}
    assert fields["Equation"]["value"] == equation.decode("ascii")
    assert fields["Equation"]["path"] == "OriginStorage/Calculation/Equation"
    assert fields["TableID"]["value"] == "17"
    assert fields["Value"]["value"] == "1.25"
    assert "Damaged" not in fields
    equation_range = fields["Equation"]["source_range"]
    assert source[equation_range["start"] : equation_range["end"]] == equation

    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    item = next(item for item in manifest["items"] if item["kind"] == "analysis_records")
    assert item["status"] == "extracted"
    assert item["verification"] == "exact"
    assert item["completeness"] == "partial"
    assert item["rows"] == 1

    human_outdir = tmp_path / "human"
    human_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(human_outdir),
            "--human",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--force",
        ]
    )
    assert human_code == 0
    human_manifest = json.loads((human_outdir / "manifest.json").read_text(encoding="utf-8"))
    assert [item["kind"] for item in human_manifest["items"]] == [
        "analysis_summary",
        "semantic_provenance",
        "semantic_provenance",
        "semantic_provenance",
    ]
    assert human_manifest["items"][0]["completeness"] == "partial"
    assert human_manifest["items"][0]["verification"] == "unverified"
    semantic_index = json.loads((human_outdir / "provenance/semantic_index.json").read_text(encoding="utf-8"))
    assert semantic_index["summary"]["analysis_count"] == 1
    assert semantic_index["summary"]["equation_count"] == 1
    assert semantic_index["summary"]["external_code_mapping"] == "not_assessed"
    assert equation.decode("ascii") in (human_outdir / "analyses/origin_storage_analyses.txt").read_text(
        encoding="utf-8"
    )
    assert not (human_outdir / "analyses/origin_storage_analysis_records.json").exists()


def test_extract_synthetic_opju_emits_note_and_function_items(tmp_path: Path) -> None:
    sample = _resolve_synthetic_fixture(
        Path(__file__),
        "synthetic-cpyua.opju",
    )
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
        ]
    )

    manifest = outdir / "manifest.json"

    assert code in {0, 4}
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    function_items = [
        item
        for item in payload["items"]
        if item.get("kind") == "function" and not str(item.get("name", "")).endswith("_collection")
    ]
    note_items = [
        item
        for item in payload["items"]
        if item.get("kind") == "note" and not str(item.get("name", "")).endswith("_collection")
    ]

    assert function_items, "Expected function artifacts for synthetic OPJU fixture"
    assert note_items, "Expected note artifacts for synthetic OPJU fixture"

    for item in function_items + note_items:
        assert item.get("status") == "extracted"
        item_path = item.get("path")
        assert item_path is not None
        assert (outdir / Path(item_path)).exists()


def test_extract_invalid_raw_min_bytes_is_usage_error(tmp_path: Path) -> None:
    sample = tmp_path / "invalid.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n")

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(tmp_path / "out"),
            "--extended",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--raw-min-bytes",
            "0",
        ]
    )

    assert code == 2


def test_extract_text_regions_exports_text_files(tmp_path: Path) -> None:
    sample = tmp_path / "textregions.opju"
    sample.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"line one\nline two\n" + b"\xff\xd8\xff\xd9"
    )

    out_dir = tmp_path / "out"
    text_dir = tmp_path / "text"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
            "--extended",
            "--text-dir",
            str(text_dir),
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "4",
        ]
    )

    assert code == 0
    payload = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    text_items = [item for item in payload["items"] if item.get("kind") == "text_region"]
    assert text_items
    files = list(text_dir.glob("text_off_*.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "line one" in text
    assert "line two" in text


def test_extract_reuses_gap_classification_for_raw_and_text_same_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "shared_gaps.opju"
    sample.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"line one\nline two\n" + b"\xff\xd8\xff\xd9"
    )

    out_dir = tmp_path / "out"
    raw_dir = tmp_path / "raw"
    text_dir = tmp_path / "text"
    classify_calls: list[int] = []

    from deopjufier.commands.simple import ExtractionSession

    original_classifier = ExtractionSession.classify_unknown_gaps

    def _counting_classifier(
        self: ExtractionSession,
        *,
        min_size: int,
        image_blocks: list[ImageBlock] | None = None,
        objects: list[OriginObject] | None = None,
        min_rows: int = 2,
        min_columns: int = 2,
        text_min_length: int = 4,
        classify_numeric: bool = True,
    ) -> tuple[list[tuple[int, int]], list[RawRegionClassification]]:
        classify_calls.append(1)
        return original_classifier(
            self,
            min_size=min_size,
            image_blocks=image_blocks,
            objects=objects,
            min_rows=min_rows,
            min_columns=min_columns,
            text_min_length=text_min_length,
            classify_numeric=classify_numeric,
        )

    monkeypatch.setattr(
        "deopjufier.commands.simple.ExtractionSession.classify_unknown_gaps",
        _counting_classifier,
    )

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
            "--extended",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
            "--raw-min-bytes",
            "1",
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "4",
        ]
    )

    assert code == 0
    assert len(classify_calls) == 1

    payload = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    raw_items = [item for item in payload["items"] if item["kind"] == "raw_dump"]
    text_items = [item for item in payload["items"] if item["kind"] == "text_region"]
    assert raw_items
    assert text_items
    if raw_items[0]["status"] == "extracted":
        assert list(raw_dir.glob("raw_off_*.bin"))
    assert list(text_dir.glob("text_off_*.txt"))


def test_extract_verbose_reports_steps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "log.opju"
    sample.write_text("plain text\n", encoding="utf-8")

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(tmp_path / "out"),
            "--extended",
            "--verbose",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "extracting embedded images" in captured.err
    assert "extracting visible strings" in captured.err
    assert "extracting numeric tables" in captured.err
    assert "exporting functions" in captured.err


def test_extract_rejects_unrecognized_input(tmp_path: Path) -> None:
    sample = tmp_path / "other.txt"
    sample.write_text("random", encoding="utf-8")

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(tmp_path / "out"),
            "--no-images",
        ]
    )

    assert code == 3


def test_extract_xlsx_format_requires_openpyxl_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def _raise_missing_dependency(*_args: object, **_kwargs: object) -> None:
        called["count"] += 1
        raise ModuleNotFoundError("openpyxl")

    sample = tmp_path / "xformat.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\n4 5 6\n")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        "deopjufier.extract.object_tables._write_book_xlsx",
        _raise_missing_dependency,
    )
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--extended",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--format",
            "xlsx",
        ]
    )

    assert code == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] in {"ok", "partial"}
    assert called["count"] == 0
    assert any(
        item.get("name") == "Book1_A"
        and item.get("status") == "partial"
        and item.get("error") == "no_extracted_table_rows"
        and item.get("discovery_type") == "parser_window"
        for item in manifest["items"]
    )


def test_extract_xlsx_format_writes_book_xlsx_with_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"count": 0}

    def _write_fake_book_xlsx(target: Path, _rows: list[tuple[int, int, int, list[str]]]) -> int:
        called["count"] += 1
        target.write_bytes(b"stubbed xlsx")
        return 1

    sample = tmp_path / "xformat_ok.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\n4 5 6\n")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        "deopjufier.extract.object_tables._write_book_xlsx",
        _write_fake_book_xlsx,
    )
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--extended",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--format",
            "xlsx",
        ]
    )

    assert code == 0
    manifest = out_dir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert called["count"] == 0
    book_items = [item for item in payload["items"] if item.get("kind") == "worksheet"]
    assert any(
        item.get("name") == "Book1_A"
        and item.get("status") == "partial"
        and item.get("error") == "no_extracted_table_rows"
        and item.get("discovery_type") == "parser_window"
        for item in book_items
    )
    assert not (out_dir / "books" / "Book" / "Book1_A" / "book.xlsx").exists()
    assert out_dir.exists()


def test_extract_json_format_outputs_json_tables_and_csv_book_exports(tmp_path: Path) -> None:
    sample = tmp_path / "jsonformat.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\n4 5 6\nGraph1\nFunction1\n")
    out_dir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--extended",
            "--no-images",
            "--no-strings",
            "--format",
            "json",
        ]
    )

    assert code == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert any(item["kind"] == "worksheet" for item in manifest["items"])
    assert (out_dir / "tables" / "guessed_tables.json").exists()
    assert not (out_dir / "tables" / "guessed_tables.csv").exists()
    assert not any(item.get("path") == "books/Book/Book1_A/book.csv" for item in manifest["items"])


def test_extract_writes_matrix_exports(tmp_path: Path) -> None:
    sample = tmp_path / "matrix.opj"
    sample.write_bytes(b"MatrixA" + b"\n1 2 3\n4 5 6\nGraph1\n")
    out_dir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--extended",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    assert code == 0

    manifest = out_dir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    matrix_items = [item for item in payload["items"] if item.get("kind") == "matrix"]
    assert matrix_items
    for item in matrix_items:
        assert item.get("path")
        matrix_path = Path(item["path"])
        assert "matrices" in matrix_path.parts
        assert (out_dir / matrix_path).exists()


def test_extract_writes_note_exports(tmp_path: Path) -> None:
    sample = tmp_path / "note.opj"
    sample.write_bytes(b"Note1\nThis is a markdown note.\n- bullet\nGraph1\n")
    out_dir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    assert code == 0
    manifest = out_dir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    note_items = [item for item in payload["items"] if item.get("kind") == "note"]
    assert note_items
    for item in note_items:
        assert item.get("path")
        note_path = Path(item["path"])
        assert "notes" in note_path.parts
        assert (out_dir / note_path).exists()


def test_extract_fail_on_partial_returns_exit_code(tmp_path: Path) -> None:
    sample = tmp_path / "partial.opju"
    sample.write_bytes(b"\x00" * 50)

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(tmp_path / "out"),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
            "--fail-on-partial",
        ]
    )

    assert code == 4


def test_extract_fail_on_partial_ignores_recon_scan_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "scan-no-match.opju"
    sample.write_text("1 2 3\\n4 5 6\\n", encoding="utf-8")

    def _empty_table_rows(
        _self: object,
        *args: object,
        **kwargs: object,
    ) -> list[tuple[int, int, int, list[str]]]:
        return []

    monkeypatch.setattr("deopjufier.session.ExtractionSession.table_rows", _empty_table_rows)

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(tmp_path / "out"),
            "--extended",
            "--no-objects",
            "--no-images",
            "--no-strings",
            "--fail-on-partial",
        ]
    )

    assert code == 0
    payload = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert any(
        item.get("kind") == "table_scan" and item.get("status") == "partial" for item in payload.get("items", [])
    )
    assert payload.get("status") == "ok"
    assert payload.get("coverage_scope") == "partial"
    assert payload.get("verification") == "unverified"
