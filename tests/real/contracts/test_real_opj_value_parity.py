"""Value-parity checks for real OPJ fixtures against committed `opj2dat` output."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter
from itertools import zip_longest
from math import isfinite, isnan
from pathlib import Path
from typing import Any

import pytest

from deopjufier.cli import main
from tests.test_core_unit_coverage_utils import _repo_root

ROOT = _repo_root(Path(__file__))

DUPLICATE_OPJ_FIXTURE_PAIRS: tuple[tuple[str, str], ...] = (
    ("refs/github/Ropj/inst/test.opj", "refs/ropj/src/Ropj/inst/test.opj"),
    ("refs/github/Ropj/inst/tree.opj", "refs/ropj/src/Ropj/inst/tree.opj"),
)

_SPREADSHEET_INDEX_RE = re.compile(r"^Spreadsheet\s+(\d+)")
_SPREADSHEET_NAME_RE = re.compile(r"^\s*Name:\s*(.*)$")
_SAVED_TO_RE = re.compile(r"^\s*saved to .*?([^/\\]+\.opj\.(\d+)\.dat)\s*$")


@pytest.fixture
def _ground_truth_dirs() -> dict[str, Path]:
    return {
        "refs/github/Ropj/inst/test.opj": ROOT / "tests" / "groundtruth" / "github-Ropj-inst-test.opj",
        "refs/github/Ropj/inst/tree.opj": ROOT / "tests" / "groundtruth" / "github-Ropj-inst-tree.opj",
        "refs/openopj/support/test.opj": ROOT / "tests" / "groundtruth" / "openopj-support-test.opj",
    }


def _parse_ground_truth_tables(log_path: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    table_dir = log_path.parent

    pending_name: str | None = None
    pending_index: str | None = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if match := _SPREADSHEET_INDEX_RE.match(line.strip()):
            pending_index = match.group(1)
            continue

        if (match := _SPREADSHEET_NAME_RE.match(line.strip())) and pending_index:
            pending_name = match.group(1).strip()
            continue

        if (match := _SAVED_TO_RE.match(line.strip())) and pending_name is not None:
            idx = match.group(2)
            candidates = sorted(table_dir.glob(f"*.opj.{idx}.dat"))
            if not candidates:
                # Historical fixtures sometimes name rows differently.
                candidates = sorted(table_dir.glob(f"*{idx}.dat"))
            if not candidates:
                # Keep deterministic failure at call-site.
                continue
            mapping[pending_name] = candidates[0]
            pending_name = None
            pending_index = None

    return mapping


def _read_separated_rows(path: Path, *, delimiter: str) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, skipinitialspace=True)
        rows: list[list[str]] = []
        for row in reader:
            rows.append([cell.strip() for cell in row])
    return rows


def _is_sentinel_like(value: float) -> bool:
    if isnan(value):
        return True
    absolute = abs(value)
    return absolute > 1.0e30 or (0.0 < absolute < 1.0e-300)


def _extract_manifest(sample: Path, output_dir: Path) -> dict[str, Any]:
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output_dir),
            "--extended",
            "--no-images",
            "--no-strings",
        ]
    )
    assert code in {0, 4}

    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _manifest_signature(payload: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    signature = Counter[tuple[Any, ...]]()
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        key = (
            item.get("kind"),
            item.get("name"),
            item.get("status"),
            item.get("error"),
            item.get("rows"),
            item.get("columns"),
            item.get("heuristic"),
            item.get("source_object_path"),
            item.get("discovery_type"),
        )
        signature[key] += 1
    return signature


def _artifact_file_hashes(output_dir: Path, payload: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    hashes: dict[tuple[str, str, str], str] = {}
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "extracted":
            continue
        path_value = item.get("path")
        kind = item.get("kind")
        name = item.get("name")
        if not isinstance(path_value, str) or not isinstance(kind, str) or not isinstance(name, str):
            continue
        if kind in {"raw_dump", "text_region", "raw_gap", "table_scan"}:
            continue
        artifact_path = output_dir / path_value
        if not artifact_path.exists():
            continue
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        hashes[(kind, name, path_value)] = digest
    return hashes


def _normalize_cell(value: str) -> float | str | None:
    text = value.strip()
    if not text or text.lower() == "nan":
        return None

    try:
        parsed = float(text)
        if not isfinite(parsed) or _is_sentinel_like(parsed):
            return None
        return parsed
    except ValueError:
        return text


def _cells_match(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, float) and isinstance(right, float):
        if math.isnan(left) and math.isnan(right):
            return True
        return math.isclose(left, right, rel_tol=5e-6, abs_tol=5e-7)
    return left == right


@pytest.mark.parametrize(
    ("fixture_rel", "expected_table_count"),
    [
        ("refs/github/Ropj/inst/test.opj", 1),
        ("refs/openopj/support/test.opj", 6),
    ],
)
def test_real_opj_spreadsheet_value_parity(
    fixture_rel: str,
    expected_table_count: int,
    _ground_truth_dirs: dict[str, Path],
    tmp_path: Path,
) -> None:
    fixture = ROOT / fixture_rel
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    ground_truth_dir = _ground_truth_dirs[fixture_rel]
    out_log = ground_truth_dir / "opj2dat.out"
    assert out_log.exists(), f"ground-truth log missing: {out_log}"

    expected_tables = _parse_ground_truth_tables(out_log)
    assert len(expected_tables) == expected_table_count, f"ground-truth tables missing: {out_log}"

    output_dir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(fixture),
            "-o",
            str(output_dir),
            "--extended",
            "--no-images",
            "--no-strings",
        ]
    )
    assert code in {0, 4}

    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    worksheet_paths = {
        item["name"]: output_dir / item["path"]
        for item in manifest.get("items", [])
        if item.get("kind") == "worksheet"
        and isinstance(item.get("path"), str)
        and not str(item.get("name", "")).endswith("_collection")
    }

    for expected_name, expected_dat_path in expected_tables.items():
        expected_rows = _read_separated_rows(expected_dat_path, delimiter=";")
        if len(expected_rows) <= 1:
            # Header-only sheets are asserted by the exact semantic inventory;
            # they must not cause a fake CSV artifact to be emitted.
            assert expected_name not in worksheet_paths
            continue
        if expected_name not in worksheet_paths:
            raise AssertionError(f"Missing worksheet extraction for {expected_name!r} in {fixture_rel}")

        expected_normalized_rows: list[list[object]] = [
            [_normalize_cell(cell) for cell in row] for row in expected_rows
        ]

        extracted_path = worksheet_paths[expected_name]
        assert extracted_path.exists()
        extracted_rows = _read_separated_rows(extracted_path, delimiter=",")

        assert extracted_rows
        assert expected_rows
        if len(extracted_rows[0]) < len(expected_normalized_rows[0]) and all(
            not cell for cell in expected_rows[0][len(extracted_rows[0]) :]
        ):
            extracted_rows[0] = extracted_rows[0] + [""] * (len(expected_normalized_rows[0]) - len(extracted_rows[0]))

        assert len(extracted_rows[0]) == len(expected_normalized_rows[0])

        expected_data_rows = expected_normalized_rows[1:]
        if not expected_data_rows:
            # opj2dat ground truth for this sheet has no payload rows.
            # We keep the header check so extraction stays deterministic, but
            # we cannot assert per-cell parity.
            continue

        expected_header = [cell for cell in expected_rows[0]]
        assert [cell.strip() for cell in extracted_rows[0]] == expected_header

        extracted_data_rows = extracted_rows[1:]
        assert len(extracted_data_rows) == len(expected_data_rows), (
            f"Row count mismatch for {expected_name!r}: extracted={len(extracted_rows) - 1}"
            f" expected={len(expected_rows) - 1}"
        )

        for row_index, (
            extracted_row,
            raw_expected_row,
            normalized_expected_row,
        ) in enumerate(
            zip_longest(
                extracted_data_rows,
                expected_rows[1:],
                expected_normalized_rows[1:],
                fillvalue=None,
            ),
            start=2,
        ):
            if extracted_row is None or raw_expected_row is None or normalized_expected_row is None:
                raise AssertionError(f"Unexpected row count mismatch for {expected_name!r} at row {row_index}")
            extracted_row_values = list(extracted_row)

            expected_row = list(normalized_expected_row)
            if len(extracted_row_values) < len(expected_row) and all(
                cell is None for cell in expected_row[len(extracted_row_values) :]
            ):
                extracted_row_values = extracted_row_values + [""] * (len(expected_row) - len(extracted_row_values))
            if len(raw_expected_row) > len(extracted_row_values):
                extracted_row_values = extracted_row_values + [""] * (len(raw_expected_row) - len(extracted_row_values))
            if len(extracted_row_values) != len(expected_row):
                raise AssertionError(
                    f"Column count mismatch in {expected_name!r} row {row_index}:"
                    f" extracted={len(extracted_row_values)} expected={len(expected_row)}"
                )

            for col_index, (left, right) in enumerate(
                zip(extracted_row_values, expected_row, strict=False),
                start=1,
            ):
                if expected_name == "TestW" and col_index >= 4:
                    # liborigin reads these 4-byte Float/Long/Integer columns
                    # through its 8-byte generic worksheet path. Its NaN/zero
                    # output is not an independent value oracle for them.
                    continue
                if not _cells_match(_normalize_cell(left), right):
                    raise AssertionError(
                        f"Value mismatch in {expected_name!r} row {row_index} col {col_index}:"
                        f" extracted={left!r} expected={right!r}"
                    )


def test_openopj_fixture_has_exact_semantic_table_inventory(tmp_path: Path) -> None:
    fixture = ROOT / "refs" / "openopj" / "support" / "test.opj"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    manifest = _extract_manifest(fixture, tmp_path / "openopj")
    worksheets = {
        item["name"]: (item["status"], item.get("rows"), item.get("columns"))
        for item in manifest["items"]
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    }
    matrices = {
        item["name"]: (item["status"], item.get("rows"), item.get("columns"))
        for item in manifest["items"]
        if item.get("kind") == "matrix" and not str(item.get("name", "")).endswith("_collection")
    }

    assert worksheets == {
        "Data1": ("extracted", 901, 8),
        "Data1Coeff": ("extracted", 774, 5),
        "Data1RAW": ("extracted", 750, 2),
        "Data1spline": ("extracted", 481, 2),
        "TestE": ("partial", 0, 12),
        "TestW": ("extracted", 45, 6),
    }
    assert matrices == {
        "TestM": ("extracted", 32, 32),
        "mRawITC": ("partial", 0, 0),
    }


def test_ropj_fixture_recovers_workbook_sheets_without_duplicate_objects(tmp_path: Path) -> None:
    fixture = ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    manifest = _extract_manifest(fixture, tmp_path / "ropj")
    semantic_items = [
        (item.get("kind"), item.get("name"), item.get("status"), item.get("rows"), item.get("columns"))
        for item in manifest["items"]
        if item.get("kind") in {"worksheet", "excel", "matrix"}
        and not str(item.get("name", "")).endswith("_collection")
    ]

    assert semantic_items == [
        ("worksheet", "Book2", "extracted", 32, 3),
        ("excel", "Book1/Sheet1", "extracted", 32, 2),
        ("excel", "Book1/Sheet2", "extracted", 32, 2),
        ("matrix", "MSheet1", "extracted", 32, 32),
    ]


def test_tree_fixture_exports_exact_binary_project_hierarchy(tmp_path: Path) -> None:
    fixture = ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    manifest = _extract_manifest(fixture, tmp_path / "tree")
    binary_items = [
        item
        for item in manifest["items"]
        if item.get("kind") == "project_tree" and item.get("discovery_type") == "opj_binary_project_tree"
    ]
    assert len(binary_items) == 12

    graph_item = next(item for item in binary_items if item.get("name") == "Graph1")
    assert graph_item["path"] == "tree/tree/1 bla bla bla text with spaces/Graph1/node.json"
    graph_node = json.loads((tmp_path / "tree" / graph_item["path"]).read_text(encoding="utf-8"))
    assert graph_node["kind"] == "window"
    assert graph_node["object_id"] == 0
    assert graph_node["parent_path"] == "tree/1 bla bla bla text with spaces"
    assert graph_node["parser_rule"] == "opj_binary_project_tree"


def test_tree_fixture_exports_native_graph_structure_without_claiming_a_preview(tmp_path: Path) -> None:
    fixture = ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    output_dir = tmp_path / "graph"
    code = main(["extract", str(fixture), "-o", str(output_dir), "--extended", "--no-strings"])
    assert code in {0, 4}

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    graph = next(item for item in manifest["items"] if item.get("kind") == "graph" and item.get("name") == "Graph1")
    assert graph["status"] == "partial"
    assert graph["error"] == "graph_definition_partial"

    metadata_item = next(
        item
        for item in manifest["items"]
        if item.get("kind") == "graph_metadata" and item.get("name") == "Graph1_metadata"
    )
    metadata = json.loads((output_dir / metadata_item["path"]).read_text(encoding="utf-8"))
    assert metadata["parsed_graph_attributes"] == [
        "axis_ranges",
        "data_binding",
        "series_metadata",
        "template_settings",
    ]
    assert metadata["unsupported_graph_attributes"] == ["legend_configuration", "style_attributes"]
    semantics = metadata["opj_semantics"]
    assert semantics["name"] == "Graph1"
    assert semantics["layers"][0]["x_range"] == [-1.0, 7.0, 1.0]
    assert semantics["curves"][0]["data_name"] == "F1"


@pytest.mark.parametrize(("left_fixture_rel", "right_fixture_rel"), DUPLICATE_OPJ_FIXTURE_PAIRS)
def test_real_opj_duplicate_payloads_maintain_manifest_parity(
    left_fixture_rel: str,
    right_fixture_rel: str,
    tmp_path: Path,
) -> None:
    left_fixture = ROOT / left_fixture_rel
    right_fixture = ROOT / right_fixture_rel
    if not left_fixture.exists():
        pytest.skip(f"fixture missing: {left_fixture}")
    if not right_fixture.exists():
        pytest.skip(f"fixture missing: {right_fixture}")

    left_output = tmp_path / "left"
    right_output = tmp_path / "right"

    left_payload = _extract_manifest(left_fixture, left_output)
    right_payload = _extract_manifest(right_fixture, right_output)

    assert _manifest_signature(left_payload) == _manifest_signature(right_payload)
    assert _artifact_file_hashes(left_output, left_payload) == _artifact_file_hashes(right_output, right_payload)
