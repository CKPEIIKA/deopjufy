"""Deterministic structural walk for OPJU containers."""

from __future__ import annotations

from dataclasses import dataclass

from deopjufier.opju.common import (
    MAGIC_OPJU,
    OPJU_REGION_KIND_COLUMN_DESCRIPTOR,
    OPJU_REGION_KIND_TAGGED_BINARY,
)
from deopjufier.opju.decoded import OpjuDecodedRegion, iter_opju_decoded_regions
from deopjufier.opju.numeric_runs import iter_opju_binary_runs_from_decoded_regions
from deopjufier.opju.records import parse_opju_records
from deopjufier.opju.tagged import OpjuColumnDescriptor, iter_opju_column_descriptors, iter_opju_tagged_envelopes
from deopjufier.opju.tagged.column_payloads import opju_column_payload_semantic_status


@dataclass(frozen=True)
class OpjuWalkElement:
    kind: str
    name: str | None
    start_offset: int
    end_offset: int
    metadata: dict[str, object]


def _region_metadata(region: object) -> dict[str, object]:
    return {
        "parser_rule": getattr(region, "parser_rule", "parse_opju_records"),
        "confidence": getattr(region, "confidence", 0.0),
        **(
            {"source_object_path": source_path}
            if (source_path := getattr(region, "source_object_path", None)) is not None
            else {}
        ),
    }


def _decoded_metadata(decoded: OpjuDecodedRegion, *, numeric_run_count: int = 0) -> dict[str, object]:
    metadata: dict[str, object] = {
        "source_kind": "decoded",
        "compression": decoded.compression,
        "compressed_length": decoded.compressed_length,
        "declared_decoded_length": decoded.declared_decoded_length,
        "decoded_length": decoded.decoded_length,
        "decoded_extension": decoded.extension,
        "framing_rule": decoded.framing_rule,
        "stream_offset": decoded.stream_offset,
    }
    optional_fields = {
        "family_marker": decoded.family_marker,
        "marker_offset": decoded.marker_offset,
        "header_offset": decoded.header_offset,
    }
    for key, value in optional_fields.items():
        if value is not None:
            metadata[key] = value
    if numeric_run_count:
        metadata["numeric_run_count"] = numeric_run_count
    return metadata


def walk_opju_file(
    data: bytes,
    *,
    column_descriptors: tuple[OpjuColumnDescriptor, ...] | None = None,
    decoded_regions: tuple[OpjuDecodedRegion, ...] | None = None,
) -> list[OpjuWalkElement]:
    """Walk known OPJU regions and decoded LZ4 source spans."""
    if not data.startswith(MAGIC_OPJU):
        return []

    records = parse_opju_records(
        data,
        max_reports=200,
        max_tables=200,
        include_decoded=True,
        include_family_binary=True,
    )
    if decoded_regions is None:
        decoded_regions = iter_opju_decoded_regions(data)
    decoded_by_span = {(region.source_start, region.source_end): region for region in decoded_regions}
    numeric_run_counts: dict[tuple[int, int], int] = {}
    for run in iter_opju_binary_runs_from_decoded_regions(decoded_regions):
        span = (run.source_start, run.source_end)
        numeric_run_counts[span] = numeric_run_counts.get(span, 0) + 1

    elements: list[OpjuWalkElement] = []
    seen_spans: set[tuple[int, int]] = set()
    for region in records.regions:
        start = region.offset
        end = region.offset + region.length
        metadata = _region_metadata(region)
        decoded = decoded_by_span.get((start, end))
        if decoded is not None:
            metadata.update(_decoded_metadata(decoded, numeric_run_count=numeric_run_counts.get((start, end), 0)))
        if region.kind == "opju_container" and records.container is not None:
            metadata.update(
                {
                    "marker": records.container.marker,
                    "version": records.container.version,
                    "declared_length": records.container.declared_length,
                }
            )
        elements.append(
            OpjuWalkElement(
                kind=region.kind,
                name=region.name,
                start_offset=start,
                end_offset=end,
                metadata=metadata,
            )
        )
        seen_spans.add((start, end))

    for index, decoded in enumerate(decoded_regions):
        span = (decoded.source_start, decoded.source_end)
        if span in seen_spans:
            continue
        elements.append(
            OpjuWalkElement(
                kind=decoded.region_kind,
                name=decoded.label or f"decoded_region_{index:04d}",
                start_offset=span[0],
                end_offset=span[1],
                metadata={
                    "parser_rule": "opju_lz4_region",
                    "confidence": 0.95,
                    **_decoded_metadata(decoded, numeric_run_count=numeric_run_counts.get(span, 0)),
                },
            )
        )

    if column_descriptors is None:
        column_descriptors = iter_opju_column_descriptors(data)
    bounded_ranges = [
        *((element.start_offset, element.end_offset) for element in elements),
        *((descriptor.start_offset, descriptor.end_offset) for descriptor in column_descriptors),
    ]
    for index, envelope in enumerate(iter_opju_tagged_envelopes(data, bounded_ranges)):
        elements.append(
            OpjuWalkElement(
                kind=OPJU_REGION_KIND_TAGGED_BINARY,
                name=f"{envelope.family}_{index:04d}",
                start_offset=envelope.start_offset,
                end_offset=envelope.end_offset,
                metadata={
                    "parser_rule": "opju_tagged_envelope_between_bounded_records",
                    "confidence": 0.9,
                    "family": envelope.family,
                    "sha256": envelope.sha256,
                    "decoded_string_count": len(envelope.strings),
                    "decoded_scalar_count": len(envelope.scalars),
                    "semantic_status": envelope.semantic_status,
                },
            )
        )

    for descriptor in column_descriptors:
        decoded_payload = descriptor.decoded_payload
        elements.append(
            OpjuWalkElement(
                kind=OPJU_REGION_KIND_COLUMN_DESCRIPTOR,
                name=descriptor.name,
                start_offset=descriptor.start_offset,
                end_offset=descriptor.end_offset,
                metadata={
                    "parser_rule": "opju_column_stored_payload",
                    "confidence": 0.98,
                    "name_offset": descriptor.name_offset,
                    "stored_payload_length": descriptor.stored_payload_length,
                    "stored_payload_length_offset": descriptor.stored_payload_length_offset,
                    "payload_prelude": descriptor.payload_prelude,
                    "payload_offset": descriptor.payload_offset,
                    "payload_end": descriptor.payload_end,
                    "header_signature": descriptor.header_signature,
                    "row_capacity": descriptor.row_capacity,
                    "stored_value_count": descriptor.stored_value_count,
                    "payload_encoding": decoded_payload.encoding if decoded_payload is not None else None,
                    "trailing_missing_count": (
                        decoded_payload.trailing_missing_count if decoded_payload is not None else None
                    ),
                    "missing_count": decoded_payload.missing_count if decoded_payload is not None else None,
                    "repeated_prefix_count": decoded_payload.repeated_prefix_count
                    if decoded_payload is not None
                    else None,
                    "first_control_byte": descriptor.first_control_byte,
                    "first_value": descriptor.first_value,
                    "semantic_status": (
                        opju_column_payload_semantic_status(decoded_payload)
                        if decoded_payload is not None
                        else "stored_payload_variant"
                    ),
                },
            )
        )

    return sorted(
        elements,
        key=lambda item: (
            item.start_offset,
            item.end_offset,
            item.kind,
            item.name or "",
        ),
    )


__all__ = ["OpjuWalkElement", "walk_opju_file"]
