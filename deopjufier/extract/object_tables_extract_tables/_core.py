import re
from pathlib import Path

from deopjufier.discovery_scan import _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES, _OPJ_PARSER_BOUNDARY_MAX_BYTES
from deopjufier.extract.discovery_helpers import book_dir as _book_dir
from deopjufier.extract.object_tables_extract_filters import *  # noqa: F403
from deopjufier.extract.object_tables_extract_tables._external_links import (
    find_external_workbook_reference,
    write_external_workbook_reference,
)
from deopjufier.extract.object_tables_helpers._compat import scan_numeric_tables_from_bytes
from deopjufier.extract.object_tables_match import *  # noqa: F403
from deopjufier.inventory import (
    iter_object_windows,
)

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_COMPOUND_FILE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _spreadsheet_payload_matches_name(name: str, payload: bytes) -> bool:
    """Validate the container signature implied by a spreadsheet filename."""
    suffix = Path(re.sub(r"(__\d+)$", "", name)).suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return payload.startswith(_ZIP_SIGNATURES)
    if suffix in {".xls", ".xlt"}:
        return payload.startswith(_OLE_COMPOUND_FILE_SIGNATURE)
    return False


def _origin_storage_raw_filename(name: str) -> str:
    stem = Path(_safe_attachment_filename(name)).stem or "attachment"
    return f"{stem}.originstorage.bin"


def _is_single_cell_noisy_numeric_row(values: list[str]) -> bool:
    """Return True for scan rows that are likely token-noise artifacts."""

    if len(values) != 1:
        return False
    token = str(values[0]).strip()
    if not token:
        return True
    if _PARSER_CELL_TOKEN_RE.fullmatch(token):
        return "." not in token.lower() and "e" not in token.lower()
    return False


def _tabular_content_class(rows: list[tuple[int, int, int, list[str]]]) -> str:
    values = [str(value).strip() for _, _, _, row in rows for value in row if str(value).strip()]
    if not values:
        return "empty"
    if all(value == "??" or value.startswith("cell://") for value in values):
        return "internal_references"
    row_width = max((len(row) for _, _, _, row in rows), default=0)
    if row_width == 1 and len(values) >= 8 and _mostly_corrupt_text(values):
        return "corrupt_text"
    return "data"


def _mostly_corrupt_text(values: list[str]) -> bool:
    if any(_PARSER_CELL_TOKEN_RE.fullmatch(value) for value in values):
        return False
    suspicious = 0
    for value in values:
        if len(value) > 160 or any(char in value for char in '<>\\"@') or value[:1] in {"!", ")", ";"}:
            suspicious += 1
    return suspicious * 2 > len(values)


def book_rows_for_object(
    rows: list[tuple[int, int, int, list[str]]], start: int, end: int
) -> list[tuple[int, int, int, list[str]]]:
    """Filter numeric-table rows to the byte range for a specific object."""

    if not rows:
        return []
    return [(table_id, row_id, offset, values) for table_id, row_id, offset, values in rows if start <= offset < end]


