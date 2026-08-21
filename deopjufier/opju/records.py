"""Typed OPJU record surface and top-level container parsing."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from deopjufier.io import sanitize_name

from . import regions as opju_regions
from .analysis import (
    OpjuAnalyzedCandidate,
    analyze_origin_storage_candidates,
)
from .common import (
    MAGIC_OPJU,
    OPJU_REGION_KIND_CONTAINER,
    OPJU_REGION_KIND_FOLDER_DIRECTORY,
    OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT,
    OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION,
    OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH,
    OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE,
    OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,
    OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT,
    OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD,
    OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET,
    OPJU_REGION_KIND_PAGE_DIRECTORY,
)
from .directory import (
    OpjuFolderDirectoryRecord,
    OpjuPageDirectoryRecord,
    parse_opju_folder_directory,
    parse_opju_page_directory,
)
from .reports import parse_opju_origin_storage_reports
from .tables import parse_opju_column_tables

if TYPE_CHECKING:
    from .regions import OpjuOriginStorageCandidate
    from .reports import OpjuOriginStorageReport
    from .tables import OpjuColumnTable

_OPJU_ORIGIN_STORAGE_REGION_RULE = "parse_opju_origin_storage_records"
_OPJU_RECORDS_CACHE_MAX_ENTRIES = 4
_OPJU_RECORDS_CACHE: OrderedDict[
    tuple[
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        bool,
        bool,
        str,
    ],
    OpjuRecords,
] = OrderedDict()


def iter_origin_storage_candidates(
    data: bytes,
    *,
    include_decoded: bool = True,
    include_family_binary: bool = False,
) -> tuple[OpjuOriginStorageCandidate, ...]:
    """Expose the regions iterator for tests and for adaptive shim behavior."""
    return tuple(
        opju_regions.iter_origin_storage_candidates(
            data,
            include_decoded=include_decoded,
            include_family_binary=include_family_binary,
        )
    )


def _iter_candidates(
    data: bytes,
    *,
    include_decoded: bool,
    include_family_binary: bool,
) -> tuple[OpjuOriginStorageCandidate, ...]:
    try:
        return tuple(
            iter_origin_storage_candidates(
                data,
                include_decoded=include_decoded,
                include_family_binary=include_family_binary,
            )
        )
    except TypeError:
        return tuple(
            iter_origin_storage_candidates(
                data,
                include_decoded=include_decoded,
            )
        )


def _cache_key_for_parse(
    data: bytes,
    *,
    path: Path | None,
    max_reports: int,
    max_input_items: int,
    max_tables: int,
    max_rows: int,
    include_decoded: bool,
    include_family_binary: bool,
) -> tuple[int, int, int, int, int, int, int, bool, bool, str]:
    if path is not None:
        try:
            stat = path.stat()
            return (
                0,
                stat.st_size,
                stat.st_mtime_ns,
                max_reports,
                max_input_items,
                max_tables,
                max_rows,
                include_decoded,
                include_family_binary,
                str(path.resolve()),
            )
        except OSError:
            pass

    return (
        1,
        len(data),
        0,
        max_reports,
        max_input_items,
        max_tables,
        max_rows,
        include_decoded,
        include_family_binary,
        str(hash(data)),
    )


def _cache_get_parse(
    data: bytes,
    *,
    path: Path | None,
    max_reports: int,
    max_input_items: int,
    max_tables: int,
    max_rows: int,
    include_decoded: bool,
    include_family_binary: bool,
) -> OpjuRecords | None:
    key = _cache_key_for_parse(
        data,
        path=path,
        max_reports=max_reports,
        max_input_items=max_input_items,
        max_tables=max_tables,
        max_rows=max_rows,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
    )
    cached = _OPJU_RECORDS_CACHE.get(key)
    if cached is None:
        return None
    _OPJU_RECORDS_CACHE.move_to_end(key)
    return cached


def _cache_set_parse(
    data: bytes,
    *,
    path: Path | None,
    max_reports: int,
    max_input_items: int,
    max_tables: int,
    max_rows: int,
    include_decoded: bool,
    include_family_binary: bool,
    parsed: OpjuRecords,
) -> None:
    key = _cache_key_for_parse(
        data,
        path=path,
        max_reports=max_reports,
        max_input_items=max_input_items,
        max_tables=max_tables,
        max_rows=max_rows,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
    )
    _OPJU_RECORDS_CACHE[key] = parsed
    _OPJU_RECORDS_CACHE.move_to_end(key)
    while len(_OPJU_RECORDS_CACHE) > _OPJU_RECORDS_CACHE_MAX_ENTRIES:
        _OPJU_RECORDS_CACHE.popitem(last=False)


@dataclass(frozen=True)
class OpjuHeaderRecord:
    marker: str
    version: str | None
    declared_length: int | None
    header_length: int
    raw_header: bytes
    parser_rule: str = "parse_opju_header"
    confidence: float = 0.99


@dataclass(frozen=True)
class OpjuRegionRecord:
    kind: str
    name: str
    offset: int
    length: int
    parser_rule: str
    confidence: float = 0.85
    source_object_path: str | None = None
    structural_name: str | None = None
    semantic_alias: str | None = None
    semantic_confidence: str | None = None


@dataclass(frozen=True)
class OpjuReportRecord:
    index: int
    name: str
    label: str | None
    offset: int
    length: int
    rows: int | None = None
    columns: int | None = None
    parser_rule: str = "parse_opju_origin_storage_reports"
    confidence: float = 0.98
    source_object_path: str | None = None


@dataclass(frozen=True)
class OpjuWorksheetRecord:
    name: str
    label: str | None
    offset: int
    length: int
    row_count: int
    parser_rule: str = "parse_opju_column_tables"
    confidence: float = 0.98
    source_object_path: str | None = None


@dataclass(frozen=True)
class OpjuRecords:
    container: OpjuHeaderRecord | None
    regions: tuple[OpjuRegionRecord, ...]
    report_records: tuple[OpjuReportRecord, ...]
    worksheet_records: tuple[OpjuWorksheetRecord, ...]
    reports: tuple[OpjuOriginStorageReport, ...]
    worksheets: tuple[OpjuColumnTable, ...]
    page_directory_records: tuple[OpjuPageDirectoryRecord, ...] = ()
    folder_directory_records: tuple[OpjuFolderDirectoryRecord, ...] = ()


def _parse_opju_header(data: bytes) -> OpjuHeaderRecord | None:
    if not data.startswith(MAGIC_OPJU):
        return None
    newline_end = data.find(b"\n")
    if newline_end >= 0:
        header_end = newline_end + 1
    else:
        header_end = data.find(b"\0")
        if header_end < 0:
            header_end = min(len(data), len(MAGIC_OPJU) + 64)
    raw_header = data[:header_end]
    if not raw_header:
        return None
    header_text = raw_header.decode("utf-8", errors="replace")
    parts = header_text.strip().split()
    if not parts or parts[0] != "CPYUA":
        return None
    version: str | None = parts[1] if len(parts) >= 2 else None
    declared_length: int | None = None
    if len(parts) >= 3 and parts[2].isdigit():
        declared_length = int(parts[2])
    return OpjuHeaderRecord(
        marker="CPYUA",
        version=version,
        declared_length=declared_length,
        header_length=header_end,
        raw_header=raw_header,
    )


def _iter_origin_storage_regions(
    analyses: tuple[OpjuAnalyzedCandidate, ...],
    *,
    include_decoded: bool = False,
) -> list[OpjuAnalyzedCandidate]:
    filtered_analyses = analyses
    if include_decoded:
        confident_decoded_starts = {
            candidate.source_start
            for candidate in analyses
            if candidate.source_kind == "decoded"
            and candidate.region_kind != OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD
        }
        filtered_analyses = tuple(
            candidate
            for candidate in analyses
            if candidate.source_kind != "raw" or (candidate.source_start - 2) not in confident_decoded_starts
        )

    candidate_regions: dict[tuple[int, int], OpjuAnalyzedCandidate] = {}
    for candidate in filtered_analyses:
        span = (candidate.source_start, candidate.source_end)
        if span[1] <= span[0]:
            continue
        existing = candidate_regions.get(span)
        if existing is not None and existing.source_kind == "decoded":
            continue
        if existing is not None and candidate.source_kind == "raw":
            continue
        candidate_regions[span] = candidate

    return sorted(candidate_regions.values(), key=lambda item: item.source_start)


def _ensure_unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        unique.append(name if count == 0 else f"{name}__{count + 1}")
    return unique


def _merge_overlapping_regions(
    candidates: list[OpjuAnalyzedCandidate],
) -> list[OpjuAnalyzedCandidate]:
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (item.source_start, -(item.source_end - item.source_start), item.region_kind),
    )

    merged: list[OpjuAnalyzedCandidate] = []
    for candidate in sorted_candidates:
        start = candidate.source_start
        end = candidate.source_end
        if end <= start:
            continue

        overlaps: list[int] = []
        for index, existing_candidate in enumerate(merged):
            existing_start = existing_candidate.source_start
            existing_end = existing_candidate.source_end
            if existing_end <= start or existing_start >= end:
                continue
            overlaps.append(index)

        if not overlaps:
            merged.append(candidate)
            continue

        is_fully_covered = False
        for index in overlaps:
            existing_candidate = merged[index]
            existing_start = existing_candidate.source_start
            existing_end = existing_candidate.source_end
            if existing_start <= start and end <= existing_end:
                existing_length = existing_end - existing_start
                candidate_length = end - start
                if existing_length >= candidate_length:
                    is_fully_covered = True
                    break

        if is_fully_covered:
            continue

        for index in reversed(overlaps):
            merged.pop(index)
        merged.append(candidate)
        merged.sort(key=lambda item: item.source_start)

    merged.sort(key=lambda item: item.source_start)
    return merged


def _build_report_records(
    parsed_reports: list[OpjuOriginStorageReport],
) -> list[OpjuReportRecord]:
    report_names = _ensure_unique_names(
        [sanitize_name(report.label or f"origin_storage_report_{report.index:03d}") for report in parsed_reports]
    )
    return [
        OpjuReportRecord(
            index=report.index,
            name=report_name,
            label=report.label,
            offset=report.offset,
            length=report.length,
            rows=report.rows,
            columns=report.columns,
            source_object_path=f"origin_storage_reports/{report_name}",
        )
        for report, report_name in zip(parsed_reports, report_names, strict=False)
    ]


def _build_worksheet_records(
    parsed_worksheets: list[OpjuColumnTable],
    *,
    source_lengths_by_offset: dict[int, int] | None = None,
) -> list[OpjuWorksheetRecord]:
    worksheet_names = _ensure_unique_names([sanitize_name(table.name) for table in parsed_worksheets])
    source_lengths = source_lengths_by_offset or {}
    return [
        OpjuWorksheetRecord(
            name=worksheet_name,
            label=table.label,
            offset=table.offset,
            length=source_lengths.get(table.offset, table.length),
            row_count=len(table.rows),
            source_object_path=f"worksheets/{worksheet_name}",
        )
        for table, worksheet_name in zip(parsed_worksheets, worksheet_names, strict=False)
    ]


def _region_record_from_candidate(
    candidate: OpjuAnalyzedCandidate,
    *,
    index: int,
    report_by_offset: dict[int, OpjuReportRecord],
    worksheet_by_offset: dict[int, OpjuWorksheetRecord],
) -> tuple[OpjuRegionRecord, tuple[int, int, str] | None]:
    start = candidate.source_start
    length = candidate.source_end - candidate.source_start
    region_kind = candidate.region_kind
    attachment_name = candidate.attachment_name

    report_record = report_by_offset.get(start)
    worksheet_record = worksheet_by_offset.get(start)
    if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT and report_record is not None:
        return (
            OpjuRegionRecord(
                kind=OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT,
                name=report_record.name,
                offset=start,
                length=length,
                parser_rule=report_record.parser_rule,
                confidence=report_record.confidence,
                source_object_path=report_record.source_object_path,
            ),
            None,
        )

    if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET and worksheet_record is not None:
        return (
            OpjuRegionRecord(
                kind=OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET,
                name=worksheet_record.name,
                offset=start,
                length=length,
                parser_rule=worksheet_record.parser_rule,
                confidence=worksheet_record.confidence,
                source_object_path=worksheet_record.source_object_path,
            ),
            None,
        )

    if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW:
        name = f"origin_storage_preview_{index:03d}"
        preview_source = f"previews/{name}"
        record = OpjuRegionRecord(
            kind=region_kind,
            name=name,
            offset=start,
            length=length,
            parser_rule=_OPJU_ORIGIN_STORAGE_REGION_RULE,
            confidence=0.9,
            source_object_path=preview_source,
        )
        return record, (start, start + length, preview_source)

    if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT:
        source_name = attachment_name or f"origin_storage_attachment_{index:03d}"
        source_object_path = f"Excel/{source_name}"
        confidence = 0.89
    elif region_kind in {
        OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE,
        OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION,
        OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH,
    }:
        kind_suffix = region_kind.removeprefix("origin_storage_")
        source_name = f"origin_storage_{kind_suffix}_{index:03d}"
        source_object_path = f"origin_storage/{source_name}"
        confidence = 0.82
    else:
        source_name = f"origin_storage_region_{index:03d}"
        source_object_path = (
            f"worksheets/{source_name}"
            if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET
            else f"origin_storage/{source_name}"
        )
        confidence = 0.86 if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET else 0.72

    return (
        OpjuRegionRecord(
            kind=region_kind,
            name=source_name,
            offset=start,
            length=length,
            parser_rule=_OPJU_ORIGIN_STORAGE_REGION_RULE,
            confidence=confidence,
            source_object_path=source_object_path,
        ),
        None,
    )


def _source_for_preview_offset(
    preview_regions: list[tuple[int, int, str]],
    offset: int,
) -> str | None:
    for region_start, region_end, source in preview_regions:
        if region_start <= offset <= region_end:
            return source
    return None


def _apply_preview_paths(
    report_records: list[OpjuReportRecord],
    preview_regions: list[tuple[int, int, str]],
) -> list[OpjuReportRecord]:
    if not preview_regions:
        return report_records
    return [
        replace(
            record,
            source_object_path=_source_for_preview_offset(preview_regions, record.offset) or record.source_object_path,
        )
        for record in report_records
    ]


def parse_opju_records(
    data: bytes,
    *,
    max_reports: int = 200,
    max_input_items: int = 10,
    max_tables: int = 16,
    max_rows: int = 256,
    include_decoded: bool = True,
    include_family_binary: bool = False,
    path: Path | None = None,
) -> OpjuRecords:
    cached = _cache_get_parse(
        data,
        path=path,
        max_reports=max_reports,
        max_input_items=max_input_items,
        max_tables=max_tables,
        max_rows=max_rows,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
    )
    if cached is not None:
        return cached

    if max_reports <= 0 and max_tables <= 0 and max_rows <= 0:
        return OpjuRecords(None, (), (), (), (), ())
    if not data.startswith(MAGIC_OPJU):
        return OpjuRecords(None, (), (), (), (), ())

    container = _parse_opju_header(data)
    if container is None:
        return OpjuRecords(None, (), (), (), (), ())

    origin_storage_candidates = _iter_candidates(
        data,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
    )
    analyzed_candidates = analyze_origin_storage_candidates(
        data,
        include_decoded=include_decoded,
        candidates=origin_storage_candidates,
    )
    origin_storage_regions = _iter_origin_storage_regions(
        analyzed_candidates,
        include_decoded=include_decoded,
    )
    parsed_reports = (
        parse_opju_origin_storage_reports(
            data,
            include_decoded=include_decoded,
            max_reports=max_reports,
            max_input_items=max_input_items,
            candidates=origin_storage_candidates,
            analyses=analyzed_candidates,
        )
        if max_reports > 0
        else []
    )
    parsed_worksheets = (
        parse_opju_column_tables(
            data,
            include_decoded=include_decoded,
            include_family_binary=include_family_binary,
            max_tables=max_tables,
            max_rows=max_rows,
            candidates=origin_storage_candidates,
            analyses=analyzed_candidates,
        )
        if max_tables > 0 and max_rows > 0
        else []
    )
    report_records = _build_report_records(parsed_reports)
    report_by_offset = {record.offset: record for record in report_records}
    source_lengths_by_offset = {
        candidate.source_start: candidate.source_end - candidate.source_start
        for candidate in analyzed_candidates
        if candidate.source_end > candidate.source_start
    }
    worksheet_records = _build_worksheet_records(
        parsed_worksheets,
        source_lengths_by_offset=source_lengths_by_offset,
    )
    worksheet_by_offset = {record.offset: record for record in worksheet_records}

    region_records: list[OpjuRegionRecord] = [
        OpjuRegionRecord(
            kind=OPJU_REGION_KIND_CONTAINER,
            name="opju_container",
            offset=0,
            length=container.header_length,
            parser_rule=container.parser_rule,
            confidence=container.confidence,
        )
    ]
    page_directory_records = parse_opju_page_directory(data)
    folder_directory_records = parse_opju_folder_directory(data)
    region_records.extend(
        OpjuRegionRecord(
            kind=OPJU_REGION_KIND_PAGE_DIRECTORY,
            name=record.name,
            offset=record.offset,
            length=record.length,
            parser_rule=record.parser_rule,
            confidence=record.confidence,
            source_object_path=record.source_object_path,
            structural_name=record.structural_name,
            semantic_alias=record.semantic_alias,
            semantic_confidence=record.semantic_confidence,
        )
        for record in page_directory_records
    )
    region_records.extend(
        OpjuRegionRecord(
            kind=OPJU_REGION_KIND_FOLDER_DIRECTORY,
            name=record.name,
            offset=record.offset,
            length=record.length,
            parser_rule=record.parser_rule,
            confidence=record.confidence,
            source_object_path=record.source_object_path,
            structural_name=record.structural_name,
            semantic_alias=record.semantic_alias,
            semantic_confidence=record.semantic_confidence,
        )
        for record in folder_directory_records
    )

    combined_regions = _merge_overlapping_regions(list(origin_storage_regions))
    seen_regions = set[tuple[int, int]]()
    preview_region_spans: list[tuple[int, int, str]] = []

    for index, candidate in enumerate(combined_regions):
        start = candidate.source_start
        region_key = (start, candidate.source_end - start)
        if region_key in seen_regions:
            continue
        seen_regions.add(region_key)
        region_record, preview_span = _region_record_from_candidate(
            candidate,
            index=index,
            report_by_offset=report_by_offset,
            worksheet_by_offset=worksheet_by_offset,
        )
        region_records.append(region_record)
        if preview_span is not None:
            preview_region_spans.append(preview_span)

    report_records = _apply_preview_paths(report_records, preview_region_spans)

    for worksheet_record in worksheet_records:
        if any(region.offset == worksheet_record.offset for region in region_records):
            continue
        region_records.append(
            OpjuRegionRecord(
                kind=OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET,
                name=worksheet_record.name,
                offset=worksheet_record.offset,
                length=worksheet_record.length,
                parser_rule=worksheet_record.parser_rule,
                confidence=worksheet_record.confidence,
                source_object_path=worksheet_record.source_object_path,
            )
        )

    region_records.sort(key=lambda item: item.offset)
    parsed = OpjuRecords(
        container=container,
        regions=tuple(region_records),
        report_records=tuple(report_records),
        worksheet_records=tuple(worksheet_records),
        reports=tuple(parsed_reports),
        worksheets=tuple(parsed_worksheets),
        page_directory_records=page_directory_records,
        folder_directory_records=folder_directory_records,
    )
    _cache_set_parse(
        data,
        path=path,
        max_reports=max_reports,
        max_input_items=max_input_items,
        max_tables=max_tables,
        max_rows=max_rows,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
        parsed=parsed,
    )
    return parsed
