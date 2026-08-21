"""Extraction of complete XML records from encoded OPJU function windows."""

from __future__ import annotations

import json
from pathlib import Path

from deopjufier.extract.path_helpers import manifest_relative_path
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju.recovery.byte_runs import OpjuRecoveredXml, recover_origin_storage_xml_records

_DISCOVERY_TYPE = "origin_storage_byte_run_phase_recovery"


def _write_bytes(target: Path, payload: bytes, *, force: bool) -> tuple[str, str | None]:
    if target.exists() and not force:
        return "skipped", "target_exists"
    target.write_bytes(payload)
    return "extracted", None


def _write_source_map(
    target: Path,
    record: OpjuRecoveredXml,
    *,
    force: bool,
) -> tuple[str, str | None]:
    if target.exists() and not force:
        return "skipped", "target_exists"
    payload = {
        "decoded_length": len(record.xml),
        "decoded_sha256": record.sha256,
        "encoded_source_range": {"start": record.source_start, "end": record.source_end},
        "marker_offset": record.marker_offset,
        "phase": record.phase,
        "source_map": list(record.source_map),
        "stop_reason": record.stop_reason,
    }
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return "extracted", None


def _record_target(target_dir: Path, record: OpjuRecoveredXml, index: int, count: int) -> Path:
    if record.classification == "related_origin_storage":
        return target_dir / f"related_{index:03d}.xml"
    if count == 1:
        return target_dir / "function.xml"
    return target_dir / f"function_part_{index:03d}.xml"


def _record_name(object_name: str, record: OpjuRecoveredXml, index: int, count: int) -> str:
    if record.classification == "related_origin_storage":
        return f"{object_name}_related_{index}"
    if count == 1:
        return object_name
    return f"{object_name}_part_{index}"


def _add_xml_item(
    manifest: Manifest,
    record: OpjuRecoveredXml,
    *,
    object_name: str,
    source_object_path: str,
    target: Path,
    manifest_root: Path,
    index: int,
    count: int,
    force: bool,
    include_source_map: bool,
) -> bool:
    status, error = _write_bytes(target, record.xml, force=force)
    if record.classification == "related_origin_storage":
        source_path = f"{source_object_path}/related_{index:03d}"
    else:
        source_path = source_object_path if count == 1 else f"{source_object_path}/part_{index:03d}"
    source_map_path: str | None = None
    if include_source_map:
        map_target = target.with_suffix(".source-map.json")
        map_status, map_error = _write_source_map(map_target, record, force=force)
        source_map_path = manifest_relative_path(map_target, manifest_root)
        manifest.add_item(
            ManifestItem(
                kind="function_source_map",
                name=f"{_record_name(object_name, record, index, count)}_source_map",
                status=map_status,
                confidence=0.98,
                discovery_type=_DISCOVERY_TYPE,
                heuristic=True,
                path=source_map_path,
                source_object_path=source_path,
                object_kind="metadata",
                range_start=record.source_start,
                range_end=record.source_end,
                extraction_method="origin_storage_byte_run_source_map",
                completeness="complete",
                verification="exact",
                error=map_error,
            )
        )

    manifest.add_item(
        ManifestItem(
            kind="function" if record.classification == "function" else "origin_storage_related",
            name=_record_name(object_name, record, index, count),
            status=status,
            confidence=0.98,
            discovery_type=_DISCOVERY_TYPE,
            heuristic=True,
            path=manifest_relative_path(target, manifest_root),
            source_object_path=source_path,
            object_kind=record.classification,
            function_name=record.family,
            calculation_label=record.calculation_label,
            calculation_uid=record.calculation_uid,
            payload_family="origin_storage_xml",
            source_map_path=source_map_path,
            range_start=record.source_start,
            range_end=record.source_end,
            extraction_method="origin_storage_byte_run_decode",
            completeness="complete",
            verification="exact",
            error=error,
        )
    )
    return status == "extracted"


def extract_encoded_opju_function_window(
    raw: bytes,
    target_dir: Path,
    manifest: Manifest,
    *,
    object_name: str,
    source_object_path: str,
    source_start: int,
    source_end: int,
    manifest_root: Path,
    force: bool,
    include_provenance: bool,
) -> int | None:
    """Recover logical records, returning ``None`` when no exact XML is found."""
    records = recover_origin_storage_xml_records(raw, source_start=source_start)
    function_records = tuple(record for record in records if record.classification == "function")
    if not function_records:
        return None

    if include_provenance:
        raw_target = target_dir / "function.encoded.bin"
        raw_status, raw_error = _write_bytes(raw_target, raw, force=force)
        manifest.add_item(
            ManifestItem(
                kind="function_encoded_source",
                name=f"{object_name}_encoded_source",
                status=raw_status,
                confidence=1.0,
                discovery_type="parser_window",
                heuristic=False,
                path=manifest_relative_path(raw_target, manifest_root),
                source_object_path=source_object_path,
                object_kind="binary",
                range_start=source_start,
                range_end=source_end,
                extraction_method="raw_region_preservation",
                completeness="complete",
                verification="exact",
                error=raw_error,
            )
        )

    exported = 0
    function_index = 0
    related_index = 0
    for record in records:
        if record.classification == "function":
            function_index += 1
            record_index = function_index
            record_count = len(function_records)
        else:
            related_index += 1
            record_index = related_index
            record_count = 1
        target = _record_target(target_dir, record, record_index, record_count)
        record_exported = _add_xml_item(
            manifest,
            record,
            object_name=object_name,
            source_object_path=source_object_path,
            target=target,
            manifest_root=manifest_root,
            index=record_index,
            count=record_count,
            force=force,
            include_source_map=include_provenance,
        )
        if record.classification == "function":
            exported += record_exported
    return exported


__all__ = ["extract_encoded_opju_function_window"]
