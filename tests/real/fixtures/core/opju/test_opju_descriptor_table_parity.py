from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from deopjufier.cli import main
from deopjufier.opju import (
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
    parse_opju_folder_directory,
    parse_opju_page_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
LOCK_PATH = REPO_ROOT / "tests/fixtures/opju-column-table-zenodo-10721640-figure-s3.json"


def _locked_fixture() -> tuple[dict[str, Any], Path, bytes]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    fixture = REPO_ROOT / str(lock["path"])
    if not fixture.is_file():
        pytest.skip("Local CC-BY Figure S3 OPJU fixture is not available in this checkout.")
    return lock, fixture, fixture.read_bytes()


def _cell_token(kind: str, value: float | int | str | None, bits: str | None) -> str:
    if kind == "missing":
        return "-"
    if bits is not None:
        return f"f:{bits}"
    if kind == "unsigned_integer":
        return f"u:{value}"
    return f"s:{str(value).encode().hex()}"


def test_figure_s3_descriptor_table_matches_independent_value_lock() -> None:
    lock, _fixture, data = _locked_fixture()
    assert len(data) == lock["size_bytes"]
    assert sha256(data).hexdigest() == lock["sha256"]

    descriptors = iter_opju_column_descriptors(data)
    metadata = iter_opju_column_metadata(data, descriptors)
    tables = group_opju_column_descriptors(descriptors, metadata)
    assert len(tables) == 1
    table = tables[0]
    expected = lock["table"]

    assert table.name == expected["name"]
    assert (table.row_count, len(table.columns)) == (expected["rows"], expected["columns"])
    assert [column.identity.column_name for column in table.columns] == expected["source_order"]
    assert [column.display_name for column in table.columns] == expected["display_order"]
    assert [column.designation for column in table.columns] == expected["designation_order"]
    assert [column.long_name for column in table.columns] == expected["long_names"]
    assert [column.formula for column in table.columns] == expected["formulas"]

    expected_payloads = lock["column_payloads"]
    for column in table.columns:
        payload = column.descriptor.decoded_payload
        assert payload is not None
        tokens = [
            _cell_token(kind, value, bits)
            for kind, value, bits in zip(payload.cell_kinds, payload.values, payload.value_bits, strict=True)
        ]
        digest = sha256("\n".join(tokens).encode()).hexdigest()
        assert [
            payload.encoding,
            payload.row_capacity,
            payload.stored_value_count,
            payload.missing_count,
            digest,
        ] == expected_payloads[column.identity.column_name]

    rows_digest = sha256(json.dumps(table.text_rows(), separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert rows_digest == expected["typed_rows_sha256"]


def test_figure_s3_has_parser_backed_project_directory_names() -> None:
    _lock, _fixture, data = _locked_fixture()

    pages = parse_opju_page_directory(data)
    folders = parse_opju_folder_directory(data)

    assert [page.name for page in pages] == ["Graph1", "Graph2"]
    assert [page.template_hint for page in pages] == ["LINE", "LINE"]
    assert all(page.frame_offset is not None for page in pages)
    assert all(page.structural_name == "opju_page_directory_name" for page in pages)
    assert all(page.semantic_alias == "project_page_directory_entry" for page in pages)
    assert all(page.semantic_confidence == "corpus_high" for page in pages)
    assert len(folders) == 1
    assert folders[0].source_object_path.startswith("project_folders/")
    assert folders[0].structural_name == "opju_folder_directory_name"
    assert folders[0].semantic_alias == "project_folder_directory_entry"
    assert folders[0].semantic_confidence == "corpus_high"


@pytest.mark.parametrize(("output_format", "suffix"), [("csv", ".csv"), ("tsv", ".tsv"), ("json", ".json")])
def test_figure_s3_descriptor_table_uses_canonical_writers(
    tmp_path: Path,
    output_format: str,
    suffix: str,
) -> None:
    lock, fixture, _data = _locked_fixture()
    output = tmp_path / output_format

    code = main(
        [
            "extract",
            str(fixture),
            "-o",
            str(output),
            "--extended",
            "--no-images",
            "--no-strings",
            "--format",
            output_format,
        ]
    )

    assert code == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    exact_items = [item for item in manifest["items"] if item.get("extraction_method") == "opju_descriptor_table"]
    assert len(exact_items) == 1
    item = exact_items[0]
    assert item["name"] == lock["table"]["name"]
    assert (item["rows"], item["columns"], item["verification"]) == (579, 10, "exact")
    target = output / item["path"]
    assert target.suffix == suffix

    if output_format == "json":
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["headers"] == lock["table"]["display_order"]
        assert len(payload["rows"]) == 579
    else:
        delimiter = "," if output_format == "csv" else "\t"
        lines = target.read_text(encoding="utf-8").splitlines()
        assert lines[0].split(delimiter) == lock["table"]["display_order"]
        assert len(lines) == 580


def test_figure_s3_human_profile_keeps_exact_table_and_semantic_provenance(tmp_path: Path) -> None:
    _lock, fixture, _data = _locked_fixture()
    output = tmp_path / "human"

    code = main(["extract", str(fixture), "-o", str(output), "--human", "--no-images", "--no-strings"])

    assert code == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert [item["kind"] for item in manifest["items"]] == [
        "worksheet",
        "semantic_provenance",
        "semantic_provenance",
        "semantic_provenance",
    ]
    item = manifest["items"][0]
    assert (item["kind"], item["name"], item["verification"]) == ("worksheet", "Book1/Sheet1", "exact")
    assert all(entry["completeness"] == "partial" for entry in manifest["items"][1:])
    assert all(entry["verification"] == "exact" for entry in manifest["items"][1:])
    artifact_paths = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert artifact_paths == {
        item["path"],
        "provenance/relationships.tsv",
        "provenance/semantic_index.json",
        "provenance/symbols.tsv",
    }
