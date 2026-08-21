#!/usr/bin/env python3
"""Regenerate OPJU parity fixtures from live extraction results."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from collections.abc import Iterable
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from deopjufier.cli import main as cli_main
from deopjufier.inventory import discover_origin_objects

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures"
PARITY_GLOBS = sorted(FIXTURE_ROOT.glob("opju-parity-*.json"))


def _collection_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _run_extract(project: Path, *, include_images: bool = True) -> tuple[int, dict[str, Any]]:
    # Use temporary storage to avoid polluting the working directory.
    with tempfile.TemporaryDirectory(prefix="deopjufier-opju-parity-") as scratch:
        output = Path(scratch) / "extract"
        output.mkdir(parents=True, exist_ok=True)
        args = [
            "extract",
            str(project),
            "-o",
            str(output),
            "--no-strings",
            "--no-tables",
            "--raw-min-bytes",
            "99999999",
        ]
        if not include_images:
            args.insert(2, "--no-images")
        code = cli_main(args)
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return code, manifest


def _run_list(project: Path) -> tuple[int, dict[str, Any]]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli_main(["list", str(project), "--json"])
    payload = json.loads(stdout.getvalue())
    return code, payload


def _counter_from_items(items: Iterable[dict], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in items:
        value = item.get(key)
        if isinstance(value, str):
            counter[value] += 1
    return dict(counter)


def _build_payload(path: Path, current: dict[str, Any]) -> dict[str, Any]:
    objects = discover_origin_objects(path)
    list_code, list_payload = _run_list(path)
    extract_code, manifest = _run_extract(path)

    object_kind_counts = Counter(obj.object_kind if obj.object_kind is not None else "unclassified" for obj in objects)
    parser_confirmed_object_kind_counts = Counter(
        obj.object_kind if obj.object_kind is not None else "unclassified" for obj in objects if obj.parser_confirmed
    )
    heuristic_object_kind_counts = Counter(
        obj.object_kind if obj.object_kind is not None else "unclassified"
        for obj in objects
        if not obj.parser_confirmed
    )

    merged = dict(current)
    merged["object_count"] = len(objects)
    merged["object_kind_counts"] = dict(sorted(object_kind_counts.items()))
    merged["parser_confirmed_object_kind_counts"] = dict(sorted(parser_confirmed_object_kind_counts.items()))
    merged["heuristic_object_kind_counts"] = dict(sorted(heuristic_object_kind_counts.items()))
    merged["list_code"] = list_code
    merged["list_item_count"] = len(list_payload["items"])
    merged["list_kind_counts"] = _counter_from_items(list_payload["items"], "kind")
    merged["list_discovery_type_counts"] = _counter_from_items(
        list_payload["items"],
        "discovery_type",
    )
    merged["list_parser_boundaries"] = _counter_from_items(
        [item for item in list_payload["items"] if item.get("heuristic") is False],
        "kind",
    )
    merged["extract_code"] = extract_code
    merged["manifest_status"] = manifest["status"]
    merged["manifest_item_count"] = len(manifest["items"])
    merged["manifest_kind_counts"] = _counter_from_items(manifest["items"], "kind")
    merged["manifest_status_counts"] = _counter_from_items(manifest["items"], "status")
    return merged


def _iter_parity_files() -> list[Path]:
    return [path for path in PARITY_GLOBS if path.is_file()]


def _read_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate regenerated payloads against committed fixtures",
    )
    args = parser.parse_args()

    mismatches = []
    for parity_path in _iter_parity_files():
        data = _read_payload(parity_path)
        fixture_rel = data.get("fixture")
        if not isinstance(fixture_rel, str):
            print(f"[skip] {parity_path.name}: missing fixture path")
            continue

        project = ROOT / fixture_rel
        if not project.exists():
            print(f"[skip] {parity_path.name}: missing fixture {fixture_rel}")
            continue

        generated = _build_payload(project, data)
        generated["format"] = "opju"
        if data.get("path") is None:
            generated["path"] = _collection_path(project)
        if data.get("fixture") is None:
            generated["fixture"] = _collection_path(project)
        if args.check:
            if generated == data:
                print(f"[ok] {parity_path.name}")
            else:
                print(f"[diff] {parity_path.name}")
                mismatches.append(parity_path.name)
            continue

        _write_payload(parity_path, generated)
        print(f"[write] {parity_path.name}")

    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
