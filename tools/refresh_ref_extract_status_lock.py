#!/usr/bin/env python3
"""Regenerate the OPJ/OPJU extract status lock from live `extract` runs."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from deopjufier import APP_NAME
from deopjufier.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
REFS_DIR = ROOT / "refs"
STATUS_LOCK_PATH = FIXTURES_DIR / "ref-extract-status-lock.json"
COMMAND_ARGS = ["--no-images", "--no-strings"]
PUBLIC_REFERENCE_ROOTS = (
    REFS_DIR / "public",
    REFS_DIR / "github" / "Ropj" / "inst",
    REFS_DIR / "ropj" / "src" / "Ropj" / "inst",
    REFS_DIR / "openopj" / "support",
)
_TREE_MATRIX_MARKER_PATH_RE = re.compile(r"^MBook\d+/MSheet\d+(?:__\d+)?$", re.IGNORECASE)


def _is_tree_matrix_reference_marker(value: str | None, item_name: str | None = None) -> bool:
    return bool(value and _TREE_MATRIX_MARKER_PATH_RE.match(value)) or bool(
        item_name and _TREE_MATRIX_MARKER_PATH_RE.match(item_name)
    )


def _discover_ref_targets(refs_root: Path) -> Iterator[Path]:
    yield from sorted(
        path
        for path in refs_root.rglob("*")
        if path.suffix.lower() in {".opj", ".opju"}
        and any(path.is_relative_to(root) for root in PUBLIC_REFERENCE_ROOTS)
    )


def _collection_path(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _artifact_histogram(
    items: list[dict[str, object]],
    detected_type: str,
) -> tuple[list[dict[str, object]], int, int]:
    counts: Counter[tuple[str, str, str | None]] = Counter()
    partial_count = 0
    unsupported_count = 0

    def _is_scoped_gap(
        artifact_type: str | None,
        item_kind: str | None,
        item_status: str,
        item_error: str | None,
        item_name: str | None = None,
        source_object_path: str | None = None,
    ) -> bool:
        if artifact_type == "opj":
            if (
                item_kind == "matrix"
                and item_status == "partial"
                and item_error == "no_extracted_table_rows"
                and _is_tree_matrix_reference_marker(source_object_path, item_name)
            ):
                return True
            if item_kind == "excel" and item_status == "unsupported":
                return item_error == "no_excel_objects"
            if item_kind == "note" and item_status == "unsupported":
                return item_error == "no_note_objects"
            if (
                item_kind == "worksheet"
                and item_status == "unsupported"
                and item_error == "no_extracted_table_rows"
                and source_object_path == "book_collection"
            ):
                return True
        if artifact_type == "opju":
            if item_kind == "note" and item_status == "unsupported" and item_error == "no_note_objects":
                return True
            if (
                item_kind == "origin_storage_report"
                and item_status == "partial"
                and item_error == "no_origin_storage_reports"
            ):
                return True
        if item_kind == "graph":
            return item_status == "unsupported" and item_error in {
                "no_graph_previews",
                "no_embedded_image_block",
            }
        if item_kind == "graph_preview":
            return item_status in {"partial", "unsupported"} and item_error == "no_embedded_image_block"
        if artifact_type == "opj":
            return (
                item_kind == "origin_storage_report"
                and item_status == "unsupported"
                and item_error == "no_origin_storage_reports"
            )
        return False

    for item in items:
        status = item.get("status")
        if not isinstance(status, str):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str):
            continue
        error = item.get("error")
        if error is not None and not isinstance(error, str):
            continue
        name = item.get("name")
        source_object_path = item.get("source_object_path")
        if not isinstance(name, str):
            name = None
        if not isinstance(source_object_path, str):
            source_object_path = None

        if _is_scoped_gap(detected_type, kind, status, error, item_name=name, source_object_path=source_object_path):
            continue

        if status == "partial" and kind != "table_scan":
            partial_count += 1
        elif status == "unsupported":
            unsupported_count += 1
        if status == "extracted":
            continue
        counts[(kind, status, error)] += 1

    histogram: list[dict[str, object]] = [
        {"kind": kind, "status": status, "error": error, "count": count}
        for (kind, status, error), count in sorted(counts.items())
    ]
    return histogram, partial_count, unsupported_count


def _to_record(project: Path, out_dir: Path) -> dict[str, object]:
    code = cli_main(
        [
            "extract",
            str(project),
            "-o",
            str(out_dir),
            *COMMAND_ARGS,
        ]
    )
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    detected_type = project.suffix.lower().lstrip(".")
    artifact_histogram, partial_items, unsupported_items = _artifact_histogram(
        manifest.get("items", []),
        detected_type=detected_type,
    )
    return {
        "code": code,
        "path": _collection_path(project),
        "parser_status": manifest.get("parser_status", ""),
        "status": manifest.get("status", ""),
        "support_class": manifest.get("support_class", ""),
        "warning_count": len(manifest.get("warnings", [])),
        "warning_signature": manifest.get("warnings", []),
        "partial_items": partial_items,
        "unsupported_items": unsupported_items,
        "artifact_histogram": artifact_histogram,
    }


def _run_extract(project: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="deopjufier-status-lock-") as scratch:
        out_dir = Path(scratch) / "extract"
        out_dir.mkdir()
        return _to_record(project, out_dir)


def _build_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "command": {"name": "extract", "arguments": COMMAND_ARGS},
        "generated_on": date.today().isoformat(),
        "schema_version": "1.0",
        "records": records,
    }


def _load_lock() -> dict[str, Any]:
    return json.loads(STATUS_LOCK_PATH.read_text(encoding="utf-8"))


def _up_to_date_differences(
    actual: list[dict[str, Any]],
    expected: dict[str, Any],
) -> list[str]:
    expected_records: dict[str, dict[str, Any]] = {}
    actual_records: dict[str, dict[str, Any]] = {}
    differences: list[str] = []
    for record in expected.get("records", []):
        if isinstance(record, dict):
            path = record.get("path")
            if isinstance(path, str):
                expected_records[path] = record

    for entry in actual:
        if not isinstance(entry, dict):
            differences.append("non-dict actual record")
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            differences.append("actual record missing path")
            continue
        actual_records[path] = entry
        base = expected_records.get(path)
        if base is None:
            differences.append(f"actual record not in lock: {path}")
            continue
        for key in {
            "code",
            "status",
            "parser_status",
            "support_class",
            "warning_count",
            "warning_signature",
            "partial_items",
            "unsupported_items",
            "artifact_histogram",
        }:
            if entry.get(key) != base.get(key):  # type: ignore[union-attr]
                differences.append(
                    f"{path}: {key}: actual={json.dumps(entry.get(key), sort_keys=True)} "
                    f"expected={json.dumps(base.get(key), sort_keys=True)}"
                )

    for path in sorted(expected_records):
        if path not in actual_records:
            differences.append(f"lock record missing from actual run: {path}")

    if len(actual_records) != len(expected_records):
        differences.append(f"record_count mismatch: actual={len(actual_records)} expected={len(expected_records)}")

    return differences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="check against existing lock instead of writing it",
    )
    args = parser.parse_args()

    records = [_run_extract(project) for project in _discover_ref_targets(REFS_DIR)]
    payload = _build_payload(records)

    if args.check:
        existing = _load_lock()
        differences = _up_to_date_differences(records, existing)
        if differences:
            print("[drift] status-lock check failed")
            for reason in differences:
                print(f"- {reason}")
            raise SystemExit(1)
        print(f"[ok] {APP_NAME} {len(records)} refs match fixture lock")
        return

    STATUS_LOCK_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[write] {STATUS_LOCK_PATH} ({len(records)} records)")


if __name__ == "__main__":
    main()
