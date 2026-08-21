"""Exact recovery of byte-run encoded OriginStorage analysis reports."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from deopjufier.extract.path_helpers import manifest_relative_path
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju.recovery.byte_runs import OpjuRecoveredXml, recover_origin_storage_xml
from deopjufier.opju.reports import parse_origin_storage_leaf_fields
from deopjufier.opju.tagged import OpjuTaggedEnvelope

_DISCOVERY_TYPE = "origin_storage_byte_run_phase_recovery"
_STATE_OPERATIONS = frozenset({"COKOGrid_MainRange", "COKOGrid_SetTree", "_TableRange"})


def _write_bytes(target: Path, payload: bytes, *, force: bool) -> tuple[str, str | None]:
    if target.exists() and not force:
        return "skipped", "target_exists"
    target.write_bytes(payload)
    return "extracted", None


def _write_json(target: Path, payload: object, *, force: bool) -> tuple[str, str | None]:
    if target.exists() and not force:
        return "skipped", "target_exists"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return "extracted", None


def _is_plain_origin_storage_xml(raw: bytes) -> bool:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return False
    return root.tag.rsplit("}", 1)[-1] == "OriginStorage"


def is_encoded_opju_report_candidate(raw: bytes) -> bool:
    """Return whether a parser window has the literal report anchors needed for phase recovery."""
    visible_prefix = raw[:2048].lstrip()
    return visible_prefix.startswith(b"<OriginStorage") and b"<Calculation" in visible_prefix


def _function_link(manifest: Manifest, record: OpjuRecoveredXml) -> tuple[dict[str, object], int | None]:
    functions = [
        item
        for item in manifest.items
        if item.kind == "function" and item.verification == "exact" and item.status in {"extracted", "skipped"}
    ]
    if record.calculation_uid is not None:
        candidates = [item for item in functions if item.calculation_uid == record.calculation_uid]
        rule = "calculation_uid"
    elif record.calculation_label:
        candidates = [item for item in functions if item.calculation_label == record.calculation_label]
        rule = "calculation_label"
    else:
        candidates = []
        rule = "no_link_key"
    if len(candidates) != 1:
        return {
            "status": "ambiguous" if candidates else "unresolved",
            "rule": rule,
            "candidate_count": len(candidates),
            "verification": "exact" if candidates else "unverified",
        }, record.calculation_uid
    function = candidates[0]
    return {
        "status": "resolved_exact",
        "rule": rule,
        "name": function.name,
        "path": function.path,
        "source_object_path": function.source_object_path,
        "calculation_label": function.calculation_label,
        "calculation_uid": function.calculation_uid,
        "verification": "exact",
    }, record.calculation_uid if record.calculation_uid is not None else function.calculation_uid


def _state_payload(envelope: OpjuTaggedEnvelope | None) -> dict[str, object] | None:
    if envelope is None:
        return None
    operations = [field.value for field in envelope.strings if field.value in _STATE_OPERATIONS]
    if not operations:
        return None
    return {
        "family": envelope.family,
        "source_range": {"start": envelope.start_offset, "end": envelope.end_offset},
        "sha256": envelope.sha256,
        "operations": operations,
        "string_fields": [
            {"offset": field.offset, "length": field.length, "tag_code": field.tag_code, "value": field.value}
            for field in envelope.strings
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
            for field in envelope.scalars
        ],
        "semantic_status": envelope.semantic_status,
        "verification": "exact",
    }


def _source_map_payload(record: OpjuRecoveredXml) -> dict[str, object]:
    return {
        "decoded_length": len(record.xml),
        "decoded_sha256": record.sha256,
        "encoded_source_range": {"start": record.source_start, "end": record.source_end},
        "marker_offset": record.marker_offset,
        "phase": record.phase,
        "source_map": list(record.source_map),
        "stop_reason": record.stop_reason,
    }


def extract_encoded_opju_report_window(
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
    adjacent_state: OpjuTaggedEnvelope | None = None,
    adjacent_state_bytes: bytes | None = None,
) -> int | None:
    """Recover one exact report XML record, or return ``None`` for a normal note."""
    if not is_encoded_opju_report_candidate(raw):
        return None
    if _is_plain_origin_storage_xml(raw):
        return None
    record = recover_origin_storage_xml(raw, source_start=source_start)
    if record is None or record.classification != "function":
        return None

    target_dir.mkdir(parents=True, exist_ok=True)
    report_target = target_dir / "report.xml"
    status, error = _write_bytes(report_target, record.xml, force=force)
    function_link, calculation_uid = _function_link(manifest, record)
    state = _state_payload(adjacent_state)
    source_map_path: str | None = None

    metadata: dict[str, object] = {
        "name": object_name,
        "encoded_window": {"start": source_start, "end": source_end},
        "decoded_source_range": {"start": record.source_start, "end": record.source_end},
        "decoded_xml_length": len(record.xml),
        "decoded_sha256": record.sha256,
        "rle_phase": record.phase,
        "rle_stop_reason": record.stop_reason,
        "calculation_label": record.calculation_label,
        "calculation_uid_in_report": record.calculation_uid,
        "calculation_uid": calculation_uid,
        "linked_function": function_link,
        "linked_state_envelope": state,
        "verification": "exact",
    }

    if include_provenance:
        encoded_target = target_dir / "report.encoded.bin"
        encoded_status, encoded_error = _write_bytes(encoded_target, raw, force=force)
        manifest.add_item(
            ManifestItem(
                kind="analysis_report_encoded_source",
                name=f"{object_name}_encoded_source",
                status=encoded_status,
                confidence=1.0,
                discovery_type="parser_window",
                heuristic=False,
                path=manifest_relative_path(encoded_target, manifest_root),
                source_object_path=source_object_path,
                object_kind="binary",
                range_start=source_start,
                range_end=source_end,
                extraction_method="raw_region_preservation",
                completeness="complete",
                verification="exact",
                error=encoded_error,
            )
        )

        map_target = target_dir / "report.source-map.json"
        map_status, map_error = _write_json(map_target, _source_map_payload(record), force=force)
        source_map_path = manifest_relative_path(map_target, manifest_root)
        manifest.add_item(
            ManifestItem(
                kind="analysis_report_source_map",
                name=f"{object_name}_source_map",
                status=map_status,
                confidence=0.98,
                discovery_type=_DISCOVERY_TYPE,
                heuristic=True,
                path=source_map_path,
                source_object_path=source_object_path,
                object_kind="metadata",
                range_start=record.source_start,
                range_end=record.source_end,
                extraction_method="origin_storage_byte_run_source_map",
                completeness="complete",
                verification="exact",
                error=map_error,
            )
        )

        fields = []
        for field in parse_origin_storage_leaf_fields(record.xml):
            payload = field.to_dict()
            payload["source_map_reference"] = {
                "path": source_map_path,
                "decoded_range": payload["payload_range"],
            }
            fields.append(payload)
        fields_target = target_dir / "report.fields.json"
        fields_status, fields_error = _write_json(fields_target, fields, force=force)
        manifest.add_item(
            ManifestItem(
                kind="analysis_report_fields",
                name=f"{object_name}_fields",
                status=fields_status,
                confidence=0.98,
                discovery_type=_DISCOVERY_TYPE,
                heuristic=True,
                path=manifest_relative_path(fields_target, manifest_root),
                source_object_path=source_object_path,
                object_kind="metadata",
                rows=len(fields),
                columns=6,
                range_start=record.source_start,
                range_end=record.source_end,
                extraction_method="origin_storage_exact_leaf_fields",
                completeness="complete",
                verification="exact",
                error=fields_error,
            )
        )

        if state is not None and adjacent_state is not None and adjacent_state_bytes is not None:
            state_target = target_dir / "state-envelope.bin"
            state_status, state_error = _write_bytes(state_target, adjacent_state_bytes, force=force)
            state["path"] = manifest_relative_path(state_target, manifest_root)
            manifest.add_item(
                ManifestItem(
                    kind="analysis_report_state",
                    name=f"{object_name}_state",
                    status=state_status,
                    confidence=0.9,
                    discovery_type="adjacent_tagged_state_envelope",
                    heuristic=True,
                    path=state["path"],
                    source_object_path=source_object_path,
                    object_kind="tagged_state_envelope",
                    range_start=adjacent_state.start_offset,
                    range_end=adjacent_state.end_offset,
                    extraction_method="raw_region_preservation",
                    completeness="partial",
                    verification="exact",
                    error=state_error,
                )
            )

    index_target = target_dir / "report.index.json"
    index_status, index_error = _write_json(index_target, metadata, force=force)
    manifest.add_item(
        ManifestItem(
            kind="analysis_report_metadata",
            name=f"{object_name}_metadata",
            status=index_status,
            confidence=0.98,
            discovery_type=_DISCOVERY_TYPE,
            heuristic=True,
            path=manifest_relative_path(index_target, manifest_root),
            source_object_path=source_object_path,
            object_kind="metadata",
            range_start=record.source_start,
            range_end=record.source_end,
            extraction_method="origin_storage_report_attribution",
            completeness="partial",
            verification="exact",
            error=index_error,
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="analysis_report",
            name=object_name,
            status=status,
            confidence=0.98,
            discovery_type=_DISCOVERY_TYPE,
            heuristic=True,
            path=manifest_relative_path(report_target, manifest_root),
            source_object_path=source_object_path,
            object_kind="analysis_report",
            function_name=record.family,
            calculation_label=record.calculation_label,
            calculation_uid=calculation_uid,
            payload_family="origin_storage_xml",
            source_map_path=source_map_path,
            range_start=record.source_start,
            range_end=record.source_end,
            extraction_method="origin_storage_byte_run_report_decode",
            completeness="complete",
            verification="exact",
            error=error,
        )
    )
    return int(status == "extracted")


__all__ = ["extract_encoded_opju_report_window", "is_encoded_opju_report_candidate"]
