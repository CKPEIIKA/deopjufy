"""Shared helpers for split core unit coverage tests."""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

from deopjufier.cli import NATIVE_BACKEND
from deopjufier.detect import DetectedFile
from deopjufier.manifest import Manifest, make_manifest

PathLike: TypeAlias = Path | str


def _repo_root(start: PathLike) -> Path:
    candidate = Path(start).resolve()
    if candidate.is_file():
        candidate = candidate.parent

    for root in (candidate, *candidate.parents):
        if (root / "pyproject.toml").exists():
            return root

    raise RuntimeError(f"Unable to locate repository root for {start}")


def _resolve_tests_fixture(start: PathLike, relative_path: PathLike) -> Path:
    reference = Path(start)
    if reference.is_file():
        reference = reference.parent

    local = reference / relative_path
    if local.exists():
        return local

    return _repo_root(start) / "tests" / Path(relative_path)


def _resolve_repo_fixture(start: PathLike, relative_path: PathLike) -> Path:
    reference = Path(start)
    if reference.is_file():
        reference = reference.parent

    local = reference / relative_path
    if local.exists():
        return local

    return _repo_root(start) / Path(relative_path)


def _resolve_synthetic_fixture(start: PathLike, filename: str) -> Path:
    return _resolve_tests_fixture(start, Path("fixtures") / "synthetic" / filename)


def _make_manifest(path: Path) -> Manifest:
    detected = DetectedFile(path=path, detected_type="opju", confidence=0.99, reason="test")
    return make_manifest(
        path,
        detected,
        NATIVE_BACKEND,
        size_bytes=path.stat().st_size,
        sha256="0" * 64,
    )
