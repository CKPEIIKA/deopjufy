"""Tests for extract warning and support behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import main
from deopjufier.inventory import OriginObject
from deopjufier.session import ExtractionSession
from tests.test_core_unit_coverage_utils import _resolve_repo_fixture


def test_extract_defaults_to_input_stem_output_directory(tmp_path: Path) -> None:
    sample = tmp_path / "implicit.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"suffix")

    code = main(
        [
            "extract",
            str(sample),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
        ]
    )

    outdir = sample.with_suffix("")
    manifest = outdir / "manifest.json"
    assert code == 0
    assert manifest.exists()


def test_extract_raw_dir_with_large_min_size_emits_no_raw_blocks(tmp_path: Path) -> None:
    sample = tmp_path / "rawsample.opju"
    sample.write_bytes(b"\x00" * 500)

    outdir = tmp_path / "out"
    rawdir = tmp_path / "raw"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
            "--raw-dir",
            str(rawdir),
            "--raw-min-bytes",
            "1000",
        ]
    )

    manifest = outdir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert code == 0
    assert "No raw byte ranges met minimum size threshold." in payload["warnings"]
    assert "No raw blocks met export criteria." in payload["warnings"]
    assert len(list(rawdir.glob("*.bin"))) == 0


def test_extract_writes_manifest_to_requested_path(tmp_path: Path) -> None:
    sample = tmp_path / "rawsample.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    outdir = tmp_path / "out"
    manifest_path = tmp_path / "custom-manifest.json"
    rawdir = tmp_path / "raw"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
            "--raw-dir",
            str(rawdir),
            "--raw-min-bytes",
            "1",
            "--manifest",
            str(manifest_path),
        ]
    )

    assert code in {0, 4}
    assert manifest_path.exists()
    assert not (outdir / "manifest.json").exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["tool"]["backend"] == "native-parser"
    assert payload["input"]["path"] == str(sample)


def test_extract_no_steps_warns_and_marks_partial(tmp_path: Path) -> None:
    sample = tmp_path / "empty.opju"
    sample.write_bytes(b"\x00" * 128)

    outdir = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
        ]
    )
    manifest = outdir / "manifest.json"

    assert code == 0
    assert manifest.exists()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["warnings"] == ["No extraction step was enabled."]
    assert payload["status"] == "unsupported"


def test_extract_warning_only_absence_stays_ok_status(tmp_path: Path) -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/tree.opj")
    if not sample.exists():
        pytest.skip("Public OPJ fixture missing.")

    outdir = tmp_path / "warn_out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
        ]
    )
    assert code == 0

    manifest = outdir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["warnings"] == [
        "No matrix data emitted to matrix exports.",
        "No excel data emitted to excel exports.",
    ]

    # Warnings represent explicit unsupported families; they should remain informative
    # without flipping status to partial.
    assert payload["status"] != "partial"


def test_extract_does_not_warn_worksheet_when_no_worksheet_objects(tmp_path: Path) -> None:
    sample = tmp_path / "graph_only.opj"
    sample.write_bytes(b"CPYA 4.2673 552#\nGraph1\n")

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
        ]
    )

    manifest = outdir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert code == 0
    assert "No worksheet data emitted to book exports." not in payload["warnings"]
    assert all(item.get("kind") != "worksheet" for item in payload["items"])


def test_extract_writes_origin_object_inventory(tmp_path: Path) -> None:
    sample = tmp_path / "objects.opj"
    sample.write_bytes(b"CPYA\0Book1_A\0Graph1\0PdMSheet1\0")

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
        ]
    )

    manifest = outdir / "manifest.json"
    inventory = outdir / "metadata" / "origin_objects.json"

    assert code == 0
    assert manifest.exists()
    assert inventory.exists()

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))

    assert any(item["kind"] == "origin_object_inventory" for item in manifest_payload["items"])
    assert any(entry.get("name") == "Book1_A" for entry in inventory_payload)
    assert any(entry.get("name") == "Graph1" for entry in inventory_payload)


def test_extract_parser_only_disables_heuristic_object_scan_for_opju(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "parser-only.opju"
    sample.write_bytes(b"CPYUA" + b"\x00" * 128)

    outdir = tmp_path / "out"
    calls: list[bool] = []
    original_objects = ExtractionSession.objects

    def _track_collect_heuristics(
        self: ExtractionSession,
        *,
        collect_heuristics: bool = True,
        max_repeats_per_name: int | None = 2,
        include_redundant_tokens: bool = False,
        heuristic_kind_limit: int | None = None,
        allowed_kinds: frozenset[str] | None = None,
        total_limit: int | None = None,
    ) -> list[OriginObject]:
        calls.append(collect_heuristics)
        return original_objects(
            self,
            collect_heuristics=collect_heuristics,
            max_repeats_per_name=max_repeats_per_name,
            include_redundant_tokens=include_redundant_tokens,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
            total_limit=total_limit,
        )

    monkeypatch.setattr(
        "deopjufier.session.ExtractionSession.objects",
        _track_collect_heuristics,
    )

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--parser-only",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    assert code == 0
    assert calls
    assert all(call is False for call in calls)
