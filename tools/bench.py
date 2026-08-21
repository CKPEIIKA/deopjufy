#!/usr/bin/env python3
"""Benchmark selected deopjufy commands over reference fixtures."""

from __future__ import annotations

import argparse
import io
import json
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from deopjufier.app import main

ROOT = Path(__file__).resolve().parents[1]


def _default_fixtures() -> list[Path]:
    return [
        ROOT / "refs/openopj/support/test.opj",
        ROOT / "refs/github/Ropj/inst/test.opj",
        ROOT / "refs/github/Ropj/inst/tree.opj",
        ROOT / "refs/ropj/src/Ropj/inst/test.opj",
        ROOT / "refs/ropj/src/Ropj/inst/tree.opj",
        ROOT / "refs/public/zenodo/zenodo-10721640-figure-s3.opju",
    ]


def _slow_fixtures() -> list[Path]:
    return [
        ROOT / "refs/public/zenodo/zenodo-18450855-eucd2p2.opju",
        ROOT / "refs/public/zenodo/zenodo-19549171-small-science-paper.opju",
    ]


def _run_command(argv: list[str]) -> float:
    stdout = io.StringIO()
    stderr = io.StringIO()
    start = perf_counter()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        main(argv)
    return perf_counter() - start


def _bench_case(runner: Callable[[], float], runs: int, warmup: int) -> list[float]:
    timings: list[float] = []
    for index in range(runs + warmup):
        elapsed = runner()
        if index >= warmup:
            timings.append(elapsed)
    return timings


def _format_stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {
            "samples": 0,
            "avg_ms": 0.0,
            "median_ms": 0.0,
            "p90_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
        }
    values_ms = [value * 1000.0 for value in values]
    sorted_values = sorted(values_ms)
    p90_index = int(0.9 * (len(sorted_values) - 1))
    return {
        "samples": len(values_ms),
        "avg_ms": mean(values_ms),
        "median_ms": median(values_ms),
        "p90_ms": sorted_values[p90_index],
        "min_ms": sorted_values[0],
        "max_ms": sorted_values[-1],
    }


def _build_runners(path: Path, quiet: bool = False) -> dict[str, Callable[[], float]]:
    def _runner(argv: list[str]) -> Callable[[], float]:
        def _inner() -> float:
            args = list(argv)
            if quiet and "--quiet" not in args:
                args.append("--quiet")
            return _run_command(args)

        return _inner

    def _run_extract() -> float:
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            args = [
                "extract",
                str(path),
                "-o",
                str(root / "out"),
                "--force",
                "--raw-dir",
                str(root / "raw"),
            ]
            if quiet:
                args.append("--quiet")
            return _run_command(args)

    return {
        "inspect": _runner(["inspect", str(path)]),
        "list": _runner(["list", str(path)]),
        "strings": _runner(["strings", str(path), "--min-length", "4"]),
        "table-scan": _runner(["table-scan", str(path), "--min-rows", "3", "--min-columns", "2", "--format", "csv"]),
        "images": _runner(["images", str(path)]),
        "extract": _run_extract,
    }


def _print_table(results: dict[str, dict[str, float | int]]) -> None:
    for command, metrics in results.items():
        print(
            "  {:<11} {:>8.3f} ms median  {:>8.3f} ms avg  {:>8.3f} ms p90  {} samples".format(
                command,
                metrics["median_ms"],
                metrics["avg_ms"],
                metrics["p90_ms"],
                metrics["samples"],
            )
        )


def _run_bench(file_path: Path, runs: int, warmup: int) -> dict[str, Any]:
    runners = _build_runners(file_path, quiet=True)
    results: dict[str, Any] = {}
    for command, runner in runners.items():
        timings = _bench_case(runner, runs=runs, warmup=warmup)
        results[command] = _format_stats(timings)
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark deopjufy hot paths")
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="iterations per command (after warm-up)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="warm-up runs ignored from metrics",
    )
    parser.add_argument("--json", action="store_true", help="print JSON output")
    parser.add_argument(
        "--preset",
        choices=["all", "slow"],
        default="all",
        help="benchmark preset (all fixtures or only slow real fixtures)",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="optional fixture paths to benchmark",
    )
    return parser.parse_args()


def main_entry() -> None:
    args = _parse_args()
    if args.preset == "slow":
        files = _slow_fixtures()
    elif args.files:
        files = [path if path.is_absolute() else ROOT / path for path in args.files]
    else:
        files = _default_fixtures()

    files = [p.resolve() for p in files if p.exists()]

    if not files:
        raise RuntimeError("no benchmark fixtures found")

    runs = max(args.iterations, 1)
    warmup = max(args.warmup, 0)

    all_results: dict[str, dict[str, Any]] = {}
    for path in files:
        try:
            label = str(path.relative_to(ROOT))
        except ValueError:
            label = str(path)
        print(f"[bench] {label}")
        benchmark = _run_bench(path, runs=runs, warmup=warmup)
        all_results[label] = benchmark
        _print_table(benchmark)

    if args.json:
        print(json.dumps(all_results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main_entry()
