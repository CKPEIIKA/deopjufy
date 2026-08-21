#!/usr/bin/env python3
"""Survey OPJU files for LZ4-compressed regions and framing hypotheses."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deopjufier.opju.lz4 import lz4_block_decompress  # noqa: E402

_ORIGIN_STORAGE_OPEN_TAG = b"<originstorage"
_MAX_REGION_BYTES = 4_000_000
_OPJU_FAMILY_SIGNATURE_MARKERS = (
    b"\x00\x00\x00\x00\x03\x00\x00\x00\x10\x00\x00\x00",
    b"\x77\x11\x11\x11",
    b"\x72\x11\x11\x11",
)
_OPJU_FAMILY_MARKER_SCAN_LEAD_BYTES = 64
_OPJU_FAMILY_MARKER_SCAN_TRAIL_BYTES = 64
_STREAM_OFFSETS = tuple(range(2, 34, 2))


@dataclass(frozen=True)
class SurveyRegion:
    marker_kind: str
    marker_offset: int
    header_offset: int
    stream_offset: int
    source_start: int
    source_end: int
    declared_size: int
    consumed_compressed: int
    payload_preview: str


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


def _preview(payload: bytes, length: int = 80) -> str:
    head = payload[:length]
    return head.decode("utf-8", "replace").replace("\n", r"\\n").replace("\r", r"\\r")


def _iter_family_signature_positions(data: bytes) -> list[tuple[int, bytes]]:
    positions: list[tuple[int, bytes]] = []
    for marker in _OPJU_FAMILY_SIGNATURE_MARKERS:
        start = 0
        while True:
            found = data.find(marker, start)
            if found < 0:
                break
            positions.append((found, marker))
            start = found + 1
    positions.sort(key=lambda item: item[0])
    return positions


def _iter_origin_storage_candidates(
    data: bytes,
    *,
    require_origin_payload: bool,
    max_candidates: int | None,
) -> Iterable[SurveyRegion]:
    seen = 0
    lowered = data.lower()
    search_start = 0

    while True:
        tag_offset = lowered.find(_ORIGIN_STORAGE_OPEN_TAG, search_start)
        if tag_offset < 0:
            return

        header_offset = tag_offset - 6
        stream_offset = 4
        source_start = tag_offset - 2
        if source_start < 0:
            search_start = tag_offset + len(_ORIGIN_STORAGE_OPEN_TAG)
            continue

        declared_size = int.from_bytes(data[header_offset : header_offset + 4], "little")
        if not (0 < declared_size <= _MAX_REGION_BYTES):
            search_start = tag_offset + 1
            continue

        if header_offset < 0:
            search_start = tag_offset + 1
            continue

        try:
            decoded, consumed = lz4_block_decompress(
                data[source_start:],
                declared_size,
            )
        except ValueError:
            search_start = tag_offset + 1
            continue

        if require_origin_payload and not _looks_like_origin_payload(decoded):
            search_start = source_start + consumed
            continue

        yield SurveyRegion(
            marker_kind="origin_tag",
            marker_offset=tag_offset,
            header_offset=header_offset,
            stream_offset=stream_offset,
            source_start=source_start,
            source_end=source_start + consumed,
            declared_size=declared_size,
            consumed_compressed=consumed,
            payload_preview=_preview(decoded),
        )

        seen += 1
        if max_candidates is not None and seen >= max_candidates:
            return

        search_start = source_start + consumed


def _iter_family_candidates(
    data: bytes,
    *,
    require_origin_payload: bool,
    max_candidates: int | None,
) -> Iterable[SurveyRegion]:
    seen = 0
    for marker_offset, marker in _iter_family_signature_positions(data):
        scan_start = max(0, marker_offset - _OPJU_FAMILY_MARKER_SCAN_LEAD_BYTES)
        scan_end = min(
            len(data) - 4,
            marker_offset + max(len(marker), _OPJU_FAMILY_MARKER_SCAN_TRAIL_BYTES),
        )
        marker_found = False

        for header_offset in range(scan_start, scan_end + 1):
            declared_size = int.from_bytes(data[header_offset : header_offset + 4], "little")
            if not (0 < declared_size <= _MAX_REGION_BYTES):
                continue

            for stream_offset in _STREAM_OFFSETS:
                source_start = header_offset + stream_offset
                if source_start <= header_offset or source_start >= len(data):
                    continue
                try:
                    decoded, consumed = lz4_block_decompress(
                        data[source_start:],
                        declared_size,
                    )
                except ValueError:
                    continue
                if require_origin_payload and not _looks_like_origin_payload(decoded):
                    continue

                yield SurveyRegion(
                    marker_kind="family_marker",
                    marker_offset=marker_offset,
                    header_offset=header_offset,
                    stream_offset=stream_offset,
                    source_start=source_start,
                    source_end=source_start + consumed,
                    declared_size=declared_size,
                    consumed_compressed=consumed,
                    payload_preview=_preview(decoded),
                )

                marker_found = True
                seen += 1
                if max_candidates is not None and seen >= max_candidates:
                    return
                break

            if marker_found:
                break


def _infer_framing_hypotheses(data: bytes, *, require_origin_payload: bool) -> list[dict[str, Any]]:
    totals = Counter(bytes(marker) for _, marker in _iter_family_signature_positions(data))
    hits: dict[tuple[bytes, int, int], set[int]] = {}

    for marker_offset, marker in _iter_family_signature_positions(data):
        for header_offset in range(
            max(0, marker_offset - _OPJU_FAMILY_MARKER_SCAN_LEAD_BYTES),
            min(
                len(data) - 4,
                marker_offset + max(len(marker), _OPJU_FAMILY_MARKER_SCAN_TRAIL_BYTES),
            )
            + 1,
        ):
            declared_size = int.from_bytes(data[header_offset : header_offset + 4], "little")
            if not (0 < declared_size <= _MAX_REGION_BYTES):
                continue

            for stream_offset in _STREAM_OFFSETS:
                source_start = header_offset + stream_offset
                if source_start <= header_offset or source_start >= len(data):
                    continue
                try:
                    decoded, _ = lz4_block_decompress(
                        data[source_start:],
                        declared_size,
                    )
                except ValueError:
                    continue
                if require_origin_payload and not _looks_like_origin_payload(decoded):
                    continue

                key = (marker, header_offset - marker_offset, stream_offset)
                marker_offsets = hits.get(key)
                if marker_offsets is None:
                    hits[key] = {marker_offset}
                else:
                    marker_offsets.add(marker_offset)
                break

    hypotheses: list[dict[str, Any]] = []
    for (marker, header_delta, stream_offset), marker_offsets in hits.items():
        total = totals[marker]
        if total <= 0:
            continue
        hypotheses.append(
            {
                "marker_hex": marker.hex(" "),
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
            -item["coverage"],
            -item["matched_markers"],
            item["header_delta"],
            item["stream_offset"],
        )
    )
    return hypotheses


def _run_survey(
    path: Path,
    *,
    max_candidates: int | None,
    include_family: bool,
    include_originstorage: bool,
    require_origin_payload: bool,
    infer_framing: bool,
    emit_json: bool,
) -> int:
    data = path.read_bytes()

    regions: list[SurveyRegion] = []
    if include_originstorage:
        regions.extend(
            _iter_origin_storage_candidates(
                data,
                require_origin_payload=require_origin_payload,
                max_candidates=max_candidates,
            )
        )
    if include_family:
        remaining = None if max_candidates is None else max(0, max_candidates - len(regions))
        regions.extend(
            _iter_family_candidates(
                data,
                require_origin_payload=require_origin_payload,
                max_candidates=remaining,
            )
        )

    if emit_json:
        payload = {
            "path": str(path),
            "records": [
                {
                    "marker_kind": region.marker_kind,
                    "marker_offset": region.marker_offset,
                    "header_offset": region.header_offset,
                    "stream_offset": region.stream_offset,
                    "source_start": region.source_start,
                    "source_end": region.source_end,
                    "declared_size": region.declared_size,
                    "consumed_compressed": region.consumed_compressed,
                    "payload_preview": region.payload_preview,
                }
                for region in regions
            ],
            "total": len(regions),
        }
        if infer_framing:
            payload["framing_hypotheses"] = _infer_framing_hypotheses(
                data,
                require_origin_payload=require_origin_payload,
            )
        print(json.dumps(payload, indent=2))
        return 0

    for region in regions:
        print(
            f"kind={region.marker_kind} marker_offset={region.marker_offset} "
            f"header_offset={region.header_offset} stream_offset={region.stream_offset} "
            f"declared={region.declared_size} consumed={region.consumed_compressed} "
            f"source={region.source_start}:{region.source_end} "
            f"preview={region.payload_preview}"
        )

    if infer_framing:
        hypotheses = _infer_framing_hypotheses(
            data,
            require_origin_payload=require_origin_payload,
        )
        print(f"framing_hypotheses={len(hypotheses)}")
        for index, hypothesis in enumerate(hypotheses[:20], start=1):
            print(
                f"[{index:02d}] marker={hypothesis['marker_hex']} "
                f"header_delta={hypothesis['header_delta']:+d} "
                f"stream={hypothesis['stream_offset']} "
                f"coverage={hypothesis['matched_markers']}/{hypothesis['total_markers']} "
                f"({hypothesis['coverage']:.2%})"
            )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to an .opju file")
    parser.add_argument("--max", type=int, default=None, help="Stop after N matches")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    parser.add_argument(
        "--family-only",
        action="store_true",
        help="Only scan family markers",
    )
    parser.add_argument(
        "--origin-only",
        action="store_true",
        help="Only scan <OriginStorage>-tag anchored regions",
    )
    parser.add_argument(
        "--no-origin-filter",
        action="store_true",
        help="Allow any LZ4-decodable payload while scanning",
    )
    parser.add_argument(
        "--infer-framing",
        action="store_true",
        help="Infer framing hypotheses across family signatures",
    )

    args = parser.parse_args()
    include_family = True
    include_originstorage = True
    if args.family_only:
        include_originstorage = False
    if args.origin_only:
        include_family = False

    return _run_survey(
        args.path,
        max_candidates=args.max,
        include_family=include_family,
        include_originstorage=include_originstorage,
        require_origin_payload=not args.no_origin_filter,
        infer_framing=args.infer_framing,
        emit_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
