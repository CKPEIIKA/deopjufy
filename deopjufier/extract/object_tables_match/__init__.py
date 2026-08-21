import json
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from deopjufier.extract.object_tables_helpers import *
from deopjufier.extract.tabular_helpers import write_book_csv as _write_book_csv
from deopjufier.inventory import OriginObject, discover_origin_objects
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opj import (
    OpjMatrixMetadata,
    OpjWorksheetMetadata,
)


def _collapse_worksheet_recovery_names(names: set[str]) -> set[str]:
    """Collapse worksheet names to worksheet roots for parser-backed recovery."""
    collapsed: set[str] = set()
    for name in names:
        normalized = name
        if "@" in normalized:
            normalized = normalized.split("@", 1)[0]
        if "_" in normalized:
            normalized = normalized.split("_", 1)[0]
        normalized = normalized.strip()
        if normalized:
            collapsed.add(normalized)
        else:
            collapsed.add(name)
    return collapsed


_ParserMetadata = OpjWorksheetMetadata | OpjMatrixMetadata


def _discover_worksheet_candidates_for_opju_parser_fallback(
    input_path: Path,
    *,
    parser_backed_worksheet_name_hints: set[str] | None,
    recovered_rows_by_name: dict[str, list[list[str]]],
    recovered_metadata_by_name: Mapping[str, _ParserMetadata],
    parser_window_name_lookup: set[str],
) -> list[OriginObject]:
    has_worksheet_hints = bool(parser_backed_worksheet_name_hints)
    trusted_parser_backed_worksheet_name_hints = (
        parser_backed_worksheet_name_hints
        if (
            parser_backed_worksheet_name_hints is not None
            and len(parser_backed_worksheet_name_hints) <= _OPJU_PARSER_NAME_HINT_LIMIT
        )
        else None
    )
    has_real_parser_row_hint = any(
        name and not name.startswith("origin_storage_family_") for name in recovered_rows_by_name
    )
    if not has_worksheet_hints and not recovered_rows_by_name and not recovered_metadata_by_name:
        return []
    if not has_real_parser_row_hint and not recovered_metadata_by_name:
        return []

    try:
        discovered_objects = discover_origin_objects(
            input_path,
            allowed_kinds=frozenset({"worksheet"}),
            collect_heuristics=True,
            heuristic_kind_limit=(
                _OPJU_PARSER_NAME_HINT_LIMIT if trusted_parser_backed_worksheet_name_hints is not None else None
            ),
            total_limit=(
                _OPJU_PARSER_NAME_HINT_LIMIT if trusted_parser_backed_worksheet_name_hints is not None else None
            ),
        )
    except Exception:
        return []

    discovered_objects = sorted(
        [
            obj
            for obj in discovered_objects
            if obj.object_kind == "worksheet"
            if _looks_like_worksheet_object_name(obj.name)
        ],
        key=lambda item: (item.offset, item.source_object_path, item.name),
    )
    if not discovered_objects:
        return []

    if trusted_parser_backed_worksheet_name_hints is not None:
        return discovered_objects

    return [
        obj
        for obj in discovered_objects
        if _parser_tabular_evidence(
            obj,
            recovered_rows_by_name=recovered_rows_by_name,
            recovered_metadata_by_name=recovered_metadata_by_name,
            parser_window_name_lookup=parser_window_name_lookup,
            parser_backed_worksheet_name_hints=trusted_parser_backed_worksheet_name_hints,
            is_opju=True,
        )
    ] or discovered_objects


