"""Heuristic object discovery helpers for OPJ and OPJU binary inputs."""

from __future__ import annotations

import mmap
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from deopjufier.io import iter_file_chunks, open_mmap

KNOWN_PREFIXES = (
    "Book",
    "Graph",
    "Matrix",
    "Sheet",
    "Page",
    "Note",
    "Layer",
    "Excel",
    "Function",
    "Curve",
    "Legend",
    "Axis",
    "PdM",
    "MBook",
    "MSheet",
    "MMatrix",
    "N2N_",
    "__",
)
_PREFIX_KIND_MAP: dict[str, str] = {
    "t": "worksheet",
    "m": "matrix",
    "e": "excel",
    "f": "function",
}

KNOWN_SUFFIXES = (
    "_Data_",
    "__LayerGridStyle",
    "__WIOTN",
    "__BCO2",
    "OriginStorage",
)

_TOK_PATTERN = re.compile(rb"[A-Za-z0-9_.@-]+")
_BRACKET_REF_PATTERN = re.compile(rb"\[([A-Za-z][A-Za-z0-9_]+)\]([A-Za-z][A-Za-z0-9_]*)")
_OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES = 128 * 1024
_OPJ_DISCOVERY_STREAM_CHUNK_SIZE = 1 << 20
_OPJ_PARSER_BOUNDARY_MAX_BYTES = 2 * 1024 * 1024
_OPJ_TOKEN_CARRY_BYTES = 64
_OPJ_BRACKET_CARRY_BYTES = 512
_OPJ_EXCEL_EXTENSIONS = (".xlsx", ".xls", ".xlsm", ".xlsb")
_PLAUSIBLE_NAME_RE = re.compile(r"[A-Za-z]+\d+(?:_[A-Za-z0-9]+)?")
_HEURISTIC_KIND_KEYS = frozenset({"unclassified", "graph", "function", "excel", "matrix", "worksheet", "note", "meta"})
_KIND_PREFIXES: dict[str, tuple[str, ...]] = {
    "worksheet": ("Book", "Sheet", "N2N_", "MBook"),
    "graph": ("Graph", "Layer", "Page"),
    "matrix": ("Matrix", "PdM", "MSheet", "MMatrix"),
    "note": ("Note",),
    "function": ("Function", "Curve"),
    "excel": ("Excel",),
    "meta": ("__",),
}


@dataclass(frozen=True)
class OriginObject:
    """Backward-compatible discovery record for callers that build synthetic items."""

    offset: int
    name: str
    length: int
    object_kind: str | None = None
    source_object_path: str = "object/item"
    parser_confirmed: bool = False


@dataclass(frozen=True)
class ParserBackedDiscoveryRecord(OriginObject):
    """Discovered object with parser-backed boundary evidence."""

    parser_rule: str = "opj_boundary"
    parser_confidence: float = 0.95
    parser_confirmed: bool = True


@dataclass(frozen=True)
class HeuristicDiscoveryRecord(OriginObject):
    """Discovered object from heuristic scan fallback."""

    heuristic_signal: str | None = None
    parser_confirmed: bool = False


