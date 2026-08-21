"""Tests for image extraction command behavior."""

from __future__ import annotations

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


def test_images_quiet_suppresses_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "img.opju"
    sample.write_bytes(b"\x00\x00" + _VALID_PNG_1X1 + b"\x11\x11")

    code = main(
        [
            "images",
            str(sample),
            "-o",
            str(tmp_path / "out"),
            "--quiet",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""


def test_images_json_quiet_suppresses_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "img-json.opju"
    sample.write_bytes(_VALID_PNG_1X1)

    code = main(
        [
            "images",
            str(sample),
            "-o",
            str(tmp_path / "out-json"),
            "--json",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_images_rejects_unrecognized_file(tmp_path: Path) -> None:
    sample = tmp_path / "not_origin.txt"
    sample.write_text("random", encoding="utf-8")

    code = main(
        [
            "images",
            str(sample),
            "-o",
            str(tmp_path / "out"),
        ]
    )

    assert code == 3


def test_images_command_prints_relative_paths_when_not_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "img2.opju"
    sample.write_bytes(_VALID_PNG_1X1 + b"suffix")

    code = main(
        [
            "images",
            str(sample),
            "-o",
            str(tmp_path / "out"),
        ]
    )
    captured = capsys.readouterr()
    lines: list[str] = [line for line in captured.out.splitlines() if line]

    assert code == 0
    assert len(lines) == 1
    assert not Path(lines[0]).is_absolute()


def test_images_defaults_to_input_stem_output_directory(tmp_path: Path) -> None:
    sample = tmp_path / "image_default.opju"
    sample.write_bytes(_VALID_PNG_1X1 + b"suffix")

    code = main(
        [
            "images",
            str(sample),
        ]
    )

    assert code == 0
    assert (sample.with_suffix("")).exists()
    assert any(p.suffix == ".png" for p in (sample.with_suffix("")).iterdir())
