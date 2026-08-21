#!/usr/bin/env python3
"""Regenerate the audited fixture-family matrix from native extraction manifests."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from deopjufier.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests" / "fixtures" / "audited_fixture_family_matrix.json"
REFS_ROOT = ROOT / "refs"
PUBLIC_REFERENCE_ROOTS = (
    REFS_ROOT / "public",
    REFS_ROOT / "github" / "Ropj" / "inst",
    REFS_ROOT / "ropj" / "src" / "Ropj" / "inst",
    REFS_ROOT / "openopj" / "support",
)


def _discover_targets() -> list[Path]:
    return sorted(
        path
        for path in REFS_ROOT.rglob("*")
        if path.suffix.lower() in {".opj", ".opju"}
        and any(path.is_relative_to(root) for root in PUBLIC_REFERENCE_ROOTS)
    )


def _record_for(path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="deopjufier-fixture-matrix-") as scratch:
        output_dir = Path(scratch) / "out"
        raw_dir = Path(scratch) / "raw"
        manifest_path = output_dir / "manifest.json"
        cli_main(
            [
                "extract",
                str(path),
                "-o",
                str(output_dir),
                "--manifest",
                str(manifest_path),
                "--extended",
                "--no-images",
                "--no-strings",
                "--raw-dir",
                str(raw_dir),
                "--raw-min-bytes",
                "1024",
            ]
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    items = [item for item in manifest.get("items", []) if isinstance(item, dict)]
    families = Counter(str(item["kind"]) for item in items if item.get("kind") is not None)
    return {
        "families": dict(sorted(families.items())),
        "partial_items": sum(item.get("status") == "partial" for item in items),
        "status": manifest["status"],
        "support_class": manifest["support_class"],
        "unsupported_items": sum(item.get("status") == "unsupported" for item in items),
        "warning_count": len(manifest.get("warnings", [])),
    }


def _build_matrix() -> dict[str, dict[str, Any]]:
    return {str(path.relative_to(ROOT)): _record_for(path) for path in _discover_targets()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the committed matrix is stale")
    args = parser.parse_args()

    matrix = _build_matrix()
    if args.check:
        expected = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        if matrix != expected:
            raise SystemExit("audited fixture-family matrix is stale")
        return

    MATRIX_PATH.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
