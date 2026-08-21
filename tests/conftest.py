"""Global pytest fixtures for the test suite."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Final

import pytest

from deopjufier.cli import main

_DEFAULT_TEST_TIMEOUT_SECONDS: Final[int] = int(os.environ.get("DEOPJUFIER_TEST_TIMEOUT_SECONDS", "45"))
_HAS_ALARM_TIMER: Final[bool] = hasattr(signal, "SIGALRM") and hasattr(signal, "ITIMER_REAL")


def _read_timeout_marker(test_item: pytest.Function) -> int:
    marker = test_item.get_closest_marker("timeout")
    if marker is not None:
        if marker.args:
            return int(marker.args[0])
    return _DEFAULT_TEST_TIMEOUT_SECONDS


def _raise_timeout(signum: int, frame: object) -> None:
    raise TimeoutError("test execution exceeded timeout")


@pytest.fixture(autouse=True)
def enforce_test_timeout(request: pytest.FixtureRequest) -> Iterator[None]:
    """Apply a per-test wall-clock timeout for Linux-style environments."""
    if not _HAS_ALARM_TIMER:
        yield
        return

    timeout_seconds = _read_timeout_marker(request.node) if hasattr(request, "node") else _DEFAULT_TEST_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


@dataclass(frozen=True)
class CachedExtractRun:
    sample: Path
    output_dir: Path
    manifest_path: Path
    payload: dict[str, Any]
    exit_code: int
    raw_dir: Path | None = None
    text_dir: Path | None = None


@contextmanager
def _exclusive_cache_lock(path: Path) -> Iterator[None]:
    with path.open("w", encoding="utf-8") as stream:
        timer_state = signal.getitimer(signal.ITIMER_REAL) if _HAS_ALARM_TIMER else None
        if timer_state is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            flock(stream.fileno(), LOCK_EX)
        finally:
            if timer_state is not None:
                signal.setitimer(signal.ITIMER_REAL, *timer_state)
        try:
            yield
        finally:
            flock(stream.fileno(), LOCK_UN)


@pytest.fixture(scope="session")
def cached_extract(tmp_path_factory: pytest.TempPathFactory):
    """Run expensive real-file extracts once per worker and argument set.

    Parallel workers share immutable completed extracts under an exclusive
    per-key lock. Uncached runs remain worker-local.
    """

    base_temp = tmp_path_factory.getbasetemp()
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    cache_root = (
        base_temp.parent / "shared_cached_extracts" if worker_id else tmp_path_factory.mktemp("cached_extracts")
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    uncached_root = base_temp / "uncached_extracts"
    uncached_root.mkdir(parents=True, exist_ok=True)
    cache: dict[tuple[object, ...], CachedExtractRun] = {}
    uncached_run_count = 0

    def _run(
        sample: Path,
        *extra_args: str,
        with_raw_dir: bool = False,
        raw_min_bytes: int | None = None,
        with_text_dir: bool = False,
        text_min_bytes: int | None = None,
        use_cache: bool = True,
    ) -> CachedExtractRun:
        key = (
            str(sample.resolve()),
            tuple(extra_args),
            with_raw_dir,
            raw_min_bytes,
            with_text_dir,
            text_min_bytes,
        )
        cached = cache.get(key)
        if cached is not None:
            return cached

        digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
        nonlocal uncached_run_count
        if use_cache:
            run_root = cache_root / digest
        else:
            uncached_run_count += 1
            run_root = uncached_root / f"{digest}-{uncached_run_count}"
        output_dir = run_root / "out"
        manifest_path = output_dir / "manifest.json"
        result_path = run_root / "extract-result.json"
        raw_dir = run_root / "raw" if with_raw_dir else None
        text_dir = run_root / "text" if with_text_dir else None

        def _load_result() -> CachedExtractRun:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            return CachedExtractRun(
                sample=sample,
                output_dir=output_dir,
                manifest_path=manifest_path,
                payload=payload,
                exit_code=int(result_payload["exit_code"]),
                raw_dir=raw_dir,
                text_dir=text_dir,
            )

        def _execute() -> CachedExtractRun:
            if run_root.exists():
                shutil.rmtree(run_root)
            args = [
                "extract",
                str(sample),
                "-o",
                str(output_dir),
                "--manifest",
                str(manifest_path),
            ]
            if raw_dir is not None:
                args.extend(["--raw-dir", str(raw_dir)])
            if (
                "--extended" not in extra_args
                and "--human" not in extra_args
                and "--human-only" not in extra_args
                and "--human-artifacts-only" not in extra_args
            ):
                args.append("--extended")
            if raw_min_bytes is not None:
                args.extend(["--raw-min-bytes", str(raw_min_bytes)])
            if text_dir is not None:
                args.extend(["--text-dir", str(text_dir)])
            if text_min_bytes is not None:
                args.extend(["--text-min-bytes", str(text_min_bytes)])
            args.extend(extra_args)

            exit_code = main(args)
            result_path.write_text(json.dumps({"exit_code": exit_code}), encoding="utf-8")
            return _load_result()

        if use_cache:
            with _exclusive_cache_lock(cache_root / f"{digest}.lock"):
                result = _load_result() if manifest_path.is_file() and result_path.is_file() else _execute()
        else:
            result = _execute()
        if use_cache:
            cache[key] = result
        return result

    return _run


__all__ = ["CachedExtractRun", "cached_extract", "enforce_test_timeout"]
