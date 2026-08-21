"""Path and filename helper policies for extraction outputs."""

from __future__ import annotations

from pathlib import Path


def manifest_relative_path(target: Path, base: Path | None = None) -> str:
    """Return a deterministic relative manifest path for a target."""
    try:
        if base is None:
            return target.name
        return target.relative_to(base).as_posix()
    except ValueError:
        return target.name


def unique_output_path(base: Path, filename: str, force: bool = False) -> Path:
    """Return a safe output filename, adding a suffix if needed."""
    target = base / filename
    base.mkdir(parents=True, exist_ok=True)
    existing = {entry.name.casefold() for entry in base.iterdir()}
    if force or target.name.casefold() not in existing:
        return target

    stem = target.stem
    suffix = target.suffix
    next_index = 2
    while True:
        candidate = base / f"{stem}__{next_index}{suffix}"
        if candidate.name.casefold() not in existing:
            return candidate
        next_index += 1
