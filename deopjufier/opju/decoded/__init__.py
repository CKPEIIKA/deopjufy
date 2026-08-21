"""Typed access to deterministically decoded OPJU LZ4 regions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from deopjufier.opju.analysis import analyze_origin_storage_candidates
from deopjufier.opju.common import MAGIC_OPJU
from deopjufier.opju.decoded.payloads import OpjuDecodedPayload, classify_decoded_payload
from deopjufier.opju.regions import iter_origin_storage_candidates
from deopjufier.strings import iter_strings


@dataclass(frozen=True)
class OpjuDecodedRegion:
    """A decoded payload and the exact compressed source span that produced it."""

    source_start: int
    source_end: int
    decoded_length: int
    payload: bytes
    region_kind: str
    label: str | None
    extension: str
    compression: str
    declared_decoded_length: int
    family_marker: str | None
    marker_offset: int | None
    header_offset: int | None
    stream_offset: int | None
    framing_rule: str
    classification: OpjuDecodedPayload

    @property
    def compressed_length(self) -> int:
        return self.source_end - self.source_start


@dataclass(frozen=True)
class OpjuDecodedString:
    """A printable string recovered from one decoded OPJU payload."""

    region_index: int
    source_start: int
    source_end: int
    string_index: int
    value: str


def _root_label(root: object) -> str | None:
    attributes = getattr(root, "attrib", None)
    if not isinstance(attributes, dict):
        return None
    for key, value in attributes.items():
        if str(key).lower() == "label" and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _decoded_extension(payload: bytes, *, has_xml_root: bool) -> str:
    if has_xml_root:
        return "xml"
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "bin"
    if not text or any(not char.isprintable() and char not in "\r\n\t" for char in text):
        return "bin"
    return "txt"


def iter_opju_decoded_regions(data: bytes) -> tuple[OpjuDecodedRegion, ...]:
    """Return unique LZ4-decoded regions in compressed-source order."""
    if not data.startswith(MAGIC_OPJU):
        return ()

    candidates = tuple(
        iter_origin_storage_candidates(
            data,
            include_decoded=True,
            include_family_binary=True,
        )
    )
    analyses = analyze_origin_storage_candidates(
        data,
        include_decoded=True,
        candidates=candidates,
    )
    candidates_by_span = {
        (candidate.source_start, candidate.source_end): candidate
        for candidate in candidates
        if candidate.source_kind == "decoded"
    }

    decoded: list[OpjuDecodedRegion] = []
    seen: set[tuple[int, int]] = set()
    for analysis in analyses:
        if analysis.source_kind != "decoded":
            continue
        span = (analysis.source_start, analysis.source_end)
        if span in seen or span[0] < 0 or span[1] <= span[0] or span[1] > len(data):
            continue
        candidate = candidates_by_span.get(span)
        if candidate is None or candidate.decompressed_size is None:
            continue
        seen.add(span)
        classification = classify_decoded_payload(analysis.payload)
        decoded.append(
            OpjuDecodedRegion(
                source_start=span[0],
                source_end=span[1],
                decoded_length=len(analysis.payload),
                payload=analysis.payload,
                region_kind=analysis.region_kind,
                label=_root_label(analysis.root),
                extension=_decoded_extension(
                    analysis.payload,
                    has_xml_root=analysis.root is not None,
                ),
                compression=candidate.compression or "lz4-block",
                declared_decoded_length=candidate.decompressed_size,
                family_marker=candidate.family_marker.hex() if candidate.family_marker is not None else None,
                marker_offset=candidate.marker_offset,
                header_offset=candidate.header_offset,
                stream_offset=candidate.stream_offset,
                framing_rule=candidate.framing_rule or "unknown_lz4_framing",
                classification=classification,
            )
        )

    return tuple(sorted(decoded, key=lambda item: (item.source_start, item.source_end)))


def iter_decoded_region_strings(
    regions: Iterable[OpjuDecodedRegion],
    *,
    encoding: str = "ascii",
    min_length: int = 4,
) -> tuple[OpjuDecodedString, ...]:
    """Return printable strings from already-decoded regions with provenance."""
    strings: list[OpjuDecodedString] = []
    for region_index, region in enumerate(regions):
        for string_index, value in enumerate(iter_strings(region.payload, encoding=encoding, min_length=min_length)):
            strings.append(
                OpjuDecodedString(
                    region_index=region_index,
                    source_start=region.source_start,
                    source_end=region.source_end,
                    string_index=string_index,
                    value=value,
                )
            )
    return tuple(strings)


def iter_opju_decoded_strings(
    data: bytes,
    *,
    encoding: str = "ascii",
    min_length: int = 4,
) -> tuple[OpjuDecodedString, ...]:
    """Return printable strings hidden inside decoded OPJU LZ4 regions."""
    return iter_decoded_region_strings(
        iter_opju_decoded_regions(data),
        encoding=encoding,
        min_length=min_length,
    )


__all__ = [
    "OpjuDecodedRegion",
    "OpjuDecodedString",
    "iter_decoded_region_strings",
    "iter_opju_decoded_regions",
    "iter_opju_decoded_strings",
]
