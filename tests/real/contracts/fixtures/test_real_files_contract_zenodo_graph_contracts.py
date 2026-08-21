"""Zenodo-family graph-family unsupported collection contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.real.fixtures.core.real_files_contract_core import (
    REPO_ROOT,
    _assert_unsupported_collection,
    _run_extract_manifest,
)


def _zenodo_lock_graph_collection_contracts() -> list[tuple[Path, str, str, str]]:
    lock_path = REPO_ROOT / "tests" / "fixtures" / "ref-extract-status-lock.json"
    if not lock_path.exists():
        return []

    lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
    records = lock_payload.get("records", [])

    collection_name_by_kind = {
        "graph": "graph_collection",
        "graph_preview": "graph_preview_collection",
    }

    entries: set[tuple[str, str, str, str]] = set()
    for record in records:
        path = record.get("path", "")
        if not isinstance(path, str) or "refs/public/zenodo/" not in path:
            continue
        for artifact in record.get("artifact_histogram", []):
            kind = artifact.get("kind")
            if kind not in collection_name_by_kind:
                continue
            if artifact.get("status") != "unsupported":
                continue
            error = artifact.get("error")
            if not isinstance(error, str):
                continue
            entries.add((path, kind, collection_name_by_kind[kind], error))

    return sorted((REPO_ROOT / entry[0], entry[1], entry[2], entry[3]) for entry in entries)


@pytest.mark.parametrize(
    ("sample", "kind", "name", "error"),
    _zenodo_lock_graph_collection_contracts(),
)
def test_zenodo_graph_contracts_keep_unsupported_collections_visible(
    sample: Path,
    kind: str,
    name: str,
    error: str,
    cached_extract,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    payload = _run_extract_manifest(sample, cached_extract, "--no-images")
    _assert_unsupported_collection(payload=payload, kind=kind, name=name, error=error)
