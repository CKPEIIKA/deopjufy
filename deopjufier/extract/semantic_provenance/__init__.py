"""Canonical OPJU symbol, analysis, and source-column provenance exports."""

from __future__ import annotations

import csv
import html
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import cast

from deopjufier.extract.path_helpers import manifest_relative_path
from deopjufier.extract.semantic_provenance.relationships import (
    SemanticRelationships,
    build_semantic_relationships,
)
from deopjufier.extract.semantic_provenance.report_tables import (
    resolve_report_tables,
    write_resolved_report_tables,
)
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju.analysis import analyze_origin_storage_candidates
from deopjufier.opju.decoded import OpjuDecodedRegion, iter_opju_decoded_regions
from deopjufier.opju.regions import iter_origin_storage_candidates
from deopjufier.opju.reports import (
    OpjuOriginStorageField,
    OpjuOriginStorageReport,
    parse_opju_origin_storage_reports,
    parse_origin_storage_leaf_fields,
)
from deopjufier.opju.tagged import (
    OpjuColumnDescriptor,
    OpjuDescriptorTable,
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
    opju_column_post_payload_range,
)
from deopjufier.opju.walker import OpjuWalkElement

_ORIGIN_REFERENCE_RE = re.compile(
    r"\[(?P<workbook>[^\]\r\n]+)\](?P<sheet>[^!\r\n]+)!(?P<column>\$?[A-Z]{1,3})(?=$|[^A-Za-z])"
)
_PARAMETER_PATH_MARKER = "/Parameters/"
_RESULT_PATH_MARKERS = ("/RegStats/", "/Summary/", "/ANOVAs/")
_TABLE_FIELD_TAGS = frozenset({"BookName", "Sheet", "SheetName", "TableID"})
_FUNCTION_EXTRACTION_METHOD = "origin_storage_byte_run_decode"
_REPORT_EXTRACTION_METHOD = "origin_storage_byte_run_report_decode"


def _range_payload(start: int, end: int) -> dict[str, int]:
    return {"start": start, "end": end}


def _metadata_ranges(table: OpjuDescriptorTable, column_index: int) -> list[dict[str, int]]:
    metadata = table.columns[column_index].metadata
    if metadata is None:
        return []
    return [_range_payload(start, end) for start, end in metadata.source_ranges]


def _sheet_aliases(table: OpjuDescriptorTable) -> tuple[str, ...]:
    aliases = [f"Sheet{table.sheet_index}"]
    long_names = {
        column.metadata.sheet_long_name
        for column in table.columns
        if column.metadata is not None and column.metadata.sheet_long_name
    }
    if len(long_names) == 1:
        aliases.append(next(iter(long_names)))
    return tuple(dict.fromkeys(aliases))


def _workbook_aliases(table: OpjuDescriptorTable) -> tuple[str, ...]:
    aliases = [table.workbook]
    for field_name in ("workbook", "workbook_long_name"):
        values = {
            getattr(column.metadata, field_name)
            for column in table.columns
            if column.metadata is not None and getattr(column.metadata, field_name)
        }
        if len(values) == 1:
            aliases.append(next(iter(values)))
    return tuple(dict.fromkeys(aliases))


