"""Helpers for object and gap-aware discovery logic."""

from __future__ import annotations

import re
from pathlib import Path

from deopjufier.blocks import ImageBlock
from deopjufier.io import sanitize_name


def book_dir(base: Path, source_object_path: str) -> Path:
    """Build a stable folder path from a source object tree path."""
    raw_parts = [part for part in re.split(r"[\\\\/]+", source_object_path) if part]
    parts = tuple(filter(None, (sanitize_name(part) for part in raw_parts)))
    if not parts:
        parts = ("book",)
    return base.joinpath(*parts)


def find_graph_block_for_object(
    blocks: list[ImageBlock], start: int, end: int, *, allow_invalid: bool = False
) -> ImageBlock | None:
    """Pick an embedded image block associated with an object range."""
    if start < 0 or end < start:
        return None

    ordered_blocks = sorted(blocks, key=lambda item: item.offset)

    for block in ordered_blocks:
        if not block.valid:
            continue
        block_start = block.offset
        block_end = block.offset + block.length
        if (start <= block_start < end) or (block_start < start < block_end):
            return block

    if not allow_invalid:
        return None

    for block in ordered_blocks:
        block_start = block.offset
        block_end = block.offset + block.length
        if (start <= block_start < end) or (block_start < start < block_end):
            return block

    return None


def gap_ranges(
    file_size: int,
    blocks: list[tuple[int, int]] | list[ImageBlock],
    *,
    min_size: int = 1,
) -> list[tuple[int, int]]:
    """Return uncovered byte ranges between sorted covered intervals."""
    if file_size <= 0 or min_size <= 0:
        return []

    if not blocks:
        return [(0, file_size)] if file_size >= min_size else []

    ranges: list[tuple[int, int]] = []
    cursor = 0
    normalized = [(block.offset, block.length) if isinstance(block, ImageBlock) else block for block in blocks]
    for offset, length in sorted(normalized, key=lambda item: item[0]):
        block_start = max(offset, 0)
        block_end = max(min(offset + length, file_size), block_start)
        start = max(cursor, min(block_start, file_size))
        if start - cursor >= min_size:
            ranges.append((cursor, start - cursor))
        cursor = max(cursor, block_end)

    if file_size - cursor >= min_size:
        ranges.append((cursor, file_size - cursor))
    return ranges
