"""Assert stream discipline and CLI error/success output paths."""

from __future__ import annotations

import io
import json
import subprocess
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


@pytest.mark.parametrize("command", ["extract", "images"])
def test_multi_file_commands_require_explicit_output_dir(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "sample.opj"
    sample.write_bytes(b"CPYA 4.2673 552#\n")

    code = main([command, str(sample)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "-o/--out" in captured.err
    assert sorted(path.name for path in tmp_path.iterdir()) == ["sample.opj"]


def test_inspect_supported_input_uses_stdout_for_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"sample")

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
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"sample")

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
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"")
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
    assert captured.err.startswith("deopjufy: extract ")
    assert captured.err.count("\n") == 1
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
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"sample")

    code = main(["images", str(sample), "--out", str(tmp_path / "img")])
    captured = capsys.readouterr()

    assert code == 3
    assert captured.out == ""
    assert "no images found" in captured.err.lower()


def test_images_default_output_is_human_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA 4.3445 200\n" + _VALID_PNG_1X1)

    code = main(["images", str(sample), "--out", str(tmp_path / "images")])
    captured = capsys.readouterr()

    assert code == 0
    assert not captured.out.startswith("{")
    assert captured.out.strip().endswith(".png")
    assert captured.err == ""


def test_images_json_output_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA 4.3445 200\n" + _VALID_PNG_1X1)

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
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"sample")

    code = main(["images", str(sample), "--out", str(tmp_path / "images"), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["input"]["path"] == str(sample)
    assert payload["status"] == "unsupported"
    assert payload["warnings"] == ["No recognizable image blocks were found."]


def test_images_json_output_marks_malformed_png_as_partial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00")

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
    sample.write_bytes(b"CPYUA 4.3445 200\n" + b"sample")

    code = main(["table-scan", str(sample), "--min-rows", "5", "--min-columns", "2"])
    captured = capsys.readouterr()

    assert code == 3
    assert captured.out == ""
    assert "# no numeric table rows detected" in captured.err


def test_compare_human_output_reports_match_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
    assert captured.out.startswith("Left ")
    assert "\nResult  match\n" in captured.out


def test_dump_block_negative_range_reports_usage_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    code = main(["dump-block", str(sample), "--offset", "-1", "--length", "10"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "usage:" in captured.err.lower()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("command", ["extract", "images"])
def test_rerun_into_non_empty_output_requires_force(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = (
        Path(__file__).resolve().parents[2] / "fixtures/synthetic/synthetic-opju-preview-report-with-valid-image.opju"
    )
    outdir = tmp_path / "out"
    assert main([command, str(sample), "-o", str(outdir)]) == 0
    before = _snapshot(outdir)
    assert before
    capsys.readouterr()

    code = main([command, str(sample), "-o", str(outdir)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "--force" in captured.err
    assert _snapshot(outdir) == before
    assert main([command, str(sample), "-o", str(outdir), "--force"]) == 0


def test_extract_refuses_existing_manifest_path_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = (
        Path(__file__).resolve().parents[2] / "fixtures/synthetic/synthetic-opju-preview-report-with-valid-image.opju"
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("keep", encoding="utf-8")

    code = main(["extract", str(sample), "-o", str(tmp_path / "out"), "--manifest", str(manifest_path)])

    assert code == 1
    assert "--force" in capsys.readouterr().err
    assert manifest_path.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "out").exists()


def test_closed_stdout_pipe_exits_quietly() -> None:
    sample = Path(__file__).resolve().parents[2] / "fixtures/synthetic/synthetic-opj-multi-family.opj"
    process = subprocess.Popen(
        [sys.executable, "-m", "deopjufier", "strings", str(sample), "--min-length", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    # Close the read end before the child writes, as `| head -0` would.
    process.stdout.close()
    stderr = process.stderr.read()
    process.stderr.close()

    assert process.wait(timeout=60) == 0
    assert b"BrokenPipeError" not in stderr
    assert b"Exception ignored" not in stderr


def test_strings_write_failure_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"visible text\x00more text")

    class _FullDisk(io.StringIO):
        def write(self, _text: str) -> int:
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(sys, "stdout", _FullDisk())
    code = main(["strings", str(sample)])

    assert code == 1
    assert "No space left on device" in capsys.readouterr().err


def test_extract_prints_one_summary_line_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = (
        Path(__file__).resolve().parents[2] / "fixtures/synthetic/synthetic-opju-preview-report-with-valid-image.opju"
    )
    outdir = tmp_path / "out"

    code = main(["extract", str(sample), "-o", str(outdir)])
    captured = capsys.readouterr()
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))

    extracted = sum(1 for item in manifest["items"] if item["status"] == "extracted")
    assert code == 0
    assert captured.out == ""
    assert captured.err == (
        f"deopjufy: extract {manifest['status']}: {extracted} extracted, "
        f"{len(manifest['items']) - extracted} not extracted, {len(manifest['warnings'])} warnings; "
        f"manifest {outdir / 'manifest.json'}\n"
    )
    assert main(["extract", str(sample), "-o", str(tmp_path / "quiet"), "--quiet"]) == 0
    assert capsys.readouterr().err == ""


def test_list_table_is_compact_and_shows_evidence(capsys: pytest.CaptureFixture[str]) -> None:
    sample = (
        Path(__file__).resolve().parents[2] / "fixtures/synthetic/synthetic-opju-preview-report-with-valid-image.opju"
    )

    main(["list", str(sample)])
    lines = capsys.readouterr().out.splitlines()
    table = lines[lines.index("Catalog") + 1 :]
    header, rule, rows = table[0], table[1], [line for line in table[2:] if line and not line.startswith("Warn")]

    assert header.split() == ["Offset", "Length", "Kind", "Evidence", "Name", "Object"]
    assert len(rule) == len(header)
    assert all(line == line.rstrip() for line in [header, *rows])
    assert all(row.split()[3] in {"parser", "heuristic"} for row in rows)
    widest_row = max(len(row) for row in rows)
    assert len(header) <= widest_row


@pytest.mark.parametrize("command", ["list", "inspect"])
def test_capped_heuristic_listing_is_disclosed(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from deopjufier.opju.common import OPJU_END_TRAILER

    sample = tmp_path / "many.opju"
    tokens = b"".join(f"\x00Book{index}_A\x00".encode() for index in range(40))
    sample.write_bytes(b"CPYUA 4.3445 200\n" + tokens + OPJU_END_TRAILER)

    main([command, str(sample), "--json"])
    capped = json.loads(capsys.readouterr().out)
    main(["list", str(sample), "--json", "--exhaustive"])
    exhaustive = json.loads(capsys.readouterr().out)

    assert "heuristic-items-capped" in {warning["code"] for warning in capped["parser_warnings"]}
    assert "heuristic-items-capped" not in {warning["code"] for warning in exhaustive["parser_warnings"]}
    assert len(exhaustive["items"]) == 41


def test_internal_type_error_is_not_reported_as_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    from deopjufier.commands import dispatch

    def _broken(_args: object) -> int:
        raise TypeError("internal bug")

    monkeypatch.setattr(dispatch, "_map_command_to_handler", lambda _command: _broken)

    with pytest.raises(TypeError, match="internal bug"):
        main(["inspect", "whatever.opj"])


@pytest.mark.parametrize("command", ["inspect", "list", "strings", "walk", "table-scan"])
def test_verbose_is_offered_only_where_it_has_an_effect(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([command, "sample.opj", "--verbose"])

    assert code == 2
    assert "unrecognized arguments: --verbose" in capsys.readouterr().err


def test_strings_json_lists_text_with_byte_offsets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"\x00\x00alpha\x00bravo")

    code = main(["strings", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == {
        "schema_version": 1,
        "file": str(sample),
        "encoding": "ascii",
        "min_length": 4,
        "decoded": False,
        "strings": [{"offset": 2, "text": "alpha"}, {"offset": 8, "text": "bravo"}],
    }


def test_strings_json_without_byte_offsets_uses_null(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes("alpha\nbravo\n".encode("utf-16-le"))

    main(["strings", str(sample), "--json", "--encoding", "utf16"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["strings"] == [{"offset": None, "text": "alpha"}, {"offset": None, "text": "bravo"}]


def test_inspect_human_output_summarizes_without_raw_structures(capsys: pytest.CaptureFixture[str]) -> None:
    from deopjufier.commands.render import _print_inspect_summary

    payload = {
        "path": "p.opj",
        "detected_type": "opj",
        "confidence": 0.99,
        "reason": "extension",
        "size_bytes": 30007,
        "sha256": "ab" * 32,
        "support_class": "partial",
        "parser_status": "ok",
        "status": "ok",
        "coverage_scope": "recovered",
        "verification": "unverified",
        "counts": {
            "items": 3,
            "images": 0,
            "origin_objects": 3,
            "origin_object_kinds": {"note": 1, "worksheet": 2},
            "parser_evidence_counts": {"heuristic": {"false": 1, "true": 2}},
        },
        "format_hints": {
            "opj_magic": "CPYA",
            "opj_build": 196,
            "opj_origin_version": 9.2,
            "magic_verified": True,
            "opj_note_sections": [{"name": "Note1", "text": "a\nb"}],
        },
        "warnings": ["cut"],
    }

    _print_inspect_summary(payload, as_json=False)
    out = capsys.readouterr().out

    assert "Type      opj (CPYA magic, confidence 0.99)\n" in out
    assert "Origin    version 9.2, build 196\n" in out
    assert "Size      30,007 bytes\n" in out
    assert "  Objects  3: 1 parser-backed, 2 heuristic\n" in out
    assert "  Kinds    worksheet 2, note 1\n" in out
    assert "opj_note_sections  1: Note1\n" in out
    assert "magic_verified     yes\n" in out
    assert "{'name'" not in out
    assert out.endswith("\nWarnings\n  - cut\n")
