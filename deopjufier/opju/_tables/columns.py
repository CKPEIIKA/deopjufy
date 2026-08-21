"""OPJU column-table extraction entrypoint."""

from __future__ import annotations

from .._tables_core import (
    MAGIC_OPJU,
    OpjuAnalyzedCandidate,
    OpjuColumnTable,
    OpjuOriginStorageCandidate,
    _iter_opju_origin_storage_blocks,
    _parse_column_tables_in_block,
    parse_opju_origin_storage_family_tables,
)


def parse_opju_column_tables(
    data: bytes,
    *,
    max_tables: int = 16,
    max_rows: int = 256,
    include_decoded: bool = False,
    include_family_binary: bool = False,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
    analyses: tuple[OpjuAnalyzedCandidate, ...] | None = None,
) -> list[OpjuColumnTable]:
    """Parse strict and XML-like column tables from an OPJU payload."""
    if max_tables <= 0 or max_rows <= 0 or not data.startswith(MAGIC_OPJU):
        return []

    normalized = data.lower()
    tables = parse_opju_origin_storage_family_tables(
        data,
        max_tables=max_tables,
        max_rows=max_rows,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
        candidates=candidates,
        analyses=analyses,
    )
    if len(tables) >= max_tables:
        return tables[:max_tables]

    for block_start, block in _iter_opju_origin_storage_blocks(
        data,
        include_decoded=include_decoded,
        candidates=candidates,
        analyses=analyses,
    ):
        if len(tables) >= max_tables:
            break
        tables.extend(
            _parse_column_tables_in_block(
                block_start,
                block,
                max_tables=max_tables - len(tables),
                max_rows=max_rows,
            )
        )
        if len(tables) >= max_tables:
            return tables[:max_tables]

    if tables or b"<columntable" not in normalized:
        return tables[:max_tables]

    tables.extend(
        _parse_column_tables_in_block(
            0,
            data,
            max_tables=max_tables - len(tables),
            max_rows=max_rows,
        )
    )
    return tables
