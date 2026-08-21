#!/usr/bin/env python3
"""Generate deterministic coverage summaries from deopjufier manifest files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_KNOWN_VERIFICATION_STATES = {"external-parity", "synthetic"}
_KNOWN_MODE_SUFFIXES = {"default", "human-only", "human-artifacts-only", "human", "map", "extended", "parser-only"}


def _coerce_manifest_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _item_status(item: dict[str, Any]) -> str:
    status = item.get("status")
    if isinstance(status, str):
        return status
    heuristic = item.get("heuristic")
    if isinstance(heuristic, bool):
        return "extracted" if not heuristic else "partial"
    return "unknown"


def _is_heuristic(item: dict[str, Any]) -> bool:
    return bool(item.get("heuristic", False)) and isinstance(item.get("heuristic"), bool)


def _is_verified(item: dict[str, Any]) -> bool:
    verification = item.get("verification")
    return isinstance(verification, str) and verification in _KNOWN_VERIFICATION_STATES


def _iter_kind_counts(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:  # noqa: C901
    def new_counts() -> dict[str, int]:
        return {
            "discovered": 0,
            "extracted": 0,
            "partial": 0,
            "unsupported": 0,
            "heuristic": 0,
            "verified": 0,
        }

    counts: defaultdict[str, dict[str, int]] = defaultdict(new_counts)
    for item in items:
        kind = item.get("kind")
        if not isinstance(kind, str) or not kind:
            kind = "unknown"
        family = counts[kind]
        family["discovered"] += 1
        status = _item_status(item)
        if status == "extracted":
            family["extracted"] += 1
        elif status == "partial":
            family["partial"] += 1
        elif status in {"unsupported", "error"}:
            family["unsupported"] += 1
        if _is_heuristic(item):
            family["heuristic"] += 1
        if _is_verified(item):
            family["verified"] += 1
    return dict(sorted(counts.items(), key=lambda pair: pair[0]))


def _fixture_label(manifest_path: Path, base_root: Path | None = None) -> str:
    parent = manifest_path.parent
    if parent.name in _KNOWN_MODE_SUFFIXES and parent.parent != parent:
        parent = parent.parent
    if base_root is not None and parent.is_relative_to(base_root):
        relative = parent.relative_to(base_root)
        if str(relative) == ".":
            return parent.name
        return str(relative)
    return str(parent)


def _collect_manifest_paths(paths: list[Path]) -> list[Path]:
    manifest_paths: list[Path] = []
    for path in paths:
        if path.is_file():
            manifest_paths.append(path)
            continue
        if not path.is_dir():
            raise FileNotFoundError(f"input path does not exist: {path}")
        manifest_paths.extend(sorted(path.rglob("manifest.json")))
    return sorted(manifest_paths, key=lambda item: str(item))


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_rows(manifest_paths: list[Path], base_root: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in manifest_paths:
        payload = _load_manifest(manifest_path)
        fixture = _fixture_label(manifest_path, base_root=base_root)
        item_counts = _iter_kind_counts(_coerce_manifest_items(payload))
        for kind in sorted(item_counts):
            row = {"fixture": fixture, "kind": kind, **item_counts[kind]}
            rows.append(row)
    return sorted(rows, key=lambda row: (row["fixture"], row["kind"]))


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_fixture: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_fixture.setdefault(row["fixture"], []).append(
            {
                "kind": row["kind"],
                "discovered": row["discovered"],
                "extracted": row["extracted"],
                "partial": row["partial"],
                "unsupported": row["unsupported"],
                "heuristic": row["heuristic"],
                "verified": row["verified"],
            },
        )
    return {"fixtures": [{"fixture": fixture, "families": families} for fixture, families in by_fixture.items()]}


def _print_text(rows: list[dict[str, Any]], *, out) -> None:
    print("fixture,kind,discovered,extracted,partial,unsupported,heuristic,verified", file=out)
    for row in rows:
        print(
            f"{row['fixture']},{row['kind']},"
            f"{row['discovered']},{row['extracted']},"
            f"{row['partial']},{row['unsupported']},"
            f"{row['heuristic']},{row['verified']}",
            file=out,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize manifest evidence by fixture-family.")
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="manifest JSON files or directories containing manifest.json files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON summary",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="base path used to shorten fixture labels",
    )
    return parser.parse_args(argv)


def main_entry(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        manifest_paths = _collect_manifest_paths(args.paths)
    except (OSError, FileNotFoundError) as exc:
        print(f"unable to collect manifests: {exc}", file=sys.stderr)
        return 2

    rows = _build_rows(manifest_paths, base_root=args.root)
    if args.json:
        print(json.dumps(_build_summary(rows), indent=2, sort_keys=True))
    else:
        _print_text(rows, out=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