def _parser_tabular_evidence(
    obj: OriginObject,
    *,
    recovered_rows_by_name: dict[str, list[list[str]]],
    recovered_metadata_by_name: Mapping[str, _ParserMetadata],
    parser_window_name_lookup: set[str],
    parser_backed_worksheet_name_hints: set[str] | None = None,
    is_opju: bool = False,
) -> bool:
    if obj.object_kind == "worksheet" and not _looks_like_worksheet_object_name(obj.name):
        return False

    parser_rows = _payload_rows_from_parser_records(
        obj.name,
        obj.offset,
        recovered_rows_by_name,
        prefer_root=True,
    )
    canonical_metadata_name = _resolve_parser_record_name(
        obj.name,
        {name: None for name in recovered_metadata_by_name},
        prefer_root=True,
    )
    metadata = recovered_metadata_by_name.get(canonical_metadata_name) if canonical_metadata_name is not None else None
    canonical_window_name = _resolve_parser_record_name(
        obj.name,
        {name: None for name in parser_window_name_lookup},
        prefer_root=True,
    )
    parser_name_hint = False
    if parser_backed_worksheet_name_hints is not None:
        if (
            parser_backed_worksheet_name_hints
            and len(parser_backed_worksheet_name_hints) <= _OPJU_PARSER_NAME_HINT_LIMIT
        ):
            parser_name_hint = (
                _resolve_parser_record_name(
                    obj.name,
                    {name: None for name in parser_backed_worksheet_name_hints},
                    prefer_root=True,
                )
                is not None
            )
        elif getattr(obj, "parser_confirmed", False):
            parser_name_hint = True

    return (
        parser_rows is not None
        or metadata is not None
        or canonical_window_name is not None
        or parser_name_hint
        or (obj.object_kind == "excel" and obj.parser_confirmed)
    )


def _output_filename(
    *,
    base: str,
    obj_name: str,
    output_format: str,
    parser_backed: bool,
) -> str:
    """Build an output filename, including sheet identifier when parser-backed."""
    if not parser_backed:
        return f"{base}.{output_format}"

    safe_name = _SAFE_NAME_RX.sub("_", obj_name).strip("._-")
    safe_name = safe_name or "sheet"
    return f"{base}_{safe_name}.{output_format}"


def _write_tabular_metadata_sidecar(
    target: Path,
    metadata: OpjWorksheetMetadata | OpjMatrixMetadata,
    *,
    force: bool,
) -> tuple[bool, str]:
    payload = metadata.to_dict()
    if not payload:
        return False, ""

    sidecar = target.with_suffix(".metadata.json")
    if sidecar.exists() and not force:
        return False, sidecar.as_posix()

    with sidecar.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(payload, fp, indent=2, sort_keys=True)
        fp.write("\n")
    return True, sidecar.as_posix()


def _write_tabular_rows(
    target: Path,
    output_format: str,
    rows: list[tuple[int, int, int, list[str]]],
    *,
    headers: list[str] | None = None,
) -> int:
    if output_format == "xlsx":
        try:
            return _write_book_xlsx(target, rows, headers=headers)
        except TypeError:
            return _write_book_xlsx(target, rows)
    if output_format == "json":
        if headers is not None:
            payload = {
                "headers": headers,
                "rows": [
                    {
                        "table_id": table_id,
                        "row_in_table": row_id,
                        "offset": offset,
                        "columns": len(values),
                        "values": values,
                    }
                    for table_id, row_id, offset, values in rows
                ],
            }
        else:
            payload = [
                {
                    "table_id": table_id,
                    "row_in_table": row_id,
                    "offset": offset,
                    "columns": len(values),
                    "values": values,
                }
                for table_id, row_id, offset, values in rows
            ]
        with target.open("w", encoding="utf-8", newline="\n") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return len(rows)
    return _write_book_csv(
        target,
        rows,
        delimiter="," if output_format == "csv" else "\t",
        headers=headers,
    )


