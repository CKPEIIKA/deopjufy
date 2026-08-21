"""Regression tests for real OPJ/OPJU targets present in this repository."""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from deopjufier.cli import main
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))


def _public_opju_report_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju"
    if sample.exists():
        return sample
    pytest.skip("Public OPJU fixture is not available in this checkout.")


def _public_opju_worksheet_gap_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10364693-ahrrenius-ybscsz.opju"
    if sample.exists():
        return sample
    pytest.skip("Public OPJU fixture is not available in this checkout.")


def _public_opju_graph_gap_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-18450855-eucd2p2.opju"
    if sample.exists():
        return sample
    pytest.skip("Public OPJU fixture is not available in this checkout.")


def _public_opju_pdf_attachment_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-18450855-eucd2p2.opju"
    if sample.exists():
        return sample
    pytest.skip("Public OPJU fixture is not available in this checkout.")


def _public_opju_jpg_attachment_sample() -> Path:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-19549171-small-science-paper.opju"
    if sample.exists():
        return sample
    pytest.skip("Public OPJU fixture is not available in this checkout.")


def _synthetic_opju_pdf_attachment_fixture() -> Path:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-opju-attachment-pdf.opju"
    if sample.exists():
        return sample
    pytest.skip("Synthetic OPJU PDF attachment fixture is not available.")


def _synthetic_opju_docx_attachment_fixture() -> Path:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-opju-attachment-docx.opju"
    if sample.exists():
        return sample
    pytest.skip("Synthetic OPJU DOCX attachment fixture is not available.")


def _project_id(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


REAL_GRAPH_FIXTURE_PATHS = [
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
    REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "openopj" / "support" / "test.opj",
]


def _assert_unsupported_collection(
    payload: dict[str, Any],
    kind: str,
    name: str,
    error: str,
) -> None:
    unsupported_collections = [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict)
        and item.get("kind") == kind
        and item.get("name") == name
        and item.get("status") == "unsupported"
        and item.get("error") == error
    ]
    assert unsupported_collections, f"Expected unsupported collection item for kind={kind} name={name} error={error}"


REAL_PROJECTS = [
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
    REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "test.opj",
]
REAL_SMOKE_PROJECTS = [
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
    REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "tree.opj",
    REPO_ROOT / "refs" / "openopj" / "support" / "test.opj",
    REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
    REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10364693-ahrrenius-ybscsz.opju",
    REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-18450855-eucd2p2.opju",
    REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-19549171-small-science-paper.opju",
]
REAL_PROJECTS = [path for path in dict.fromkeys(REAL_PROJECTS) if path.exists()]
REAL_SMOKE_PROJECTS = [path for path in dict.fromkeys(REAL_SMOKE_PROJECTS) if path.exists()]
LIGHT_REAL_PROJECTS = list(REAL_PROJECTS)


def _run_list(path: Path) -> tuple[int, dict]:
    stdout = StringIO()
    with redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(["list", str(path), "--json"])
    payload = json.loads(stdout.getvalue())
    return code, payload


if not REAL_PROJECTS:
    pytest.skip("No real OPJ/OPJU fixtures available for smoke coverage.", allow_module_level=True)


def _run_inspect(path: Path) -> tuple[int, dict]:
    stdout = StringIO()
    with redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(["inspect", str(path), "--json"])
    payload = json.loads(stdout.getvalue())
    return code, payload


def _run_extract_manifest(sample: Path, cached_extract: Any, *extra_args: str) -> dict[str, Any]:
    run = cached_extract(sample, "--no-strings", "--no-tables", *extra_args)
    assert run.exit_code in {0, 4}
    return run.payload
