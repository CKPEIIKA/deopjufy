"""Exact and confidence-explicit OPJU semantic relationship recovery."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import cast

from deopjufier.manifest import Manifest
from deopjufier.opju.common import OPJU_REGION_KIND_TAGGED_BINARY
from deopjufier.opju.decoded import OpjuDecodedRegion
from deopjufier.opju.tagged import (
    OpjuColumnDescriptor,
    iter_tagged_scalars,
    iter_tagged_strings,
    opju_column_post_payload_range,
)
from deopjufier.opju.walker import OpjuWalkElement, walk_opju_file

_CELL_URI_RE = re.compile(r"cell://(?:\[(?P<workbook>[^\]\r\n]+)\])?(?P<sheet>[^!\r\n]+)!(?P<path>.+)")
_STATE_OPERATIONS = frozenset({"COKOGrid_MainRange", "COKOGrid_SetTree", "_TableRange"})


@dataclass(frozen=True)
class SemanticRelationships:
    """Relationship collections added to the canonical semantic index."""

    worksheet_identities: list[dict[str, object]]
    analysis_aliases: list[dict[str, object]]
    report_tables: list[dict[str, object]]
    state_tables: list[dict[str, object]]
    graph_bindings: list[dict[str, object]]
    source_ranges: list[dict[str, int]]


@dataclass
class _ReportAccumulator:
    workbook: str | None
    sheet: str
    cells: list[dict[str, object]] = field(default_factory=list)
    owner_symbol_ids: set[str] = field(default_factory=set)
    source_spans: set[tuple[int, int]] = field(default_factory=set)


def _range_payload(start: int, end: int) -> dict[str, int]:
    return {"start": start, "end": end}


def _descriptor_envelopes(
    data: bytes,
    descriptors: tuple[OpjuColumnDescriptor, ...],
    descriptor_symbols: dict[tuple[int, int], str],
) -> list[tuple[int, int, str]]:
    envelopes: list[tuple[int, int, str]] = []
    for descriptor in descriptors:
        symbol_id = descriptor_symbols.get((descriptor.start_offset, descriptor.end_offset))
        envelope = opju_column_post_payload_range(data, descriptor)
        if symbol_id is not None and envelope is not None:
            envelopes.append((*envelope, symbol_id))
    return envelopes


def _enclosing_symbol(region: OpjuDecodedRegion, envelopes: list[tuple[int, int, str]]) -> str | None:
    owners = [
        symbol_id for start, end, symbol_id in envelopes if start <= region.source_start and region.source_end <= end
    ]
    return owners[0] if len(owners) == 1 else None


def _string_records(region: OpjuDecodedRegion) -> list[dict[str, object]]:
    raw_records = region.classification.fields.get("string_records")
    if isinstance(raw_records, list):
        return [cast(dict[str, object], record) for record in raw_records if isinstance(record, dict)]
    raw_strings = region.classification.fields.get("strings")
    if not isinstance(raw_strings, list):
        return []
    return [{"index": index, "value": value} for index, value in enumerate(raw_strings) if isinstance(value, str)]


def _cell_record(
    region: OpjuDecodedRegion,
    record: dict[str, object],
) -> tuple[tuple[str | None, str], dict[str, object]] | None:
    value = record.get("value")
    if not isinstance(value, str) or (match := _CELL_URI_RE.fullmatch(value)) is None:
        return None
    workbook = match.group("workbook")
    sheet = match.group("sheet")
    path = match.group("path")
    payload: dict[str, object] = {
        "uri": value,
        "cell_path": path,
        "path_components": path.split("."),
        "decoded_string_index": record.get("index"),
        "decoded_range": record.get("decoded_range"),
        "source_region_range": _range_payload(region.source_start, region.source_end),
        "source_attribution": "decoded_range_with_compressed_source_region",
        "verification": "exact",
    }
    return (workbook, sheet), payload


def _report_accumulators(
    regions: tuple[OpjuDecodedRegion, ...],
    envelopes: list[tuple[int, int, str]],
) -> dict[tuple[str | None, str], _ReportAccumulator]:
    reports: dict[tuple[str | None, str], _ReportAccumulator] = {}
    for region in regions:
        if region.classification.family != "mser_strings_pset":
            continue
        owner_symbol_id = _enclosing_symbol(region, envelopes)
        for string_record in _string_records(region):
            parsed = _cell_record(region, string_record)
            if parsed is None:
                continue
            key, cell = parsed
            report = reports.setdefault(key, _ReportAccumulator(workbook=key[0], sheet=key[1]))
            report.cells.append(cell)
            report.source_spans.add((region.source_start, region.source_end))
            if owner_symbol_id is not None:
                report.owner_symbol_ids.add(owner_symbol_id)
    return reports


def _symbols_by_table(symbols: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol in symbols:
        semantic_object = cast(dict[str, object], symbol["semantic_object"])
        grouped[str(semantic_object["worksheet"])].append(symbol)
    for table_symbols in grouped.values():
        table_symbols.sort(key=lambda symbol: str(cast(dict[str, object], symbol["address"])["column"]))
    return grouped


def _owner_tables(report: _ReportAccumulator, symbols_by_id: dict[str, dict[str, object]]) -> list[str]:
    tables = {
        str(cast(dict[str, object], symbols_by_id[symbol_id]["semantic_object"])["worksheet"])
        for symbol_id in report.owner_symbol_ids
        if symbol_id in symbols_by_id
    }
    return sorted(tables)


def _append_alias(symbol: dict[str, object], alias: str) -> None:
    aliases = cast(list[str], symbol["aliases"])
    if alias not in aliases:
        aliases.append(alias)


def _register_report_alias(
    report: _ReportAccumulator,
    owner_tables: list[str],
    table_symbols: dict[str, list[dict[str, object]]],
    lookup: dict[tuple[str, str, str], list[str]],
    alias_evidence: dict[str, list[dict[str, object]]],
) -> None:
    if report.workbook is None or len(owner_tables) != 1:
        return
    table = owner_tables[0]
    source_ranges = [_range_payload(start, end) for start, end in sorted(report.source_spans)]
    evidence: dict[str, object] = {
        "workbook": report.workbook,
        "sheet": report.sheet,
        "evidence_kind": "descriptor_owned_report_cell_uri",
        "source_ranges": source_ranges,
        "verification": "exact",
    }
    if evidence not in alias_evidence[table]:
        alias_evidence[table].append(evidence)
    for symbol in table_symbols.get(table, []):
        address = cast(dict[str, object], symbol["address"])
        column = str(address["column"])
        symbol_id = str(symbol["symbol_id"])
        alias = f"[{report.workbook}]{report.sheet}!{column}"
        _append_alias(symbol, alias)
        key = (report.workbook, report.sheet, column)
        if symbol_id not in lookup.setdefault(key, []):
            lookup[key].append(symbol_id)


def _table_field_records(analysis: dict[str, object]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for field_payload in cast(list[dict[str, object]], analysis["table_fields"]):
        path = str(field_payload.get("path") or "")
        grouped[path.rsplit("/", 1)[0]].append(field_payload)
    records: list[dict[str, object]] = []
    for path, fields in sorted(grouped.items()):
        values = {str(item["tag"]): item["value"] for item in fields}
        workbook = values.get("BookName")
        sheet = values.get("SheetName") or values.get("Sheet")
        if workbook is None and sheet is None and "TableID" not in values:
            continue
        records.append(
            {
                "path": path,
                "role": path.rsplit("/", 1)[-1],
                "workbook": workbook,
                "sheet": sheet,
                "sheet_name": values.get("SheetName"),
                "sheet_index_or_selector": values.get("Sheet"),
                "table_id": values.get("TableID"),
                "fields": fields,
                "verification": "exact",
            }
        )
    return records


def _link_analysis_reports(
    analyses: list[dict[str, object]],
    report_payloads: list[dict[str, object]],
) -> None:
    reports_by_address: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for report in report_payloads:
        workbook = report["workbook"]
        if isinstance(workbook, str):
            reports_by_address[(workbook, str(report["sheet"]))].append(report)
    for analysis in analyses:
        records = _table_field_records(analysis)
        links: list[dict[str, object]] = []
        for record in records:
            workbook = record["workbook"]
            sheet = record["sheet"]
            candidates = reports_by_address.get((str(workbook), str(sheet)), []) if workbook and sheet else []
            record["report_table_ids"] = [candidate["report_table_id"] for candidate in candidates]
            record["report_link_status"] = "resolved_exact" if len(candidates) == 1 else "unresolved"
            if len(candidates) != 1:
                continue
            report = candidates[0]
            analysis_id = str(analysis["analysis_id"])
            report_analysis_ids = cast(list[str], report["analysis_ids"])
            if analysis_id not in report_analysis_ids:
                report_analysis_ids.append(analysis_id)
            links.append(
                {
                    "report_table_id": report["report_table_id"],
                    "table_field_path": record["path"],
                    "role": record["role"],
                    "status": "resolved_exact",
                    "verification": "exact",
                }
            )
        analysis["table_records"] = records
        analysis["report_table_links"] = links


def _report_payloads(
    reports: dict[tuple[str | None, str], _ReportAccumulator],
    symbols: list[dict[str, object]],
    lookup: dict[tuple[str, str, str], list[str]],
    alias_evidence: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    symbols_by_id = {str(symbol["symbol_id"]): symbol for symbol in symbols}
    table_symbols = _symbols_by_table(symbols)
    payloads: list[dict[str, object]] = []
    for _key, report in sorted(reports.items(), key=lambda item: (item[0][0] or "", item[0][1])):
        owner_tables = _owner_tables(report, symbols_by_id)
        _register_report_alias(report, owner_tables, table_symbols, lookup, alias_evidence)
        ownership_status = "resolved_exact" if len(owner_tables) == 1 else "ambiguous_or_unresolved"
        address = f"[{report.workbook}]{report.sheet}" if report.workbook is not None else report.sheet
        payloads.append(
            {
                "report_table_id": f"report_table:{address}",
                "workbook": report.workbook,
                "sheet": report.sheet,
                "cell_reference_count": len(report.cells),
                "cells": sorted(
                    report.cells,
                    key=lambda cell: (
                        str(cell["uri"]),
                        cast(dict[str, int], cell["source_region_range"])["start"],
                        int(cell["decoded_string_index"]),
                    ),
                ),
                "owner_symbol_ids": sorted(report.owner_symbol_ids),
                "owner_worksheet_ids": owner_tables,
                "ownership_status": ownership_status,
                "ownership_rule": "cell URI payload is inside a descriptor-owned post-payload envelope",
                "analysis_ids": [],
                "source_ranges": [_range_payload(start, end) for start, end in sorted(report.source_spans)],
                "completeness": "partial",
                "verification": "exact",
            }
        )
    return payloads


def _initial_alias_evidence(symbols: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    evidence: dict[str, list[dict[str, object]]] = defaultdict(list)
    for table, table_symbols in _symbols_by_table(symbols).items():
        first_address = cast(dict[str, object], table_symbols[0]["address"])
        workbook_aliases = cast(list[str], first_address.get("workbook_aliases", [first_address["workbook"]]))
        sheet_aliases = cast(list[str], first_address.get("sheet_aliases", [first_address["sheet"]]))
        for workbook in workbook_aliases:
            for sheet in sheet_aliases:
                evidence[table].append(
                    {
                        "workbook": workbook,
                        "sheet": sheet,
                        "evidence_kind": "descriptor_identity_or_system_metadata",
                        "verification": "exact",
                    }
                )
    return evidence


def _worksheet_identities(
    symbols: list[dict[str, object]],
    alias_evidence: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    identities: list[dict[str, object]] = []
    for table, table_symbols in sorted(_symbols_by_table(symbols).items()):
        address = cast(dict[str, object], table_symbols[0]["address"])
        descriptor_ranges = [
            cast(dict[str, object], cast(dict[str, object], symbol["source"])["descriptor_range"])
            for symbol in table_symbols
        ]
        identities.append(
            {
                "worksheet_id": table,
                "canonical_address": {
                    "workbook": address["workbook"],
                    "sheet": address["sheet"],
                    "sheet_index": address["sheet_index"],
                },
                "address_aliases": sorted(
                    alias_evidence.get(table, []),
                    key=lambda item: (str(item["workbook"]), str(item["sheet"]), str(item["evidence_kind"])),
                ),
                "symbol_ids": [str(symbol["symbol_id"]) for symbol in table_symbols],
                "source_ranges": descriptor_ranges,
                "identity_status": "resolved_exact",
                "verification": "exact",
            }
        )
    return identities


def _column_ordinal(column: str) -> int:
    ordinal = 0
    for character in column:
        ordinal = ordinal * 26 + ord(character) - ord("A") + 1
    return ordinal - 1


def _table_candidate_index(
    symbols: list[dict[str, object]], identities: list[dict[str, object]]
) -> dict[str, tuple[set[str], dict[str, str]]]:
    identity_by_table = {str(identity["worksheet_id"]): identity for identity in identities}
    candidates: dict[str, tuple[set[str], dict[str, str]]] = {}
    for table, table_symbols in _symbols_by_table(symbols).items():
        identity = identity_by_table[table]
        aliases = cast(list[dict[str, object]], identity["address_aliases"])
        sheets = {str(alias["sheet"]) for alias in aliases}
        columns = {
            str(cast(dict[str, object], symbol["address"])["column"]): str(symbol["symbol_id"])
            for symbol in table_symbols
        }
        candidates[table] = sheets, columns
    return candidates


def _analysis_aliases(
    analyses: list[dict[str, object]],
    table_index: dict[str, tuple[set[str], dict[str, str]]],
    identities: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], dict[str, object]] = {}
    aliases_by_table = {
        str(identity["worksheet_id"]): {
            (str(alias["workbook"]), str(alias["sheet"]))
            for alias in cast(list[dict[str, object]], identity["address_aliases"])
        }
        for identity in identities
    }
    for analysis in analyses:
        for reference in cast(list[dict[str, object]], analysis["references"]):
            key = str(reference["workbook"]), str(reference["sheet"])
            group = groups.setdefault(key, {"columns": set(), "analysis_ids": set(), "occurrences": 0})
            cast(set[str], group["columns"]).add(str(reference["column"]))
            cast(set[str], group["analysis_ids"]).add(str(analysis["analysis_id"]))
            group["occurrences"] = cast(int, group["occurrences"]) + 1
    payloads: list[dict[str, object]] = []
    for (workbook, sheet), group in sorted(groups.items()):
        columns = cast(set[str], group["columns"])
        exact_candidates = sorted(table for table, aliases in aliases_by_table.items() if (workbook, sheet) in aliases)
        structural_candidates = sorted(
            table for table, (_sheets, owned_columns) in table_index.items() if columns <= owned_columns.keys()
        )
        if len(exact_candidates) == 1:
            status = "resolved_exact"
            candidates = exact_candidates
            verification = "exact"
        elif exact_candidates:
            status = "ambiguous_exact_candidates"
            candidates = exact_candidates
            verification = "exact"
        elif len(structural_candidates) == 1:
            status = "unique_structural_candidate"
            candidates = structural_candidates
            verification = "unverified"
        elif structural_candidates:
            status = "ambiguous_structural_candidates"
            candidates = structural_candidates
            verification = "unverified"
        else:
            status = "unresolved"
            candidates = []
            verification = "unverified"
        payloads.append(
            {
                "reference_address": {"workbook": workbook, "sheet": sheet},
                "referenced_columns": sorted(columns, key=lambda column: (_column_ordinal(column), column)),
                "reference_occurrence_count": group["occurrences"],
                "analysis_ids": sorted(cast(set[str], group["analysis_ids"])),
                "status": status,
                "worksheet_candidates": candidates,
                "candidate_rule": (
                    "exact decoded worksheet alias"
                    if exact_candidates
                    else "parser-owned worksheet contains every referenced column; no alias is asserted"
                ),
                "verification": verification,
            }
        )
    return payloads


def _graph_owner_candidates(region: OpjuDecodedRegion, manifest: Manifest) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for item in manifest.items:
        if item.kind != "graph" or not item.source_ranges:
            continue
        contains = any(
            source_range["start"] <= region.source_start and region.source_end <= source_range["end"]
            for source_range in item.source_ranges
        )
        if not contains:
            continue
        candidates.append(
            {
                "name": item.name,
                "source_object_path": item.source_object_path,
                "discovery_type": item.discovery_type,
                "heuristic": item.heuristic,
                "verification": item.verification,
            }
        )
    return sorted(candidates, key=lambda item: (str(item["source_object_path"]), str(item["name"])))


def _graph_owner_status(candidates: list[dict[str, object]]) -> str:
    exact = [
        candidate
        for candidate in candidates
        if candidate["heuristic"] is False and candidate["verification"] == "exact"
    ]
    if len(exact) == 1:
        return "resolved_exact"
    if candidates:
        return "candidate_only"
    return "unresolved"


def _binding_candidates(
    source: dict[str, object],
    table_index: dict[str, tuple[set[str], dict[str, str]]],
) -> tuple[str, list[dict[str, str]]]:
    worksheet = source.get("worksheet")
    x_column = source.get("x_column_short_name")
    y_column = source.get("y_column_short_name")
    x_ordinal = source.get("x_column_ordinal_zero_based")
    y_ordinal = source.get("y_column_ordinal_zero_based")
    if not isinstance(worksheet, str) or not isinstance(x_column, str) or not isinstance(y_column, str):
        return "unresolved_missing_source_fields", []
    if x_ordinal != _column_ordinal(x_column) or y_ordinal != _column_ordinal(y_column):
        return "invalid_column_ordinal_invariant", []
    candidates = [
        {"worksheet_id": table, "x_symbol_id": columns[x_column], "y_symbol_id": columns[y_column]}
        for table, (sheet_aliases, columns) in sorted(table_index.items())
        if worksheet in sheet_aliases and x_column in columns and y_column in columns
    ]
    if len(candidates) == 1:
        return "resolved_exact", candidates
    if candidates:
        return "ambiguous_exact_candidates", candidates
    return "unresolved", []


def _graph_bindings(
    regions: tuple[OpjuDecodedRegion, ...],
    symbols: list[dict[str, object]],
    identities: list[dict[str, object]],
    manifest: Manifest,
) -> list[dict[str, object]]:
    bindings: list[dict[str, object]] = []
    table_index = _table_candidate_index(symbols, identities)
    for region in regions:
        if region.classification.family != "style_holder_source_info_v1":
            continue
        owner_candidates = _graph_owner_candidates(region, manifest)
        subrecords = region.classification.fields.get("subrecords")
        if not isinstance(subrecords, list):
            continue
        for raw_subrecord in cast(list[object], subrecords):
            if not isinstance(raw_subrecord, dict):
                continue
            record = cast(dict[str, object], raw_subrecord)
            if not isinstance(record.get("source_range"), dict):
                continue
            source = cast(dict[str, object], record["source_range"])
            status, candidates = _binding_candidates(source, table_index)
            decoded_start = record["offset"]
            decoded_end = record["end"]
            if not isinstance(decoded_start, int) or not isinstance(decoded_end, int):
                continue
            bindings.append(
                {
                    "graph_binding_id": f"graph_binding:{region.source_start}:{record['index']}",
                    "slot_index_zero_based": record["slot_index_zero_based"],
                    "source": source,
                    "dataset_binding_status": status,
                    "dataset_candidates": candidates,
                    "graph_owner_status": _graph_owner_status(owner_candidates),
                    "graph_owner_candidates": owner_candidates,
                    "decoded_range": _range_payload(decoded_start, decoded_end),
                    "source_region_range": _range_payload(region.source_start, region.source_end),
                    "binding_semantics": "persistent style-holder source slot; not necessarily a current curve",
                    "completeness": "partial",
                    "verification": "exact",
                }
            )
    return bindings


def _walk_elements(
    data: bytes,
    descriptors: tuple[OpjuColumnDescriptor, ...],
    regions: tuple[OpjuDecodedRegion, ...],
    supplied: list[OpjuWalkElement] | None,
) -> list[OpjuWalkElement]:
    if supplied is not None:
        return supplied
    return walk_opju_file(data, column_descriptors=descriptors, decoded_regions=regions)


def _state_tables(data: bytes, elements: list[OpjuWalkElement]) -> list[dict[str, object]]:
    tables: list[dict[str, object]] = []
    for element in elements:
        if element.kind != OPJU_REGION_KIND_TAGGED_BINARY:
            continue
        payload = data[element.start_offset : element.end_offset]
        strings = iter_tagged_strings(payload, source_start=element.start_offset)
        operations = [field.value for field in strings if field.value in _STATE_OPERATIONS]
        if not operations:
            continue
        scalars = iter_tagged_scalars(payload, source_start=element.start_offset)
        tables.append(
            {
                "state_table_id": f"report_state:{element.start_offset}",
                "family": element.metadata.get("family"),
                "operations": operations,
                "string_fields": [
                    {
                        "offset": item.offset,
                        "length": item.length,
                        "tag_code": item.tag_code,
                        "value": item.value,
                    }
                    for item in strings
                ],
                "scalar_fields": [
                    {
                        "offset": item.offset,
                        "end_offset": item.end_offset,
                        "field_code": item.field_code,
                        "declared_size": item.declared_size,
                        "descriptor_hex": item.descriptor_hex,
                        "value_width": item.value_width,
                        "value_hex": item.value_hex,
                        "little_endian_unsigned": item.little_endian_unsigned,
                    }
                    for item in scalars
                ],
                "source_range": _range_payload(element.start_offset, element.end_offset),
                "semantic_status": "operation names and framed fields decoded; neutral field meanings remain unknown",
                "completeness": "partial",
                "verification": "exact",
            }
        )
    return tables


def build_semantic_relationships(
    data: bytes,
    symbols: list[dict[str, object]],
    analyses: list[dict[str, object]],
    lookup: dict[tuple[str, str, str], list[str]],
    descriptors: tuple[OpjuColumnDescriptor, ...],
    descriptor_symbols: dict[tuple[int, int], str],
    regions: tuple[OpjuDecodedRegion, ...],
    manifest: Manifest,
    *,
    walk_elements: list[OpjuWalkElement] | None = None,
) -> SemanticRelationships:
    """Build exact relationships and explicit ambiguity sets from decoded records."""
    envelopes = _descriptor_envelopes(data, descriptors, descriptor_symbols)
    reports = _report_accumulators(regions, envelopes)
    alias_evidence = _initial_alias_evidence(symbols)
    report_tables = _report_payloads(reports, symbols, lookup, alias_evidence)
    _link_analysis_reports(analyses, report_tables)
    identities = _worksheet_identities(symbols, alias_evidence)
    table_index = _table_candidate_index(symbols, identities)
    analysis_aliases = _analysis_aliases(analyses, table_index, identities)
    graph_bindings = _graph_bindings(regions, symbols, identities, manifest)
    state_tables = _state_tables(data, _walk_elements(data, descriptors, regions, walk_elements))
    source_ranges = [
        *(
            cast(dict[str, int], source_range)
            for report in report_tables
            for source_range in cast(list[dict[str, object]], report["source_ranges"])
        ),
        *(cast(dict[str, int], binding["source_region_range"]) for binding in graph_bindings),
        *(cast(dict[str, int], table["source_range"]) for table in state_tables),
    ]
    return SemanticRelationships(
        worksheet_identities=identities,
        analysis_aliases=analysis_aliases,
        report_tables=report_tables,
        state_tables=state_tables,
        graph_bindings=graph_bindings,
        source_ranges=source_ranges,
    )


__all__ = ["SemanticRelationships", "build_semantic_relationships"]