def _extract_single_tabular_object(
    obj: OriginObject,
    *,
    start: int,
    end: int,
    object_kind: str,
    collection_root: Path,
    output_format: str,
    filename_base: str,
    manifest: Manifest,
    manifest_root: Path | None,
    out_dir: Path,
    manifest_item_kind: str,
    metadata_item_kind: str,
    data: bytes,
    can_scan: bool,
    force: bool,
    allow_parser_recovery: bool,
    is_opju: bool,
    table_min_rows: int,
    table_min_columns: int,
    recovered_rows_by_name: dict[str, list[list[str]]],
    recovered_dimensions_by_name: dict[str, tuple[int, int]],
    recovered_metadata_by_name: dict[str, OpjWorksheetMetadata] | dict[str, OpjMatrixMetadata],
    verified_parser_table_names: set[str],
    recovered_source_ranges_by_name: dict[str, list[dict[str, int]]],
    parser_window_name_lookup: set[str],
    parser_backed_worksheet_name_hints: set[str] | None,
    scan_worksheet_name_hints: set[str] | None = None,
    scan_rows: list[tuple[int, int, int, list[str]]] | None = None,
    suppress_solo_unbacked_worksheet: bool = False,
) -> tuple[int, list[tuple[int, int, int, list[str]]] | None]:
    parser_lookup = {
        name: None
        for name in {
            *recovered_rows_by_name.keys(),
            *recovered_metadata_by_name.keys(),
            *parser_window_name_lookup,
        }
    }
    canonical_name = _resolve_parser_record_name(
        obj.name,
        parser_lookup,
        prefer_root=object_kind != "worksheet" or not is_opju,
    )
    object_name = canonical_name or obj.name
    if object_kind != "worksheet":
        object_name = obj.name

    parser_rows_lookup_name = canonical_name if canonical_name is not None else object_name
    if object_kind == "worksheet" and is_opju:
        parser_rows_lookup_name = _resolve_parser_record_name(
            obj.name,
            parser_lookup,
            prefer_root=False,
        )
        if parser_rows_lookup_name is None:
            # Most parser-recovered worksheet payloads are emitted at workbook
            # scope (for example ``Book1``) while discovered windows may use
            # suffixes (for example ``Book1_A``). Fall back to root matching
            # so parser-backed evidence can still drive extraction.
            parser_rows_lookup_name = _resolve_parser_record_name(
                obj.name,
                parser_lookup,
                prefer_root=True,
            )

    verified_parser_table = (parser_rows_lookup_name or object_name) in verified_parser_table_names
    parser_source_ranges = recovered_source_ranges_by_name.get(parser_rows_lookup_name or object_name)

    parser_rows = _payload_rows_from_parser_records(
        parser_rows_lookup_name or object_name,
        start,
        recovered_rows_by_name,
        prefer_root=object_kind != "worksheet" or not is_opju,
    )
    rows = parser_rows
    parser_rows_payload = [values for _, _, _, values in parser_rows or []]
    parser_rows_meaningful = False
    if parser_rows_payload:
        parser_rows_meaningful = _is_parser_recovered_row_meaningful(parser_rows_payload)
    parser_rows_recovered = parser_rows is not None
    canonical_metadata_name = _resolve_parser_record_name(
        obj.name,
        {name: None for name in recovered_metadata_by_name},
    )
    metadata = recovered_metadata_by_name.get(canonical_metadata_name) if canonical_metadata_name is not None else None
    metadata_dims = _metadata_dimensions(metadata)
    if (
        metadata_dims is not None
        and canonical_metadata_name is not None
        and canonical_metadata_name not in recovered_dimensions_by_name
    ):
        recovered_dimensions_by_name[canonical_metadata_name] = metadata_dims
    canonical_window_name = _resolve_parser_record_name(
        obj.name,
        {name: None for name in parser_window_name_lookup},
    )
    parser_backed_name_hint = False
    if parser_backed_worksheet_name_hints is not None:
        parser_backed_name_hint = (
            _resolve_parser_record_name(
                obj.name,
                {name: None for name in parser_backed_worksheet_name_hints},
                prefer_root=object_kind == "worksheet",
            )
            is not None
        )

    scan_worksheet_name_lookup = (
        {name: None for name in scan_worksheet_name_hints} if scan_worksheet_name_hints else None
    )
    scan_worksheet_name_hint = False
    if scan_worksheet_name_lookup is not None:
        scan_worksheet_name_hint = (
            _resolve_parser_record_name(
                obj.name,
                scan_worksheet_name_lookup,
                prefer_root=object_kind == "worksheet",
            )
            is not None
        )

    parser_backed_signal = (
        parser_rows is not None
        or metadata is not None
        or canonical_window_name is not None
        or parser_backed_name_hint
        or obj.parser_confirmed
    )
    scan_allowed = not parser_backed_name_hint
    if is_opju and object_kind == "worksheet":
        should_scan = False
        allow_small_discovery_scan = (
            scan_worksheet_name_hint
            and len(scan_worksheet_name_hints or set()) <= 2
            and len(data) <= 2 * _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
        )
        if parser_backed_signal or allow_small_discovery_scan:
            parser_payload_rows = [values for _, _, _, values in rows] if rows is not None else []
            parser_rows_meaningful = (
                rows is not None and bool(rows) and _is_parser_recovered_row_meaningful(parser_payload_rows)
            )
            should_scan = rows is None or rows == [] or not parser_rows_meaningful
        scan_allowed = scan_allowed or should_scan
    else:
        should_scan = rows is None and not parser_backed_signal

    scan_window_is_bounded = end - start <= _OPJ_PARSER_BOUNDARY_MAX_BYTES
    can_scan_window = can_scan and (not is_opju or scan_window_is_bounded)
    if should_scan and can_scan_window and metadata is None and scan_allowed:
        # For parser-backed OPJU worksheet windows, single-column payloads are often
        # legitimate; relax the width gate to preserve recoverable one-column evidence.
        scan_min_columns = table_min_columns
        if is_opju and object_kind == "worksheet" and (parser_backed_signal or scan_worksheet_name_hint):
            scan_min_columns = 1
        if scan_rows is None:
            scan_rows = []
        window_has_rows = any(start <= row_offset < end for _, _, row_offset, _ in scan_rows)
        if not window_has_rows:
            new_scan_rows = scan_numeric_tables_from_bytes(
                data,
                min_rows=table_min_rows,
                min_columns=scan_min_columns,
                start=start,
                end=end,
            )
            for row in new_scan_rows:
                if row not in scan_rows:
                    scan_rows.append(row)
        scanned_rows = book_rows_for_object(scan_rows, start, end)
        if scanned_rows:
            if parser_rows is not None and rows == [] and len(scanned_rows) == 1:
                # Single-cell rows from parser-declared worksheets are often
                # token-like false positives; keep such fixtures explicit partial.
                if _is_single_cell_noisy_numeric_row(scanned_rows[0][3]):
                    scanned_rows = []
            if scanned_rows:
                rows = scanned_rows

    source_object_path = obj.source_object_path
    if object_kind == "worksheet":
        if not is_opju:
            source_object_path = _normalize_opj_worksheet_source_path(obj.source_object_path)
            if object_name != obj.name and "/" in source_object_path:
                head, _ = source_object_path.rsplit("/", 1)
                source_object_path = f"{head}/{object_name}"
        else:
            source_object_path = _normalize_opju_worksheet_source_path(
                obj.source_object_path,
                obj.name,
            )

    parser_rows_recovered = parser_rows is not None or metadata is not None or canonical_window_name is not None
    parser_rows_recovered_and_non_empty = parser_rows_recovered and bool(parser_rows)

    if rows is None:
        rows = []

    # Parser recovery and windowed scans both retain offsets relative to the
    # source file. Keeping that coordinate system intact makes exported table
    # provenance match the manifest object window.
    parser_backed_window = obj.parser_confirmed
    parser_backed_payload = parser_rows_recovered or parser_backed_window or parser_backed_name_hint
    headers = None
    if parser_backed_payload and metadata is not None:
        row_width = max((len(values) for _, _, _, values in rows), default=0)
        headers = _tabular_headers(metadata, row_width)
    elif parser_backed_payload:
        row_width = max((len(values) for _, _, _, values in rows), default=0)
        headers = [f"col_{index}" for index in range(1, row_width + 1)] if row_width else None

    if parser_backed_payload:
        discovery_type = "opju_column_descriptor_table" if verified_parser_table else "parser_window"
        confidence = 0.99 if verified_parser_table else (0.95 if parser_rows_recovered else 0.85)
        heuristic = False
        extraction_method = "opju_descriptor_table" if verified_parser_table else "parser_window"
    else:
        if is_opju:
            discovery_type = "parser_backed_hint"
            confidence = 0.6
            heuristic = False
            extraction_method = "table_scan_recon"
        else:
            discovery_type = "heuristic_object_scan"
            confidence = 0.6
            heuristic = True
            extraction_method = "numeric_table_scan"

    if _should_skip_matrix_like_worksheet_fallback(
        obj,
        parser_backed_payload=parser_backed_payload,
        rows=rows,
    ):
        return 0, scan_rows

    if (
        object_kind == "matrix"
        and not allow_parser_recovery
        and not getattr(obj, "parser_confirmed", False)
        and not parser_backed_payload
        and len(rows) == 0
    ):
        normalized_name = obj.name.lower()
        if normalized_name.startswith("msheet") or normalized_name.startswith("mbook"):
            return 0, scan_rows

    if (
        object_kind == "worksheet"
        and not is_opju
        and metadata is None
        and not parser_rows
        and len(rows) == 0
        and can_scan
        and not parser_backed_payload
    ):
        return 0, scan_rows

    if (
        object_kind == "worksheet"
        and is_opju
        and suppress_solo_unbacked_worksheet
        and not parser_rows_recovered
        and not parser_backed_name_hint
        and len(rows) == 0
    ):
        return 0, scan_rows

    emitted_manifest_kind = manifest_item_kind
    if (
        object_kind == "excel"
        and not parser_rows_recovered_and_non_empty
        and not rows
        and (
            not obj.parser_confirmed
            or not _looks_like_excel_attachment(obj.name)
            or _looks_like_opju_sheet_excel_attachment(obj.name)
        )
    ):
        emitted_manifest_kind = "attachment"
    is_special_non_tabular_attachment = (
        emitted_manifest_kind == "attachment" and _looks_like_known_non_tabular_attachment(obj)
    )
    emitted_metadata_item_kind = metadata_item_kind if emitted_manifest_kind != "attachment" else "attachment_metadata"
    emitted_item_root = out_dir / "attachments" if emitted_manifest_kind == "attachment" else collection_root

    out_dir_for_obj = _book_dir(emitted_item_root, source_object_path)
    out_dir_for_obj.mkdir(parents=True, exist_ok=True)
    filename = (
        _safe_attachment_filename(obj.name)
        if is_special_non_tabular_attachment
        else _output_filename(
            base=filename_base,
            obj_name=object_name,
            output_format=output_format,
            parser_backed=parser_backed_payload,
        )
    )
    target = out_dir_for_obj / filename

    if target.exists() and not force:
        manifest_rows = 0
        manifest_columns = 0
        manifest.add_item(
            ManifestItem(
                kind=emitted_manifest_kind,
                name=object_name,
                status="skipped",
                confidence=confidence,
                discovery_type=discovery_type,
                heuristic=heuristic,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                extraction_method=extraction_method,
                completeness="partial",
                rows=manifest_rows,
                columns=manifest_columns,
                error="target_exists",
            )
        )
        return 0, scan_rows

    if is_special_non_tabular_attachment:
        attachment_data = data[start:end]
        if not attachment_data:
            manifest.add_item(
                ManifestItem(
                    kind=emitted_manifest_kind,
                    name=object_name,
                    status="unsupported",
                    confidence=0.4,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=source_object_path,
                    object_kind=obj.object_kind,
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    extraction_method=extraction_method,
                    completeness="partial",
                    rows=0,
                    columns=0,
                    error="no_attachment_payload",
                )
            )
            return 0, scan_rows

        if (
            is_opju
            and obj.parser_confirmed
            and _looks_like_excel_attachment(obj.name)
            and not _spreadsheet_payload_matches_name(obj.name, attachment_data)
        ):
            external_reference = find_external_workbook_reference(
                attachment_data,
                source_offset=start,
            )
            link_status: str | None = None
            if external_reference is not None:
                reference, workbook_path, reference_start, reference_end = external_reference
                link_target = out_dir_for_obj / "external_workbook_link.json"
                if link_target.exists() and not force:
                    link_status = "skipped"
                    link_error = "target_exists"
                else:
                    write_external_workbook_reference(
                        link_target,
                        advertised_filename=obj.name,
                        reference=reference,
                        workbook_path=workbook_path,
                        source_start=reference_start,
                        source_end=reference_end,
                    )
                    link_status = "extracted"
                    link_error = None
                manifest.add_item(
                    ManifestItem(
                        kind="external_workbook_link",
                        name=object_name,
                        status=link_status,
                        confidence=0.99,
                        discovery_type="parser_window",
                        heuristic=False,
                        path=_manifest_path(link_target, manifest_root or out_dir),
                        source_object_path=source_object_path,
                        object_kind="external_workbook_reference",
                        offset=reference_start,
                        length=reference_end - reference_start,
                        range_start=reference_start,
                        range_end=reference_end,
                        extraction_method="opju_external_workbook_reference",
                        completeness="complete" if link_status == "extracted" else "partial",
                        verification="exact",
                        embedded_payload=False,
                        error=link_error,
                    )
                )

            target = out_dir_for_obj / _origin_storage_raw_filename(obj.name)
            if target.exists() and not force:
                status = "skipped"
                error = "target_exists"
            else:
                target.write_bytes(attachment_data)
                status = "partial"
                error = (
                    "external_workbook_reference_source_preserved"
                    if external_reference is not None
                    else "advertised_spreadsheet_signature_mismatch"
                )
            manifest.add_item(
                ManifestItem(
                    kind="origin_storage_region",
                    name=object_name,
                    status=status,
                    confidence=0.4,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=source_object_path,
                    object_kind="origin_storage_attachment",
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    extraction_method="raw_region_preservation",
                    completeness="partial",
                    embedded_payload=False if external_reference is not None else None,
                    rows=0,
                    columns=0,
                    error=error,
                )
            )
            return (
                (1 if link_status == "extracted" else 0) + (1 if status == "partial" else 0),
                scan_rows,
            )

        target.write_bytes(attachment_data)
        manifest.add_item(
            ManifestItem(
                kind=emitted_manifest_kind,
                name=object_name,
                status="extracted",
                confidence=confidence,
                discovery_type=discovery_type,
                heuristic=heuristic,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                extraction_method=extraction_method,
                completeness="complete" if parser_rows_recovered_and_non_empty or parser_backed_window else "partial",
                rows=0,
                columns=0,
            )
        )
        return 1, scan_rows

    rows_written = 0
    if rows:
        if force and target.exists():
            target.unlink(missing_ok=True)
        write_headers = headers
        rows_written = _write_tabular_rows(target, output_format, rows, headers=write_headers)
    elif force and target.exists():
        target.unlink(missing_ok=True)

    manifest_rows_lookup_name = _resolve_parser_record_name(
        object_name,
        {name: None for name in recovered_dimensions_by_name},
        prefer_root=object_kind != "worksheet" or not is_opju,
    )
    manifest_rows_cols = (
        recovered_dimensions_by_name.get(manifest_rows_lookup_name) if manifest_rows_lookup_name is not None else None
    )
    verified_empty_table = verified_parser_table and manifest_rows_cols == (0, 0) and not rows

    emitted_status = (
        "extracted"
        if (
            rows_written > 0
            or verified_empty_table
            or (emitted_manifest_kind == "attachment" and not can_scan and not parser_backed_payload)
        )
        else "partial"
    )

    if (
        emitted_manifest_kind == "attachment"
        and not is_special_non_tabular_attachment
        and emitted_status == "extracted"
    ):
        if output_format == "xlsx":
            pass
        elif target.exists() and not force:
            manifest_rows = 0
            manifest_columns = 0
            manifest.add_item(
                ManifestItem(
                    kind=emitted_manifest_kind,
                    name=object_name,
                    status="skipped",
                    confidence=0.4,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=source_object_path,
                    object_kind=obj.object_kind,
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    extraction_method=extraction_method,
                    completeness="partial",
                    rows=manifest_rows,
                    columns=manifest_columns,
                    error="target_exists",
                )
            )
            return 0, scan_rows
        else:
            if force and target.exists():
                target.unlink(missing_ok=True)
            _write_tabular_rows(target, output_format, [])

    if emitted_manifest_kind == "attachment" and is_special_non_tabular_attachment:
        emitted_status = "extracted"
    if (
        object_kind == "matrix"
        and not allow_parser_recovery
        and not can_scan
        and emitted_status == "partial"
        and not rows
        and output_format != "xlsx"
    ):
        if force and target.exists():
            target.unlink(missing_ok=True)
        _write_tabular_rows(target, output_format, [])

    table_partial_error = None if emitted_status == "extracted" else "no_extracted_table_rows"

    if manifest_rows_cols is not None and (rows_written == 0 or not is_opju):
        manifest_rows, manifest_columns = manifest_rows_cols
    else:
        manifest_rows = rows_written
        if rows_written == 0:
            manifest_columns = 0
        else:
            manifest_columns = max((len(values) for _, _, _, values in rows), default=0)

    manifest_item_path = (
        _manifest_path(target, manifest_root or out_dir)
        if rows_written > 0
        or (
            emitted_manifest_kind == "attachment"
            and emitted_status == "extracted"
            and not is_special_non_tabular_attachment
            and output_format != "xlsx"
        )
        or (
            object_kind == "matrix"
            and not allow_parser_recovery
            and not can_scan
            and emitted_status == "partial"
            and not rows
            and output_format != "xlsx"
        )
        else None
    )
    manifest.add_item(
        ManifestItem(
            kind=emitted_manifest_kind,
            name=object_name,
            status=emitted_status,
            confidence=confidence if rows_written > 0 or verified_empty_table else 0.4,
            discovery_type=discovery_type,
            heuristic=heuristic,
            path=manifest_item_path,
            source_object_path=source_object_path,
            object_kind=obj.object_kind,
            offset=obj.offset,
            length=obj.length,
            range_start=start,
            range_end=end,
            source_ranges=parser_source_ranges,
            extraction_method=extraction_method,
            completeness="complete" if emitted_status == "extracted" and not heuristic else "partial",
            verification="exact" if verified_parser_table else None,
            rows=manifest_rows,
            columns=manifest_columns,
            content_class=_tabular_content_class(rows),
            error=table_partial_error,
        )
    )

    if metadata is not None:
        metadata_written, metadata_path = _write_tabular_metadata_sidecar(
            target,
            metadata,
            force=force,
        )
        manifest.add_item(
            ManifestItem(
                kind=emitted_metadata_item_kind,
                name=f"{object_name}_metadata",
                status="extracted" if metadata_written else "skipped",
                confidence=0.95 if metadata_written else 0.85,
                discovery_type="parser_backed_hint",
                heuristic=False,
                path=_manifest_path(
                    Path(metadata_path),
                    manifest_root or out_dir,
                )
                if metadata_path
                else None,
                source_object_path=source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                source_ranges=parser_source_ranges,
                error=None if metadata_written else "target_exists",
                extraction_method="metadata_extraction",
                completeness="complete" if metadata_written else "partial",
                verification="exact" if verified_parser_table else None,
            )
        )

    extracted = 1 if rows_written > 0 or verified_empty_table else 0

    return extracted, scan_rows


