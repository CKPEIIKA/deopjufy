"""Tests for the compare command and manifest diff helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deopjufier.cli import main
from deopjufier.compare import compare_manifests


def _write_manifest(path: Path, *, status: str, items: list[dict[str, Any]]) -> None:
    payload = {
        "input": {
            "path": "sample.opj",
            "size_bytes": 0,
            "sha256": "placeholder",
            "detected_type": "opj",
        },
        "tool": {
            "name": "deopjufy",
            "version": "test",
            "backend": "native-parser",
        },
        "status": status,
        "items": items,
        "warnings": [],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_compare_command_returns_match_for_equal_manifests(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    left_items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/Book1",
            "path": "books/Book1/table.csv",
        }
    ]
    right_items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/Book1",
            "path": "books/Book1/table.csv",
        }
    ]
    _write_manifest(left / "manifest.json", status="ok", items=left_items)
    _write_manifest(right / "manifest.json", status="ok", items=right_items)

    code = main(["compare", str(left), str(right), "--json"])
    assert code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["match"] is True
    assert payload["left"]["item_count"] == 1
    assert payload["right"]["item_count"] == 1
    assert payload["summary"]["left_items"] == 1


def test_compare_default_output_is_human_readable(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/Book1",
            "path": "books/Book1/table.csv",
        }
    ]
    _write_manifest(left / "manifest.json", status="ok", items=items)
    _write_manifest(right / "manifest.json", status="ok", items=items)

    code = main(["compare", str(left), str(right)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    assert captured.out.startswith("left=")


def test_compare_command_reports_missing_and_byte_differences(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    left_books = left / "books" / "Book1"
    right_books = right / "books" / "Book1"
    left_books.mkdir(parents=True)
    right_books.mkdir(parents=True)

    (left_books / "table.csv").write_text("1,2,3\n", encoding="utf-8")
    (right_books / "table.csv").write_text("1,2,4\n", encoding="utf-8")

    left_items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/Book1",
            "path": "books/Book1/table.csv",
        }
    ]
    right_items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/Book1",
            "path": "books/Book1/table.csv",
        }
    ]
    _write_manifest(left / "manifest.json", status="ok", items=left_items)
    _write_manifest(right / "manifest.json", status="ok", items=right_items)

    code = main(["compare", str(left), str(right), "--compare-bytes", "--json"])
    assert code != 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["match"] is False
    assert payload["mismatches"]["files"], "expected file comparison differences"
    assert any(
        entry["status"]
        in {
            "hash_mismatch",
            "table_text_mismatch",
            "table_numeric_mismatch",
            "table_shape_mismatch",
            "table_read_error",
        }
        for entry in payload["mismatches"]["files"]
    )


def test_compare_command_reports_table_shape_mismatch(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    left_books = left / "books" / "Book1"
    right_books = right / "books" / "Book1"
    left_books.mkdir(parents=True)
    right_books.mkdir(parents=True)

    (left_books / "table.csv").write_text("1,2,3\n4,5,6\n", encoding="utf-8")
    (right_books / "table.csv").write_text("1,2,3\n", encoding="utf-8")

    items = [
        {
            "kind": "worksheet",
            "name": "Book1",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/Book1",
            "path": "books/Book1/table.csv",
        }
    ]
    _write_manifest(left / "manifest.json", status="ok", items=items)
    _write_manifest(right / "manifest.json", status="ok", items=items)

    code = main(["compare", str(left), str(right), "--compare-bytes", "--json"])
    assert code != 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["match"] is False
    assert any(entry["status"] == "table_shape_mismatch" for entry in payload["mismatches"]["files"])


def test_compare_api_handles_direct_manifests_and_counts_payload_signatures(
    tmp_path: Path,
) -> None:
    left = tmp_path / "deopjufy-left-manifest.json"
    right = tmp_path / "deopjufy-right-manifest.json"

    left.write_text(
        json.dumps(
            {
                "input": {
                    "path": "sample.opj",
                    "size_bytes": 0,
                    "sha256": "placeholder",
                    "detected_type": "opj",
                },
                "tool": {
                    "name": "deopjufy",
                    "version": "test",
                    "backend": "native-parser",
                },
                "status": "ok",
                "items": [{"kind": "worksheet", "name": "left", "status": "extracted", "path": "a.csv"}],
                "warnings": [],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    right.write_text(
        json.dumps(
            {
                "input": {
                    "path": "sample.opj",
                    "size_bytes": 0,
                    "sha256": "placeholder",
                    "detected_type": "opj",
                },
                "tool": {
                    "name": "deopjufy",
                    "version": "test",
                    "backend": "native-parser",
                },
                "status": "ok",
                "items": [{"kind": "worksheet", "name": "right", "status": "partial", "path": "b.csv"}],
                "warnings": [],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    try:
        result = compare_manifests(left, right)
    finally:
        left.unlink(missing_ok=True)
        right.unlink(missing_ok=True)

    assert result["match"] is False
    assert result["left"]["path"].endswith("deopjufy-left-manifest.json")
    assert len(result["mismatches"]["manifest_signatures"]) == 2


def test_compare_command_treats_missing_both_artifacts_as_matching_when_dirs_match(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    left_items = [
        {
            "kind": "table_scan",
            "name": "SharedOnly",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "shared/only",
            "path": "missing_dir/scan.csv",
        }
    ]
    right_items = [
        {
            "kind": "table_scan",
            "name": "SharedOnly",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "shared/only",
            "path": "missing_dir/scan.csv",
        }
    ]
    _write_manifest(left / "manifest.json", status="ok", items=left_items)
    _write_manifest(right / "manifest.json", status="ok", items=right_items)

    result = compare_manifests(left, right, compare_bytes=True)
    assert result["match"] is True


def test_compare_command_reports_unmatched_files_by_side(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    left_files = left / "tables"
    left_files.mkdir()
    (right / "tables").mkdir()

    (left_files / "only_left.csv").write_text("1,2,3\n", encoding="utf-8")

    left_items = [
        {
            "kind": "worksheet",
            "name": "OnlyLeft",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/OnlyLeft",
            "path": "tables/only_left.csv",
        }
    ]
    right_items = [
        {
            "kind": "worksheet",
            "name": "OnlyRight",
            "status": "extracted",
            "confidence": 0.8,
            "source_object_path": "book/OnlyRight",
            "path": "tables/only_right.csv",
        }
    ]
    _write_manifest(left / "manifest.json", status="ok", items=left_items)
    _write_manifest(right / "manifest.json", status="ok", items=right_items)

    code = main(["compare", str(left), str(right), "--compare-bytes", "--json"])
    assert code != 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    statuses = {entry["status"] for entry in payload["mismatches"]["files"]}
    assert "missing_in_right" in statuses
    assert "missing_in_left" in statuses
