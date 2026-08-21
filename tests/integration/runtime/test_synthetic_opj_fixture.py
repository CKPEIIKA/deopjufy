"""Regression test for the synthetic OPJ fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from deopjufier.cli import main
from deopjufier.detect import detect_file
from tests.test_core_unit_coverage_utils import (
    _resolve_synthetic_fixture,
    _resolve_tests_fixture,
)

SYNTHETIC_OPJ_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-opj-multi-family.opj")
CONTRACT_PATH = _resolve_tests_fixture(
    Path(__file__), Path("fixtures") / "synthetic" / "synthetic-opj-multi-family.contract.json"
)


def _load_contract() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _assert_manifest_item(actual: dict[str, object], expected: dict[str, object]) -> None:
    for key, expected_value in expected.items():
        if key == "sha256":
            continue
        assert key in actual
        assert actual[key] == expected_value


def test_synthetic_opj_multi_family_fixture_can_be_detected_and_extracted(tmp_path: Path) -> None:
    assert SYNTHETIC_OPJ_FIXTURE.exists()
    detected = detect_file(SYNTHETIC_OPJ_FIXTURE)
    assert detected.detected_type == "opj"
    assert detected.reason == "extension"
    assert detected.magic_type == "opj"

    output = tmp_path / "synthetic-opj-multi-family-out"
    output.mkdir(parents=True, exist_ok=True)
    code = main(
        [
            "extract",
            str(SYNTHETIC_OPJ_FIXTURE),
            "-o",
            str(output),
            "--extended",
            "--no-images",
            "--no-strings",
        ]
    )
    assert code in {0, 4}
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    note_items = [item for item in manifest["items"] if item.get("kind") == "note" and item.get("name") == "Note1"]
    function_items = [
        item for item in manifest["items"] if item.get("kind") == "function" and item.get("name") == "Function1"
    ]
    assert len(note_items) == 1
    assert len(function_items) == 1

    note_path = output / note_items[0]["path"]
    function_path = output / function_items[0]["path"]
    assert note_path.exists()
    assert function_path.exists()
    assert note_items[0]["status"] == "extracted"
    assert function_items[0]["status"] == "extracted"


def test_synthetic_opj_multi_family_fixture_matches_fixture_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if not SYNTHETIC_OPJ_FIXTURE.exists():
        pytest.skip("synthetic OPJ fixture missing.")
    if not CONTRACT_PATH.exists():
        pytest.skip("synthetic OPJ contract missing.")

    contract = _load_contract()
    list_expectation = cast(dict[str, object], contract["list"])
    extract_expectation = cast(dict[str, object], contract["extract"])

    list_code = main(["list", str(SYNTHETIC_OPJ_FIXTURE), "--json"])
    assert list_code == 0
    list_payload = json.loads(capsys.readouterr().out)

    assert list_payload["detected_type"] == list_expectation["detected_type"]
    assert (
        len([item for item in list_payload["items"] if item.get("kind") == "origin_object"])
        == list_expectation["origin_object_count"]
    )

    expected_origin_objects = {
        item["name"]: item for item in cast(list[dict[str, object]], list_expectation["origin_objects"])
    }
    origin_object_items = [item for item in list_payload["items"] if item.get("kind") == "origin_object"]
    observed_kind_counts: dict[str, int] = {}

    for item in origin_object_items:
        expected_item = expected_origin_objects[item["name"]]
        for field in ("name", "object_kind", "offset", "length", "source_object_path"):
            assert item[field] == expected_item[field]
        observed_kind_counts[item["object_kind"]] = observed_kind_counts.get(item["object_kind"], 0) + 1

    assert observed_kind_counts == list_expectation["object_kind_counts"]

    output = tmp_path / "synthetic-opj-multi-family-contract-out"
    output.mkdir(parents=True, exist_ok=True)
    extract_code = main(
        [
            "extract",
            str(SYNTHETIC_OPJ_FIXTURE),
            "-o",
            str(output),
            "--extended",
            "--no-images",
            "--no-strings",
        ]
    )
    assert extract_code in {0, 4}
    extract_payload = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    expected_items = {
        (item["kind"], item["name"]): item
        for item in cast(list[dict[str, object]], extract_expectation["required_items"])
    }
    for (kind, name), expected_item in expected_items.items():
        match = [item for item in extract_payload["items"] if item.get("kind") == kind and item.get("name") == name]
        assert match, f"missing manifest item for {(kind, name)}"
        actual_item = match[0]
        _assert_manifest_item(actual_item, expected_item)

        expected_path = expected_item.get("path")
        expected_sha = expected_item.get("sha256")
        if isinstance(expected_path, str) and expected_path != "":
            artifact_path = output / expected_path
            assert artifact_path.exists()
            if expected_sha is not None:
                actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                assert actual_sha == expected_sha
