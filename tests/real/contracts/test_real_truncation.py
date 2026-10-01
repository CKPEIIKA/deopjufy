"""Truncated copies of public OPJ files must be reported, not passed as complete."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import main
from tests.test_core_unit_coverage_utils import _resolve_repo_fixture


def _public_opj() -> Path:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/test.opj")
    if not sample.exists():
        pytest.skip("Public Ropj OPJ fixture missing.")
    return sample


def _truncated_copy(tmp_path: Path) -> Path:
    data = _public_opj().read_bytes()
    target = tmp_path / "cut.opj"
    target.write_bytes(data[: len(data) // 2])
    return target


def test_inspect_reports_truncated_opj(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["inspect", str(_truncated_copy(tmp_path)), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 6
    assert "input-truncated" in {warning["code"] for warning in payload["parser_warnings"]}


def test_extract_reports_truncated_opj_as_partial(tmp_path: Path) -> None:
    outdir = tmp_path / "out"
    code = main(["extract", str(_truncated_copy(tmp_path)), "-o", str(outdir)])

    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    assert code == 6
    assert manifest["status"] == "partial"
    assert "input-truncated" in {warning["code"] for warning in manifest["parser_warnings"]}


def test_complete_opj_has_no_truncation_warning(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["inspect", str(_public_opj()), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "input-truncated" not in {warning["code"] for warning in payload["parser_warnings"]}