def _symbol_payload(
    table: OpjuDescriptorTable,
    column_index: int,
    workbook_aliases: tuple[str, ...],
    sheet_aliases: tuple[str, ...],
) -> dict[str, object]:
    column = table.columns[column_index]
    payload = column.descriptor.decoded_payload
    origin_address = f"[{table.workbook}]Sheet{table.sheet_index}!{column.identity.column_name}"
    aliases = [column.identity.dataset_name, origin_address]
    aliases.extend(
        f"[{workbook}]{sheet}!{column.identity.column_name}"
        for workbook in workbook_aliases
        for sheet in sheet_aliases
        if workbook != table.workbook or sheet != f"Sheet{table.sheet_index}"
    )
    if column.long_name:
        aliases.append(column.long_name)
    descriptor_range = _range_payload(column.descriptor.start_offset, column.descriptor.end_offset)
    symbol_id = f"worksheet:{origin_address}"
    return {
        "symbol_id": symbol_id,
        "symbol": column.long_name or column.identity.dataset_name,
        "aliases": list(dict.fromkeys(aliases)),
        "address": {
            "workbook": table.workbook,
            "workbook_aliases": list(workbook_aliases),
            "sheet": f"Sheet{table.sheet_index}",
            "sheet_aliases": list(sheet_aliases),
            "sheet_index": table.sheet_index,
            "column": column.identity.column_name,
            "display_name": column.display_name,
            "dataset_name": column.identity.dataset_name,
            "origin": origin_address,
        },
        "semantic_object": {
            "kind": "worksheet_column",
            "source_object_path": f"worksheets/{table.name}",
            "worksheet": table.name,
        },
        "metadata": {
            "designation": column.designation,
            "long_name": column.long_name,
            "units": column.units,
            "comment": column.metadata.comment if column.metadata is not None else None,
            "value_type": column.value_type,
        },
        "value_shape": {
            "row_capacity": payload.row_capacity if payload is not None else None,
            "stored_value_count": payload.stored_value_count if payload is not None else None,
            "missing_count": payload.missing_count if payload is not None else None,
        },
        "formula": column.formula,
        "source": {
            "descriptor_range": descriptor_range,
            "metadata_ranges": _metadata_ranges(table, column_index),
        },
        "analysis_links": [],
        "provenance_status": "column_formula" if column.formula else "source_column_only",
        "equation_status": "column_formula" if column.formula else "no_attributable_equation_recovered",
        "external_code_status": "not_assessed",
        "verification": "exact",
    }


def _build_symbols(
    data: bytes,
    *,
    descriptors: tuple[OpjuColumnDescriptor, ...] | None = None,
) -> tuple[
    list[dict[str, object]],
    dict[tuple[str, str, str], list[str]],
    dict[tuple[int, int], str],
    tuple[OpjuColumnDescriptor, ...],
    list[dict[str, int]],
]:
    if descriptors is None:
        descriptors = iter_opju_column_descriptors(data)
    metadata = iter_opju_column_metadata(data, descriptors)
    tables = group_opju_column_descriptors(descriptors, metadata)
    symbols: list[dict[str, object]] = []
    lookup: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    descriptor_symbols: dict[tuple[int, int], str] = {}
    source_ranges: list[dict[str, int]] = []
    for table in tables:
        sheet_aliases = _sheet_aliases(table)
        workbook_aliases = _workbook_aliases(table)
        for column_index, column in enumerate(table.columns):
            symbol = _symbol_payload(table, column_index, workbook_aliases, sheet_aliases)
            symbol_id = str(symbol["symbol_id"])
            symbols.append(symbol)
            descriptor_symbols[(column.descriptor.start_offset, column.descriptor.end_offset)] = symbol_id
            source_ranges.append(_range_payload(column.descriptor.start_offset, column.descriptor.end_offset))
            source_ranges.extend(_metadata_ranges(table, column_index))
            for workbook_alias in workbook_aliases:
                for sheet_alias in sheet_aliases:
                    lookup[(workbook_alias, sheet_alias, column.identity.column_name)].append(symbol_id)
    return symbols, lookup, descriptor_symbols, descriptors, source_ranges


def _field_payload(field: OpjuOriginStorageField, *, source_map_path: str | None = None) -> dict[str, object]:
    payload = field.to_dict()
    if source_map_path is not None:
        payload["source_map_reference"] = {
            "path": source_map_path,
            "decoded_range": payload["payload_range"],
        }
    return payload


