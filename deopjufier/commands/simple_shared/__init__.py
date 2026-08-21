"""Simple one-shot command handlers for non-dataflow commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from deopjufier.blocks import ImageBlock
from deopjufier.commands.artifact_policy import (
    has_malformed_graph_preview,
    should_warn_for_missing_artifact,
)
from deopjufier.commands.render import _print_compare_summary
from deopjufier.commands.support import (
    _EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND,
    _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES,
    EXIT_GENERAL,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    SUPPORTED_TYPES,
    _add_parser_warning,
    _build_session,
    _coerce_counts_by_artifact,
    _default_output_dir,
    _ensure_file,
    _is_recon_heuristic_item,
    _limit_extract_objects,
    _log,
    _support_class,
)
from deopjufier.compare import compare_manifests
from deopjufier.detect import detect_file
from deopjufier.errors import CorruptedInputError, UnsupportedFileError
from deopjufier.extract import (
    extract_books,
    extract_byte_map,
    extract_excel,
    extract_functions,
    extract_graph_previews,
    extract_images,
    extract_matrices,
    extract_notes,
    extract_opju_decoded_regions,
    extract_opju_semantic_provenance,
    extract_opju_tagged_envelopes,
    extract_origin_inventory,
    extract_origin_storage_analysis_summary,
    extract_origin_storage_reports,
    extract_project_tree,
    extract_raw_blocks,
    extract_strings,
    extract_tables,
    extract_text_regions,
)
from deopjufier.extract.graphs import (
    _derive_graph_unsupported_range,
    _unsupported_graph_collection_item,
)
from deopjufier.extract.raw_regions import RAW_REGION_CLASS_TEXT, RawRegionClassification
from deopjufier.extract.tables import scan_numeric_tables, write_tables_csv
from deopjufier.inventory import (
    OriginObject,
    ParserBackedDiscoveryRecord,
    parse_opj_boundaries,
)
from deopjufier.io import dump_range
from deopjufier.manifest import Manifest, ManifestItem, make_manifest
from deopjufier.opj import walk_opj_file
from deopjufier.opj.stream import OpjStreamError
from deopjufier.opju import iter_opju_decoded_strings, walk_opju_file
from deopjufier.session import ExtractionSession
from deopjufier.strings import iter_strings


def _compute_parser_status(step_enabled: bool, manifest_items: list) -> str:
    if not step_enabled:
        return "unsupported"
    if not manifest_items:
        return "empty"
    if any(item.status == "extracted" for item in manifest_items):
        return "ok"
    if any(item.status == "partial" for item in manifest_items):
        return "unsupported"
    if any(item.status == "unsupported" for item in manifest_items):
        return "unsupported"
    return "empty"


def _manifest_has_skipped_table_scan(manifest: Manifest) -> bool:
    return any(item.kind == "table_scan" and item.status == "skipped" for item in manifest.items)


def _manifest_has_partial_outputs(manifest: Manifest) -> bool:
    for item in manifest.items:
        if item.status not in {"partial", "unsupported"}:
            continue
        if _is_recon_heuristic_item(
            kind=item.kind,
            status=item.status,
            error=item.error,
            source_object_path=item.source_object_path,
            item_name=item.name,
            discovery_type=item.discovery_type,
        ):
            continue
        return True
    return False


def _classify_extract_outcome(*, step_enabled: bool, hard_failure: bool) -> str:
    """Return a stable extraction-outcome classifier.

    Warning-only misses stay informational. Only hard extraction failures force
    `status="partial"`.
    """
    if not step_enabled:
        return "unsupported but honest"
    if hard_failure:
        return "partial failure"
    return "ok but absent"


def _scan_gaps_once(
    *,
    session: ExtractionSession,
    mode: str,
    min_size: int,
    image_blocks: list | None,
    objects: list[OriginObject] | None,
    min_rows: int,
    min_columns: int,
    text_min_length: int,
    classify_numeric: bool = True,
) -> tuple[list[tuple[int, int]], list[RawRegionClassification]]:
    """Classify unknown regions once and return ranges + classifications.

    The session cache keeps this deterministic result keyed by the same option tuple.
    """
    return session.classify_unknown_gaps(
        min_size=min_size,
        image_blocks=image_blocks,
        objects=objects,
        min_rows=min_rows,
        min_columns=min_columns,
        text_min_length=text_min_length,
        classify_numeric=classify_numeric,
    )


def _ensure_carved_raw_gap_evidence(manifest: Manifest) -> None:
    if any(item.discovery_type == "carved" for item in manifest.items):
        return

    for item in manifest.items:
        if item.kind == "raw_dump" and item.discovery_type == "unknown_gap":
            item.discovery_type = "carved"
            return


def _graph_boundary_fallback_objects(
    data: bytes,
    path: Path,
) -> list[OriginObject]:
    """Recover graph/layer objects via parser fallback when scan is disabled."""
    fallback_objects: list[OriginObject] = []
    seen: set[tuple[int, int, str, str | None]] = set()
    for boundary in parse_opj_boundaries(
        data,
        path=path,
        disable_heavy_scans=False,
    ):
        if boundary.kind not in {"graph", "layer"}:
            continue
        key = (boundary.start_offset, boundary.length, boundary.name, boundary.kind)
        if key in seen:
            continue
        seen.add(key)
        fallback_objects.append(
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
    return fallback_objects


def _filter_unowned_image_blocks(
    image_blocks: list[ImageBlock] | None,
    owned_blocks: list[ImageBlock],
) -> list[ImageBlock] | None:
    """Return image blocks that are not already claimed by parser-owned objects."""
    if image_blocks is None:
        return None
    if not owned_blocks:
        return image_blocks
    return [block for block in image_blocks if block not in owned_blocks]


_GRAPH_PREVIEW_OBJECT_KINDS = frozenset({"graph", "layer", "opju_graph_payload", "opju_preview"})
_OPJU_GRAPH_PREVIEW_KIND_LIMIT = 16


def _export_graph_previews(
    args,
    detection,
    session,
    manifest: Manifest,
    outdir: Path,
    shared_blocks: list[ImageBlock] | None,
    owned_image_blocks: list[ImageBlock],
    shared_objects: list[OriginObject] | None,
    use_parser_only_objects: bool,
    required_file_data,
    get_image_blocks,
    warn,
) -> bool:
    if args.no_images:
        if not any(item.kind == "graph" and item.name == "graph_collection" for item in manifest.items):
            graph_objects = list(shared_objects or [])
            graph_objects = [
                obj
                for obj in graph_objects
                if obj.object_kind in {"graph", "layer", "opju_preview", "opju_graph_payload"}
            ]
            unsupported_graph_range = _derive_graph_unsupported_range(
                None,
                input_path=args.file,
                graph_objects=graph_objects,
            )
            _unsupported_graph_collection_item(
                manifest,
                collection_path="graphs",
                out_dir=outdir,
                manifest_root=outdir,
                error="no_graph_previews",
                range_start=unsupported_graph_range[0] if unsupported_graph_range is not None else None,
                range_end=unsupported_graph_range[1] if unsupported_graph_range is not None else None,
                source_object_path=(unsupported_graph_range[2] if unsupported_graph_range is not None else None),
            )
        return False

    graph_blocks_for_previews: list | None = shared_blocks if shared_blocks is not None else None
    if graph_blocks_for_previews is None and shared_blocks is None:
        graph_blocks_for_previews = get_image_blocks()
    if graph_blocks_for_previews is not None and not any(block.valid for block in graph_blocks_for_previews):
        graph_blocks_for_previews = []
    graph_objects = shared_objects
    if detection.detected_type == "opju":
        graph_objects = list(shared_objects or [])
        opju_graph_objects = session.objects(
            collect_heuristics=not use_parser_only_objects,
            heuristic_kind_limit=_OPJU_GRAPH_PREVIEW_KIND_LIMIT,
            allowed_kinds=frozenset({"graph", "layer"}),
        )
        graph_signatures = {
            (item.object_kind, item.name, item.offset, item.length)
            for item in graph_objects
            if item.object_kind in _GRAPH_PREVIEW_OBJECT_KINDS
        }
        for obj in opju_graph_objects:
            if obj.object_kind not in _GRAPH_PREVIEW_OBJECT_KINDS:
                continue
            signature = (obj.object_kind, obj.name, obj.offset, obj.length)
            if signature in graph_signatures:
                continue
            graph_objects.append(obj)
            graph_signatures.add(signature)
    elif graph_objects is None or not any(item.object_kind in _GRAPH_PREVIEW_OBJECT_KINDS for item in graph_objects):
        graph_objects = session.objects(
            collect_heuristics=not use_parser_only_objects,
            heuristic_kind_limit=_EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND,
        )
    if detection.detected_type == "opj" and not any(
        item.object_kind in {"graph", "layer", "opju_preview", "opju_graph_payload"} for item in graph_objects
    ):
        graph_objects = list(graph_objects or [])
        fallback_graph_objects = _graph_boundary_fallback_objects(
            required_file_data(),
            args.file,
        )
        existing = {(obj.offset, obj.length, obj.name, obj.object_kind) for obj in graph_objects}
        for obj in fallback_graph_objects:
            key = (obj.offset, obj.length, obj.name, obj.object_kind)
            if key not in existing:
                graph_objects.append(obj)
    has_graph_objects = any(
        item.object_kind in {"graph", "layer", "opju_preview", "opju_graph_payload"} for item in graph_objects
    )
    if not has_graph_objects:
        graph_blocks_for_previews = []
    graph_count = extract_graph_previews(
        args.file,
        outdir,
        manifest,
        force=args.force,
        file_data=required_file_data(),
        image_blocks=graph_blocks_for_previews,
        objects=graph_objects,
        owned_image_blocks=owned_image_blocks if detection.detected_type == "opj" else None,
        manifest_root=outdir,
    )
    if graph_count == 0 and (
        should_warn_for_missing_artifact(
            manifest,
            "graph",
            detected_type=detection.detected_type,
        )
        or any(item.kind == "malformed_graph_preview" and item.status == "partial" for item in manifest.items)
    ):
        warn("No graph previews emitted to graph exports.", "no-graph-previews")
    if has_malformed_graph_preview(manifest):
        return True
    return False


def _export_notes_and_functions(
    *,
    args,
    manifest: Manifest,
    outdir: Path,
    shared_objects: list[OriginObject] | None,
    function_objects: list[OriginObject] | None,
    function_allow_parser_recovery: bool,
    function_has_parser_backed_artifacts: bool,
    file_data: bytes,
    detection,
    use_parser_only_objects: bool,
    warn,
    walk_elements=None,
) -> bool:
    function_count = extract_functions(
        args.file,
        outdir,
        manifest,
        force=args.force,
        objects=(function_objects if function_objects is not None and function_objects else None),
        allow_parser_recovery=function_allow_parser_recovery,
        include_provenance=bool(args.extended),
        file_data=file_data,
        manifest_root=outdir,
    )
    note_count = extract_notes(
        args.file,
        outdir,
        manifest,
        force=args.force,
        objects=shared_objects,
        file_data=file_data,
        manifest_root=outdir,
        include_provenance=bool(args.extended),
        walk_elements=walk_elements,
    )
    if note_count == 0 and should_warn_for_missing_artifact(
        manifest,
        "note",
        detected_type=detection.detected_type,
    ):
        warn("No note or analysis-report data emitted to text exports.", "no-note-data")

    non_lossless_functions = [
        item for item in manifest.items if item.kind == "function" and item.error == "non_lossless_function_text"
    ]
    if non_lossless_functions:
        replacement_count = sum(item.replacement_character_count or 0 for item in non_lossless_functions)
        control_count = sum(item.control_character_count or 0 for item in non_lossless_functions)
        warn(
            f"Preserved {len(non_lossless_functions)} function payloads as raw bytes because text decoding was not "
            f"lossless ({replacement_count} replacement characters, {control_count} control characters).",
            "non-lossless-function-text",
        )
    if (
        function_count == 0
        and not use_parser_only_objects
        and should_warn_for_missing_artifact(
            manifest,
            "function",
            detected_type=detection.detected_type,
            has_parser_backed_artifacts=function_has_parser_backed_artifacts,
        )
    ):
        warn(
            "No function data emitted to function exports.",
            "no-function-data",
        )
    return bool(non_lossless_functions)


__all__ = [name for name in globals() if not name.startswith("__")]
