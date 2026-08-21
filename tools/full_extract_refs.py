#!/usr/bin/env python3
"""Run full extraction audits for approved public reference fixtures."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, TypedDict

from deopjufier.cli import main

ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_EXTENSIONS = {".opj", ".opju"}
PUBLIC_REFERENCE_ROOTS = (
    ROOT / "refs" / "public",
    ROOT / "refs" / "github" / "Ropj" / "inst",
    ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst",
    ROOT / "refs" / "openopj" / "support",
)
DEFAULT_MODES: list[str] = ["default", "parser-only", "human-only", "extended"]
MODE_FLAGS: dict[str, list[str]] = {
    "default": [],
    "parser-only": ["--parser-only"],
    "human-only": ["--human-only"],
    "extended": ["--extended"],
}


class AuditRecord(TypedDict):
    path: str
    mode: str
    args: list[str]
    exit_code: int
    status: str
    support_class: str
    parser_status: str
    item_count: int
    partial_items: int
    unsupported_items: int
    heuristic_items: int
    warnings: int
    kind_counts: dict[str, int]


def _iter_fixtures(root: Path) -> list[Path]:
    return sorted(
        {
            fixture
            for fixture in root.glob("refs/**/*")
            if fixture.is_file()
            and fixture.suffix.lower() in SUPPORTED_EXTENSIONS
            and any(fixture.is_relative_to(reference_root) for reference_root in PUBLIC_REFERENCE_ROOTS)
        },
        key=lambda path: str(path.relative_to(root)),
    )


def _run_extract(path: Path, output_dir: Path, base_args: list[str]) -> tuple[int, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    args = [
        "extract",
        str(path),
        "-o",
        str(output_dir),
        "--manifest",
        str(manifest_path),
        *base_args,
    ]
    if "--extended" in base_args:
        args.extend(
            [
                "--raw-dir",
                str(output_dir / "raw"),
                "--text-dir",
                str(output_dir / "text"),
            ]
        )
    exit_code = main(args)
    payload: dict[str, Any] = {}
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return exit_code, payload


def _snapshot(output_root: Path, path: Path) -> AuditRecord:
    payload = output_root / "manifest.json"
    if not payload.exists():
        return {
            "path": str(path),
            "mode": "",
            "args": [],
            "exit_code": 1,
            "status": "failed",
            "support_class": "failed",
            "parser_status": "error",
            "item_count": 0,
            "partial_items": 0,
            "unsupported_items": 0,
            "heuristic_items": 0,
            "warnings": 0,
            "kind_counts": {},
        }

    data = json.loads(payload.read_text(encoding="utf-8"))
    items = data.get("items", [])
    heuristics = sum(1 for item in items if item.get("heuristic"))
    kind_counts = Counter(item.get("kind") for item in items if isinstance(item.get("kind"), str))
    missing = []
    for item in items:
        rel = item.get("path")
        if isinstance(rel, str):
            item_path = output_root / rel
            if item.get("kind") == "raw_dump":
                item_path = item_path if item_path.exists() else output_root / "raw" / rel
            elif item.get("kind") == "text_region":
                item_path = item_path if item_path.exists() else output_root / "text" / rel
            if not item_path.exists():
                missing.append(rel)
    if missing:
        data["path_integrity_errors"] = missing
    return {
        "path": str(path),
        "mode": "",
        "args": [],
        "exit_code": 0,
        "status": data.get("status", "failed"),
        "support_class": data.get("support_class", "failed"),
        "parser_status": data.get("parser_status", "error"),
        "item_count": len(items),
        "partial_items": data.get("partial_items", 0),
        "unsupported_items": data.get("unsupported_items", 0),
        "heuristic_items": heuristics,
        "warnings": len(data.get("warnings", [])),
        "kind_counts": dict(kind_counts),
    }


def _run_audit(
    fixtures: list[Path],
    output_root: Path,
    include_modes: list[str],
) -> list[dict[str, AuditRecord]]:
    results: list[dict[str, AuditRecord]] = []
    for fixture in fixtures:
        label = str(fixture.relative_to(ROOT))
        fixture_results: dict[str, AuditRecord] = {}
        for mode in include_modes:
            mode_output = output_root / label / mode
            args = MODE_FLAGS.get(mode, [])
            exit_code, _ = _run_extract(fixture, mode_output, args)
            record = _snapshot(mode_output, fixture)
            record["mode"] = mode
            record["args"] = args
            record["exit_code"] = exit_code
            fixture_results[mode] = record
        results.append(fixture_results)
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run extraction across checked-in fixtures.")
    parser.add_argument(
        "output_root",
        nargs="?",
        default="/tmp/full_extract_refs",
        type=Path,
        help="output directory for fixture manifests and outputs",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=DEFAULT_MODES,
        default=None,
        help="extract mode to run per fixture",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON summary",
    )
    return parser.parse_args()


def _print_summary(results: list[dict[str, AuditRecord]]) -> None:
    for fixture in results:
        rows = list(fixture.values())
        if not rows:
            continue
        fixture_path = rows[0]["path"]
        for row in rows:
            print(
                f"{Path(fixture_path).name:48} {row['mode']:11} "
                f"status={row['status']:<8} support={row['support_class']:<8} "
                f"items={row['item_count']:4d} heur={row['heuristic_items']:3d} "
                f"partial={row['partial_items']:3d} unsupported={row['unsupported_items']:3d} "
                f"warnings={row['warnings']:2d}"
            )


def _evaluate_results(results: list[dict[str, AuditRecord]]) -> int:
    for fixture in results:
        for row in fixture.values():
            if row["exit_code"] not in {0, 4}:
                return 1
            if row["status"] == "failed" and row["item_count"] == 0:
                return 2
    return 0


def _build_summary(results: list[dict[str, AuditRecord]], mode_names: list[str]) -> dict[str, Any]:
    return {
        "fixtures": len(results),
        "modes": mode_names,
        "results": results,
    }


def main_entry() -> int:
    args = _parse_args()
    mode_names = args.mode if args.mode is not None else DEFAULT_MODES
    modes = list(dict.fromkeys(mode_names))
    args.output_root.mkdir(parents=True, exist_ok=True)
    fixtures = [fixture for fixture in _iter_fixtures(ROOT) if fixture.is_file()]
    if not fixtures:
        print("no fixtures found under refs/")
        return 1

    results = _run_audit(fixtures, args.output_root, modes)
    summary = _build_summary(results, modes)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_summary(results)

    return _evaluate_results(results)


if __name__ == "__main__":
    raise SystemExit(main_entry())
