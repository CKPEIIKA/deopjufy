"""Export exact LZ4-decoded OPJU payloads with source provenance."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from deopjufier.extract.path_helpers import manifest_relative_path
from deopjufier.io import sanitize_name
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju import (
    OPJU_REGION_KIND_TAGGED_BINARY,
    OpjuColumnDescriptor,
    OpjuDecodedRegion,
    OpjuTaggedEnvelope,
    iter_decoded_region_strings,
    iter_opju_column_descriptors,
    iter_opju_decoded_regions,
    iter_opju_tagged_envelopes,
    iter_tagged_scalars,
    iter_tagged_strings,
    walk_opju_file,
)
from deopjufier.opju.numeric_runs import iter_opju_binary_runs_from_decoded_regions
from deopjufier.opju.regions import iter_origin_storage_candidates
from deopjufier.opju.tagged.column_payloads import opju_column_payload_semantic_status
from deopjufier.opju.walker import OpjuWalkElement


def _region_filename(index: int, offset: int, kind: str, extension: str) -> str:
    kind_name = sanitize_name(kind.removeprefix("origin_storage_"))
    return f"region_{index:04d}_off_{offset:012d}_{kind_name}.{extension}"


def _function_items_by_uid(manifest: Manifest) -> dict[int, list[ManifestItem]]:
    items: dict[int, list[ManifestItem]] = {}
    for item in manifest.items:
        if item.kind != "function" or item.calculation_uid is None:
            continue
        items.setdefault(item.calculation_uid, []).append(item)
    return items


def _calculation_references(
    regions: tuple[OpjuDecodedRegion, ...],
    manifest: Manifest,
) -> list[dict[str, object]]:
    functions_by_uid = _function_items_by_uid(manifest)
    references: list[dict[str, object]] = []
    for region_index, region in enumerate(regions):
        if region.classification.family != "storage_cell_ref_data":
            continue
        records = region.classification.fields.get("records")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            record_fields = cast(dict[str, object], record)
            uid = record_fields.get("calculation_uid")
            if not isinstance(uid, int):
                continue
            functions = functions_by_uid.get(uid, [])
            references.append(
                {
                    "decoded_region_index": region_index,
                    "compressed_source_range": {"start": region.source_start, "end": region.source_end},
                    "ordinal": record_fields.get("ordinal"),
                    "calculation_uid": uid,
                    "resolved": bool(functions),
                    "functions": [
                        {
                            "name": item.name,
                            "path": item.path,
                            "source_object_path": item.source_object_path,
                        }
                        for item in functions
                    ],
                }
            )
    return references


def _write_calculation_links(
    regions: tuple[OpjuDecodedRegion, ...],
    region_root: Path,
    manifest: Manifest,
    *,
    force: bool,
    manifest_root: Path,
) -> None:
    references = _calculation_references(regions, manifest)
    if not references:
        return
    all_resolved = all(bool(reference["resolved"]) for reference in references)
    target = region_root / "calculation_links.json"
    exists = target.exists()
    if not exists or force:
        unique_uids = sorted(
            {uid for reference in references if isinstance((uid := reference.get("calculation_uid")), int)}
        )
        payload = {
            "all_references_resolved": all_resolved,
            "reference_count": len(references),
            "unique_calculation_uids": unique_uids,
            "references": references,
        }
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    manifest.add_item(
        ManifestItem(
            kind="opju_calculation_links",
            name="opju_calculation_links",
            status="skipped" if exists and not force else "extracted",
            confidence=0.99 if all_resolved else 0.85,
            discovery_type="opju_storage_cell_ref_data",
            heuristic=False,
            object_kind="analysis",
            path=manifest_relative_path(target, manifest_root),
            source_object_path="opju/decoded/calculation_links",
            rows=len(references),
            source_ranges=[
                {"start": region.source_start, "end": region.source_end}
                for region in regions
                if region.classification.family == "storage_cell_ref_data"
            ],
            extraction_method="opju_calculation_uid_resolution",
            completeness="complete" if all_resolved else "partial",
            verification="exact",
            error=None if all_resolved else "unresolved_calculation_uid",
        )
    )


def _write_decoded_strings(
    regions: tuple[OpjuDecodedRegion, ...],
    region_root: Path,
    manifest: Manifest,
    *,
    min_length: int,
    force: bool,
    manifest_root: Path,
) -> None:
    strings = iter_decoded_region_strings(regions, min_length=min_length)
    if not strings:
        return

    target = region_root / "strings.tsv"
    exists = target.exists()
    if not exists or force:
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(("region_index", "source_start", "source_end", "string_index", "value"))
            for item in strings:
                writer.writerow((item.region_index, item.source_start, item.source_end, item.string_index, item.value))
    manifest.add_item(
        ManifestItem(
            kind="opju_decoded_strings",
            name="opju_decoded_strings",
            status="skipped" if exists and not force else "extracted",
            confidence=0.9,
            discovery_type="opju_decoded_strings",
            heuristic=False,
            object_kind="metadata",
            path=manifest_relative_path(target, manifest_root),
            source_object_path="opju/decoded/strings",
            rows=len(strings),
            error="target_exists" if exists and not force else None,
        )
    )


def _write_numeric_run_inventory(
    regions: tuple[OpjuDecodedRegion, ...],
    region_root: Path,
    manifest: Manifest,
    *,
    force: bool,
    manifest_root: Path,
) -> None:
    runs = iter_opju_binary_runs_from_decoded_regions(regions)
    if not runs:
        return

    rows = [
        {
            "family_marker": run.family_marker,
            "first_values": list(run.first_values),
            "payload_offset": run.payload_offset,
            "primitive": run.primitive,
            "primitive_size": run.primitive_size,
            "run_length": run.run_length,
            "source_end": run.source_end,
            "source_start": run.source_start,
            "tag": run.tag,
        }
        for run in runs
    ]
    target = region_root / "numeric_runs.json"
    exists = target.exists()
    if not exists or force:
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(rows, handle, indent=2, sort_keys=True)
            handle.write("\n")
    manifest.add_item(
        ManifestItem(
            kind="opju_numeric_run_inventory",
            name="opju_numeric_runs",
            status="skipped" if exists and not force else "extracted",
            confidence=0.9,
            discovery_type="opju_numeric_blob_run",
            heuristic=False,
            object_kind="metadata",
            path=manifest_relative_path(target, manifest_root),
            source_object_path="opju/decoded/numeric_runs",
            rows=len(rows),
            error="target_exists" if exists and not force else None,
        )
    )


def extract_opju_decoded_regions(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    file_data: bytes | None = None,
    manifest_root: Path | None = None,
    include_strings: bool = True,
    strings_min_length: int = 4,
    include_numeric_runs: bool = True,
    regions: tuple[OpjuDecodedRegion, ...] | None = None,
) -> int:
    """Save every uniquely framed decoded OPJU payload and a JSON index."""
    data = file_data if file_data is not None else input_path.read_bytes()
    if regions is None:
        regions = iter_opju_decoded_regions(data)
    if not regions:
        return 0

    region_root = out_dir / "metadata" / "opju_decoded"
    region_root.mkdir(parents=True, exist_ok=True)
    root = manifest_root or out_dir
    index_rows: list[dict[str, object]] = []
    extracted = 0

    for index, region in enumerate(regions):
        filename = _region_filename(
            index,
            region.source_start,
            region.region_kind,
            region.extension,
        )
        target = region_root / filename
        exists = target.exists()
        if not exists or force:
            target.write_bytes(region.payload)
            status = "extracted"
            error = None
            extracted += 1
        else:
            status = "skipped"
            error = "target_exists"

        relative_path = manifest_relative_path(target, root)
        source_path = f"opju/decoded/{region.source_start:012d}"
        payload_sha256 = hashlib.sha256(region.payload).hexdigest()
        structural_name = region.classification.fields.get("structural_name")
        semantic_alias = region.classification.fields.get("semantic_alias")
        semantic_confidence = region.classification.fields.get("semantic_confidence")
        index_rows.append(
            {
                "name": region.label or f"decoded_region_{index:04d}",
                "region_kind": region.region_kind,
                "source_start": region.source_start,
                "source_end": region.source_end,
                "compressed_length": region.compressed_length,
                "compression": region.compression,
                "declared_decoded_length": region.declared_decoded_length,
                "decoded_length": region.decoded_length,
                "decoded_sha256": payload_sha256,
                "family_marker": region.family_marker,
                "framing_rule": region.framing_rule,
                "header_offset": region.header_offset,
                "marker_offset": region.marker_offset,
                "path": relative_path,
                "stream_offset": region.stream_offset,
                "classification": region.classification.to_dict(),
            }
        )
        manifest.add_item(
            ManifestItem(
                kind="opju_decoded_region",
                name=region.label or f"decoded_region_{index:04d}",
                status=status,
                confidence=0.95,
                discovery_type="opju_lz4_region",
                heuristic=False,
                object_kind=region.region_kind,
                path=relative_path,
                source_object_path=source_path,
                offset=region.source_start,
                length=region.compressed_length,
                range_start=region.source_start,
                range_end=region.source_end,
                decoded_length=region.decoded_length,
                compression=region.compression,
                declared_length=region.declared_decoded_length,
                family_marker=region.family_marker,
                marker_offset=region.marker_offset,
                header_offset=region.header_offset,
                stream_offset=region.stream_offset,
                framing_rule=region.framing_rule,
                payload_family=region.classification.family,
                structural_name=structural_name if isinstance(structural_name, str) else None,
                semantic_alias=semantic_alias if isinstance(semantic_alias, str) else None,
                semantic_confidence=semantic_confidence if isinstance(semantic_confidence, str) else None,
                completeness=region.classification.completeness,
                verification=region.classification.verification,
                error=error,
            )
        )

    index_target = region_root / "index.json"
    index_exists = index_target.exists()
    if not index_exists or force:
        with index_target.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(index_rows, handle, indent=2, sort_keys=True)
            handle.write("\n")
    manifest.add_item(
        ManifestItem(
            kind="opju_decoded_index",
            name="opju_decoded_regions",
            status="skipped" if index_exists and not force else "extracted",
            confidence=0.95,
            discovery_type="opju_lz4_region",
            heuristic=False,
            object_kind="metadata",
            path=manifest_relative_path(index_target, root),
            source_object_path="opju/decoded",
            rows=len(index_rows),
            error="target_exists" if index_exists and not force else None,
        )
    )
    if include_strings:
        _write_decoded_strings(
            regions,
            region_root,
            manifest,
            min_length=strings_min_length,
            force=force,
            manifest_root=root,
        )
    if include_numeric_runs:
        _write_numeric_run_inventory(
            regions,
            region_root,
            manifest,
            force=force,
            manifest_root=root,
        )
    _write_calculation_links(
        regions,
        region_root,
        manifest,
        force=force,
        manifest_root=root,
    )
    return extracted


def _manifest_parser_ranges(manifest: Manifest, file_size: int) -> list[tuple[int, int]]:
    boundary_kinds = {"opju_decoded_region", "origin_storage_region"}
    ranges: list[tuple[int, int]] = []
    for item in manifest.items:
        if item.kind not in boundary_kinds or item.heuristic is not False or item.source_ranges is None:
            continue
        for source_range in item.source_ranges:
            start = source_range.get("start")
            end = source_range.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= file_size:
                ranges.append((start, end))
    return ranges


def _walk_element_as_tagged_envelope(data: bytes, element: OpjuWalkElement) -> OpjuTaggedEnvelope:
    payload = data[element.start_offset : element.end_offset]
    return OpjuTaggedEnvelope(
        family=str(element.metadata["family"]),
        start_offset=element.start_offset,
        end_offset=element.end_offset,
        sha256=hashlib.sha256(payload).hexdigest(),
        strings=iter_tagged_strings(payload, source_start=element.start_offset),
        scalars=iter_tagged_scalars(payload, source_start=element.start_offset),
        semantic_status=str(element.metadata["semantic_status"]),
    )


def extract_opju_tagged_envelopes(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    file_data: bytes | None = None,
    manifest_root: Path | None = None,
    walk_elements: Iterable[OpjuWalkElement] | None = None,
    descriptors: tuple[OpjuColumnDescriptor, ...] | None = None,
) -> int:
    """Export bounded tagged envelopes and every explicitly framed string field."""
    data = file_data if file_data is not None else input_path.read_bytes()
    if descriptors is None:
        descriptors = iter_opju_column_descriptors(data)
    if walk_elements is None:
        bounded_ranges = _manifest_parser_ranges(manifest, len(data))
        newline_offset = data.find(b"\n")
        if newline_offset >= 0:
            bounded_ranges.append((0, newline_offset + 1))
        bounded_ranges.extend(
            (candidate.source_start, candidate.source_end)
            for candidate in iter_origin_storage_candidates(data, include_decoded=False)
        )
        bounded_ranges.extend((descriptor.start_offset, descriptor.end_offset) for descriptor in descriptors)
        envelopes = iter_opju_tagged_envelopes(data, bounded_ranges)
    else:
        elements = [element for element in walk_elements if element.kind == OPJU_REGION_KIND_TAGGED_BINARY]
        envelopes = tuple(_walk_element_as_tagged_envelope(data, element) for element in elements)
    if not envelopes and not descriptors:
        return 0

    tagged_root = out_dir / "metadata" / "opju_tagged"
    tagged_root.mkdir(parents=True, exist_ok=True)
    root = manifest_root or out_dir
    index_rows: list[dict[str, object]] = []
    extracted = 0
    source_ranges: list[dict[str, int]] = []
    for index, envelope in enumerate(envelopes):
        payload = data[envelope.start_offset : envelope.end_offset]
        family = envelope.family
        filename = f"envelope_{index:04d}_off_{envelope.start_offset:012d}_{family}.bin"
        target = tagged_root / filename
        exists = target.exists()
        if not exists or force:
            target.write_bytes(payload)
            extracted += 1
        fields = envelope.strings
        scalars = envelope.scalars
        source_ranges.append({"start": envelope.start_offset, "end": envelope.end_offset})
        index_rows.append(
            {
                "family": family,
                "source_start": envelope.start_offset,
                "source_end": envelope.end_offset,
                "length": len(payload),
                "sha256": envelope.sha256,
                "path": manifest_relative_path(target, root),
                "semantic_status": envelope.semantic_status,
                "string_fields": [
                    {
                        "offset": field.offset,
                        "length": field.length,
                        "tag_code": field.tag_code,
                        "value": field.value,
                    }
                    for field in fields
                ],
                "scalar_fields": [
                    {
                        "offset": field.offset,
                        "end_offset": field.end_offset,
                        "field_code": field.field_code,
                        "declared_size": field.declared_size,
                        "descriptor_hex": field.descriptor_hex,
                        "value_width": field.value_width,
                        "value_hex": field.value_hex,
                        "little_endian_unsigned": field.little_endian_unsigned,
                    }
                    for field in scalars
                ],
            }
        )

    index_target = tagged_root / "index.json"
    index_exists = index_target.exists()
    if not index_exists or force:
        index_target.write_text(
            json.dumps(index_rows, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    manifest.add_item(
        ManifestItem(
            kind="opju_tagged_index",
            name="opju_tagged_envelopes",
            status="skipped" if index_exists and not force else "extracted",
            confidence=0.8,
            discovery_type="tagged_gap_signature",
            heuristic=True,
            object_kind="metadata",
            path=manifest_relative_path(index_target, root),
            source_object_path="opju/tagged",
            source_ranges=source_ranges,
            rows=len(index_rows),
            content_class="tagged_binary_fields_partial",
            completeness="partial",
            verification="exact",
            error="target_exists" if index_exists and not force else None,
        )
    )
    if descriptors:
        all_descriptors_decoded = all(descriptor.decoded_payload is not None for descriptor in descriptors)
        descriptor_target = tagged_root / "column_descriptors.json"
        descriptor_exists = descriptor_target.exists()
        if not descriptor_exists or force:
            descriptor_target.write_text(
                json.dumps(
                    [
                        {
                            "name": descriptor.name,
                            "source_start": descriptor.start_offset,
                            "source_end": descriptor.end_offset,
                            "name_offset": descriptor.name_offset,
                            "stored_payload_length_offset": descriptor.stored_payload_length_offset,
                            "stored_payload_length": descriptor.stored_payload_length,
                            "payload_prelude": descriptor.payload_prelude,
                            "payload_offset": descriptor.payload_offset,
                            "payload_end": descriptor.payload_end,
                            "header_signature": descriptor.header_signature,
                            "row_capacity": descriptor.row_capacity,
                            "stored_value_count": descriptor.stored_value_count,
                            "payload_encoding": (
                                descriptor.decoded_payload.encoding if descriptor.decoded_payload is not None else None
                            ),
                            "trailing_missing_count": (
                                descriptor.decoded_payload.trailing_missing_count
                                if descriptor.decoded_payload is not None
                                else None
                            ),
                            "missing_count": (
                                descriptor.decoded_payload.missing_count
                                if descriptor.decoded_payload is not None
                                else None
                            ),
                            "repeated_prefix_count": (
                                descriptor.decoded_payload.repeated_prefix_count
                                if descriptor.decoded_payload is not None
                                else None
                            ),
                            "first_control_byte": descriptor.first_control_byte,
                            "first_value": descriptor.first_value,
                            "values": (
                                descriptor.decoded_payload.values if descriptor.decoded_payload is not None else None
                            ),
                            "value_bits": (
                                descriptor.decoded_payload.value_bits
                                if descriptor.decoded_payload is not None
                                else None
                            ),
                            "cell_kinds": (
                                descriptor.decoded_payload.cell_kinds
                                if descriptor.decoded_payload is not None
                                else None
                            ),
                            "semantic_status": (
                                opju_column_payload_semantic_status(descriptor.decoded_payload)
                                if descriptor.decoded_payload is not None
                                else "stored_payload_variant"
                            ),
                        }
                        for descriptor in descriptors
                    ],
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
        manifest.add_item(
            ManifestItem(
                kind="opju_column_descriptor_index",
                name="opju_column_descriptors",
                status="skipped" if descriptor_exists and not force else "extracted",
                confidence=0.98,
                discovery_type="opju_column_stored_payload",
                heuristic=False,
                object_kind="worksheet_metadata",
                path=manifest_relative_path(descriptor_target, root),
                source_object_path="opju/tagged/column_descriptors",
                source_ranges=[
                    {"start": descriptor.start_offset, "end": descriptor.end_offset} for descriptor in descriptors
                ],
                rows=len(descriptors),
                content_class=(
                    "decoded_column_values" if all_descriptors_decoded else "column_stored_payload_variants"
                ),
                completeness="complete" if all_descriptors_decoded else "partial",
                verification="exact" if all_descriptors_decoded else "parser_bounded",
                error="target_exists" if descriptor_exists and not force else None,
            )
        )
    return extracted


__all__ = ["extract_opju_decoded_regions", "extract_opju_tagged_envelopes"]
