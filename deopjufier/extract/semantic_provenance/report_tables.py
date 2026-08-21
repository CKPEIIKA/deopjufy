"""Resolve descriptor-backed report tables through exact MSer string references."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from deopjufier.extract.discovery_helpers import book_dir
from deopjufier.extract.path_helpers import manifest_relative_path
from deopjufier.extract.tabular_helpers import write_book_csv, write_book_xlsx
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju.decoded import OpjuDecodedRegion
from deopjufier.opju.tagged import (
    OpjuColumnDescriptor,
    OpjuDescriptorTable,
    group_opju_column_descriptors,
    iter_opju_column_metadata,
)

# MSer string records have a 24-byte header. Stored report references are
# one-based offsets into the following string blob, hence decoded_start - 23.
_MSER_STRING_REFERENCE_BIAS = 23
_REPORT_TABLE_STRUCTURAL_NAME = "report_table"
_REPORT_TABLE_SEMANTIC_ALIAS = "analysis_report_placeholder_reference_table"
_REPORT_TABLE_SEMANTIC_CONFIDENCE = "corpus_high"


@dataclass(frozen=True)
class ResolvedReportTable:
    """One report-reference table whose every stored offset resolved uniquely."""

    report_table_id: str
    worksheet_id: str
    workbook: str | None
    sheet: str
    headers: list[str]
    offset_rows: list[list[int]]
    resolved_rows: list[list[str]]
    column_source_ranges: list[dict[str, int]]
    source_ranges: list[dict[str, int]]
    structural_name: str = _REPORT_TABLE_STRUCTURAL_NAME
    semantic_alias: str = _REPORT_TABLE_SEMANTIC_ALIAS
    semantic_confidence: str = _REPORT_TABLE_SEMANTIC_CONFIDENCE


def _region_mapping(region: OpjuDecodedRegion) -> dict[int, str] | None:
    classification = region.classification
    if (
        classification.family != "mser_strings_pset"
        or classification.completeness != "complete"
        or classification.verification != "exact"
    ):
        return None
    records = classification.fields.get("string_records")
    if not isinstance(records, list):
        return None
    mapping: dict[int, str] = {}
    for raw_record in records:
        if not isinstance(raw_record, dict):
            return None
        raw_record = cast(dict[str, object], raw_record)
        decoded_range = raw_record.get("decoded_range")
        value = raw_record.get("value")
        if not isinstance(decoded_range, dict) or not isinstance(value, str):
            return None
        decoded_range = cast(dict[str, object], decoded_range)
        decoded_start = decoded_range.get("start")
        if not isinstance(decoded_start, int) or decoded_start < 24:
            return None
        reference = decoded_start - _MSER_STRING_REFERENCE_BIAS
        if reference in mapping:
            return None
        mapping[reference] = value
    return mapping


def _integer_reference(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _table_offset_rows(table: OpjuDescriptorTable) -> list[list[int]] | None:
    rows: list[list[int]] = []
    for row_index in range(table.row_count):
        row: list[int] = []
        for column in table.columns:
            payload = column.descriptor.decoded_payload
            raw_value = payload.values[row_index] if payload is not None and row_index < len(payload.values) else None
            reference = _integer_reference(raw_value)
            if reference is None:
                return None
            row.append(reference)
        rows.append(row)
    return rows or None


def _source_regions(
    report: dict[str, object],
    regions_by_span: dict[tuple[int, int], OpjuDecodedRegion],
) -> list[tuple[OpjuDecodedRegion, dict[int, str]]] | None:
    sources: list[tuple[OpjuDecodedRegion, dict[int, str]]] = []
    for source_range in cast(list[dict[str, object]], report.get("source_ranges", [])):
        start = source_range.get("start")
        end = source_range.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        region = regions_by_span.get((start, end))
        mapping = _region_mapping(region) if region is not None else None
        if region is None or mapping is None:
            return None
        sources.append((region, mapping))
    return sources or None


def _resolve_columns(
    offset_rows: list[list[int]],
    sources: list[tuple[OpjuDecodedRegion, dict[int, str]]],
) -> tuple[list[list[str]], list[dict[str, int]]] | None:
    column_count = len(offset_rows[0])
    resolved_columns: list[list[str]] = []
    source_ranges: list[dict[str, int]] = []
    for column_index in range(column_count):
        references = [row[column_index] for row in offset_rows]
        candidates = [(region, mapping) for region, mapping in sources if all(value in mapping for value in references)]
        if len(candidates) != 1:
            return None
        region, mapping = candidates[0]
        resolved_columns.append([mapping[value] for value in references])
        source_ranges.append({"start": region.source_start, "end": region.source_end})
    resolved_rows = [
        [resolved_columns[column_index][row_index] for column_index in range(column_count)]
        for row_index in range(len(offset_rows))
    ]
    return resolved_rows, source_ranges


def resolve_report_tables(
    data: bytes,
    reports: list[dict[str, object]],
    descriptors: tuple[OpjuColumnDescriptor, ...],
    decoded_regions: tuple[OpjuDecodedRegion, ...],
) -> tuple[ResolvedReportTable, ...]:
    """Return report tables only when ownership and every string reference are exact."""
    metadata = iter_opju_column_metadata(data, descriptors)
    tables = {table.name: table for table in group_opju_column_descriptors(descriptors, metadata)}
    regions_by_span = {(region.source_start, region.source_end): region for region in decoded_regions}
    resolved: list[ResolvedReportTable] = []
    for report in reports:
        owners = report.get("owner_worksheet_ids")
        if report.get("ownership_status") != "resolved_exact" or not isinstance(owners, list) or len(owners) != 1:
            report["resolution_status"] = "unresolved_ownership"
            continue
        worksheet_id = owners[0]
        if not isinstance(worksheet_id, str):
            report["resolution_status"] = "unresolved_ownership"
            continue
        workbook_value = report.get("workbook")
        table = tables.get(worksheet_id)
        offset_rows = _table_offset_rows(table) if table is not None else None
        sources = _source_regions(report, regions_by_span)
        column_resolution = _resolve_columns(offset_rows, sources) if offset_rows is not None and sources else None
        if table is None or offset_rows is None or column_resolution is None:
            report["resolution_status"] = "unresolved_string_references"
            continue
        resolved_rows, column_source_ranges = column_resolution
        report["resolution_status"] = "resolved_exact"
        report["completeness"] = "complete"
        report["reference_semantics"] = "one_based_offset_into_mser_string_blob"
        report["structural_name"] = _REPORT_TABLE_STRUCTURAL_NAME
        report["semantic_alias"] = _REPORT_TABLE_SEMANTIC_ALIAS
        report["semantic_confidence"] = _REPORT_TABLE_SEMANTIC_CONFIDENCE
        resolved.append(
            ResolvedReportTable(
                report_table_id=str(report["report_table_id"]),
                worksheet_id=worksheet_id,
                workbook=workbook_value if isinstance(workbook_value, str) else None,
                sheet=str(report["sheet"]),
                headers=[column.display_name for column in table.columns],
                offset_rows=offset_rows,
                resolved_rows=resolved_rows,
                column_source_ranges=column_source_ranges,
                source_ranges=[*table.source_ranges, *column_source_ranges],
            )
        )
    return tuple(resolved)


def _write_table(target: Path, table: ResolvedReportTable, output_format: str) -> int:
    rows = [(0, index, 0, values) for index, values in enumerate(table.resolved_rows)]
    if output_format == "xlsx":
        return write_book_xlsx(target, rows, headers=table.headers)
    if output_format == "json":
        payload = {
            "structural_name": table.structural_name,
            "semantic_alias": table.semantic_alias,
            "semantic_confidence": table.semantic_confidence,
            "headers": table.headers,
            "rows": table.resolved_rows,
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return len(rows)
    delimiter = "\t" if output_format == "tsv" else ","
    return write_book_csv(target, rows, delimiter, headers=table.headers)


def write_resolved_report_tables(
    tables: tuple[ResolvedReportTable, ...],
    out_dir: Path,
    manifest: Manifest,
    *,
    output_format: str,
    force: bool,
    manifest_root: Path,
) -> int:
    """Materialize resolved tables and exact offset provenance."""
    extracted = 0
    extension = output_format if output_format in {"csv", "tsv", "json", "xlsx"} else "csv"
    for table in tables:
        target_dir = book_dir(out_dir / "report_tables", table.worksheet_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"report_table.{extension}"
        if target.exists() and not force:
            status, error = "skipped", "target_exists"
        else:
            _write_table(target, table, extension)
            status, error = "extracted", None
            extracted += 1

        offsets_target = target_dir / "report_table.offsets.json"
        offsets_payload = {
            "structural_name": table.structural_name,
            "semantic_alias": table.semantic_alias,
            "semantic_confidence": table.semantic_confidence,
            "headers": table.headers,
            "rows": table.offset_rows,
            "reference_semantics": "one_based_offset_into_mser_string_blob",
            "mser_string_reference_bias": _MSER_STRING_REFERENCE_BIAS,
            "column_source_ranges": table.column_source_ranges,
        }
        offsets_status = "skipped" if offsets_target.exists() and not force else "extracted"
        if offsets_status == "extracted":
            offsets_target.write_text(
                json.dumps(offsets_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        manifest.add_item(
            ManifestItem(
                kind="report_table_offsets",
                name=f"{table.worksheet_id}_offsets",
                status=offsets_status,
                confidence=1.0,
                discovery_type="opju_report_table_reference_resolution",
                heuristic=False,
                path=manifest_relative_path(offsets_target, manifest_root),
                source_object_path=f"report_tables/{table.worksheet_id}",
                object_kind="metadata",
                rows=len(table.offset_rows),
                columns=len(table.headers),
                source_ranges=table.source_ranges,
                extraction_method="opju_report_table_offset_preservation",
                completeness="complete",
                verification="exact",
                error="target_exists" if offsets_status == "skipped" else None,
            )
        )
        manifest.add_item(
            ManifestItem(
                kind="report_table",
                name=table.worksheet_id,
                status=status,
                confidence=0.98,
                discovery_type="opju_report_table_reference_resolution",
                heuristic=False,
                path=manifest_relative_path(target, manifest_root),
                source_object_path=f"report_tables/{table.worksheet_id}",
                object_kind="report_table",
                structural_name=table.structural_name,
                semantic_alias=table.semantic_alias,
                semantic_confidence=table.semantic_confidence,
                rows=len(table.resolved_rows),
                columns=len(table.headers),
                content_class="resolved_report_references",
                source_ranges=table.source_ranges,
                extraction_method="opju_report_table_reference_resolution",
                completeness="complete",
                verification="exact",
                error=error,
            )
        )
    return extracted


__all__ = ["ResolvedReportTable", "resolve_report_tables", "write_resolved_report_tables"]
