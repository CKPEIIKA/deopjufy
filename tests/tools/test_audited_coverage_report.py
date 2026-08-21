"""Coverage-report script contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_report(*paths: Path, json_out: bool = False, root: Path | None = None) -> str:
    cmd = [sys.executable, "tools/audited_coverage_report.py"]
    if json_out:
        cmd.append("--json")
    if root is not None:
        cmd.extend(["--root", str(root)])
    cmd.extend(str(path) for path in paths)
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stderr == ""
    return result.stdout


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_coverage_report_json_counts_manifest_paths(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "fixture_one" / "manifest.json",
        {
            "input": {"path": "sample.opj"},
            "items": [
                {"kind": "worksheet", "status": "extracted", "heuristic": False},
                {"kind": "worksheet", "status": "partial", "heuristic": True},
                {"kind": "matrix", "status": "unsupported", "heuristic": False},
                {"kind": "note", "status": "partial", "heuristic": False, "verification": "external-parity"},
                {"kind": "graph", "status": "error", "heuristic": False},
            ],
        },
    )

    _write_manifest(
        tmp_path / "fixture_two" / "manifest.json",
        {
            "input": {"path": "sample.opju"},
            "items": [
                {"kind": "worksheet", "status": "partial", "heuristic": True},
                {"kind": "image", "status": "extracted", "heuristic": False},
            ],
        },
    )

    output = _run_report(
        tmp_path / "fixture_one" / "manifest.json",
        tmp_path / "fixture_two" / "manifest.json",
        json_out=True,
        root=tmp_path,
    )
    payload = json.loads(output)
    fixtures = payload["fixtures"]
    assert len(fixtures) == 2
    fixture_one = next(item for item in fixtures if item["fixture"] == "fixture_one")
    worksheet_counts = {
        "kind": "worksheet",
        "discovered": 2,
        "extracted": 1,
        "partial": 1,
        "unsupported": 0,
        "heuristic": 1,
        "verified": 0,
    }
    matrix_counts = {
        "kind": "matrix",
        "discovered": 1,
        "extracted": 0,
        "partial": 0,
        "unsupported": 1,
        "heuristic": 0,
        "verified": 0,
    }
    graph_counts = {
        "kind": "graph",
        "discovered": 1,
        "extracted": 0,
        "partial": 0,
        "unsupported": 1,
        "heuristic": 0,
        "verified": 0,
    }
    note_counts = {
        "kind": "note",
        "discovered": 1,
        "extracted": 0,
        "partial": 1,
        "unsupported": 0,
        "heuristic": 0,
        "verified": 1,
    }
    assert worksheet_counts in fixture_one["families"]
    assert matrix_counts in fixture_one["families"]
    assert graph_counts in fixture_one["families"]
    assert note_counts in fixture_one["families"]


def test_coverage_report_text_output_and_mode_label_root(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "fixture_three" / "extended" / "manifest.json",
        {
            "input": {"path": "sample.opj"},
            "items": [
                {"kind": "worksheet", "status": "extracted", "heuristic": False},
            ],
        },
    )

    output = _run_report(tmp_path, root=tmp_path / "fixture_three")
    lines = output.splitlines()
    assert lines[0] == "fixture,kind,discovered,extracted,partial,unsupported,heuristic,verified"
    assert lines[1].startswith("fixture_three,worksheet")
