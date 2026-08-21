"""Assert stream discipline and CLI error/success output paths."""

from __future__ import annotations

import json
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


def test_global_version_option_reports_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--version"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "deopjufy 0.6.0\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["inspect"],
        ["list"],
        ["get"],
        ["extract"],
        ["strings"],
        ["images"],
        ["table-scan"],
        ["dump-block"],
    ],
)
def test_usage_errors_are_emitted_to_stderr_only(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    code = main(argv)
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "usage:" in captured.err.lower()


def test_inspect_supported_input_uses_stdout_for_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    assert captured.out.startswith("{")
    assert "Path" not in captured.out


def test_list_supported_input_uses_stdout_for_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["list", str(sample), "--json"])
    captured = capsys.readouterr()

    assert code in (0, 3)
    assert captured.err == ""
    assert captured.out.startswith("{")


def test_inspect_default_output_is_human_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["inspect", str(sample)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    assert not captured.out.startswith("{")
    assert "Path" in captured.out


def test_list_default_output_is_human_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["list", str(sample)])
    captured = capsys.readouterr()

    assert code in (0, 3)
    assert captured.err == ""
    assert not captured.out.startswith("{")


def test_extract_command_writes_files_and_stays_quiet_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"")
    output = tmp_path / "output"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert output.exists()
    assert (output / "manifest.json").exists()


def test_strings_output_goes_to_stdout_and_not_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("alpha beta", encoding="utf-8")

    code = main(["strings", str(sample), "--min-length", "1"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    assert "alpha" in captured.out


def test_images_command_no_images_prints_supported_error_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["images", str(sample), "--out", str(tmp_path / "img")])
    captured = capsys.readouterr()

    assert code == 3
    assert captured.out == ""
    assert "no images found" in captured.err.lower()


def test_images_default_output_is_human_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(_VALID_PNG_1X1)

    code = main(["images", str(sample), "--out", str(tmp_path / "images")])
    captured = capsys.readouterr()

    assert code == 0
    assert not captured.out.startswith("{")
    assert captured.out.strip().endswith(".png")
    assert captured.err == ""


def test_images_json_output_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(_VALID_PNG_1X1)

    code = main(["images", str(sample), "--out", str(tmp_path / "images"), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert isinstance(payload, dict)
    assert payload["input"]["path"] == str(sample)
    assert payload["status"] == "ok"
    assert payload["items"]
    assert payload["items"][0]["kind"] == "image"


def test_images_json_output_on_no_images_reports_supported_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["images", str(sample), "--out", str(tmp_path / "images"), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["input"]["path"] == str(sample)
    assert payload["status"] == "unsupported"
    assert payload["warnings"] == ["No recognizable image blocks were found."]


def test_images_json_output_marks_malformed_png_as_partial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00")

    code = main(
        [
            "images",
            str(sample),
            "--out",
            str(tmp_path / "images"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["status"] == "unsupported"
    assert payload["items"][0]["status"] == "partial"
    assert payload["items"][0]["error"] == "png_chunk_crc_mismatch"


def test_table_scan_no_rows_outputs_message_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["table-scan", str(sample), "--min-rows", "5", "--min-columns", "2"])
    captured = capsys.readouterr()

    assert code == 3
    assert captured.out == ""
    assert "# no numeric table rows detected" in captured.err


def test_compare_default_output_is_human_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    (left / "manifest.json").write_text(
        json.dumps(
            {
                "input": {
                    "path": "sample.opj",
                    "size_bytes": 0,
                    "sha256": "left-hash",
                    "detected_type": "opj",
                },
                "tool": {"name": "deopjufy", "version": "0.6.0", "backend": "native-parser"},
                "status": "ok",
                "items": [],
                "warnings": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (right / "manifest.json").write_text(
        json.dumps(
            {
                "input": {
                    "path": "sample.opj",
                    "size_bytes": 0,
                    "sha256": "right-hash",
                    "detected_type": "opj",
                },
                "tool": {"name": "deopjufy", "version": "0.6.0", "backend": "native-parser"},
                "status": "ok",
                "items": [],
                "warnings": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    code = main(["compare", str(left), str(right)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    assert captured.out.startswith("left=")


def test_dump_block_negative_range_reports_usage_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["dump-block", str(sample), "--offset", "-1", "--length", "10"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "usage:" in captured.err.lower()
