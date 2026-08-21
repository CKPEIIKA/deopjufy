"""Helpers for discovery across source-buffer windows."""

from deopjufier.blocks_parse import GIF_SIGS, JPEG_SIG, PNG_SIG
from deopjufier.discovery_scan import *


def _bracket_offsets_from_stream(
    path: Path,
    *,
    chunk_size: int = _OPJ_DISCOVERY_STREAM_CHUNK_SIZE,
    max_repeats_per_name: int | None = None,
    heuristic_kind_limit: int | None = None,
    kind_hits: dict[str, int] | None = None,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    return _scan_discovery_stream(
        path,
        chunk_size=chunk_size,
        scan_chunk=_scan_bracket_matches_in_chunk,
        drain_tail=_bracket_matches_reached_limit,
        max_repeats_per_name=max_repeats_per_name,
        heuristic_kind_limit=heuristic_kind_limit,
        kind_hits=kind_hits,
        allowed_kinds=allowed_kinds,
        total_limit=total_limit,
    )


def _is_media_signature(offset: int, data: bytes) -> bool:
    for marker in (b"CPYA", b"CPYUA", PNG_SIG, JPEG_SIG, *GIF_SIGS):
        if data.startswith(marker, offset):
            return True
    return False


def _ensure_unique_paths(items: list[OriginObject]) -> list[OriginObject]:
    def _clone(item: OriginObject, *, source_object_path: str) -> OriginObject:
        if isinstance(item, ParserBackedDiscoveryRecord):
            return ParserBackedDiscoveryRecord(
                offset=item.offset,
                name=item.name,
                length=item.length,
                object_kind=item.object_kind,
                source_object_path=source_object_path,
                parser_rule=item.parser_rule,
                parser_confidence=item.parser_confidence,
                parser_confirmed=item.parser_confirmed,
            )
        if isinstance(item, HeuristicDiscoveryRecord):
            return HeuristicDiscoveryRecord(
                offset=item.offset,
                name=item.name,
                length=item.length,
                object_kind=item.object_kind,
                source_object_path=source_object_path,
                heuristic_signal=item.heuristic_signal,
                parser_confirmed=item.parser_confirmed,
            )
        return OriginObject(
            offset=item.offset,
            name=item.name,
            length=item.length,
            object_kind=item.object_kind,
            source_object_path=source_object_path,
            parser_confirmed=item.parser_confirmed,
        )

    seen: dict[str, int] = {}
    unique: list[OriginObject] = []
    for item in items:
        base = item.source_object_path
        count = seen.get(base, 0) + 1
        seen[base] = count
        path = _append_path_suffix(base, duplicate_index=count)
        unique.append(_clone(item, source_object_path=path))
    return unique


def _source_object_root(source_object_path: str | None) -> str | None:
    if not source_object_path:
        return None
    parts = source_object_path.split("/", 1)
    return parts[0] if parts else None


def iter_object_windows(
    objects: list[OriginObject],
    file_size: int,
    *,
    scope_by_source_prefix: bool = False,
) -> list[tuple[OriginObject, int, int]]:
    """Return stable object windows from parser-confirmed spans when available.

    Parser-confirmed spans keep their declared extent; heuristic spans fall back to
    scan-order boundaries so they still get a deterministic owner when no parser
    size is available.

    If ``scope_by_source_prefix`` is enabled, non-confirmed fallback windows only
    advance to the next object sharing the same first source-path segment.
    """
    if file_size < 0:
        return []

    ordered = sorted(objects, key=lambda item: item.offset)
    if not ordered:
        return []

    windows: list[tuple[OriginObject, int, int]] = []
    for index, item in enumerate(ordered):
        start = max(item.offset, 0)
        next_offset: int | None = None
        if index + 1 < len(ordered):
            if scope_by_source_prefix:
                source_root = _source_object_root(getattr(item, "source_object_path", None))
                if source_root:
                    for candidate in ordered[index + 1 :]:
                        candidate_root = _source_object_root(getattr(candidate, "source_object_path", None))
                        if candidate_root == source_root and candidate.offset > start:
                            next_offset = candidate.offset
                            break
            if next_offset is None:
                next_offset = max(ordered[index + 1].offset, start)

        end = start
        if item.parser_confirmed and item.length > 0:
            parser_end = item.offset + item.length
            if parser_end > start:
                end = min(parser_end, file_size)
        else:
            if next_offset is not None:
                end = next_offset

        if end < start:
            end = start
        if index == len(ordered) - 1 and end == start:
            end = file_size
        windows.append((item, start, end))
    return windows


__all__ = [
    "KNOWN_PREFIXES",
    "KNOWN_SUFFIXES",
    "_BRACKET_REF_PATTERN",
    "_OPJ_BRACKET_CARRY_BYTES",
    "_OPJ_DISCOVERY_STREAM_CHUNK_SIZE",
    "_OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES",
    "_OPJ_PARSER_BOUNDARY_MAX_BYTES",
    "_OPJ_TOKEN_CARRY_BYTES",
    "_TOK_PATTERN",
    "HeuristicDiscoveryRecord",
    "OriginObject",
    "ParserBackedDiscoveryRecord",
    "_append_token_object_offsets",
    "_bracket_offsets",
    "_bracket_offsets_from_file",
    "_classify_object_kind",
    "_derive_source_path",
    "_ensure_unique_paths",
    "_extract_embedded_origin_name_offsets",
    "_is_media_signature",
    "_is_plausible_origin_name",
    "_token_offsets",
    "_token_offsets_from_file",
    "iter_object_windows",
]
