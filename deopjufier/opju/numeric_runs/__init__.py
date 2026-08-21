"""Discover numeric blob-array runs inside decoded OPJU payloads."""

from __future__ import annotations

import base64
import binascii
import math
import re
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ..decoded import OpjuDecodedRegion
from ..regions import OpjuOriginStorageCandidate, iter_origin_storage_candidates

_KNOWN_FAMILY_MARKERS = (
    b"\x00\x00\x00\x00\x03\x00\x00\x00\x10\x00\x00\x00",
    b"\x77\x11\x11\x11",
    b"\x72\x11\x11\x11",
)
_BLOB_ARR_ELEMENTARY_TYPES: dict[str, tuple[int, str]] = {
    "1": (1, "u1"),
    "2": (2, "u2"),
    "3": (4, "u4"),
    "4": (4, "f4"),
    "5": (8, "f8"),
    "6": (8, "f8"),
}
_BASE64_BLOB_RUN_RE = re.compile(
    rb"<(?P<tag>[A-Za-z][A-Za-z0-9_:-]*)\b(?P<attrs>[^>]*)>(?P<data>[A-Za-z0-9+/=\s]+)</(?P=tag)>",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(
    rb"(?P<key>[A-Za-z_][A-Za-z0-9_:-]*)\s*=\s*(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<unquoted>[^\s>]+))"
)


@dataclass(frozen=True)
class OpjuNumericBlobRun:
    source_start: int
    source_end: int
    family_marker: str | None
    payload_offset: int
    primitive: str
    primitive_size: int
    run_length: int
    tag: str
    first_values: tuple[str, ...]


def _extract_xml_attributes(raw_attrs: bytes) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(raw_attrs):
        key = match.group("key")
        if key is None:
            continue

        value: bytes
        if match.group("dq") is not None:
            value = match.group("dq")
        elif match.group("sq") is not None:
            value = match.group("sq")
        else:
            assert match.group("unquoted") is not None
            value = match.group("unquoted")

        attrs[key.decode("utf-8", errors="ignore").lower()] = value.decode("utf-8", errors="ignore")
    return attrs


def _primitive_from_attributes(attrs: bytes) -> tuple[int, str] | None:
    normalized = _extract_xml_attributes(attrs)
    element_type = normalized.get("blobarrelementarytype")
    if not element_type:
        return None
    return _BLOB_ARR_ELEMENTARY_TYPES.get(element_type)


def _decode_first_values(raw: bytes, primitive_size: int) -> tuple[str, ...] | None:
    if primitive_size not in {1, 2, 4, 8} or len(raw) < primitive_size:
        return None
    if len(raw) % primitive_size != 0:
        return None

    total = len(raw) // primitive_size
    max_values = min(total, 4)
    if max_values <= 0:
        return None

    if primitive_size == 1:
        fmt = "<B"
    elif primitive_size == 2:
        fmt = "<H"
    elif primitive_size == 4:
        fmt = "<f"
    else:
        fmt = "<d"

    values: list[str] = []
    for index in range(max_values):
        try:
            value = struct.unpack_from(fmt, raw, index * primitive_size)[0]
        except (IndexError, struct.error):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        values.append(str(float(value)) if isinstance(value, float) else str(int(value)))

    return tuple(values)


def _iter_blob_runs(
    payload: bytes,
) -> Iterator[tuple[int, str, bytes, bytes, int, str]]:
    for match in _BASE64_BLOB_RUN_RE.finditer(payload):
        tag = match.group("tag").decode("utf-8", errors="ignore")
        attrs = match.group("attrs")
        raw_data = match.group("data")
        payload_offset = match.start("data")
        primitive = _primitive_from_attributes(attrs)
        if primitive is None:
            continue
        primitive_size, primitive_name = primitive
        yield (payload_offset, tag, attrs, raw_data, primitive_size, primitive_name)


def _normalize_family_marker(data: bytes, source_start: int) -> str | None:
    if source_start <= 0 or source_start > len(data):
        return None
    best: tuple[int, str] | None = None
    for marker in _KNOWN_FAMILY_MARKERS:
        marker_len = len(marker)
        scan_start = max(0, source_start - 64)
        scan_end = min(len(data), source_start + 64)
        offset = data.find(marker, scan_start, scan_end + marker_len)
        if offset < 0:
            continue
        delta = abs(offset - source_start)
        if best is None or delta < best[0]:
            best = (delta, marker.hex())
    return best[1] if best else None


def _iter_payload_runs(
    payload: bytes,
    *,
    source_start: int,
    source_end: int,
    family_marker: str | None,
) -> Iterator[OpjuNumericBlobRun]:
    for (
        payload_offset,
        tag,
        _attrs,
        raw_data,
        primitive_size,
        primitive,
    ) in _iter_blob_runs(payload):
        cleaned = b"".join(raw_data.split())
        if not cleaned:
            continue
        try:
            raw = base64.b64decode(cleaned, validate=True)
        except (binascii.Error, ValueError):
            continue

        values = _decode_first_values(raw, primitive_size)
        if values is None:
            continue

        run_length = len(raw) // primitive_size
        if run_length <= 0:
            continue

        yield OpjuNumericBlobRun(
            source_start=source_start,
            source_end=source_end,
            family_marker=family_marker,
            payload_offset=payload_offset,
            primitive=primitive,
            primitive_size=primitive_size,
            run_length=run_length,
            tag=tag,
            first_values=tuple(values),
        )


def _iter_candidate_runs(candidate: OpjuOriginStorageCandidate, source_data: bytes) -> Iterator[OpjuNumericBlobRun]:
    if not (0 <= candidate.payload_start < candidate.payload_end):
        return
    yield from _iter_payload_runs(
        candidate.payload,
        source_start=candidate.source_start,
        source_end=candidate.source_end,
        family_marker=_normalize_family_marker(source_data, candidate.source_start),
    )


def iter_opju_binary_runs_from_decoded_regions(
    regions: Iterable[OpjuDecodedRegion],
) -> list[OpjuNumericBlobRun]:
    """Return numeric blob-array runs from already-decoded OPJU regions."""
    runs: list[OpjuNumericBlobRun] = []
    for region in regions:
        runs.extend(
            _iter_payload_runs(
                region.payload,
                source_start=region.source_start,
                source_end=region.source_end,
                family_marker=region.family_marker,
            )
        )
    runs.sort(key=lambda item: (item.source_start, item.payload_offset))
    return runs


def iter_opju_binary_runs_from_file(
    data: bytes,
    *,
    include_family_binary: bool = True,
    include_decoded: bool = True,
    include_originstorage: bool = True,
) -> list[OpjuNumericBlobRun]:
    """Return numeric blob-array runs from decoded candidates."""
    if not data.startswith(b"CPYUA"):
        return []

    if not include_originstorage and not include_family_binary:
        return []

    candidates = tuple(
        iter_origin_storage_candidates(
            data,
            include_decoded=include_decoded,
            include_family_binary=include_family_binary,
        )
    )
    if not candidates:
        return []

    runs: list[OpjuNumericBlobRun] = []
    for candidate in candidates:
        if candidate.source_kind != "decoded":
            continue
        runs.extend(_iter_candidate_runs(candidate, data))

    runs.sort(key=lambda item: (item.source_start, item.payload_offset))
    return runs


__all__ = [
    "OpjuNumericBlobRun",
    "iter_opju_binary_runs_from_decoded_regions",
    "iter_opju_binary_runs_from_file",
]
