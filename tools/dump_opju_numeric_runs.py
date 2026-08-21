#!/usr/bin/env python3
"""Dump stable numeric-array run candidates from an OPJU file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print numeric-run candidates found in decoded OPJU payloads.")
    parser.add_argument("path", type=Path, help="Path to a CPYUA(OPJU) file.")
    parser.add_argument(
        "--max",
        type=int,
        default=25,
        help="Maximum number of runs to print.",
    )
    return parser


def _safe_values(values: tuple[str, ...]) -> str:
    joined = ", ".join(values)
    return joined


def main(argv: list[str] | None = None) -> int:
    from deopjufier.opju.numeric_runs import iter_opju_binary_runs_from_file

    parser = _build_parser()
    args = parser.parse_args(argv)
    data = args.path.read_bytes()

    runs = iter_opju_binary_runs_from_file(data)
    for run in runs[: args.max]:
        print(
            "family_marker="
            f"{run.family_marker or '<none>'} "
            f"decompressed_offset={run.source_start} "
            f"primitive={run.primitive} "
            f"run_length={run.run_length} "
            f"first_values=[{_safe_values(run.first_values)}]"
        )

    if not runs:
        print("no_numeric_runs_found")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