def _extract_tabular_objects(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    object_kind: str,
    manifest_item_kind: str,
    collection_path: str,
    collection_name: str,
    missing_error: str,
    filename_base: str,
    output_format: str = "csv",
    force: bool = False,
    table_min_rows: int = 1,
    table_min_columns: int = 1,
    manifest_root: Path | None = None,
    objects: list[OriginObject] | None = None,
    allow_parser_recovery: bool | None = None,
    allow_heuristic_scan: bool = True,
    recovery_max_tables: int = 200,
    file_data: bytes | None = None,
    recovered_rows_by_name: dict[str, list[list[str]]] | None = None,
    recovered_dimensions_by_name: dict[str, tuple[int, int]] | None = None,
    recovered_metadata_by_name: dict[str, OpjWorksheetMetadata] | dict[str, OpjMatrixMetadata] | None = None,
    metadata_item_kind: str = "worksheet_metadata",
    recovered_non_family_rows_present: bool = False,
    parser_backed_worksheet_name_hints: set[str] | None = None,
    scan_worksheet_name_hints: set[str] | None = None,
    emit_unsupported_collection: bool = True,
    recovery_include_family_binary: bool = True,
    verified_parser_table_names: set[str] | None = None,
    recovered_source_ranges_by_name: dict[str, list[dict[str, int]]] | None = None,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
) -> int:
    """Extract table-shaped objects with explicit parser-vs-heuristic manifest signals."""
    out_dir.mkdir(parents=True, exist_ok=True)
    data = file_data if file_data is not None else input_path.read_bytes()
    is_opju = _is_opju_file(file_data, input_path)
    objects_for_extract = list(objects or [])
    if allow_parser_recovery is None:
        allow_parser_recovery = False
    matching_objects = [
        obj
        for obj in objects_for_extract
        if obj.object_kind == object_kind
        and (selected_object_keys is None or (obj.offset, obj.name, obj.source_object_path) in selected_object_keys)
    ]
    file_size = input_path.stat().st_size
    emit_unsupported_collection = emit_unsupported_collection and not (is_opju and object_kind in {"excel", "matrix"})

    extracted = 0
    collection_root = out_dir / collection_path
    if output_format not in {"csv", "tsv", "json", "xlsx"}:
        output_format = "csv"

    recovered_rows_by_name = recovered_rows_by_name or {}
    recovered_dimensions_by_name = recovered_dimensions_by_name or {}
    recovered_metadata_by_name = recovered_metadata_by_name or {}
    verified_parser_table_names = verified_parser_table_names or set()
    recovered_source_ranges_by_name = recovered_source_ranges_by_name or {}
    parser_backed_worksheet_name_hints = (
        set(parser_backed_worksheet_name_hints) if parser_backed_worksheet_name_hints is not None else set()
    )
    scan_worksheet_name_hints = (
        set(scan_worksheet_name_hints)
        if scan_worksheet_name_hints is not None
        else set(parser_backed_worksheet_name_hints)
    )
    has_parser_backed_worksheet_window = any(
        obj.parser_confirmed for obj in matching_objects if obj.object_kind == object_kind
    )
    has_scan_worksheet_hints = bool(scan_worksheet_name_hints)
    can_scan = allow_heuristic_scan and (
        (
            is_opju
            and object_kind == "worksheet"
            and (
                recovered_non_family_rows_present
                or has_parser_backed_worksheet_window
                or (
                    has_scan_worksheet_hints
                    and len(scan_worksheet_name_hints) <= 2
                    and file_size <= 2 * _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
                )
            )
        )
        or (file_size <= _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES)
    )
    scan_rows: list[tuple[int, int, int, list[str]]] | None = None
    parser_window_name_lookup: set[str] = (
        _parser_window_lookup(data, input_path)
        if object_kind == "worksheet"
        and allow_parser_recovery is True
        and file_size <= _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
        else set()
    )
    unsupported_range = (
        _derive_opju_worksheet_unsupported_range(
            data,
            input_path=input_path,
            max_tables=recovery_max_tables,
            include_decoded=False,
            worksheet_objects=[obj for obj in matching_objects if obj.object_kind == "worksheet"],
        )
        if is_opju and object_kind == "worksheet"
        else None
    )
    unsupported_source_object_path = None
    if unsupported_range is not None:
        (
            unsupported_range_start,
            unsupported_range_end,
            unsupported_source_object_path,
        ) = unsupported_range
        unsupported_range = (unsupported_range_start, unsupported_range_end)

    matching_objects, should_stop = _resolve_tabular_matching_objects_for_extract(
        matching_objects,
        input_path=input_path,
        object_kind=object_kind,
        is_opju=is_opju,
        allow_parser_recovery=allow_parser_recovery,
        recovered_rows_by_name=recovered_rows_by_name,
        recovered_metadata_by_name=recovered_metadata_by_name,
        parser_window_name_lookup=parser_window_name_lookup,
        parser_backed_worksheet_name_hints=parser_backed_worksheet_name_hints,
        recovered_non_family_rows_present=recovered_non_family_rows_present,
        emit_unsupported_collection=emit_unsupported_collection,
        unsupported_range=unsupported_range,
        unsupported_source_object_path=unsupported_source_object_path,
        manifest=manifest,
        manifest_item_kind=manifest_item_kind,
        collection_name=collection_name,
        collection_path=collection_path,
        manifest_root=manifest_root or out_dir,
        out_dir=out_dir,
        missing_error=missing_error,
    )
    if should_stop:
        return 0

    ordered_objects = sorted(matching_objects, key=lambda item: item.offset)
    all_objects = [obj for obj in (objects or []) if obj.object_kind == object_kind]
    ordered_window_objects = sorted(all_objects, key=lambda item: item.offset) if all_objects else ordered_objects
    object_windows = iter_object_windows(
        ordered_window_objects,
        file_size,
        scope_by_source_prefix=(object_kind == "worksheet" and is_opju),
    )
    object_window_map = {
        (window_item.offset, window_item.source_object_path): (start, end) for window_item, start, end in object_windows
    }
    is_solo_opju_worksheet_without_backed_hints = (
        object_kind == "worksheet" and is_opju and len(ordered_objects) == 1 and not parser_backed_worksheet_name_hints
    )

    for obj in ordered_objects:
        start, end = object_window_map.get(
            (obj.offset, obj.source_object_path),
            (obj.offset, file_size),
        )
        extracted_for_obj, scan_rows = _extract_single_tabular_object(
            obj,
            start=start,
            end=end,
            object_kind=object_kind,
            collection_root=collection_root,
            output_format=output_format,
            filename_base=filename_base,
            manifest=manifest,
            manifest_root=manifest_root,
            out_dir=out_dir,
            manifest_item_kind=manifest_item_kind,
            metadata_item_kind=metadata_item_kind,
            data=data,
            can_scan=can_scan,
            force=force,
            allow_parser_recovery=allow_parser_recovery,
            is_opju=is_opju,
            table_min_rows=table_min_rows,
            table_min_columns=table_min_columns,
            recovered_rows_by_name=recovered_rows_by_name,
            recovered_dimensions_by_name=recovered_dimensions_by_name,
            recovered_metadata_by_name=recovered_metadata_by_name,
            verified_parser_table_names=verified_parser_table_names,
            recovered_source_ranges_by_name=recovered_source_ranges_by_name,
            parser_window_name_lookup=parser_window_name_lookup,
            parser_backed_worksheet_name_hints=parser_backed_worksheet_name_hints,
            scan_worksheet_name_hints=scan_worksheet_name_hints,
            scan_rows=scan_rows,
            suppress_solo_unbacked_worksheet=(is_solo_opju_worksheet_without_backed_hints),
        )
        extracted += extracted_for_obj

    if object_kind == "worksheet":
        _dedupe_partial_tabular_items_with_extracted_names(
            manifest,
            manifest_item_kind=manifest_item_kind,
            collection_name=collection_name,
            out_dir=out_dir,
        )

    if emit_unsupported_collection and extracted == 0:
        has_partial_parser_backed_no_rows = any(
            item.kind == manifest_item_kind
            and item.status == "partial"
            and item.error == "no_extracted_table_rows"
            and item.heuristic is False
            for item in manifest.items
        )
        collection_name_key = f"{collection_name}_collection"
        has_collection_item = any(
            item.kind == manifest_item_kind and item.name == collection_name_key for item in manifest.items
        )
        has_table_item = any(
            item.kind == manifest_item_kind
            and item.name != collection_name_key
            and item.status in {"extracted", "skipped"}
            for item in manifest.items
        )
        if (
            not has_collection_item
            and not has_table_item
            and not (object_kind == "worksheet" and is_opju and has_partial_parser_backed_no_rows)
        ):
            collection_dir = out_dir / collection_path
            collection_dir.mkdir(parents=True, exist_ok=True)
            manifest.add_item(
                ManifestItem(
                    kind=manifest_item_kind,
                    name=collection_name_key,
                    status="unsupported",
                    confidence=0.4,
                    discovery_type="parser_backed_hint",
                    heuristic=False,
                    extraction_method="table_scan_recon",
                    completeness="partial",
                    path=_manifest_path(
                        collection_dir,
                        manifest_root or out_dir,
                    ),
                    source_object_path=collection_name_key,
                    error="no_extracted_table_rows",
                )
            )

    return extracted


def _scan_ranges_for_object_rows(
    rows: list[tuple[int, int, int, list[str]]], start: int, end: int
) -> list[tuple[int, int, int, list[str]]]:
    return [(table_id, row_id, offset, values) for table_id, row_id, offset, values in rows if start <= offset < end]
