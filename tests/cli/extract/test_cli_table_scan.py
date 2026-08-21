from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import main


def test_table_scan_json_output(tmp_path: Path) -> None:
    sample = tmp_path / "tables.bin"
    sample.write_bytes(b"header\n1 2 3\n4 5 6\nnot-a-table\n7 8 9\n10 11 12\n")

    code = main(
        [
            "table-scan",
            str(sample),
            "--format",
            "json",
            "--min-rows",
            "2",
            "--min-columns",
            "2",
        ]
    )

    assert code == 0


def test_table_scan_json_payload_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "tables.bin"
    sample.write_bytes(b"header\n1 2 3\n4 5 6\nnot-a-table\n7 8 9\n10 11 12\n")

    code = main(
        [
            "table-scan",
            str(sample),
            "--format",
            "json",
            "--min-rows",
            "2",
            "--min-columns",
            "2",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert isinstance(payload, list)
    assert len(payload) >= 1
    row = payload[0]
    assert {"table_id", "row_in_table", "offset", "columns", "values"} <= set(row)


def test_table_scan_json_flag_is_available(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "tables.bin"
    sample.write_bytes(b"header\n1 2 3\n4 5 6\nnot-a-table\n7 8 9\n10 11 12\n")

    code = main(
        [
            "table-scan",
            str(sample),
            "--json",
            "--min-rows",
            "2",
            "--min-columns",
            "2",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert isinstance(payload, list)


def test_table_scan_no_matches_is_unsupported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "none.opju"
    sample.write_text("abc\ndef\n", encoding="utf-8")

    code = main(
        [
            "table-scan",
            str(sample),
            "--format",
            "csv",
            "--min-rows",
            "4",
            "--min-columns",
            "3",
        ]
    )
    captured = capsys.readouterr()

    assert code == 3
    assert "no numeric table rows detected" in captured.err


def test_table_scan_runs_on_unrecognized_input_files(tmp_path: Path) -> None:
    sample = tmp_path / "numeric.bin"
    sample.write_bytes(b"1 2 3\n4 5 6\n")

    code = main(["table-scan", str(sample), "--format", "csv"])

    assert code == 0


def test_table_scan_tsv_is_tab_delimited(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "tables.bin"
    sample.write_bytes(b"x\n1 2 3\n4 5 6\n")

    code = main(
        [
            "table-scan",
            str(sample),
            "--format",
            "tsv",
            "--min-rows",
            "2",
            "--min-columns",
            "2",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    lines = captured.out.strip().splitlines()
    assert len(lines) >= 2
    assert "\t" in lines[1]
    assert lines[1].count("\t") >= 1


def test_table_scan_quiet_keeps_exit_status_and_suppresses_rows(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = tmp_path / "tables.bin"
    sample.write_bytes(b"1 2 3\n4 5 6\n")

    code = main(
        [
            "table-scan",
            str(sample),
            "--format",
            "json",
            "--min-rows",
            "2",
            "--min-columns",
            "2",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert captured.err == ""
