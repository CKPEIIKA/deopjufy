"""Shared OPJU region discovery helpers.

The parser relies on a small number of primitives that are repeated in multiple
OPJU modules today: locating `<OriginStorage>` regions and probing raw bytes in
front of them as potential LZ4-compressed payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .lz4 import lz4_block_decompress

_ORIGIN_STORAGE_OPEN_TAG = b"<originstorage"
_ORIGIN_STORAGE_CLOSE_TAG = b"</originstorage>"
_ORIGIN_STORAGE_OPEN_TAG_BYTES = b"<OriginStorage"
_ORIGIN_STORAGE_CLOSE_TAG_BYTES = b"</OriginStorage>"
_MAX_LZ4_EXPECTED_SIZE = 16_000_000
_OPJU_FAMILY_SIGNATURE_MARKERS = (
    b"\x00\x00\x00\x00\x03\x00\x00\x00\x10\x00\x00\x00",
    b"\x77\x11\x11\x11",
    b"\x72\x11\x11\x11",
)
_OPJU_FAMILY_MARKER_SCAN_LEAD_BYTES = 64
_OPJU_FAMILY_MARKER_SCAN_TRAIL_BYTES = 64
_OPJU_FAMILY_MARKER_STREAM_OFFSETS = (4, 6, 8, 10, 12, 14, 16, 18, 20)
_OPJU_FAMILY_MARKER_HEADER_HINTS = {
    _OPJU_FAMILY_SIGNATURE_MARKERS[0]: ((-6, 4),),
    _OPJU_FAMILY_SIGNATURE_MARKERS[1]: ((-6, 4),),
    _OPJU_FAMILY_SIGNATURE_MARKERS[2]: ((-5, 4),),
}
_OPJU_FAMILY_FRAMING_INFERENCE_SCAN_LIMIT = 2000


class _FamilyFramingHypothesis(TypedDict):
    marker: bytes
    header_delta: int
    stream_offset: int
    matched_markers: int
    total_markers: int
    coverage: float
    marker_offsets: list[int]


def _looks_like_origin_payload(payload: bytes) -> bool:
    trimmed = payload.lstrip(b"\x00\x1f\x1e\x1d\x1c\x1b\x1a\t\r\n ")
    if not trimmed.startswith(b"<"):
        return False
    if b"\x00" in trimmed[:2048]:
        return False

    close_index = trimmed.find(b">")
    if close_index <= 0:
        return False

    return trimmed[: close_index + 1].rstrip() != b""


@dataclass(frozen=True)
class OpjuOriginStorageCandidate:
    source_kind: str
    source_start: int
    source_end: int
    payload_start: int
    payload_end: int
    payload: bytes
    decompressed_size: int | None = None
    consumed_compressed_bytes: int | None = None
    compression: str | None = None
    family_marker: bytes | None = None
    marker_offset: int | None = None
    header_offset: int | None = None
    stream_offset: int | None = None
    framing_rule: str | None = None


def _is_self_closing_tag(data: bytes, close_offset: int) -> bool:
    return close_offset > 0 and data[close_offset - 1] == 0x2F


def find_matching_origin_storage_close(data: bytes, start: int, lower_data: bytes | None = None) -> int:
    open_end = data.find(b">", start + len(_ORIGIN_STORAGE_OPEN_TAG_BYTES))
    if open_end < 0:
        return -1
    if _is_self_closing_tag(data, open_end):
        return open_end + 1

    normalized = lower_data if lower_data is not None else data.lower()
    depth = 1
    cursor = open_end + 1
    while cursor < len(data):
        next_open = normalized.find(_ORIGIN_STORAGE_OPEN_TAG, cursor)
        next_close = normalized.find(_ORIGIN_STORAGE_CLOSE_TAG, cursor)
        if next_close < 0:
            return -1

        if next_open != -1 and next_open < next_close:
            nested_end = data.find(b">", next_open + len(_ORIGIN_STORAGE_OPEN_TAG_BYTES))
            if nested_end < 0:
                cursor = next_open + 1
                continue
            if not _is_self_closing_tag(data, nested_end):
                depth += 1
            cursor = nested_end + 1
            continue

        cursor = next_close + len(_ORIGIN_STORAGE_CLOSE_TAG_BYTES)
        depth -= 1
        if depth == 0:
            return cursor
        if depth < 0:
            return -1

    return -1


def _iter_origin_storage_raw_regions(data: bytes) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    normalized = data.lower()
    scan_pos = 0
    while True:
        start = normalized.find(_ORIGIN_STORAGE_OPEN_TAG, scan_pos)
        if start < 0:
            break
        end = find_matching_origin_storage_close(data, start, lower_data=normalized)
        if end < 0:
            fallback = data.lower().find(_ORIGIN_STORAGE_CLOSE_TAG, start + len(_ORIGIN_STORAGE_OPEN_TAG))
            if fallback < 0:
                scan_pos = start + len(_ORIGIN_STORAGE_OPEN_TAG)
                continue
            end = fallback + len(_ORIGIN_STORAGE_CLOSE_TAG)
        regions.append((start, end))
        scan_pos = end
    return regions


def _iter_lz4_candidates(data: bytes, raw_start: int) -> list[OpjuOriginStorageCandidate]:
    if raw_start < 6:
        return []

    declared_size = int.from_bytes(data[raw_start - 6 : raw_start - 2], "little")
    if declared_size <= 0 or declared_size > _MAX_LZ4_EXPECTED_SIZE:
        return []

    block_start = raw_start - 2
    if block_start >= len(data):
        return []

    try:
        decoded, consumed = lz4_block_decompress(data[block_start:], declared_size)
    except ValueError:
        return []
    if not decoded.lower().startswith(_ORIGIN_STORAGE_OPEN_TAG):
        return []

    return [
        OpjuOriginStorageCandidate(
            source_kind="decoded",
            source_start=block_start,
            source_end=block_start + consumed,
            payload_start=0,
            payload_end=len(decoded),
            payload=decoded,
            decompressed_size=declared_size,
            consumed_compressed_bytes=consumed,
            compression="lz4-block",
            header_offset=raw_start - 6,
            stream_offset=4,
            framing_rule="origin_storage_anchor",
        )
    ]


def _iter_opju_family_signature_positions(data: bytes) -> list[int]:
    positions: list[int] = []
    for marker in _OPJU_FAMILY_SIGNATURE_MARKERS:
        scan_pos = 0
        while True:
            found = data.find(marker, scan_pos)
            if found < 0:
                break
            positions.append(found)
            scan_pos = found + 1
    return sorted(set(positions))


def _iter_opju_family_lz4_candidates(
    data: bytes,
    marker_position: int,
    marker: bytes,
    *,
    framing_hints: list[tuple[int, int]] | None = None,
    header_delta_hint: int | None = None,
    stream_offset_hint: int | None = None,
    require_origin_payload: bool = True,
    framing_rule: str = "family_marker_scan",
) -> list[OpjuOriginStorageCandidate]:
    """Decode candidate OPJU regions using non-`<OriginStorage>` family markers."""
    if marker_position < 0 or marker_position + len(marker) > len(data):
        return []

    scan_starts: list[tuple[int, tuple[int, ...]]] = []
    if framing_hints is not None:
        scan_starts = [
            (marker_position + header_delta, (stream_offset,)) for header_delta, stream_offset in framing_hints
        ]
    elif header_delta_hint is not None and stream_offset_hint is not None:
        scan_starts = [(marker_position + header_delta_hint, (stream_offset_hint,))]

    if not scan_starts:
        scan_starts = [
            (header_start, _OPJU_FAMILY_MARKER_STREAM_OFFSETS)
            for header_start in range(
                max(0, marker_position - _OPJU_FAMILY_MARKER_SCAN_LEAD_BYTES),
                min(
                    len(data) - 4,
                    marker_position + max(len(marker), _OPJU_FAMILY_MARKER_SCAN_TRAIL_BYTES),
                )
                + 1,
            )
        ]

    if not scan_starts:
        return []

    candidates: list[OpjuOriginStorageCandidate] = []
    seen_starts: set[tuple[int, int]] = set()

    for header_start, stream_offsets in scan_starts:
        if header_start < 0 or header_start + 4 > len(data):
            continue
        declared_size = int.from_bytes(data[header_start : header_start + 4], "little")
        if declared_size <= 0 or declared_size > _MAX_LZ4_EXPECTED_SIZE:
            continue

        for stream_offset in stream_offsets:
            block_start = header_start + stream_offset
            if block_start <= header_start or block_start >= len(data):
                continue
            try:
                decoded, consumed = lz4_block_decompress(data[block_start:], declared_size)
            except ValueError:
                continue
            if require_origin_payload and not _looks_like_origin_payload(decoded):
                continue

            key = (block_start, block_start + consumed)
            if key in seen_starts:
                continue
            candidates.append(
                OpjuOriginStorageCandidate(
                    source_kind="decoded",
                    source_start=block_start,
                    source_end=block_start + consumed,
                    payload_start=0,
                    payload_end=len(decoded),
                    payload=decoded,
                    decompressed_size=declared_size,
                    consumed_compressed_bytes=consumed,
                    compression="lz4-block",
                    family_marker=marker,
                    marker_offset=marker_position,
                    header_offset=header_start,
                    stream_offset=stream_offset,
                    framing_rule=framing_rule,
                )
            )
            seen_starts.add(key)
            break

    candidates.sort(key=lambda item: item.source_start)
    return candidates


def _infer_family_framing_hypotheses(
    data: bytes, *, require_origin_payload: bool = True
) -> list[_FamilyFramingHypothesis]:
    """Infer candidate header/stream framing hypotheses from known family markers."""
    marker_positions = _iter_opju_signature_and_marker_positions(data)
    if not marker_positions:
        return []

    marker_totals = {marker: 0 for marker in _OPJU_FAMILY_SIGNATURE_MARKERS}
    for _, marker in marker_positions:
        marker_totals[marker] = marker_totals.get(marker, 0) + 1

    hits: dict[tuple[bytes, int, int], set[int]] = {}

    for marker_position, marker in marker_positions:
        for header_delta, stream_offset in _OPJU_FAMILY_MARKER_HEADER_HINTS.get(marker, ()):
            header_start = marker_position + header_delta
            if header_start + 4 > len(data) or header_start <= 0:
                continue

            declared_size = int.from_bytes(data[header_start : header_start + 4], "little")
            if declared_size <= 0 or declared_size > _MAX_LZ4_EXPECTED_SIZE:
                continue
            block_start = header_start + stream_offset
            if block_start <= header_start or block_start >= len(data):
                continue

            try:
                decoded, _ = lz4_block_decompress(data[block_start:], declared_size)
            except ValueError:
                continue
            if require_origin_payload and not _looks_like_origin_payload(decoded):
                continue

            key = (marker, header_delta, stream_offset)
            marker_offsets = hits.setdefault(key, set())
            marker_offsets.add(marker_position)

    scan_positions = 0
    scan_limit = _OPJU_FAMILY_FRAMING_INFERENCE_SCAN_LIMIT
    for marker_position, marker in marker_positions:
        for header_start in range(
            max(0, marker_position - _OPJU_FAMILY_MARKER_SCAN_LEAD_BYTES),
            min(
                len(data) - 4,
                marker_position + max(len(marker), _OPJU_FAMILY_MARKER_SCAN_TRAIL_BYTES),
            )
            + 1,
        ):
            header_delta = header_start - marker_position
            scan_positions += 1
            if scan_limit is not None and scan_positions > scan_limit:
                break

            declared_size = int.from_bytes(data[header_start : header_start + 4], "little")
            if declared_size <= 0 or declared_size > _MAX_LZ4_EXPECTED_SIZE:
                continue

            for stream_offset in _OPJU_FAMILY_MARKER_STREAM_OFFSETS:
                block_start = header_start + stream_offset
                if block_start <= header_start or block_start >= len(data):
                    continue

                try:
                    decoded, _ = lz4_block_decompress(data[block_start:], declared_size)
                except ValueError:
                    continue
                if require_origin_payload and not _looks_like_origin_payload(decoded):
                    continue

                key = (marker, header_delta, stream_offset)
                marker_offsets = hits.setdefault(key, set())
                marker_offsets.add(marker_position)
                break
        if scan_limit is not None and scan_positions > scan_limit:
            break

    hypotheses: list[_FamilyFramingHypothesis] = []
    for (marker, header_delta, stream_offset), marker_offsets in hits.items():
        total = marker_totals.get(marker, 0)
        if total <= 0:
            continue
        hypotheses.append(
            {
                "marker": marker,
                "header_delta": header_delta,
                "stream_offset": stream_offset,
                "matched_markers": len(marker_offsets),
                "total_markers": total,
                "coverage": len(marker_offsets) / total,
                "marker_offsets": sorted(marker_offsets),
            }
        )

    hypotheses.sort(
        key=lambda item: (
            -float(item["coverage"]),
            -int(item["matched_markers"]),
            int(item["header_delta"]),
            int(item["stream_offset"]),
        )
    )
    return hypotheses


def _iter_opju_signature_and_marker_positions(
    data: bytes,
) -> list[tuple[int, bytes]]:
    positions: list[tuple[int, bytes]] = []
    for marker in _OPJU_FAMILY_SIGNATURE_MARKERS:
        scan_pos = 0
        while True:
            found = data.find(marker, scan_pos)
            if found < 0:
                break
            positions.append((found, marker))
            scan_pos = found + 1
    return sorted(positions, key=lambda item: item[0])


def _iter_opju_family_framing_for_markers(
    data: bytes, *, require_origin_payload: bool = True
) -> list[tuple[bytes, int, int]]:
    """Return framing hypotheses with full coverage from marker signatures."""
    hypotheses = _infer_family_framing_hypotheses(
        data,
        require_origin_payload=require_origin_payload,
    )
    return [
        (
            entry["marker"],
            int(entry["header_delta"]),
            int(entry["stream_offset"]),
        )
        for entry in hypotheses
        if entry["coverage"] >= 1.0 and entry["matched_markers"] > 0
    ]


def iter_origin_storage_candidates(
    data: bytes,
    *,
    include_decoded: bool = True,
    include_family_binary: bool = False,
) -> list[OpjuOriginStorageCandidate]:
    """Enumerate raw and decoded `OriginStorage` payload candidates in order."""
    if not data.startswith(b"CPYUA"):
        return []

    candidates: list[OpjuOriginStorageCandidate] = []
    has_decoded_candidate = False
    seen: set[tuple[int, int, str]] = set()

    for start, end in _iter_origin_storage_raw_regions(data):
        raw_key = (start, end, "raw")
        if raw_key not in seen:
            candidates.append(
                OpjuOriginStorageCandidate(
                    source_kind="raw",
                    source_start=start,
                    source_end=end,
                    payload_start=0,
                    payload_end=end - start,
                    payload=data[start:end],
                )
            )
            seen.add(raw_key)

        if include_decoded:
            for decoded in _iter_lz4_candidates(data, start):
                key = (decoded.source_start, decoded.source_end, "decoded")
                if key not in seen:
                    candidates.append(decoded)
                    seen.add(key)
                    has_decoded_candidate = True

    if include_decoded:
        allow_family = include_family_binary or not has_decoded_candidate
        if allow_family:
            framing_hints = _iter_opju_family_framing_for_markers(
                data,
                require_origin_payload=not include_family_binary,
            )
            hints_by_marker: dict[bytes, list[tuple[int, int]]] = {}
            for marker, header_delta, stream_offset in framing_hints:
                if marker is None:
                    continue
                pair = (int(header_delta), int(stream_offset))
                marker_hints = hints_by_marker.setdefault(marker, [])
                if pair not in marker_hints:
                    marker_hints.append(pair)
            # Keep explicit constant hints as a fast fallback for known signatures.
            for marker, fallback_pairs in _OPJU_FAMILY_MARKER_HEADER_HINTS.items():
                for fallback_header_delta, fallback_stream_offset in fallback_pairs:
                    pair = (fallback_header_delta, fallback_stream_offset)
                    marker_hints = hints_by_marker.setdefault(marker, [])
                    if pair not in marker_hints:
                        marker_hints.append(pair)

            for marker_position in _iter_opju_family_signature_positions(data):
                marker = b""
                for known_marker in _OPJU_FAMILY_SIGNATURE_MARKERS:
                    if data[marker_position : marker_position + len(known_marker)] == known_marker:
                        marker = known_marker
                        break
                if not marker:
                    continue

                canonical_hints = list(_OPJU_FAMILY_MARKER_HEADER_HINTS.get(marker, ()))
                marker_hints = [(hint, "canonical_family_marker") for hint in canonical_hints]
                for inferred_hint in hints_by_marker.get(marker, ()):
                    if inferred_hint not in canonical_hints:
                        marker_hints.append((inferred_hint, "inferred_family_marker"))

                # One marker denotes one framed payload. Prefer the framing that
                # repeats across the audited corpus, then try inferred alternatives
                # one at a time. This avoids admitting nested/shifted LZ4 parses
                # when several hypotheses happen to decode at the same marker.
                for marker_hint, framing_rule in marker_hints:
                    decoded_candidates = _iter_opju_family_lz4_candidates(
                        data,
                        marker_position,
                        marker,
                        framing_hints=[marker_hint],
                        require_origin_payload=not include_family_binary,
                        framing_rule=framing_rule,
                    )
                    if not decoded_candidates:
                        continue
                    for decoded in decoded_candidates:
                        key = (
                            decoded.source_start,
                            decoded.source_end,
                            decoded.source_kind,
                        )
                        if key not in seen:
                            candidates.append(decoded)
                            seen.add(key)
                    break

    candidates.sort(key=lambda item: (item.source_start, item.payload_start))
    return candidates