def _build_tabular_manifest_item(
    *,
    object_rows: list[tuple[int, int, int, list[str]]],
    object_name: str,
    object_kind: str,
    manifest_kind: str,
    manifest_root: Path | None,
    out_dir: Path,
    out_path: Path,
    source_object_path: str,
    discovery_type: str,
    heuristic: bool,
    confidence: float,
    offset: int,
    length: int,
    window_start: int,
    window_end: int,
    rows: tuple[int, int] | None = None,
    metadata: OpjWorksheetMetadata | OpjMatrixMetadata | None = None,
    force: bool = False,
) -> list[ManifestItem]:
    status = "extracted" if object_rows else "partial"
    item_status = status
    if status == "partial":
        item_status = "partial"

    # rows/columns may come from parser metadata and should not be inferred from output length.
    manifest_rows = rows[0] if rows else (len(object_rows) if object_rows else 0)
    manifest_columns = rows[1] if rows else (max((len(values) for _, _, _, values in object_rows), default=0))

    items: list[ManifestItem] = [
        ManifestItem(
            kind=manifest_kind,
            name=object_name,
            status=item_status,
            confidence=confidence if status == "extracted" else 0.4,
            discovery_type=discovery_type,
            heuristic=heuristic,
            path=_manifest_path(out_path, manifest_root or out_dir),
            source_object_path=source_object_path,
            object_kind=object_kind,
            offset=offset,
            length=length,
            range_start=window_start,
            range_end=window_end,
            rows=manifest_rows,
            columns=manifest_columns,
        )
    ]

    if metadata is not None:
        metadata_written, metadata_path = _write_tabular_metadata_sidecar(
            out_path,
            metadata,
            force=force,
        )
        manifest_metadata_kind = "worksheet_metadata" if manifest_kind == "worksheet" else "matrix_metadata"
        manifest_metadata_name = f"{object_name}_metadata"
        manifest_items = [
            ManifestItem(
                kind=manifest_metadata_kind,
                name=manifest_metadata_name,
                status="extracted" if metadata_written else "skipped",
                confidence=0.95 if metadata_written else 0.85,
                discovery_type="parser_backed_hint",
                heuristic=False,
                path=_manifest_path(Path(metadata_path), manifest_root or out_dir),
                source_object_path=source_object_path,
                object_kind=object_kind,
                offset=offset,
                length=length,
                range_start=window_start,
                range_end=window_end,
                error=None if metadata_written else "target_exists",
            )
        ]
        if metadata_path:
            items.extend(manifest_items)
    return items


_T = TypeVar("_T")


def _merge_record_maps(base: dict[str, _T], overlay: dict[str, _T]) -> dict[str, _T]:
    merged: dict[str, _T] = dict(base)
    merged.update(overlay)
    return merged


