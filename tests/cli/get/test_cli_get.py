from __future__ import annotations

import base64
import json
import struct
import sys
from pathlib import Path

import pytest

from deopjufier.cli import main

_VALID_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    + b"\x90wS\xde"
    + b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x17"
    + b"8U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _small_opju(path: Path) -> None:
    path.write_bytes(
        b"CPYUA 4.3318 0\x00"
        b'<OriginStorage Label="Report One"><Notes>hello</Notes></OriginStorage>'
        b"\x00\x01\x02unowned payload\x03\x04"
    )


def _descriptor_opju(path: Path) -> None:
    def record(name: bytes, payload: bytes) -> bytes:
        header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
        return bytes((len(name),)) + name + header + b"12345678" + payload

    numeric = bytes.fromhex("0a 05 02 00 00 50") + struct.pack("<d", 1.0) + bytes.fromhex("ff ff 01 01 02 00 ce")
    text = bytes.fromhex("0a 05 02 ff ff 02 01 01 01") + b"x" + bytes.fromhex("02 00 ce")
    path.write_bytes(b"CPYUA 4.3445 200\n" + record(b"Book1_B", text) + record(b"Book1_A", numeric))


def test_list_json_exposes_versioned_document_bound_catalog(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "catalog.opju"
    _small_opju(sample)

    code = main(["list", str(sample), "--json", "--include-raw-gaps"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["schema_version"] == 1
    assert payload["document"]["sha256"]
    assert payload["document"]["size_bytes"] == sample.stat().st_size
    assert payload["tool"]["name"] == "deopjufy"
    assert payload["items"]
    assert all(str(item["id"]).startswith("item:v1:") for item in payload["items"])
    assert all(item["retrieval_formats"] for item in payload["items"])


def test_get_materializes_one_raw_catalog_item_as_exact_bytes(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "raw.opju"
    _small_opju(sample)

    list_code = main(["list", str(sample), "--json", "--include-raw-gaps"])
    list_payload = json.loads(capsys.readouterr().out)
    raw_item = next(item for item in list_payload["items"] if item["kind"] == "raw_dump")

    get_code = main(["get", str(sample), raw_item["id"], "--json"])
    get_payload = json.loads(capsys.readouterr().out)

    assert list_code == 0
    assert get_code == 0
    assert get_payload["schema_version"] == 1
    assert get_payload["item"]["id"] == raw_item["id"]
    assert get_payload["status"] == "ok"
    assert get_payload["content_encoding"] == "base64"
    recovered = base64.b64decode(get_payload["content"])
    start = raw_item["offset"]
    end = start + raw_item["length"]
    assert recovered == sample.read_bytes()[start:end]


def test_get_materializes_exact_descriptor_worksheet_and_jsonl(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "descriptor.opju"
    output = tmp_path / "sheet.jsonl"
    _descriptor_opju(sample)

    list_code = main(["list", str(sample), "--json"])
    list_payload = json.loads(capsys.readouterr().out)
    worksheet = next(item for item in list_payload["items"] if item["discovery_type"] == "opju_column_descriptor_table")

    get_code = main(["get", str(sample), worksheet["id"], "--json"])
    get_payload = json.loads(capsys.readouterr().out)
    jsonl_code = main(["get", str(sample), worksheet["id"], "--format", "jsonl", "--output", str(output), "--json"])
    json.loads(capsys.readouterr().out)

    assert list_code == get_code == jsonl_code == 0
    assert get_payload["status"] == "ok"
    assert get_payload["content"]["headers"] == ["A", "B"]
    assert [row["values"] for row in get_payload["content"]["rows"]] == [["1.0", "x"], ["", ""]]
    jsonl_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert jsonl_rows[0] == {"headers": ["A", "B"], "schema_version": 1, "type": "table"}
    assert [row["row"]["values"] for row in jsonl_rows[1:]] == [["1.0", "x"], ["", ""]]


def test_get_exports_descriptor_worksheet_as_xlsx(tmp_path: Path, capsys) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    sample = tmp_path / "descriptor.opju"
    output = tmp_path / "sheet.xlsx"
    _descriptor_opju(sample)

    main(["list", str(sample), "--json"])
    list_payload = json.loads(capsys.readouterr().out)
    worksheet = next(item for item in list_payload["items"] if item["discovery_type"] == "opju_column_descriptor_table")
    code = main(["get", str(sample), worksheet["id"], "--format", "xlsx", "-o", str(output), "--json"])
    json.loads(capsys.readouterr().out)
    workbook = openpyxl.load_workbook(output, read_only=True, data_only=True)

    assert code == 0
    assert workbook.active is not None
    assert list(workbook.active.values) == [("A", "B"), ("1.0", "x"), (None, None)]


def test_get_xlsx_reports_missing_optional_dependency(tmp_path: Path, capsys, monkeypatch) -> None:
    sample = tmp_path / "descriptor.opju"
    output = tmp_path / "sheet.xlsx"
    _descriptor_opju(sample)

    main(["list", str(sample), "--json"])
    list_payload = json.loads(capsys.readouterr().out)
    worksheet = next(item for item in list_payload["items"] if item["discovery_type"] == "opju_column_descriptor_table")
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    code = main(["get", str(sample), worksheet["id"], "--format", "xlsx", "-o", str(output), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 5
    assert payload["error"] == "optional dependency unavailable: openpyxl"
    assert not output.exists()


def test_get_returns_selected_image_as_base64(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "image.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00" + _VALID_PNG_1X1)

    list_code = main(["list", str(sample), "--json"])
    list_payload = json.loads(capsys.readouterr().out)
    image_item = next(item for item in list_payload["items"] if item["kind"] == "png")
    get_code = main(["get", str(sample), image_item["id"], "--json"])
    get_payload = json.loads(capsys.readouterr().out)

    assert list_code == get_code == 0
    assert get_payload["status"] == "ok"
    assert get_payload["content_encoding"] == "base64"
    assert base64.b64decode(get_payload["content"]) == _VALID_PNG_1X1


def test_get_named_project_page_returns_and_exports_exact_preview(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "page-preview.opju"
    output = tmp_path / "GraphOne.png"
    page = b"\x0a\x80\x75\x08\x00\x00GraphOne\x90\x0c\x81\x04LINE\x83\x0cSYSTEM"
    sample.write_bytes(b"CPYUA 4.3318 0\x00" + _VALID_PNG_1X1 + page)

    list_code = main(["list", str(sample), "--json"])
    list_payload = json.loads(capsys.readouterr().out)
    project_page = next(item for item in list_payload["items"] if item.get("object_kind") == "project_page")
    get_code = main(["get", str(sample), project_page["id"], "--json"])
    get_payload = json.loads(capsys.readouterr().out)
    export_code = main(["get", str(sample), project_page["id"], "--format", "png", "--output", str(output), "--json"])
    json.loads(capsys.readouterr().out)

    assert list_code == get_code == export_code == 0
    assert project_page["preview_item_id"]
    assert project_page["retrieval_formats"] == ["json", "png"]
    assert base64.b64decode(get_payload["content"]) == _VALID_PNG_1X1
    assert output.read_bytes() == _VALID_PNG_1X1


def test_get_rejects_an_id_from_other_input_bytes_with_structured_json(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "changed.opju"
    _small_opju(sample)

    code = main(["get", str(sample), "item:v1:not-for-this-document", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 3
    assert payload["schema_version"] == 1
    assert payload["status"] == "error"
    assert payload["error"] == "catalog item does not exist for these input bytes"


def test_get_non_json_format_requires_explicit_output(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "usage.opju"
    _small_opju(sample)

    code = main(["get", str(sample), "item:v1:any", "--format", "csv", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "error"
    assert payload["error"] == "non-JSON formats require --output"


def test_get_rejects_format_not_declared_by_catalog_item(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "format.opju"
    output = tmp_path / "raw.csv"
    _small_opju(sample)

    main(["list", str(sample), "--json", "--include-raw-gaps"])
    list_payload = json.loads(capsys.readouterr().out)
    raw_item = next(item for item in list_payload["items"] if item["kind"] == "raw_dump")
    code = main(["get", str(sample), raw_item["id"], "--format", "csv", "--output", str(output), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 3
    assert "not available" in payload["error"]
    assert not output.exists()


def test_get_human_error_uses_stderr(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "missing-id.opju"
    _small_opju(sample)

    code = main(["get", str(sample), "item:v1:missing"])
    captured = capsys.readouterr()

    assert code == 3
    assert captured.out == ""
    assert "does not exist" in captured.err