def _sanitize_path_segment(value: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    sanitized = sanitized.strip(".-")
    return sanitized or "item"


def _append_path_suffix(path: str, *, duplicate_index: int) -> str:
    if duplicate_index <= 1:
        return path

    if "/" in path:
        parent, _, leaf = path.rpartition("/")
        leaf = f"{leaf}__{duplicate_index}"
        return f"{parent}/{leaf}" if parent else leaf

    return f"{path}__{duplicate_index}"


@lru_cache(maxsize=32768)
def _classify_object_kind(name: str) -> str | None:
    lowered = name.lower()
    if not lowered:
        return None
    prefixed = _split_liborigin_prefixed_name(name)
    if prefixed is not None:
        return prefixed
    if any(lowered.endswith(ext) for ext in _OPJ_EXCEL_EXTENSIONS):
        return "excel"
    if lowered.startswith("graph") or lowered.startswith("layer"):
        return "graph"
    if lowered.startswith("function"):
        return "function"
    if lowered.startswith("excel"):
        return "excel"
    if lowered.startswith("msheet") or lowered.startswith("matrix_"):
        return "matrix"
    if lowered.startswith(("pdm", "matrix", "spread")):
        return "matrix"
    if lowered.startswith(("book", "n2n", "o2o", "sheet", "spreadsheet")):
        return "worksheet"
    if lowered.startswith("mbook"):
        return "worksheet"
    if lowered.startswith("note"):
        return "note"
    if lowered.startswith("__"):
        return "meta"
    return None


def _allow_discovery_name(
    name: str,
    *,
    name_hits: dict[str, int] | None,
    max_repeats_per_name: int | None,
) -> bool:
    if max_repeats_per_name is None or name_hits is None:
        return True

    seen_count = name_hits.get(name, 0)
    if seen_count >= max_repeats_per_name:
        return False
    name_hits[name] = seen_count + 1
    return True


def _allow_discovery_kind(
    kind: str | None,
    *,
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
) -> bool:
    if heuristic_kind_limit is None or kind_hits is None:
        return True

    key = kind or "unclassified"
    seen_count = kind_hits.get(key, 0)
    if seen_count >= heuristic_kind_limit:
        return False
    kind_hits[key] = seen_count + 1
    return True


def _passes_discovery_gates(
    name: str,
    object_kind: str | None,
    *,
    name_hits: dict[str, int] | None,
    max_repeats_per_name: int | None,
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
    allowed_kinds: frozenset[str] | None,
) -> bool:
    if allowed_kinds is not None and (object_kind or "unclassified") not in allowed_kinds:
        return False
    if not _allow_discovery_name(
        name,
        name_hits=name_hits,
        max_repeats_per_name=max_repeats_per_name,
    ):
        return False
    if not _allow_discovery_kind(
        object_kind,
        kind_hits=kind_hits,
        heuristic_kind_limit=heuristic_kind_limit,
    ):
        return False
    return True


def _append_heuristic_discovery_record(
    name: str,
    offset: int,
    length: int,
    *,
    out: list[OriginObject],
    object_kind: str | None,
    heuristic_signal: str,
    name_hits: dict[str, int] | None = None,
    max_repeats_per_name: int | None = None,
    kind_hits: dict[str, int] | None = None,
    heuristic_kind_limit: int | None = None,
    allowed_kinds: frozenset[str] | None = None,
) -> bool:
    resolved_kind = object_kind if object_kind is not None else _classify_object_kind(name)
    if not _passes_discovery_gates(
        name,
        resolved_kind,
        name_hits=name_hits,
        max_repeats_per_name=max_repeats_per_name,
        kind_hits=kind_hits,
        heuristic_kind_limit=heuristic_kind_limit,
        allowed_kinds=allowed_kinds,
    ):
        return False

    out.append(
        HeuristicDiscoveryRecord(
            offset=offset,
            name=name,
            length=length,
            object_kind=resolved_kind,
            heuristic_signal=heuristic_signal,
        )
    )
    return True


def _heuristic_kind_limits_reached(
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
) -> bool:
    if heuristic_kind_limit is None or kind_hits is None:
        return False
    if not kind_hits:
        return False

    # Keep streaming bounded by per-kind caps, but do not stop scanning when the
    # only limiting signal is noise classes like `unclassified`.
    tracked = [count for kind, count in kind_hits.items() if kind != "unclassified"]
    if len(tracked) < 2:
        return False

    # Continue scanning to let late-arriving higher-value kinds (e.g. `note`,
    # `function`) appear while lower-value kinds are already saturated.
    return all(count >= heuristic_kind_limit for count in tracked)


@lru_cache(maxsize=32768)
def _is_plausible_origin_name(token: str) -> bool:
    if not (4 <= len(token) <= 64):
        return False
    if any(ch.isspace() for ch in token):
        return False
    if token[0].isdigit():
        return False
    if token.startswith("M") and len(token) == 1:
        return False
    if any(token.startswith(prefix) for prefix in KNOWN_PREFIXES):
        return True
    if any(token.endswith(suffix) for suffix in KNOWN_SUFFIXES):
        return True
    if token.isupper() and len(token) > 4 and "_" in token:
        return True
    if _PLAUSIBLE_NAME_RE.fullmatch(token):
        return True
    return False


@lru_cache(maxsize=32)
def _candidate_prefixes_for_allowed_kinds(
    allowed_kinds: frozenset[str] | None,
) -> tuple[str, ...]:
    if not allowed_kinds:
        return KNOWN_PREFIXES

    prefixes: list[str] = []
    for kind in allowed_kinds:
        prefixes.extend(_KIND_PREFIXES.get(kind, ()))
    if not prefixes:
        return KNOWN_PREFIXES
    return tuple(dict.fromkeys(prefixes))


@lru_cache(maxsize=65536)
def _extract_embedded_origin_name_offsets(
    token: str,
    *,
    allowed_kinds: frozenset[str] | None = None,
) -> tuple[tuple[int, str], ...]:
    matches: list[tuple[int, str]] = []
    if _is_plausible_origin_name(token):
        token_kind = _classify_object_kind(token) or "unclassified"
        if allowed_kinds is None or token_kind in allowed_kinds:
            matches.append((0, token))

    candidate_prefixes = _candidate_prefixes_for_allowed_kinds(allowed_kinds)
    if not candidate_prefixes:
        return tuple(matches)

    lowered = token.lower()
    if not any(prefix.lower() in lowered for prefix in candidate_prefixes):
        return tuple(matches)

    for prefix in candidate_prefixes:
        pref = prefix.lower()
        idx = 0
        while True:
            loc = lowered.find(pref, idx)
            if loc < 0:
                break
            if loc > 0:
                candidate = token[loc:]
                if _is_plausible_origin_name(candidate):
                    matches.append((loc, candidate))
            idx = loc + len(pref)

    deduped: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for entry in matches:
        if entry not in seen:
            deduped.append(entry)
            seen.add(entry)
    deduped.sort(key=lambda item: item[0])
    return tuple(deduped)


def _derive_source_path(name: str) -> str:
    if "/" in name or "\\" in name:
        parts = tuple(_sanitize_path_segment(part) for part in re.split(r"[\\\\/]+", name))
        parts = tuple(part for part in parts if part)
        if len(parts) >= 2:
            return "/".join(parts)
        return f"object/{parts[0]}" if parts else "object/item"

    prefixed = _split_liborigin_prefixed_name(name)
    if prefixed is not None:
        return f"{prefixed}/{_sanitize_path_segment(name[2:])}"

    if name.startswith("__"):
        return f"meta/{_sanitize_path_segment(name)}"

    if "_" in name:
        head, tail = name.split("_", 1)
        if head and tail:
            alpha_numeric_head = re.fullmatch(r"([A-Za-z]+)(\d+)", head)
            if alpha_numeric_head is None:
                return f"{_sanitize_path_segment(head)}/{_sanitize_path_segment(name)}"
            return f"{_sanitize_path_segment(alpha_numeric_head.group(1))}/{_sanitize_path_segment(name)}"

    for prefix in KNOWN_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            return f"{_sanitize_path_segment(prefix)}/{_sanitize_path_segment(name)}"

    if len(name) > 1 and name[0].isalpha():
        return f"object/{_sanitize_path_segment(name)}"

    return f"object/{_sanitize_path_segment('item_' + name)}"


def _split_liborigin_prefixed_name(name: str) -> str | None:
    if not name or len(name) < 3:
        return None
    prefix = name[0].lower()
    if name[1] != "_":
        return None
    return _PREFIX_KIND_MAP.get(prefix)


def _append_token_object_offsets(
    token: str,
    chunk_base: int,
    match: re.Match[bytes],
    *,
    out: list[OriginObject],
    name_hits: dict[str, int] | None = None,
    max_repeats_per_name: int | None = None,
    kind_hits: dict[str, int] | None = None,
    heuristic_kind_limit: int | None = None,
    allowed_kinds: frozenset[str] | None = None,
) -> None:
    for name_offset, name in _extract_embedded_origin_name_offsets(
        token,
        allowed_kinds=allowed_kinds,
    ):
        if _is_plausible_origin_name(name):
            _append_heuristic_discovery_record(
                name,
                chunk_base + match.start() + name_offset,
                len(name),
                out=out,
                object_kind=_classify_object_kind(name),
                heuristic_signal="token_scan",
                name_hits=name_hits,
                max_repeats_per_name=max_repeats_per_name,
                kind_hits=kind_hits,
                heuristic_kind_limit=heuristic_kind_limit,
                allowed_kinds=allowed_kinds,
            )


def _append_bracket_match_record(
    match: re.Match[bytes],
    *,
    chunk_base: int,
    out: list[OriginObject],
    name_hits: dict[str, int] | None = None,
    max_repeats_per_name: int | None = None,
    kind_hits: dict[str, int] | None = None,
    heuristic_kind_limit: int | None = None,
    allowed_kinds: frozenset[str] | None = None,
) -> bool:
    container = match.group(1).decode("ascii", errors="ignore")
    item = match.group(2).decode("ascii", errors="ignore")
    if not item or not _is_plausible_origin_name(container):
        return False
    return _append_heuristic_discovery_record(
        f"{container}/{item}",
        chunk_base + match.start(),
        match.end() - match.start(),
        out=out,
        object_kind=None,
        heuristic_signal="bracket_scan",
        name_hits=name_hits,
        max_repeats_per_name=max_repeats_per_name,
        kind_hits=kind_hits,
        heuristic_kind_limit=heuristic_kind_limit,
        allowed_kinds=allowed_kinds,
    )


def _token_offsets_from_file(
    path: Path,
    *,
    chunk_size: int = _OPJ_DISCOVERY_STREAM_CHUNK_SIZE,
    max_repeats_per_name: int | None = None,
    heuristic_kind_limit: int | None = None,
    kind_hits: dict[str, int] | None = None,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    with open_mmap(path) as mapped:
        if mapped is not None:
            return _token_offsets_from_buffer(
                mapped,
                max_repeats_per_name=max_repeats_per_name,
                heuristic_kind_limit=heuristic_kind_limit,
                kind_hits=kind_hits,
                allowed_kinds=allowed_kinds,
                total_limit=total_limit,
            )

    return _token_offsets_from_stream(
        path,
        chunk_size=chunk_size,
        max_repeats_per_name=max_repeats_per_name,
        heuristic_kind_limit=heuristic_kind_limit,
        kind_hits=kind_hits,
        allowed_kinds=allowed_kinds,
        total_limit=total_limit,
    )


def _scan_token_matches_in_chunk(
    chunk: bytes,
    *,
    carry_len: int,
    chunk_base: int,
    out: list[OriginObject],
    name_hits: dict[str, int] | None,
    max_repeats_per_name: int | None,
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
    allowed_kinds: frozenset[str] | None,
    total_limit: int | None,
) -> tuple[bytes, bool, bool]:
    for match in _TOK_PATTERN.finditer(chunk):
        if match.end() == len(chunk):
            carry = chunk[match.start() :]
            if len(carry) > _OPJ_TOKEN_CARRY_BYTES:
                carry = carry[-_OPJ_TOKEN_CARRY_BYTES:]
            return carry, False, bool(carry)
        if match.start() < carry_len and match.end() <= carry_len:
            continue

        token = match.group().decode("ascii", errors="ignore")
        _append_token_object_offsets(
            token,
            chunk_base,
            match,
            out=out,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
        )
        if _discovery_limit_reached(
            out,
            kind_hits=kind_hits,
            total_limit=total_limit,
            heuristic_kind_limit=heuristic_kind_limit,
        ):
            return b"", True, False
    return b"", False, False


def _scan_bracket_matches_in_chunk(
    chunk: bytes,
    *,
    carry_len: int,
    chunk_base: int,
    out: list[OriginObject],
    name_hits: dict[str, int] | None,
    max_repeats_per_name: int | None,
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
    allowed_kinds: frozenset[str] | None,
    total_limit: int | None,
) -> tuple[bytes, bool, bool]:
    for match in _BRACKET_REF_PATTERN.finditer(chunk):
        if match.end() == len(chunk):
            carry = chunk[match.start() :]
            if len(carry) > _OPJ_BRACKET_CARRY_BYTES:
                carry = carry[-_OPJ_BRACKET_CARRY_BYTES:]
            return carry, False, True

        if match.start() < carry_len and match.end() <= carry_len:
            continue

        if _append_bracket_match_record(
            match,
            chunk_base=chunk_base,
            out=out,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
        ):
            if _discovery_limit_reached(
                out,
                kind_hits=kind_hits,
                total_limit=total_limit,
                heuristic_kind_limit=heuristic_kind_limit,
            ):
                return b"", True, False
    carry = chunk[-min(len(chunk), _OPJ_BRACKET_CARRY_BYTES) :]
    return carry, False, False


def _discovery_limit_reached(
    items: list[OriginObject],
    *,
    kind_hits: dict[str, int] | None,
    total_limit: int | None,
    heuristic_kind_limit: int | None,
) -> bool:
    if total_limit is not None and len(items) >= total_limit:
        return True
    return _heuristic_kind_limits_reached(kind_hits, heuristic_kind_limit)


def _drain_matches_for_discovery(
    data: bytes,
    *,
    matcher: re.Pattern[bytes],
    append_match: Callable[[re.Match[bytes]], bool],
) -> bool:
    for match in matcher.finditer(data):
        if append_match(match):
            return True
    return False


def _token_matches_reached_limit(
    data: bytes,
    *,
    chunk_base: int,
    out: list[OriginObject],
    name_hits: dict[str, int] | None,
    max_repeats_per_name: int | None,
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
    allowed_kinds: frozenset[str] | None,
    total_limit: int | None,
) -> bool:
    def _append(match: re.Match[bytes]) -> bool:
        token = match.group().decode("ascii", errors="ignore")
        _append_token_object_offsets(
            token,
            chunk_base,
            match,
            out=out,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
        )
        return _discovery_limit_reached(
            out,
            kind_hits=kind_hits,
            total_limit=total_limit,
            heuristic_kind_limit=heuristic_kind_limit,
        )

    return _drain_matches_for_discovery(
        data,
        matcher=_TOK_PATTERN,
        append_match=_append,
    )


def _bracket_matches_reached_limit(
    data: bytes,
    *,
    chunk_base: int,
    out: list[OriginObject],
    name_hits: dict[str, int] | None,
    max_repeats_per_name: int | None,
    kind_hits: dict[str, int] | None,
    heuristic_kind_limit: int | None,
    allowed_kinds: frozenset[str] | None,
    total_limit: int | None,
) -> bool:
    def _append(match: re.Match[bytes]) -> bool:
        _append_bracket_match_record(
            match,
            chunk_base=chunk_base,
            out=out,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
        )
        return _discovery_limit_reached(
            out,
            kind_hits=kind_hits,
            total_limit=total_limit,
            heuristic_kind_limit=heuristic_kind_limit,
        )

    return _drain_matches_for_discovery(
        data,
        matcher=_BRACKET_REF_PATTERN,
        append_match=_append,
    )


def _scan_discovery_stream(
    path: Path,
    *,
    chunk_size: int,
    scan_chunk: Callable[..., tuple[bytes, bool, bool]],
    drain_tail: Callable[..., bool],
    max_repeats_per_name: int | None = None,
    heuristic_kind_limit: int | None = None,
    kind_hits: dict[str, int] | None = None,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    items: list[OriginObject] = []
    name_hits: dict[str, int] | None = {} if max_repeats_per_name is not None else None
    if heuristic_kind_limit is not None and kind_hits is None:
        kind_hits = {}
    carry = b""
    offset = 0
    should_scan_tail = False
    exhausted = False

    for block in iter_file_chunks(path, chunk_size=chunk_size):
        chunk = carry + block
        chunk_base = max(0, offset - len(carry))
        carry, exhausted, should_scan_tail = scan_chunk(
            chunk,
            carry_len=len(carry),
            chunk_base=chunk_base,
            out=items,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
            total_limit=total_limit,
        )
        if exhausted:
            return items
        offset += len(block)

    if should_scan_tail and carry:
        if drain_tail(
            carry,
            chunk_base=max(0, offset - len(carry)),
            out=items,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
            total_limit=total_limit,
        ):
            return items

    return items


def _token_offsets_from_buffer(
    data: bytes | mmap.mmap,
    *,
    max_repeats_per_name: int | None = None,
    heuristic_kind_limit: int | None = None,
    kind_hits: dict[str, int] | None = None,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    objects: list[OriginObject] = []
    name_hits: dict[str, int] | None = {} if max_repeats_per_name is not None else None
    if heuristic_kind_limit is not None and kind_hits is None:
        kind_hits = {}

    for match in _TOK_PATTERN.finditer(data):
        token = match.group().decode("ascii", errors="ignore")
        _append_token_object_offsets(
            token,
            0,
            match,
            out=objects,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
        )
        if total_limit is not None and len(objects) >= total_limit:
            break
        if _heuristic_kind_limits_reached(kind_hits, heuristic_kind_limit):
            break

    return objects


def _token_offsets_from_stream(
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
        scan_chunk=_scan_token_matches_in_chunk,
        drain_tail=_token_matches_reached_limit,
        max_repeats_per_name=max_repeats_per_name,
        heuristic_kind_limit=heuristic_kind_limit,
        kind_hits=kind_hits,
        allowed_kinds=allowed_kinds,
        total_limit=total_limit,
    )


def _token_offsets(data: bytes) -> list[OriginObject]:
    objects: list[OriginObject] = []
    for match in _TOK_PATTERN.finditer(data):
        token = match.group().decode("ascii", errors="ignore")
        _append_token_object_offsets(token, 0, match, out=objects)
    return objects


def _bracket_offsets(data: bytes) -> list[OriginObject]:
    objects: list[OriginObject] = []
    for match in _BRACKET_REF_PATTERN.finditer(data):
        _append_bracket_match_record(
            match,
            chunk_base=0,
            out=objects,
        )
    return objects


def _bracket_offsets_from_file(
    path: Path,
    *,
    chunk_size: int = _OPJ_DISCOVERY_STREAM_CHUNK_SIZE,
    max_repeats_per_name: int | None = None,
    heuristic_kind_limit: int | None = None,
    kind_hits: dict[str, int] | None = None,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    with open_mmap(path) as mapped:
        if mapped is not None:
            return _bracket_offsets_from_buffer(
                mapped,
                max_repeats_per_name=max_repeats_per_name,
                heuristic_kind_limit=heuristic_kind_limit,
                kind_hits=kind_hits,
                allowed_kinds=allowed_kinds,
                total_limit=total_limit,
            )

    from deopjufier.discovery_windows import _bracket_offsets_from_stream

    return _bracket_offsets_from_stream(
        path,
        chunk_size=chunk_size,
        max_repeats_per_name=max_repeats_per_name,
        heuristic_kind_limit=heuristic_kind_limit,
        kind_hits=kind_hits,
        allowed_kinds=allowed_kinds,
        total_limit=total_limit,
    )


def _bracket_offsets_from_buffer(
    data: bytes | mmap.mmap,
    *,
    max_repeats_per_name: int | None = None,
    heuristic_kind_limit: int | None = None,
    kind_hits: dict[str, int] | None = None,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    objects: list[OriginObject] = []
    name_hits: dict[str, int] | None = {} if max_repeats_per_name is not None else None
    if heuristic_kind_limit is not None and kind_hits is None:
        kind_hits = {}

    for match in _BRACKET_REF_PATTERN.finditer(data):
        _append_bracket_match_record(
            match,
            chunk_base=0,
            out=objects,
            name_hits=name_hits,
            max_repeats_per_name=max_repeats_per_name,
            kind_hits=kind_hits,
            heuristic_kind_limit=heuristic_kind_limit,
            allowed_kinds=allowed_kinds,
        )
        if total_limit is not None and len(objects) >= total_limit:
            break
        if _heuristic_kind_limits_reached(kind_hits, heuristic_kind_limit):
            break

    return objects


__all__ = [name for name in globals() if not name.startswith("__")]