def _resolve_tabular_matching_objects_for_extract(
    matching_objects: list[OriginObject],
    *,
    input_path: Path,
    object_kind: str,
    is_opju: bool,
    allow_parser_recovery: bool,
    recovered_rows_by_name: dict[str, list[list[str]]],
    recovered_metadata_by_name: Mapping[str, OpjWorksheetMetadata] | Mapping[str, OpjMatrixMetadata],
    parser_window_name_lookup: set[str],
    parser_backed_worksheet_name_hints: set[str] | None,
    recovered_non_family_rows_present: bool = False,
    emit_unsupported_collection: bool,
    unsupported_range: tuple[int, int] | None = None,
    unsupported_source_object_path: str | None = None,
    manifest: Manifest,
    manifest_item_kind: str,
    collection_name: str,
    collection_path: str,
    manifest_root: Path,
    out_dir: Path,
    missing_error: str,
) -> tuple[list[OriginObject], bool]:
    all_matching_objects = list(matching_objects)
    parser_backed_hints_trusted = (
        parser_backed_worksheet_name_hints is not None
        and len(parser_backed_worksheet_name_hints) <= _OPJU_PARSER_NAME_HINT_LIMIT
    )

    if not matching_objects and is_opju and object_kind == "worksheet":
        matching_objects = _discover_worksheet_candidates_for_opju_parser_fallback(
            input_path,
            parser_backed_worksheet_name_hints=(set(parser_backed_worksheet_name_hints or set())),
            recovered_rows_by_name=recovered_rows_by_name,
            recovered_metadata_by_name=recovered_metadata_by_name,
            parser_window_name_lookup=parser_window_name_lookup,
        )
        if matching_objects:
            all_matching_objects = list(matching_objects)
            emit_unsupported_collection = False

    if not matching_objects and emit_unsupported_collection:
        unsupported_source = (
            unsupported_source_object_path
            if is_opju and object_kind == "worksheet"
            else f"{collection_name}_collection"
        )
        collection_dir = out_dir / collection_path
        collection_dir.mkdir(parents=True, exist_ok=True)
        manifest.add_item(
            ManifestItem(
                kind=manifest_item_kind,
                name=f"{collection_name}_collection",
                status="unsupported",
                confidence=0.4,
                discovery_type="parser_backed_hint",
                heuristic=False,
                path=_manifest_path(collection_dir, manifest_root or out_dir),
                source_object_path=unsupported_source,
                error=missing_error,
            )
        )
        return [], True

    should_surface_unmatched_worksheet_windows = object_kind == "worksheet" and parser_backed_hints_trusted
    parser_supported_objects: list[OriginObject] = [] if is_opju else list(matching_objects)
    if is_opju:
        for obj in matching_objects:
            if _parser_tabular_evidence(
                obj,
                recovered_rows_by_name=recovered_rows_by_name,
                recovered_metadata_by_name=recovered_metadata_by_name,
                parser_window_name_lookup=parser_window_name_lookup,
                parser_backed_worksheet_name_hints=(
                    parser_backed_worksheet_name_hints if object_kind == "worksheet" else None
                ),
                is_opju=True,
            ):
                parser_supported_objects.append(obj)

        if not parser_supported_objects and object_kind == "worksheet":
            if parser_backed_hints_trusted:
                hint_lookup = {name: None for name in (parser_backed_worksheet_name_hints or set())}
                parser_supported_objects = [
                    obj
                    for obj in matching_objects
                    if _resolve_parser_record_name(obj.name, hint_lookup, prefer_root=True) is not None
                ]
            if not parser_supported_objects:
                # Keep per-worksheet entries when parser evidence is absent or hint
                # matching misses, but avoid worksheet collection placeholders that
                # can hide parser-coverage gaps.
                matching_objects = [
                    obj
                    for obj in matching_objects
                    if obj.object_kind == "worksheet" and _looks_like_worksheet_object_name(obj.name)
                ]
                parser_supported_objects = matching_objects
                emit_unsupported_collection = False
            elif should_surface_unmatched_worksheet_windows:
                matching_objects = all_matching_objects
            else:
                matching_objects = parser_supported_objects
        elif object_kind == "worksheet" and (
            not parser_backed_worksheet_name_hints
            or should_surface_unmatched_worksheet_windows
            or not parser_backed_hints_trusted
        ):
            matching_objects = all_matching_objects
        else:
            matching_objects = parser_supported_objects

    if (
        object_kind != "worksheet"
        and len(parser_supported_objects) != len(matching_objects)
        and emit_unsupported_collection
    ):
        manifest.add_item(
            ManifestItem(
                kind=manifest_item_kind,
                name=f"{collection_name}_collection",
                status="unsupported",
                confidence=0.7,
                discovery_type="parser_backed_hint",
                heuristic=False,
                path=_manifest_path(out_dir / collection_path, manifest_root or out_dir),
                source_object_path=unsupported_source_object_path or f"{collection_name}_collection",
                error="some_objects_lack_parser_backed_records",
            )
        )
    if object_kind == "worksheet" and not parser_supported_objects:
        # Keep per-worksheet evidence windows only when parser-backed matching
        # is not available.
        matching_objects = [
            obj
            for obj in all_matching_objects
            if obj.object_kind == "worksheet" and _looks_like_worksheet_object_name(obj.name)
        ]

    elif (
        object_kind == "worksheet"
        and allow_parser_recovery
        and not is_opju
        and (recovered_rows_by_name or recovered_metadata_by_name)
    ):
        evidence_objects: list[OriginObject] = []
        for obj in matching_objects:
            if obj.object_kind != "worksheet":
                continue
            if _parser_tabular_evidence(
                obj,
                recovered_rows_by_name=recovered_rows_by_name,
                recovered_metadata_by_name=recovered_metadata_by_name,
                parser_window_name_lookup=parser_window_name_lookup,
                is_opju=is_opju,
            ):
                evidence_objects.append(obj)
        if evidence_objects:
            matching_objects = evidence_objects

    if object_kind == "worksheet" and (allow_parser_recovery is True or is_opju):
        matching_objects = _coalesce_parser_backed_worksheet_objects(
            objects=matching_objects,
            recovered_rows_by_name=recovered_rows_by_name,
            recovered_metadata_by_name={
                name: metadata
                for name, metadata in recovered_metadata_by_name.items()
                if isinstance(metadata, OpjWorksheetMetadata)
            },
            parser_window_name_lookup=parser_window_name_lookup,
            parser_backed_worksheet_name_hints=(parser_backed_worksheet_name_hints),
            is_opju=is_opju,
        )

    return matching_objects, False


__all__ = [name for name in globals() if not name.startswith("__")]
