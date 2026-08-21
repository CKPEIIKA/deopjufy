"""Lightweight Origin object discovery for `.opj` and `.opju` binaries."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, TypeVar, cast

from deopjufier import discovery as discovery_helpers
from deopjufier import opj as opj_parser
from deopjufier import opju as opju_parser
from deopjufier.blocks import GIF_SIGS, JPEG_SIG, PNG_SIG
from deopjufier.io import iter_file_chunks, read_cached_bytes
from deopjufier.opj import records as opj_records
from deopjufier.opju import reports as opju_reports

MAGIC_OPJ = opj_parser.MAGIC_OPJ
MAGIC_OPJU = opj_parser.MAGIC_OPJU
OPJ_HEADER_MARKER = (MAGIC_OPJ, MAGIC_OPJU)
OPJU_HINTS_MAX_BLOCKS = opju_parser.OPJU_HINTS_MAX_BLOCKS
OPJU_HINTS_MAX_CHARS = opju_parser.OPJU_HINTS_MAX_CHARS
OPJU_HINTS_MAX_DESCRIPTION_BYTES = opju_parser.OPJU_HINTS_MAX_DESCRIPTION_BYTES
OPJ_PARAMETERS_MAX_RECORDS = opj_parser.OPJ_PARAMETERS_MAX_RECORDS
OPJ_PARAMETERS_SCAN_WINDOW = opj_parser.OPJ_PARAMETERS_SCAN_WINDOW
OPJ_NOTES_MAX_BLOCKS = opj_parser.OPJ_NOTES_MAX_BLOCKS
OPJ_NOTES_MAX_CHARS = opj_parser.OPJ_NOTES_MAX_CHARS
OPJ_NOTE_SECTION_NAMES = opj_parser.OPJ_NOTE_SECTION_NAMES
_ORIGIN_OBJECT_CACHE: dict[
    tuple[Path, int, int, tuple[object, ...]],
    list[discovery_helpers.OriginObject],
] = {}
_OPJU_RECORDS_CACHE: dict[tuple[Path, int, int, tuple[object, ...]], opju_parser.OpjuRecords] = {}
_OPJ_BOUNDARIES_CACHE: dict[tuple[Path, int, int, tuple[object, ...]], list[OpjObjectBoundary]] = {}
_OPJ_NOTE_SECTIONS_CACHE: dict[tuple[Path, int, int, tuple[object, ...]], list[OpjNoteSection]] = {}
_OPJ_DATA_SECTIONS_CACHE: dict[tuple[Path, int, int, tuple[object, ...]], list[OpjDataSection]] = {}
_OPJ_CACHE_MAX_ENTRIES = 16
_OPJU_REGION_OBJECT_KIND_BY_KIND = {
    opju_parser.OPJU_REGION_KIND_CONTAINER: "meta",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT: "opju_report",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET: "worksheet",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW: "opju_preview",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT: "excel",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD: "opju_raw_payload",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE: "opju_note_payload",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION: "function",
    opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH: "opju_graph_payload",
    opju_parser.OPJU_REGION_KIND_PAGE_DIRECTORY: "project_page",
    opju_parser.OPJU_REGION_KIND_FOLDER_DIRECTORY: "project_folder",
}
_CacheKey = TypeVar("_CacheKey")
_CacheValue = TypeVar("_CacheValue")
OriginObject = discovery_helpers.OriginObject
ParserBackedDiscoveryRecord = discovery_helpers.ParserBackedDiscoveryRecord
HeuristicDiscoveryRecord = discovery_helpers.HeuristicDiscoveryRecord
iter_object_windows = discovery_helpers.iter_object_windows

OpjSignature = opj_parser.OpjSignature
OpjDataSection = opj_parser.OpjDataSection
OpjParameter = opj_parser.OpjParameter
OpjNoteSection = opj_parser.OpjNoteSection
OpjObjectBoundary = opj_parser.OpjObjectBoundary
OpjWorksheetMetadata = opj_parser.OpjWorksheetMetadata
OpjMatrixMetadata = opj_parser.OpjMatrixMetadata
OpjFunctionMetadata = opj_parser.OpjFunctionMetadata
parse_opj_function_payload = opj_parser.parse_opj_function_payload


OpjuOriginStorageReport = opju_parser.OpjuOriginStorageReport
OpjuColumnTable = opju_parser.OpjuColumnTable
OpjuRecords = opju_parser.OpjuRecords
OpjuReportRecord = opju_parser.OpjuReportRecord
_ORIGIN_STORAGE_OPEN_TAG = b"<OriginStorage"
_OPJU_COLUMN_TABLE_MARKER = b"<columntable"
_OPJU_LARGE_HEURISTIC_ALLOWED_KINDS = frozenset({"worksheet", "graph", "matrix", "note", "function", "excel"})
_OPJU_LARGE_HEURISTIC_TOTAL_LIMIT = 64


parse_opj_signature = opj_records.parse_opj_signature
parse_opj_parameters = opj_records.parse_opj_parameters
parse_opj_worksheet_metadata = opj_parser.parse_opj_worksheet_metadata
parse_opj_matrix_metadata = opj_parser.parse_opj_matrix_metadata
parse_opj_function_metadata = opj_records.parse_opj_function_metadata
_clean_origin_storage_text = opju_reports._clean_origin_storage_text


_extract_text = opju_reports._extract_text


_extract_row_fields = opju_reports._extract_row_fields


_append_unique = opju_reports._append_unique


def parse_opju_origin_storage_reports(
    data: bytes,
    *,
    max_reports: int = 8,
    max_input_items: int = 10,
    include_decoded: bool = True,
    path: Path | None = None,
) -> list[OpjuOriginStorageReport]:
    """Parse lightweight `OriginStorage` report blocks from OPJU containers."""
    parsed = parse_opju_records(
        data,
        max_reports=max_reports,
        max_input_items=max_input_items,
        include_decoded=include_decoded,
        path=path,
    )
    return list(parsed.reports)


def parse_opju_records(
    data: bytes,
    *,
    max_reports: int = 8,
    max_input_items: int = 10,
    max_tables: int = 16,
    max_rows: int = 256,
    include_decoded: bool = True,
    include_family_binary: bool = False,
    path: Path | None = None,
) -> OpjuRecords:
    """Parse OPJU records with file-stat keyed caching."""
    cache_key = _cache_key_for_path(
        path,
        max_reports,
        max_input_items,
        max_tables,
        max_rows,
        include_decoded,
        include_family_binary,
    )
    if cache_key is not None:
        cached = _OPJU_RECORDS_CACHE.get(cache_key)
        if cached is not None:
            return cached

    parsed_kwargs = {
        "max_reports": max_reports,
        "max_input_items": max_input_items,
        "max_tables": max_tables,
        "max_rows": max_rows,
    }
    parse_kwargs: dict[str, object] = dict(parsed_kwargs)
    accepted = set(inspect.signature(opju_parser.parse_opju_records).parameters)
    if "include_decoded" in accepted:
        parse_kwargs["include_decoded"] = include_decoded
    if "include_family_binary" in accepted:
        parse_kwargs["include_family_binary"] = include_family_binary
    if path is not None and "path" in accepted:
        parse_kwargs["path"] = path
    backend_parser = cast(Any, opju_parser.parse_opju_records)
    parsed = backend_parser(data, **parse_kwargs)

    if cache_key is not None:
        _OPJU_RECORDS_CACHE[cache_key] = parsed
        _prune_cache(_OPJU_RECORDS_CACHE)
    return parsed


def parse_opju_column_tables(
    data: bytes,
    *,
    max_tables: int = 16,
    max_rows: int = 256,
    include_decoded: bool = True,
    include_family_binary: bool = False,
    path: Path | None = None,
) -> list[OpjuColumnTable]:
    """Parse explicit CPYUA worksheet-style column tables from an OPJU blob."""
    parsed = parse_opju_records(
        data,
        max_tables=max_tables,
        max_rows=max_rows,
        include_decoded=include_decoded,
        include_family_binary=include_family_binary,
        path=path,
    )
    return list(parsed.worksheets)


def parse_opju_description(data: bytes) -> str | None:
    """Extract a best-effort human description from OPJU header area."""
    return opju_parser.parse_opju_description(data)


def _cache_key_for_path(path: Path | None, *parts: object) -> tuple[Path, int, int, tuple[object, ...]] | None:
    if path is None:
        return None
    try:
        stats = path.stat()
    except OSError:
        return None
    return (path.resolve(), stats.st_size, stats.st_mtime_ns, tuple(parts))


def _prune_cache(cache: dict[_CacheKey, _CacheValue]) -> None:
    while len(cache) > _OPJ_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key)


def parse_opj_boundaries(
    data: bytes,
    *,
    max_sections: int | None = None,
    path: Path | None = None,
    disable_heavy_scans: bool | None = None,
) -> list[OpjObjectBoundary]:
    """Parse OPJ boundaries with optional file-level caching."""
    cache_key = _cache_key_for_path(path, max_sections, disable_heavy_scans)
    if cache_key is not None:
        cached = _OPJ_BOUNDARIES_CACHE.get(cache_key)
        if cached is not None:
            return [*cached]

    if disable_heavy_scans is None:
        disable_heavy_scans = False

    parsed = opj_parser.parse_opj_boundaries(
        data,
        max_sections=max_sections,
        disable_heavy_scans=disable_heavy_scans,
    )
    if cache_key is not None:
        _OPJ_BOUNDARIES_CACHE[cache_key] = parsed
        _prune_cache(_OPJ_BOUNDARIES_CACHE)
    return [*parsed]


def iter_opj_data_sections(
    data: bytes, *, max_sections: int | None = None, path: Path | None = None
) -> list[OpjDataSection]:
    """Parse OPJ data sections with optional file-level caching."""
    cache_key = _cache_key_for_path(path, max_sections)
    if cache_key is not None:
        cached = _OPJ_DATA_SECTIONS_CACHE.get(cache_key)
        if cached is not None:
            return [*cached]

    sections = opj_parser.iter_opj_data_sections(data, max_sections=max_sections)
    if cache_key is not None:
        _OPJ_DATA_SECTIONS_CACHE[cache_key] = sections
        _prune_cache(_OPJ_DATA_SECTIONS_CACHE)
    return [*sections]


def parse_opj_note_sections(
    data: bytes,
    *,
    max_sections: int = opj_parser.OPJ_NOTES_MAX_BLOCKS,
    max_chars: int = opj_parser.OPJ_NOTES_MAX_CHARS,
    path: Path | None = None,
) -> list[OpjNoteSection]:
    """Parse OPJ note sections with optional file-level caching."""
    cache_key = _cache_key_for_path(path, max_sections, max_chars)
    if cache_key is not None:
        cached = _OPJ_NOTE_SECTIONS_CACHE.get(cache_key)
        if cached is not None:
            return [*cached]

    sections = opj_parser.parse_opj_note_sections(
        data,
        max_sections=max_sections,
        max_chars=max_chars,
    )
    if cache_key is not None:
        _OPJ_NOTE_SECTIONS_CACHE[cache_key] = sections
        _prune_cache(_OPJ_NOTE_SECTIONS_CACHE)
    return [*sections]


def _clone_discovery_record(
    item: discovery_helpers.OriginObject, *, source_object_path: str | None = None
) -> OriginObject:
    source = source_object_path or item.source_object_path

    if isinstance(item, discovery_helpers.ParserBackedDiscoveryRecord):
        return ParserBackedDiscoveryRecord(
            offset=item.offset,
            name=item.name,
            length=item.length,
            object_kind=item.object_kind,
            source_object_path=source,
            parser_rule=item.parser_rule,
            parser_confidence=item.parser_confidence,
            parser_confirmed=item.parser_confirmed,
        )
    if isinstance(item, discovery_helpers.HeuristicDiscoveryRecord):
        return HeuristicDiscoveryRecord(
            offset=item.offset,
            name=item.name,
            length=item.length,
            object_kind=item.object_kind,
            source_object_path=source,
            heuristic_signal=item.heuristic_signal,
            parser_confirmed=item.parser_confirmed,
        )
    return OriginObject(
        offset=item.offset,
        name=item.name,
        length=item.length,
        object_kind=item.object_kind,
        source_object_path=source,
        parser_confirmed=item.parser_confirmed,
    )


def extract_origin_storage_blocks(
    data: bytes, *, max_blocks: int = OPJU_HINTS_MAX_BLOCKS, max_chars: int = OPJU_HINTS_MAX_CHARS
) -> list[dict[str, int | str]]:
    """Collect lightweight OriginStorage text snippets from OPJU-like blobs."""
    if max_blocks <= 0 or max_chars <= 0:
        return []

    if not data or _ORIGIN_STORAGE_OPEN_TAG not in data:
        return []
    reports = parse_opju_origin_storage_reports(data, max_reports=max_blocks)
    if not reports:
        return []

    blocks: list[dict[str, int | str]] = []
    for report in reports:
        preview = report.raw_text
        if len(preview) > max_chars:
            preview = preview[: max_chars - 3] + "..."
        blocks.append(
            {
                "index": report.index,
                "offset": report.offset,
                "length": report.length,
                "label": report.label or "",
                "function": report.function or "",
                "time": report.time or "",
                "preview": preview,
            }
        )
    return blocks


def _parse_opj_objects(data: bytes, path: Path | None = None) -> list[OriginObject]:
    disable_heavy_scans = False
    if path is not None:
        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = None
        else:
            disable_heavy_scans = file_size > discovery_helpers._OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
    boundaries = parse_opj_boundaries(
        data,
        path=path,
        disable_heavy_scans=disable_heavy_scans,
    )
    if not boundaries:
        return []

    def _semantic_boundary_name(boundary: OpjObjectBoundary) -> str:
        name = boundary.name.split("@", 1)[0]
        if boundary.kind == "worksheet" and "_" in name:
            name = name.split("_", 1)[0]
        return name.casefold()

    window_kinds_by_name: dict[str, set[str]] = {}
    for boundary in boundaries:
        if boundary.parser_rule != "opj_window":
            continue
        window_kinds_by_name.setdefault(_semantic_boundary_name(boundary), set()).add(boundary.kind)

    objects: list[OriginObject] = []
    for boundary in boundaries:
        if boundary.parser_rule == "opj_data_section":
            window_kinds = window_kinds_by_name.get(_semantic_boundary_name(boundary), set())
            if boundary.kind == "worksheet" and window_kinds.intersection({"worksheet", "excel"}):
                continue
            if boundary.kind == "matrix" and "matrix" in window_kinds:
                continue
        objects.append(
            ParserBackedDiscoveryRecord(
                offset=boundary.start_offset,
                name=boundary.name,
                length=boundary.length,
                object_kind=boundary.kind,
                source_object_path=boundary.source_object_path,
                parser_rule=boundary.parser_rule,
                parser_confidence=boundary.confidence,
            )
        )
    return objects


def _signature_at_offset(path: Path, offset: int, *, data_window: bytes | None = None, data_offset: int = 0) -> bool:
    if data_window is not None:
        local_offset = offset - data_offset
        if local_offset >= 0:
            for marker in (*OPJ_HEADER_MARKER, PNG_SIG, JPEG_SIG, *GIF_SIGS):
                marker_len = len(marker)
                if local_offset + marker_len <= len(data_window) and data_window.startswith(marker, local_offset):
                    return True

    with path.open("rb") as fh:
        fh.seek(offset)
        signature = fh.read(max(len(PNG_SIG), len(JPEG_SIG), len(GIF_SIGS[0])))
    for marker in (*OPJ_HEADER_MARKER, PNG_SIG, JPEG_SIG, *GIF_SIGS):
        if signature.startswith(marker):
            return True
    return False


def _streaming_has_column_table(path: Path) -> bool:
    """Return whether an OPJU stream contains a `<ColumnTable` marker."""
    marker = _OPJU_COLUMN_TABLE_MARKER
    carry = b""
    carry_size = len(marker) - 1
    for chunk in iter_file_chunks(path, chunk_size=discovery_helpers._OPJ_DISCOVERY_STREAM_CHUNK_SIZE):
        payload = (carry + chunk).lower()
        if marker in payload:
            return True
        if carry_size > 0:
            carry = payload[-carry_size:]
    return False


def _opju_worksheet_discovery_records(data: bytes, path: Path | None = None) -> list[OriginObject]:
    records = parse_opju_records(data, path=path)
    objects: list[OriginObject] = []
    for region in records.regions:
        if region.kind != opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET:
            continue
        objects.append(
            ParserBackedDiscoveryRecord(
                offset=region.offset,
                name=region.name,
                length=region.length,
                object_kind=_OPJU_REGION_OBJECT_KIND_BY_KIND.get(
                    region.kind,
                    "opju_region",
                ),
                source_object_path=(
                    discovery_helpers._derive_source_path(region.name)
                    if region.kind == opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET
                    else region.source_object_path or discovery_helpers._derive_source_path(region.name)
                ),
                parser_rule=region.parser_rule,
                parser_confidence=region.confidence,
            )
        )
    return objects


def _opju_region_discovery_records(records: OpjuRecords, *, path: Path | None = None) -> list[OriginObject]:
    return [
        ParserBackedDiscoveryRecord(
            offset=region.offset,
            name=region.name,
            length=region.length,
            object_kind=_OPJU_REGION_OBJECT_KIND_BY_KIND.get(
                region.kind,
                "opju_region",
            ),
            source_object_path=(
                discovery_helpers._derive_source_path(region.name)
                if region.kind == opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET
                else region.source_object_path or discovery_helpers._derive_source_path(region.name)
            ),
            parser_rule=region.parser_rule,
            parser_confidence=region.confidence,
        )
        for region in records.regions
    ]


def _filter_graph_heuristics_from_opju_reports(
    heuristic_objects: list[OriginObject],
    opju_report_records: tuple[OpjuReportRecord, ...],
) -> list[OriginObject]:
    if not heuristic_objects:
        return []

    report_spans = sorted(
        ((record.offset, record.offset + record.length) for record in opju_report_records if record.length > 0),
        key=lambda span: span[0],
    )
    if not report_spans:
        return list(heuristic_objects)

    def _is_within_report(offset: int) -> bool:
        for start, end in report_spans:
            if offset < start:
                return False
            if offset < end:
                return True
        return False

    filtered: list[OriginObject] = []
    for item in heuristic_objects:
        if (
            item.object_kind in {"graph", "layer"}
            and getattr(item, "heuristic_signal", None) == "bracket_scan"
            and _is_within_report(item.offset)
        ):
            continue
        filtered.append(item)
    return filtered


def _merge_parser_and_heuristic_objects(
    parser_objects: list[OriginObject], heuristic_objects: list[OriginObject]
) -> list[OriginObject]:
    if not parser_objects:
        return list(heuristic_objects)

    parser_note_names = {item.name for item in parser_objects if item.object_kind == "note"}
    matrix_parser_sources_by_name: dict[str, set[str]] = {}
    for item in parser_objects:
        if item.object_kind != "matrix":
            continue
        key_names = {item.name}
        if "/" in item.name:
            key_names.add(item.name.rsplit("/", 1)[1])
        for name in key_names:
            matrix_parser_sources_by_name.setdefault(name, set()).add(item.source_object_path)

    matrix_parser_source_by_name: dict[str, str] = {
        name: sorted(paths)[0] for name, paths in matrix_parser_sources_by_name.items() if len(paths) == 1
    }

    parser_names = {((item.object_kind or "unknown"), item.name) for item in parser_objects}
    parser_name_source_paths = {
        ((item.object_kind or "unknown"), item.name, item.source_object_path) for item in parser_objects
    }
    parser_name_offsets = {((item.object_kind or "unknown"), item.name, item.offset) for item in parser_objects}

    kept_path_duplicates: set[tuple[str, str, str | None]] = set()
    objects = list(parser_objects)
    normalized_heuristics: list[OriginObject] = []
    for item in heuristic_objects:
        if item.object_kind == "matrix":
            preferred_source = matrix_parser_source_by_name.get(item.name)
            if preferred_source is None:
                leaf = item.name.rsplit("/", 1)[-1] if "/" in item.name else item.name
                preferred_source = matrix_parser_source_by_name.get(leaf)
            if preferred_source is not None and preferred_source != item.source_object_path:
                normalized_heuristics.append(_clone_discovery_record(item, source_object_path=preferred_source))
                continue
        normalized_heuristics.append(item)

    heuristic_objects = normalized_heuristics
    for item in heuristic_objects:
        parser_key = (item.object_kind or "unknown", item.name)
        if parser_key in parser_names:
            # Keep one non-note fallback duplicate when parser has one deterministic
            # boundary for a given kind/name.
            if item.object_kind == "note":
                if item.name in parser_note_names:
                    continue
            elif (parser_key[0], item.name, item.offset) in parser_name_offsets:
                continue
            elif (parser_key[0], item.name, item.source_object_path) in parser_name_source_paths:
                continue
            elif (parser_key[0], item.name, item.source_object_path) in kept_path_duplicates:
                continue
            kept_path_duplicates.add((parser_key[0], item.name, item.source_object_path))

        objects.append(item)

    return objects


def discover_origin_objects(
    path: Path,
    *,
    max_repeats_per_name: int | None = 2,
    include_redundant_tokens: bool = False,
    heuristic_kind_limit: int | None = None,
    collect_heuristics: bool = True,
    allowed_kinds: frozenset[str] | None = None,
    total_limit: int | None = None,
) -> list[OriginObject]:
    """Return best-effort Origin object inventory from raw bytes.

    The probe is intentionally conservative and only emits obvious-looking names.
    """
    file_stats = path.stat()
    with path.open("rb") as fh:
        header_magic = fh.read(max(len(MAGIC_OPJU), len(MAGIC_OPJ)))

    cache_key = _cache_key_for_path(
        path,
        max_repeats_per_name,
        include_redundant_tokens,
        heuristic_kind_limit,
        collect_heuristics,
        tuple(sorted(allowed_kinds)) if allowed_kinds is not None else None,
        total_limit,
    )
    if cache_key is not None and cache_key in _ORIGIN_OBJECT_CACHE:
        if header_magic.startswith(MAGIC_OPJU):
            # Keep parser-evidence instrumentation visible even when object discovery cache
            # is reused across sessions/runs.
            cached_data = read_cached_bytes(path)
            if cached_data:
                parse_opju_records(cached_data, path=path)
        return [_clone_discovery_record(item) for item in _ORIGIN_OBJECT_CACHE[cache_key]]

    use_streaming_discovery = (
        file_stats.st_size > discovery_helpers._OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
        and header_magic.startswith(OPJ_HEADER_MARKER)
    )
    if use_streaming_discovery:
        parser_objects: list[OriginObject] = []
        opju_records: OpjuRecords | None = None
        if header_magic.startswith(MAGIC_OPJU):
            data = read_cached_bytes(path)
            if data:
                opju_records = parse_opju_records(data, path=path)
                parser_objects.extend(_opju_region_discovery_records(opju_records, path=path))
        elif header_magic.startswith(MAGIC_OPJ):
            data = read_cached_bytes(path)
            if data:
                parser_objects.extend(_parse_opj_objects(data, path=path))
        if collect_heuristics:
            kind_hits: dict[str, int] | None = {} if heuristic_kind_limit is not None else None
            allowed_kinds = (
                allowed_kinds
                if allowed_kinds is not None
                else (
                    _OPJU_LARGE_HEURISTIC_ALLOWED_KINDS
                    if header_magic.startswith(MAGIC_OPJU) and parser_objects
                    else None
                )
            )
            effective_total_limit = (
                total_limit
                if total_limit is not None
                else (
                    _OPJU_LARGE_HEURISTIC_TOTAL_LIMIT
                    if header_magic.startswith(MAGIC_OPJU) and parser_objects
                    else None
                )
            )
            heuristic_objects = discovery_helpers._token_offsets_from_file(
                path,
                max_repeats_per_name=max_repeats_per_name,
                heuristic_kind_limit=heuristic_kind_limit,
                kind_hits=kind_hits,
                allowed_kinds=allowed_kinds,
                total_limit=effective_total_limit,
            ) + discovery_helpers._bracket_offsets_from_file(
                path,
                max_repeats_per_name=max_repeats_per_name,
                heuristic_kind_limit=heuristic_kind_limit,
                kind_hits=kind_hits,
                allowed_kinds=allowed_kinds,
                total_limit=effective_total_limit,
            )
            if header_magic.startswith(MAGIC_OPJU) and opju_records is not None:
                heuristic_objects = _filter_graph_heuristics_from_opju_reports(
                    heuristic_objects,
                    opju_records.report_records,
                )
            objects = _merge_parser_and_heuristic_objects(parser_objects, heuristic_objects)
        else:
            objects = parser_objects
    else:
        data = read_cached_bytes(path)
        if not data:
            return []

        opju_records = parse_opju_records(data, path=path)
        opju_worksheet_regions: set[str] = {
            region.name
            for region in opju_records.regions
            if region.kind == opju_parser.OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET
        }
        objects = list(_opju_region_discovery_records(opju_records, path=path))
        if header_magic.startswith(MAGIC_OPJ):
            objects.extend(list(_parse_opj_objects(data, path=path)))
        if collect_heuristics:
            kind_hits: dict[str, int] | None = {} if heuristic_kind_limit is not None else None
            effective_allowed_kinds = (
                allowed_kinds
                if allowed_kinds is not None
                else (_OPJU_LARGE_HEURISTIC_ALLOWED_KINDS if header_magic.startswith(MAGIC_OPJU) and objects else None)
            )
            effective_total_limit = (
                total_limit
                if total_limit is not None
                else (_OPJU_LARGE_HEURISTIC_TOTAL_LIMIT if header_magic.startswith(MAGIC_OPJU) and objects else None)
            )
            heuristic_objects = discovery_helpers._token_offsets_from_file(
                path,
                max_repeats_per_name=max_repeats_per_name,
                heuristic_kind_limit=heuristic_kind_limit,
                kind_hits=kind_hits,
                allowed_kinds=effective_allowed_kinds,
                total_limit=effective_total_limit,
            ) + discovery_helpers._bracket_offsets_from_file(
                path,
                max_repeats_per_name=max_repeats_per_name,
                heuristic_kind_limit=heuristic_kind_limit,
                kind_hits=kind_hits,
                allowed_kinds=effective_allowed_kinds,
                total_limit=effective_total_limit,
            )
            if header_magic.startswith(MAGIC_OPJU):
                heuristic_objects = _filter_graph_heuristics_from_opju_reports(
                    heuristic_objects,
                    opju_records.report_records,
                )
            objects = _merge_parser_and_heuristic_objects(objects, heuristic_objects)

        if opju_worksheet_regions:
            objects = [obj for obj in objects if not (obj.name in opju_worksheet_regions and not obj.parser_confirmed)]

        objects = [
            obj
            for obj in objects
            if obj.parser_confirmed or not discovery_helpers._is_media_signature(obj.offset, data)
        ]

    if use_streaming_discovery:
        # best effort for large headered files, avoid full file reads.
        objects = [obj for obj in objects if not _signature_at_offset(path, obj.offset)]

    objects = [
        _clone_discovery_record(
            obj,
            source_object_path=(
                discovery_helpers._derive_source_path(obj.name)
                if obj.source_object_path == "object/item"
                else obj.source_object_path
            ),
        )
        for obj in objects
    ]
    # prefer unique names and stable offsets.
    dedup: list[OriginObject] = []
    seen: set[tuple[int, str, str | None]] = set()
    for obj in objects:
        # A parser-backed generic page identity and a heuristic object-kind
        # interpretation can legitimately refer to the same name bytes. Keep
        # both until the page directory grammar can classify page kinds.
        key = (obj.offset, obj.name, obj.object_kind)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(obj)

    if not dedup and header_magic.startswith(OPJ_HEADER_MARKER):
        dedup.append(
            OriginObject(
                offset=0,
                name="origin_project",
                length=0,
                source_object_path="project/origin_project",
            )
        )

    dedup.sort(key=lambda item: item.offset)

    if max_repeats_per_name is not None:
        limited: list[OriginObject] = []
        parser_name_counts: dict[tuple[str | None, str], int] = {}
        for obj in dedup:
            if obj.parser_confirmed:
                key = (obj.object_kind, obj.name)
                parser_name_counts[key] = parser_name_counts.get(key, 0) + 1
        name_hits: dict[tuple[str | None, str], int] = {}
        heuristic_name_hits: dict[tuple[str | None, str], int] = {}
        for obj in dedup:
            key = (obj.object_kind, obj.name)
            if obj.parser_confirmed:
                seen_count = name_hits.get(key, 0)
                if seen_count >= max_repeats_per_name:
                    continue
                name_hits[key] = seen_count + 1
            else:
                parser_slots = min(parser_name_counts.get(key, 0), max_repeats_per_name)
                heuristic_slots = max_repeats_per_name - parser_slots
                seen_count = heuristic_name_hits.get(key, 0)
                if seen_count >= heuristic_slots:
                    continue
                heuristic_name_hits[key] = seen_count + 1
            limited.append(obj)
        dedup = limited

    discovered = discovery_helpers._ensure_unique_paths(dedup)
    if cache_key is not None:
        _ORIGIN_OBJECT_CACHE[cache_key] = discovered
        _prune_cache(_ORIGIN_OBJECT_CACHE)
    return [_clone_discovery_record(item) for item in discovered]
