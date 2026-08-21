"""End-to-end command contracts for a framed OPJU payload."""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import pytest

from deopjufier.cli import main


def _write_framed_opju(path: Path, payload: bytes | None = None) -> bytes:
    payload = payload or b'<OriginStorage Label="Layout"><Col>2</Col><Row>1</Row></OriginStorage>'
    stream = bytes((0xF0, len(payload) - 15)) + payload
    data = b"CPYUA 4.3318 0\x00" + len(payload).to_bytes(4, "little") + stream
    path.write_bytes(data)
    return data


def test_walk_command_supports_opju_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "framed.opju"
    payload = _write_framed_opju(sample)

    code = main(["walk", str(sample), "--json"])
    captured = capsys.readouterr()
    walked = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert walked[0]["kind"] == "opju_container"
    decoded = next(item for item in walked if item["metadata"].get("source_kind") == "decoded")
    assert decoded["metadata"]["decoded_length"] < len(payload)
    assert decoded["metadata"]["decoded_length"] > 0

    assert main(["walk", str(sample), "--json", "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_extended_extract_exports_decoded_opju_regions_and_honors_force(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "framed.opju"
    _write_framed_opju(sample)
    out_dir = tmp_path / "out"
    args = [
        "extract",
        str(sample),
        "-o",
        str(out_dir),
        "--extended",
        "--parser-only",
        "--no-images",
        "--no-strings",
        "--no-tables",
    ]

    first_code = main([*args, "--force"])
    first = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    second_code = main(args)
    second = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert first_code in {0, 4}
    assert second_code in {0, 4}
    first_regions = [item for item in first["items"] if item["kind"] == "opju_decoded_region"]
    second_regions = [item for item in second["items"] if item["kind"] == "opju_decoded_region"]
    assert len(first_regions) == 1
    assert first_regions[0]["status"] == "extracted"
    assert first_regions[0]["compression"] == "lz4-block"
    assert first_regions[0]["framing_rule"] == "origin_storage_anchor"
    assert (out_dir / first_regions[0]["path"]).is_file()
    assert not any(item["kind"] == "opju_decoded_strings" for item in first["items"])
    assert not any(item["kind"] == "opju_numeric_run_inventory" for item in first["items"])
    assert len(second_regions) == 1
    assert second_regions[0]["status"] == "skipped"
    assert second_regions[0]["error"] == "target_exists"


def test_extended_extract_exports_decoded_string_and_numeric_inventories(tmp_path: Path) -> None:
    encoded = base64.b64encode(struct.pack("<4d", 1.0, 2.0, 3.0, 4.0))
    payload = b'<OriginStorage><Counts BlobArrElementaryType="5">' + encoded + b"</Counts></OriginStorage>"
    sample = tmp_path / "numeric.opju"
    _write_framed_opju(sample, payload)
    out_dir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--extended",
            "--parser-only",
            "--no-images",
            "--force",
        ]
    )
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    items = {item["kind"]: item for item in manifest["items"]}

    assert code in {0, 4}
    assert items["opju_decoded_strings"]["rows"] == 1
    assert items["opju_numeric_run_inventory"]["rows"] == 1
    assert (out_dir / items["opju_decoded_strings"]["path"]).is_file()
    assert (out_dir / items["opju_numeric_run_inventory"]["path"]).is_file()


def test_human_extract_omits_decoded_region_provenance(tmp_path: Path) -> None:
    sample = tmp_path / "framed.opju"
    _write_framed_opju(sample)
    out_dir = tmp_path / "human"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(out_dir),
            "--human",
            "--parser-only",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert code in {0, 4}
    assert not (out_dir / "metadata" / "opju_decoded").exists()
    assert all(not item["kind"].startswith("opju_decoded_") for item in manifest["items"])


def test_opju_inspect_list_strings_and_dump_block_options(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = tmp_path / "framed.opju"
    data = _write_framed_opju(sample)

    assert main(["inspect", str(sample), "--json"]) == 0
    inspect_payload = json.loads(capsys.readouterr().out)
    assert inspect_payload["detected_type"] == "opju"
    assert main(["inspect", str(sample), "--json", "--quiet"]) == 0
    assert capsys.readouterr().out == ""

    assert main(["list", str(sample), "--json", "--exhaustive"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert any(item["object_kind"] == "meta" for item in list_payload["items"])
    assert main(["list", str(sample), "--json", "--quiet"]) == 0
    assert capsys.readouterr().out == ""

    assert main(["strings", str(sample), "--encoding", "utf-8", "--min-length", "8"]) == 0
    assert "OriginStorage" in capsys.readouterr().out
    assert main(["strings", str(sample), "--decoded", "--min-length", "8"]) == 0
    assert "OriginStorage" in capsys.readouterr().out
    assert main(["strings", str(sample), "--quiet"]) == 0
    assert capsys.readouterr().out == ""

    assert main(["dump-block", str(sample), "--offset", "0", "--length", "5"]) == 0
    assert capsys.readouterr().out.encode() == data[:5]
    assert main(["dump-block", str(sample), "--offset", "0", "--length", "5", "--quiet"]) == 0
    assert capsys.readouterr().out == ""