def _selected_fields(
    fields: tuple[OpjuOriginStorageField, ...],
    *,
    path_marker: str | None = None,
    path_markers: tuple[str, ...] = (),
    tags: frozenset[str] = frozenset(),
    source_map_path: str | None = None,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for field in fields:
        path = field.path or ""
        if path_marker is not None and path_marker not in path:
            continue
        if path_markers and not any(marker in path for marker in path_markers):
            continue
        if tags and field.tag not in tags:
            continue
        selected.append(_field_payload(field, source_map_path=source_map_path))
    return selected


def _equation_fields(
    fields: tuple[OpjuOriginStorageField, ...], *, source_map_path: str | None = None
) -> list[dict[str, object]]:
    return [
        _field_payload(field, source_map_path=source_map_path) for field in fields if field.tag.casefold() == "equation"
    ]


def _reference_fields(
    fields: tuple[OpjuOriginStorageField, ...], *, source_map_path: str | None = None
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for field in fields:
        decoded_value = html.unescape(field.value)
        for match in _ORIGIN_REFERENCE_RE.finditer(decoded_value):
            workbook = match.group("workbook")
            sheet = match.group("sheet").strip("'")
            column = match.group("column").lstrip("$")
            references.append(
                {
                    "reference": f"[{workbook}]{sheet}!{column}",
                    "workbook": workbook,
                    "sheet": sheet,
                    "column": column,
                    "field": _field_payload(field, source_map_path=source_map_path),
                }
            )
    return references


def _analysis_semantic_status(entry: dict[str, object]) -> str:
    equations = entry["equations"]
    references = entry["references"]
    assert isinstance(equations, list)
    assert isinstance(references, list)
    if equations and references:
        return "equation_with_source_references"
    if equations:
        return "equation_without_source_reference"
    if references:
        return "source_references_without_equation"
    if entry["parameter_fields"]:
        return "parameters_without_equation_or_source_reference"
    return "leaf_fields_only"


def _analysis_entry(
    report: OpjuOriginStorageReport,
    index: int,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "analysis_id": f"origin_storage_analysis:{index:03d}",
        "evidence_kind": "origin_storage_leaf_fields",
        "source_object_path": f"analyses/origin_storage_analysis_{index:03d}",
        "label": report.label,
        "function": report.function,
        "field_count": len(report.fields),
        "equations": _equation_fields(report.fields),
        "references": _reference_fields(report.fields),
        "parameter_fields": _selected_fields(report.fields, path_marker=_PARAMETER_PATH_MARKER),
        "result_fields": _selected_fields(report.fields, path_markers=_RESULT_PATH_MARKERS),
        "operation_fields": _selected_fields(report.fields, path_marker="/Operation/"),
        "table_fields": _selected_fields(report.fields, tags=_TABLE_FIELD_TAGS),
        "completeness": "partial",
        "verification": "exact",
        "source_attribution": "raw_source_ranges"
        if report.fields
        and all(field.source_start is not None and field.source_end is not None for field in report.fields)
        else "decoded_payload_ranges",
    }
    if report.length > 0:
        entry["source_range"] = _range_payload(report.offset, report.offset + report.length)
    entry["semantic_status"] = _analysis_semantic_status(entry)
    return entry


def _report_entries(data: bytes) -> tuple[list[dict[str, object]], list[dict[str, int]]]:
    candidates = tuple(iter_origin_storage_candidates(data, include_decoded=True))
    analyses = analyze_origin_storage_candidates(data, include_decoded=True, candidates=candidates)
    reports = parse_opju_origin_storage_reports(
        data,
        max_reports=1000,
        include_decoded=True,
        include_analyses=True,
        candidates=candidates,
        analyses=analyses,
    )
    record_reports = [report for report in reports if report.fields]
    entries = [_analysis_entry(report, index) for index, report in enumerate(record_reports)]
    source_ranges = [
        _range_payload(report.offset, report.offset + report.length) for report in record_reports if report.length > 0
    ]
    return entries, source_ranges


def _artifact_path(out_dir: Path, relative_path: str | None) -> Path | None:
    if relative_path is None:
        return None
    target = out_dir / relative_path
    try:
        target.resolve(strict=False).relative_to(out_dir.resolve(strict=False))
    except ValueError:
        return None
    return target if target.is_file() else None


def _manifest_xml_entries(
    out_dir: Path,
    manifest: Manifest,
    *,
    kind: str,
    extraction_method: str,
    analysis_id_prefix: str,
    evidence_kind: str,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    items = sorted(
        (
            item
            for item in manifest.items
            if item.kind == kind and item.extraction_method == extraction_method and item.verification == "exact"
        ),
        key=lambda item: (item.source_object_path or "", item.name),
    )
    for item in items:
        target = _artifact_path(out_dir, item.path)
        if target is None:
            continue
        fields = parse_origin_storage_leaf_fields(target.read_bytes())
        entry: dict[str, object] = {
            "analysis_id": f"{analysis_id_prefix}:{item.name}",
            "evidence_kind": evidence_kind,
            "source_object_path": item.source_object_path,
            "artifact_path": item.path,
            "source_map_path": item.source_map_path,
            "function": item.function_name,
            "calculation_label": item.calculation_label,
            "calculation_uid": item.calculation_uid,
            "field_count": len(fields),
            "equations": _equation_fields(fields, source_map_path=item.source_map_path),
            "references": _reference_fields(fields, source_map_path=item.source_map_path),
            "parameter_fields": _selected_fields(
                fields,
                path_marker=_PARAMETER_PATH_MARKER,
                source_map_path=item.source_map_path,
            ),
            "result_fields": _selected_fields(
                fields,
                path_markers=_RESULT_PATH_MARKERS,
                source_map_path=item.source_map_path,
            ),
            "operation_fields": _selected_fields(
                fields,
                path_marker="/Operation/",
                source_map_path=item.source_map_path,
            ),
            "table_fields": _selected_fields(fields, tags=_TABLE_FIELD_TAGS, source_map_path=item.source_map_path),
            "completeness": "partial",
            "verification": "exact",
            "source_attribution": "decoded_byte_source_map" if item.source_map_path else "encoded_record_range",
        }
        if item.source_ranges:
            entry["source_ranges"] = item.source_ranges
        entry["semantic_status"] = _analysis_semantic_status(entry)
        entries.append(entry)
    return entries


def _function_entries(out_dir: Path, manifest: Manifest) -> list[dict[str, object]]:
    return _manifest_xml_entries(
        out_dir,
        manifest,
        kind="function",
        extraction_method=_FUNCTION_EXTRACTION_METHOD,
        analysis_id_prefix="function",
        evidence_kind="origin_storage_function_xml",
    )


def _recovered_report_entries(out_dir: Path, manifest: Manifest) -> list[dict[str, object]]:
    return _manifest_xml_entries(
        out_dir,
        manifest,
        kind="analysis_report",
        extraction_method=_REPORT_EXTRACTION_METHOD,
        analysis_id_prefix="analysis_report",
        evidence_kind="origin_storage_byte_run_report_xml",
    )


def _resolve_references(
    analyses: list[dict[str, object]],
    symbols: list[dict[str, object]],
    lookup: dict[tuple[str, str, str], list[str]],
) -> int:
    symbols_by_id = {str(symbol["symbol_id"]): symbol for symbol in symbols}
    unresolved_count = 0
    for analysis in analyses:
        references = cast(list[dict[str, object]], analysis["references"])
        equations = cast(list[dict[str, object]], analysis["equations"])
        equation_values = [str(equation["value"]) for equation in equations]
        for reference in references:
            key = (str(reference["workbook"]), str(reference["sheet"]), str(reference["column"]))
            symbol_ids = lookup.get(key, [])
            reference["symbol_ids"] = symbol_ids
            if len(symbol_ids) == 1:
                reference["status"] = "resolved_exact"
                symbol = symbols_by_id[symbol_ids[0]]
                links = cast(list[dict[str, object]], symbol["analysis_links"])
                field = cast(dict[str, object], reference["field"])
                links.append(
                    {
                        "analysis_id": analysis["analysis_id"],
                        "role": field["tag"],
                        "field_path": field.get("path"),
                        "reference": reference["reference"],
                        "equations": equation_values,
                    }
                )
                continue
            unresolved_count += 1
            reference["status"] = "ambiguous_exact_match" if symbol_ids else "unresolved"
    return unresolved_count


def _descriptor_envelopes(
    data: bytes,
    descriptors: tuple[OpjuColumnDescriptor, ...],
    descriptor_symbols: dict[tuple[int, int], str],
) -> list[tuple[int, int, str]]:
    envelopes: list[tuple[int, int, str]] = []
    for descriptor in descriptors:
        symbol_id = descriptor_symbols.get((descriptor.start_offset, descriptor.end_offset))
        envelope_range = opju_column_post_payload_range(data, descriptor)
        if symbol_id is None or envelope_range is None:
            continue
        envelopes.append((*envelope_range, symbol_id))
    return envelopes


def _owning_envelope(
    source_start: int,
    source_end: int,
    envelopes: list[tuple[int, int, str]],
) -> str | None:
    owners = [
        symbol_id
        for envelope_start, envelope_end, symbol_id in envelopes
        if envelope_start <= source_start and source_end <= envelope_end
    ]
    return owners[0] if len(owners) == 1 else None


def _functions_by_uid(analyses: list[dict[str, object]]) -> dict[int, list[dict[str, object]]]:
    functions: dict[int, list[dict[str, object]]] = defaultdict(list)
    for analysis in analyses:
        uid = analysis.get("calculation_uid")
        if analysis.get("evidence_kind") == "origin_storage_function_xml" and isinstance(uid, int):
            functions[uid].append(analysis)
    return functions


def _storage_reference_records(region_fields: dict[str, object]) -> tuple[list[int], list[int]]:
    raw_records = region_fields.get("records")
    if not isinstance(raw_records, list):
        return [], []
    uids: set[int] = set()
    ordinals: set[int] = set()
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record = cast(dict[str, object], raw_record)
        uid = record.get("calculation_uid")
        ordinal = record.get("ordinal")
        if isinstance(uid, int):
            uids.add(uid)
        if isinstance(ordinal, int):
            ordinals.add(ordinal)
    return sorted(uids), sorted(ordinals)


def _calculation_link(
    *,
    symbol_id: str | None,
    uid: int,
    ordinals: list[int],
    source_start: int,
    source_end: int,
    functions: list[dict[str, object]],
) -> dict[str, object]:
    if symbol_id is None:
        status = "unresolved_column_owner"
    elif len(functions) == 1:
        status = "resolved_exact"
    elif functions:
        status = "ambiguous_calculation_uid"
    else:
        status = "unresolved_calculation_uid"
    return {
        "status": status,
        "symbol_id": symbol_id,
        "calculation_uid": uid,
        "dependency_ordinals_zero_based": ordinals,
        "function_analysis_ids": [function["analysis_id"] for function in functions],
        "source_range": _range_payload(source_start, source_end),
        "ownership_rule": "decoded region is inside the column descriptor's bounded post-payload envelope",
        "verification": "exact",
    }


def _link_calculations(
    data: bytes,
    analyses: list[dict[str, object]],
    symbols: list[dict[str, object]],
    descriptors: tuple[OpjuColumnDescriptor, ...],
    descriptor_symbols: dict[tuple[int, int], str],
    regions: tuple[OpjuDecodedRegion, ...] | None = None,
) -> list[dict[str, object]]:
    symbols_by_id = {str(symbol["symbol_id"]): symbol for symbol in symbols}
    functions_by_uid = _functions_by_uid(analyses)
    envelopes = _descriptor_envelopes(data, descriptors, descriptor_symbols)
    links: list[dict[str, object]] = []
    if regions is None:
        regions = iter_opju_decoded_regions(data)
    for region in regions:
        if region.classification.family != "storage_cell_ref_data":
            continue
        uids, ordinals = _storage_reference_records(region.classification.fields)
        symbol_id = _owning_envelope(region.source_start, region.source_end, envelopes)
        for uid in uids:
            functions = functions_by_uid.get(uid, [])
            link = _calculation_link(
                symbol_id=symbol_id,
                uid=uid,
                ordinals=ordinals,
                source_start=region.source_start,
                source_end=region.source_end,
                functions=functions,
            )
            links.append(link)
            if link["status"] != "resolved_exact" or symbol_id is None:
                continue
            symbol_links = cast(list[dict[str, object]], symbols_by_id[symbol_id]["analysis_links"])
            function = functions[0]
            equations = cast(list[dict[str, object]], function["equations"])
            symbol_links.append(
                {
                    "analysis_id": function["analysis_id"],
                    "role": "computed_column",
                    "field_path": None,
                    "reference": f"calculation_uid:{uid}",
                    "relationship": "storage_cell_calculation_uid",
                    "equations": [str(equation["value"]) for equation in equations],
                    "source_range": link["source_range"],
                }
            )
    return links


def _finalize_symbols(symbols: list[dict[str, object]]) -> None:
    for symbol in symbols:
        links = cast(list[dict[str, object]], symbol["analysis_links"])
        links.sort(key=lambda link: (str(link["analysis_id"]), str(link["reference"]), str(link["field_path"])))
        formula = symbol["formula"]
        linked_equations = {
            equation
            for link in links
            for equation in cast(list[object], link["equations"])
            if isinstance(equation, str) and equation
        }
        calculation_linked = any(link.get("relationship") == "storage_cell_calculation_uid" for link in links)
        if calculation_linked and formula:
            symbol["provenance_status"] = "column_formula_and_calculation_link"
        elif calculation_linked:
            symbol["provenance_status"] = "linked_to_calculation"
        elif links and formula:
            symbol["provenance_status"] = "column_formula_and_analysis_link"
        elif links:
            symbol["provenance_status"] = "linked_to_analysis"
        if linked_equations:
            symbol["equation_status"] = "attributable_equation_recovered"
        elif links:
            symbol["equation_status"] = "linked_analysis_has_no_equation"


def _deduplicated_ranges(ranges: list[dict[str, int]]) -> list[dict[str, int]]:
    return [
        _range_payload(start, end)
        for start, end in sorted({(item["start"], item["end"]) for item in ranges if item["end"] > item["start"]})
    ]


def _semantic_payload(
    symbols: list[dict[str, object]],
    analyses: list[dict[str, object]],
    calculation_links: list[dict[str, object]],
    unresolved_reference_count: int,
    relationships: SemanticRelationships,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "status": "partial",
        "scope": (
            "OPJU worksheet identity, worksheet-column, OriginStorage analysis, report/state-table, and graph-layer "
            "source-binding provenance"
        ),
        "non_claims": [
            "Structural references do not establish scientific meaning.",
            "External source-code locations are not assessed by the extractor.",
            "Absent links mean no attributable relation was recovered by the confirmed grammar; "
            "they do not prove that no relation exists.",
            "A persistent style-holder source slot is not proof that the dataset is a currently rendered curve.",
        ],
        "summary": {
            "symbol_count": len(symbols),
            "analysis_count": len(analyses),
            "equation_count": sum(len(cast(list[object], analysis["equations"])) for analysis in analyses),
            "linked_symbol_count": sum(bool(symbol["analysis_links"]) for symbol in symbols),
            "calculation_link_count": len(calculation_links),
            "resolved_calculation_link_count": sum(link["status"] == "resolved_exact" for link in calculation_links),
            "unresolved_reference_count": unresolved_reference_count,
            "worksheet_identity_count": len(relationships.worksheet_identities),
            "analysis_alias_count": len(relationships.analysis_aliases),
            "resolved_analysis_alias_count": sum(
                alias["status"] == "resolved_exact" for alias in relationships.analysis_aliases
            ),
            "report_table_count": len(relationships.report_tables),
            "resolved_report_table_count": sum(
                report.get("resolution_status") == "resolved_exact" for report in relationships.report_tables
            ),
            "report_cell_reference_count": sum(
                cast(int, report["cell_reference_count"]) for report in relationships.report_tables
            ),
            "analysis_linked_report_table_count": sum(
                bool(report["analysis_ids"]) for report in relationships.report_tables
            ),
            "state_table_count": len(relationships.state_tables),
            "graph_binding_count": len(relationships.graph_bindings),
            "resolved_graph_binding_count": sum(
                binding["dataset_binding_status"] == "resolved_exact" for binding in relationships.graph_bindings
            ),
            "external_code_mapping": "not_assessed",
        },
        "symbols": symbols,
        "analyses": analyses,
        "calculation_links": calculation_links,
        "worksheet_identities": relationships.worksheet_identities,
        "analysis_aliases": relationships.analysis_aliases,
        "report_tables": relationships.report_tables,
        "state_tables": relationships.state_tables,
        "graph_bindings": relationships.graph_bindings,
    }


def _write_json(target: Path, payload: dict[str, object], *, force: bool) -> tuple[str, str | None]:
    if target.exists() and not force:
        return "skipped", "target_exists"
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return "extracted", None


def _symbol_equations(symbol: dict[str, object]) -> list[str]:
    links = cast(list[dict[str, object]], symbol["analysis_links"])
    return sorted({str(equation) for link in links for equation in cast(list[object], link["equations"]) if equation})


def _write_symbols_tsv(target: Path, symbols: list[dict[str, object]], *, force: bool) -> tuple[str, str | None]:
    if target.exists() and not force:
        return "skipped", "target_exists"
    header = (
        "symbol_id",
        "symbol",
        "workbook",
        "sheet",
        "column",
        "dataset_name",
        "designation",
        "units",
        "formula",
        "provenance_status",
        "equation_status",
        "linked_analysis_ids",
        "equations",
        "external_code_status",
        "descriptor_start",
        "descriptor_end",
        "metadata_ranges",
    )
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        for symbol in symbols:
            address = cast(dict[str, object], symbol["address"])
            metadata = cast(dict[str, object], symbol["metadata"])
            source = cast(dict[str, object], symbol["source"])
            links = cast(list[dict[str, object]], symbol["analysis_links"])
            descriptor_range = cast(dict[str, object], source["descriptor_range"])
            writer.writerow(
                (
                    symbol["symbol_id"],
                    symbol["symbol"],
                    address["workbook"],
                    address["sheet"],
                    address["column"],
                    address["dataset_name"],
                    metadata["designation"],
                    metadata["units"],
                    symbol["formula"],
                    symbol["provenance_status"],
                    symbol["equation_status"],
                    " | ".join(sorted({str(link["analysis_id"]) for link in links})),
                    " | ".join(_symbol_equations(symbol)),
                    symbol["external_code_status"],
                    descriptor_range["start"],
                    descriptor_range["end"],
                    json.dumps(source["metadata_ranges"], separators=(",", ":")),
                )
            )
    return "extracted", None


def _relationship_rows(relationships: SemanticRelationships) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for identity in relationships.worksheet_identities:
        canonical = cast(dict[str, object], identity["canonical_address"])
        rows.append(
            (
                "worksheet_identity",
                str(identity["worksheet_id"]),
                str(identity["identity_status"]),
                f"[{canonical['workbook']}]{canonical['sheet']}",
                json.dumps(identity["address_aliases"], separators=(",", ":"), sort_keys=True),
                str(identity["worksheet_id"]),
                "",
                "descriptor and exact identity fields",
                json.dumps(identity["source_ranges"], separators=(",", ":")),
            )
        )
    for index, alias in enumerate(relationships.analysis_aliases):
        address = cast(dict[str, object], alias["reference_address"])
        rows.append(
            (
                "analysis_alias",
                f"analysis_alias:{index:04d}",
                str(alias["status"]),
                f"[{address['workbook']}]{address['sheet']}",
                " | ".join(cast(list[str], alias["worksheet_candidates"])),
                "",
                " | ".join(cast(list[str], alias["analysis_ids"])),
                str(alias["candidate_rule"]),
                "",
            )
        )
    for report in relationships.report_tables:
        owners = cast(list[str], report["owner_worksheet_ids"])
        analysis_ids = cast(list[str], report["analysis_ids"])
        rows.append(
            (
                "report_table",
                str(report["report_table_id"]),
                str(report["ownership_status"]),
                f"[{report['workbook']}]{report['sheet']}",
                f"{report['cell_reference_count']} cell references",
                " | ".join(owners),
                " | ".join(analysis_ids),
                str(report["ownership_rule"]),
                json.dumps(report["source_ranges"], separators=(",", ":")),
            )
        )
        for index, cell in enumerate(cast(list[dict[str, object]], report["cells"])):
            rows.append(
                (
                    "report_cell",
                    f"{report['report_table_id']}:cell:{index:04d}",
                    "decoded_exact",
                    str(cell["uri"]),
                    str(cell["cell_path"]),
                    " | ".join(owners),
                    " | ".join(analysis_ids),
                    str(cell["source_attribution"]),
                    json.dumps(cell["source_region_range"], separators=(",", ":")),
                )
            )
    for state in relationships.state_tables:
        rows.append(
            (
                "report_state",
                str(state["state_table_id"]),
                "decoded_fields_partial",
                " | ".join(cast(list[str], state["operations"])),
                f"{len(cast(list[object], state['string_fields']))} strings; "
                f"{len(cast(list[object], state['scalar_fields']))} scalars",
                "",
                "",
                str(state["semantic_status"]),
                json.dumps(state["source_range"], separators=(",", ":")),
            )
        )
    for binding in relationships.graph_bindings:
        source = cast(dict[str, object], binding["source"])
        candidates = cast(list[dict[str, str]], binding["dataset_candidates"])
        rows.append(
            (
                "graph_binding",
                str(binding["graph_binding_id"]),
                str(binding["dataset_binding_status"]),
                f"{source['worksheet']}!{source['x_column_short_name']}:{source['y_column_short_name']}",
                " | ".join(candidate["worksheet_id"] for candidate in candidates),
                str(binding["graph_owner_status"]),
                "",
                str(binding["binding_semantics"]),
                json.dumps(binding["source_region_range"], separators=(",", ":")),
            )
        )
    return rows


def _write_relationships_tsv(
    target: Path,
    relationships: SemanticRelationships,
    *,
    force: bool,
) -> tuple[str, str | None, int]:
    if target.exists() and not force:
        return "skipped", "target_exists", 0
    rows = _relationship_rows(relationships)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "kind",
                "relationship_id",
                "status",
                "source",
                "target",
                "owner",
                "analysis_ids",
                "evidence",
                "source_ranges",
            )
        )
        writer.writerows(rows)
    return "extracted", None, len(rows)


def extract_opju_semantic_provenance(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    descriptors: tuple[OpjuColumnDescriptor, ...] | None = None,
    decoded_regions: tuple[OpjuDecodedRegion, ...] | None = None,
    walk_elements: list[OpjuWalkElement] | None = None,
    output_format: str = "csv",
) -> int:
    """Write a canonical, confidence-explicit OPJU scientific provenance index."""
    data = file_data if file_data is not None else input_path.read_bytes()
    symbols, lookup, descriptor_symbols, parsed_descriptors, source_ranges = _build_symbols(
        data,
        descriptors=descriptors,
    )
    analyses, analysis_ranges = _report_entries(data)
    analyses.extend(_function_entries(out_dir, manifest))
    analyses.extend(_recovered_report_entries(out_dir, manifest))
    analyses.sort(key=lambda entry: str(entry["analysis_id"]))
    if decoded_regions is None:
        decoded_regions = iter_opju_decoded_regions(data)
    calculation_links = _link_calculations(
        data,
        analyses,
        symbols,
        parsed_descriptors,
        descriptor_symbols,
        regions=decoded_regions,
    )
    relationships = build_semantic_relationships(
        data,
        symbols,
        analyses,
        lookup,
        parsed_descriptors,
        descriptor_symbols,
        decoded_regions,
        manifest,
        walk_elements=walk_elements,
    )
    resolved_report_tables = resolve_report_tables(
        data,
        relationships.report_tables,
        parsed_descriptors,
        decoded_regions,
    )
    if (
        not symbols
        and not analyses
        and not any((relationships.report_tables, relationships.state_tables, relationships.graph_bindings))
    ):
        return 0
    unresolved_reference_count = _resolve_references(analyses, symbols, lookup)
    _finalize_symbols(symbols)
    symbols.sort(key=lambda symbol: str(symbol["symbol_id"]))
    payload = _semantic_payload(symbols, analyses, calculation_links, unresolved_reference_count, relationships)

    target_dir = out_dir / "provenance"
    target_dir.mkdir(parents=True, exist_ok=True)
    json_target = target_dir / "semantic_index.json"
    tsv_target = target_dir / "symbols.tsv"
    relationships_target = target_dir / "relationships.tsv"
    json_status, json_error = _write_json(json_target, payload, force=force)
    tsv_status, tsv_error = _write_symbols_tsv(tsv_target, symbols, force=force)
    relationships_status, relationships_error, relationship_row_count = _write_relationships_tsv(
        relationships_target,
        relationships,
        force=force,
    )
    root = manifest_root or out_dir
    write_resolved_report_tables(
        resolved_report_tables,
        out_dir,
        manifest,
        output_format=output_format,
        force=force,
        manifest_root=root,
    )
    calculation_ranges = [cast(dict[str, int], link["source_range"]) for link in calculation_links]
    ranges = _deduplicated_ranges([*source_ranges, *analysis_ranges, *calculation_ranges, *relationships.source_ranges])
    unresolved_calculations = sum(link["status"] != "resolved_exact" for link in calculation_links)
    unresolved_graph_bindings = sum(
        binding["dataset_binding_status"] != "resolved_exact" for binding in relationships.graph_bindings
    )
    has_unresolved = bool(unresolved_reference_count or unresolved_calculations or unresolved_graph_bindings)
    confidence = 0.98 if not has_unresolved else 0.95
    error = "unresolved_semantic_relationships" if has_unresolved else None
    for name, target, status, write_error, columns in (
        ("opju_semantic_index", json_target, json_status, json_error, None),
        ("opju_symbol_provenance", tsv_target, tsv_status, tsv_error, 17),
        (
            "opju_semantic_relationships",
            relationships_target,
            relationships_status,
            relationships_error,
            9,
        ),
    ):
        rows = relationship_row_count if target == relationships_target else len(symbols)
        manifest.add_item(
            ManifestItem(
                kind="semantic_provenance",
                name=name,
                status=status,
                confidence=confidence,
                discovery_type="opju_exact_semantic_relationships",
                heuristic=False,
                path=manifest_relative_path(target, root),
                source_object_path="provenance",
                object_kind="metadata",
                rows=rows,
                columns=columns,
                source_ranges=ranges,
                extraction_method="opju_exact_semantic_relationships",
                completeness="partial",
                verification="exact",
                error=write_error or error,
            )
        )
    return len(symbols)


__all__ = ["extract_opju_semantic_provenance"]
