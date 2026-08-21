#!/usr/bin/env python3
"""Regenerate and verify OPJ parity fixture snapshots."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from deopjufier.inventory import (
    discover_origin_objects,
    iter_opj_data_sections,
    parse_opj_note_sections,
    parse_opj_parameters,
    parse_opj_signature,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures"


def _collection_root(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _build_discovery_payload(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    objects = discover_origin_objects(path)

    object_kind_counts = Counter(obj.object_kind if obj.object_kind is not None else "unclassified" for obj in objects)
    worksheet_books = Counter(
        (obj.source_object_path or "").split("/")[0]
        for obj in objects
        if obj.object_kind == "worksheet" and obj.source_object_path
    )

    grouped_paths: dict[str, list[str]] = {}
    for obj in objects:
        grouped_paths.setdefault(obj.name, []).append(obj.source_object_path)
    collisions = {name: values for name, values in grouped_paths.items() if len(values) > 1}

    note_paths = sorted(
        {obj.source_object_path for obj in objects if obj.object_kind == "note" and obj.source_object_path}
    )
    matrix_paths = sorted(
        {obj.source_object_path for obj in objects if obj.object_kind == "matrix" and obj.source_object_path}
    )
    layer_paths = sorted(
        {
            obj.source_object_path
            for obj in objects
            if obj.object_kind == "layer" and obj.parser_confirmed and obj.source_object_path
        }
    )

    payload: dict[str, Any] = {
        "fixture": _collection_root(path),
        "object_count": len(objects),
        "object_kind_counts": dict(sorted(object_kind_counts.items())),
        "tree_paths": sorted({obj.source_object_path for obj in objects if obj.source_object_path}),
        "workbook_sheet_counts": dict(sorted(worksheet_books.items())),
        "note_present": bool(note_paths),
        "note_paths": note_paths,
        "matrix_present": bool(matrix_paths),
        "matrix_paths": matrix_paths,
        "layer_paths": layer_paths,
    }

    if collisions:
        payload["collision_paths"] = collisions

    sections = list(iter_opj_data_sections(data))
    if sections:
        payload["data_sections"] = {
            "count": len(sections),
            "names": [section.name for section in sections],
            "sample_values": {},
        }
        for section in sections[:6]:
            sample = section.values[:6]
            payload["data_sections"]["sample_values"][section.name] = {
                "value_count": len(section.values),
                "first_values": sample,
            }

    parameters = parse_opj_parameters(data)
    if parameters:
        payload["parameters"] = {
            "count": len(parameters),
            "records": [{"name": p.name, "value": p.value} for p in parameters],
        }

    notes = parse_opj_note_sections(data)
    if notes:
        payload["notes"] = {
            "count": len(notes),
            "names": [note.name for note in notes],
            "lengths": [note.length for note in notes],
            "sample_texts": [note.text[:80] for note in notes],
        }

    signature = parse_opj_signature(data)
    if signature is not None:
        payload["signature"] = {
            "magic": signature.magic,
            "file_version": signature.file_version,
            "build": signature.build,
            "origin_version": signature.origin_version,
        }

    return payload


def _merge_payload(base: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    collisions = generated.pop("collision_paths", None)
    for key, value in generated.items():
        base[key] = value
    if collisions:
        base["collision_paths"] = collisions
    return base


def _discover_parity_fixtures() -> list[Path]:
    return sorted(FIXTURE_ROOT.glob("opj-parity-*.json"))


def _load_parity_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _matches_required_fields(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return (
        expected["object_count"] == actual.get("object_count")
        and expected["object_kind_counts"] == actual.get("object_kind_counts")
        and expected["tree_paths"] == actual.get("tree_paths")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate OPJ parity fixture files from parser discovery.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify discovered parity fields only without writing files",
    )
    args = parser.parse_args()

    files = _discover_parity_fixtures()
    failures = 0
    for parity_path in files:
        payload = _load_parity_payload(parity_path)
        fixture_rel = payload.get("fixture")
        if not isinstance(fixture_rel, str):
            print(f"[skip] {parity_path}: missing fixture field")
            continue
        fixture_path = ROOT / fixture_rel
        if not fixture_path.exists():
            print(f"[skip] {parity_path}: missing fixture {fixture_rel}")
            continue
        generated = _build_discovery_payload(fixture_path)
        merged = _merge_payload(dict(payload), generated)

        if args.check:
            if not _matches_required_fields(generated, payload):
                failures += 1
                print(f"[mismatch] {parity_path}: fixture={fixture_rel} tree path/object-count/object-kind-map differs")
            else:
                print(f"[ok] {parity_path}: object parity snapshot matches")
            if "layer_paths" not in payload and "layer_paths" in merged:
                failures += 1
                print(f"[missing] {parity_path}: layer_paths should be refreshed in parity fixture")
            continue

        _write_payload(parity_path, merged)
        print(f"[write] {parity_path}")

    if args.check and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
