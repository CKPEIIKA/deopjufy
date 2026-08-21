"""Lossless whole-file byte maps for machine-oriented extraction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from deopjufier.extract.path_helpers import manifest_relative_path
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju.common import MAGIC_OPJU, OPJU_REGION_KIND_TAGGED_BINARY
from deopjufier.opju.walker import OpjuWalkElement, walk_opju_file


@dataclass(frozen=True)
class _EvidenceRange:
    start: int
    end: int
    evidence_class: str
    label: str


def _evidence_class(item: ManifestItem) -> str:
    if item.discovery_type in {"carved", "signature_scan"} or item.signature is not None:
        return "carved"
    if item.heuristic is False:
        return "parser_bounded"
    if item.heuristic is True:
        return "heuristic"
    return "bounded_unverified"


def _evidence_ranges(manifest: Manifest, file_size: int) -> list[_EvidenceRange]:
    ranges: list[_EvidenceRange] = []
    for item in manifest.items:
        if item.offset is not None and item.length is not None and item.length <= 0:
            continue
        for source_range in item.source_ranges or ():
            start = max(0, min(source_range["start"], file_size))
            end = max(start, min(source_range["end"], file_size))
            if end <= start:
                continue
            ranges.append(
                _EvidenceRange(
                    start=start,
                    end=end,
                    evidence_class=_evidence_class(item),
                    label=f"{item.kind}:{item.name}",
                )
            )
    return ranges


def _opju_walk_ranges(
    data: bytes,
    walk_elements: Iterable[OpjuWalkElement] | None = None,
) -> list[_EvidenceRange]:
    if not data.startswith(MAGIC_OPJU):
        return []
    elements = walk_opju_file(data) if walk_elements is None else walk_elements
    return [
        _EvidenceRange(
            start=element.start_offset,
            end=element.end_offset,
            evidence_class=(
                "heuristic"
                if element.kind == OPJU_REGION_KIND_TAGGED_BINARY
                and element.metadata.get("semantic_status") == "fields_partial"
                else "parser_bounded"
            ),
            label=f"opju_walk:{element.kind}:{element.name or ''}",
        )
        for element in elements
        if 0 <= element.start_offset < element.end_offset <= len(data)
    ]


def _segment_class(overlaps: list[_EvidenceRange]) -> str:
    classes = {item.evidence_class for item in overlaps}
    if not classes:
        return "unknown"
    if "parser_bounded" in classes:
        return "parser_bounded"
    if "carved" in classes:
        return "carved"
    if "bounded_unverified" in classes:
        return "bounded_unverified"
    return "heuristic"


def _partition(file_size: int, evidence: list[_EvidenceRange]) -> list[tuple[int, int, str, list[str]]]:
    boundaries = {0, file_size}
    for item in evidence:
        boundaries.update((item.start, item.end))
    ordered = sorted(boundaries)
    segments: list[tuple[int, int, str, list[str]]] = []
    for start, end in pairwise(ordered):
        if end <= start:
            continue
        overlaps = [item for item in evidence if item.start < end and item.end > start]
        labels = sorted({item.label for item in overlaps})
        segment_class = _segment_class(overlaps)
        if segments and segments[-1][1] == start and segments[-1][2:] == (segment_class, labels):
            previous_start, _, _, _ = segments[-1]
            segments[-1] = (previous_start, end, segment_class, labels)
        else:
            segments.append((start, end, segment_class, labels))
    return segments


def extract_byte_map(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    file_data: bytes | None = None,
    manifest_root: Path | None = None,
    walk_elements: Iterable[OpjuWalkElement] | None = None,
) -> int:
    """Write an exact, ordered partition from which the source can be reconstructed."""
    data = file_data if file_data is not None else input_path.read_bytes()
    map_root = out_dir / "byte-map"
    segment_root = map_root / "segments"
    index_path = map_root / "index.json"
    if index_path.exists() and not force:
        manifest.add_item(
            ManifestItem(
                kind="byte_map",
                name="whole_file_byte_map",
                status="skipped",
                confidence=1.0,
                discovery_type="exact_byte_partition",
                heuristic=False,
                path=manifest_relative_path(index_path, manifest_root or out_dir),
                range_start=0,
                range_end=len(data),
                completeness="complete",
                verification="exact",
                error="target_exists",
            )
        )
        return 0

    evidence = [*_evidence_ranges(manifest, len(data)), *_opju_walk_ranges(data, walk_elements)]
    segments = _partition(len(data), evidence)
    segment_root.mkdir(parents=True, exist_ok=True)
    class_bytes: dict[str, int] = {}
    index_segments: list[dict[str, object]] = []
    reconstruction = hashlib.sha256()
    for index, (start, end, segment_class, labels) in enumerate(segments):
        payload = data[start:end]
        reconstruction.update(payload)
        class_bytes[segment_class] = class_bytes.get(segment_class, 0) + len(payload)
        filename = f"segment_{index:04d}_off_{start:012d}_len_{len(payload):012d}.bin"
        target = segment_root / filename
        target.write_bytes(payload)
        index_segments.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "length": len(payload),
                "class": segment_class,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "path": target.relative_to(map_root).as_posix(),
                "evidence": labels,
            }
        )

    reconstructed_sha256 = reconstruction.hexdigest()
    source_sha256 = hashlib.sha256(data).hexdigest()
    payload = {
        "schema_version": 1,
        "input": {
            "size_bytes": len(data),
            "sha256": source_sha256,
        },
        "byte_accounting": {
            "complete": sum(class_bytes.values()) == len(data),
            "accounted_bytes": sum(class_bytes.values()),
            "unaccounted_bytes": len(data) - sum(class_bytes.values()),
            "segment_count": len(index_segments),
            "class_bytes": dict(sorted(class_bytes.items())),
        },
        "reconstruction": {
            "sha256": reconstructed_sha256,
            "matches_input": reconstructed_sha256 == source_sha256,
            "ordered_segments": True,
        },
        "semantic_claim": (
            "Classes describe evidence boundaries; unknown and bounded ranges are not semantic decoding claims."
        ),
        "segments": index_segments,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    manifest.add_item(
        ManifestItem(
            kind="byte_map",
            name="whole_file_byte_map",
            status="extracted",
            confidence=1.0,
            discovery_type="exact_byte_partition",
            heuristic=False,
            path=manifest_relative_path(index_path, manifest_root or out_dir),
            range_start=0,
            range_end=len(data),
            completeness="complete",
            verification="exact",
            rows=len(index_segments),
            content_class="byte_complete_semantics_partial" if class_bytes.get("unknown", 0) else "byte_complete",
        )
    )
    return len(index_segments)
