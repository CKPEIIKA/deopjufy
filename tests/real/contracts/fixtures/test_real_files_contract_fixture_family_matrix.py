"""Coverage-contract checks for audited OPJ/OPJU family extraction shape."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import cast

import pytest

from tests.real.fixtures.core.real_files_contract_core import REPO_ROOT

FIXTURE_MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "audited_fixture_family_matrix.json"
ZENODO_HASH_LOCK_PATH = REPO_ROOT / "tools" / "zenodo_fixtures.sha256"


def _zenodo_hash_lock() -> dict[str, str]:
    records: dict[str, str] = {}
    for line in ZENODO_HASH_LOCK_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        _record_id, filename, digest = line.split()
        assert digest != "-", f"Missing source hash for {filename}"
        records[filename] = digest
    return records


def _assert_tabular_artifact_matches_manifest(
    output_dir: Path,
    item: dict[str, object],
) -> None:
    if item.get("kind") not in {"worksheet", "matrix"}:
        return
    status = item.get("status")
    row_count = item.get("rows")
    name = str(item.get("name"))
    if status == "extracted" and not name.endswith("_collection"):
        assert isinstance(row_count, int), f"Extracted tabular artifact is missing row count: {name}"
        assert row_count > 0, f"Extracted tabular artifact has no rows: {name}"

    if status != "extracted" or not isinstance(row_count, int) or row_count <= 0:
        return

    relative_path = item.get("path")
    assert isinstance(relative_path, str) and relative_path
    artifact = output_dir / relative_path
    assert artifact.is_file(), f"Missing extracted artifact: {relative_path}"
    assert artifact.suffix == ".csv", f"Unexpected default tabular format: {relative_path}"

    with artifact.open("r", encoding="utf-8", newline="") as stream:
        records = list(csv.reader(stream))
    assert records, f"Empty extracted tabular artifact: {relative_path}"
    assert len(records) - 1 == item["rows"], (
        f"Manifest/file row mismatch for {relative_path}: manifest={item['rows']} file={len(records) - 1}"
    )
    provenance_header = ["table_id", "row_in_table", "offset", "columns", "values"]
    if records[0] != provenance_header:
        assert len(records[0]) == item["columns"], (
            f"Manifest/file logical-column mismatch for {relative_path}: "
            f"manifest={item['columns']} header={len(records[0])}"
        )
        assert all(len(record) == item["columns"] for record in records[1:]), (
            f"Ragged direct CSV rows for {relative_path}"
        )
        return

    for record in records[1:]:
        assert len(record) == 5, f"Malformed provenance CSV row: {relative_path}"
        assert int(record[3]) == item["columns"], (
            f"Manifest/file logical-column mismatch for {relative_path}: manifest={item['columns']} row={record[3]}"
        )
        assert len(record[4].split(";")) == item["columns"], f"Packed-value width mismatch for {relative_path}"


def test_public_zenodo_fixture_identity_and_audit_coverage() -> None:
    """Keep corpus breadth independent from parser-generated expectation files."""
    locked = _zenodo_hash_lock()
    matrix = json.loads(FIXTURE_MATRIX_PATH.read_text(encoding="utf-8"))
    public_dir = REPO_ROOT / "refs" / "public" / "zenodo"
    local_fixtures = sorted(
        path for path in public_dir.iterdir() if path.is_file() and path.suffix.lower() in {".opj", ".opju"}
    )
    assert local_fixtures, "Expected public Zenodo OPJ/OPJU fixtures"
    local_fixture_names = {path.name for path in local_fixtures}
    local_fixture_rels = {str(fixture.relative_to(REPO_ROOT)) for fixture in local_fixtures}

    matrix_public_refs = {fixture_rel for fixture_rel in matrix if fixture_rel.startswith("refs/public/zenodo/")}

    assert matrix_public_refs == local_fixture_rels, (
        "Audited fixture matrix drifted from refs/public/zenodo files:\n"
        f"extra in matrix: {sorted(matrix_public_refs - local_fixture_rels)}\n"
        f"missing in matrix: {sorted(local_fixture_rels - matrix_public_refs)}"
    )

    assert set(locked) == local_fixture_names, (
        "Zenodo fixture hash registry drifted from refs/public/zenodo files:\n"
        f"extra in lock: {sorted(set(locked) - local_fixture_names)}\n"
        f"missing in lock: {sorted(local_fixture_names - set(locked))}"
    )

    for fixture in local_fixtures:
        relative = str(fixture.relative_to(REPO_ROOT))
        assert fixture.name in locked, f"Fixture is not source-hash locked: {relative}"
        assert relative in matrix, f"Fixture is absent from the audited family matrix: {relative}"
        digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
        assert digest == locked[fixture.name], f"Fixture bytes differ from source lock: {relative}"


@pytest.mark.parametrize(
    ("fixture_rel", "expectation"),
    list(json.loads(FIXTURE_MATRIX_PATH.read_text(encoding="utf-8")).items()),
)
@pytest.mark.timeout(180)
def test_audited_fixture_family_matrix_contract(
    fixture_rel: str,
    expectation: dict[str, object],
    cached_extract,
):
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    result = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        with_raw_dir=True,
        raw_min_bytes=1024,
    )
    assert result.exit_code in {0, 4}

    payload = result.payload
    actual_family_counts = Counter(
        item.get("kind") for item in payload.get("items", []) if isinstance(item, dict) and item.get("kind") is not None
    )

    expected_families = cast(dict[str, int], expectation["families"])
    actual_families = set(actual_family_counts)
    expected_families_keys = {kind for kind, count in expected_families.items() if isinstance(count, int) and count > 0}
    assert actual_families == expected_families_keys, (
        f"{fixture_rel}: expected families {sorted(expected_families_keys)}; got {sorted(actual_families)}"
    )
    for family, expected_count in expected_families.items():
        assert actual_family_counts[family] == expected_count, (
            f"{fixture_rel}: expected {expected_count} {family} items, got {actual_family_counts[family]}"
        )

    assert payload["support_class"] == expectation["support_class"]
    assert payload["status"] == expectation["status"]
    actual_partial_items = sum(1 for item in payload["items"] if item.get("status") == "partial")
    actual_unsupported_items = sum(1 for item in payload["items"] if item.get("status") == "unsupported")
    actual_warning_count = len(payload.get("warnings", []))

    assert actual_partial_items == expectation["partial_items"]
    assert actual_unsupported_items == expectation["unsupported_items"]
    assert actual_warning_count == expectation["warning_count"]

    for item in payload.get("items", []):
        if isinstance(item, dict):
            _assert_tabular_artifact_matches_manifest(result.output_dir, item)
