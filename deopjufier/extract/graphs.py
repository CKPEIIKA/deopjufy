"""Graph and preview extraction helpers."""

from __future__ import annotations

import bisect
import json
from pathlib import Path

from deopjufier.blocks import ImageBlock, find_all_blocks, is_displayable_image_block
from deopjufier.extract.discovery_helpers import (
    book_dir as _book_dir,
)
from deopjufier.extract.path_helpers import manifest_relative_path as _manifest_path
from deopjufier.inventory import OriginObject
from deopjufier.io import dump_range
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opj import parse_opj_window_metadata
from deopjufier.opju import (
    OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH,
    OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,
    parse_opju_records,
)

_UNSUPPORTED_GRAPH_ATTRIBUTES = (
    "axes",
    "data_binding",
    "legend_configuration",
    "series_metadata",
    "style_attributes",
    "template_settings",
)
_NATIVE_UNSUPPORTED_GRAPH_ATTRIBUTES = ("legend_configuration", "style_attributes")
_PARSED_GRAPH_ATTRIBUTES = ("axis_ranges", "data_binding", "series_metadata", "template_settings")
_GRAPH_PREVIEW_KIND = "graph_preview"
_GRAPH_PREVIEW_MALFORMED_KIND = "malformed_graph_preview"
_PARSER_BACKED_PREVIEW_KIND = "parser_backed_graph_preview"
_MALFORMED_GRAPH_PREVIEW_MAX_BYTES = 4 * 1024 * 1024


def _iter_graph_object_windows(objects: list[OriginObject], file_size: int) -> list[tuple[OriginObject, int, int]]:
    """Return object windows for graph extraction with parser-friendly boundaries."""
    if not objects:
        return []
    ordered = objects

    parser_offsets = [obj.offset for obj in ordered if obj.parser_confirmed]
    parser_offsets.sort()
    parser_index = 0
    windows: list[tuple[OriginObject, int, int]] = []

    for index, obj in enumerate(ordered):
        start = max(obj.offset, 0)
        next_offset = ordered[index + 1].offset if index + 1 < len(ordered) else None
        if next_offset is not None and next_offset <= start:
            next_offset = None

        base_end = start + obj.length if obj.length > 0 else start
        if base_end < start:
            base_end = start

        end = base_end
        if obj.parser_confirmed:
            while parser_index < len(parser_offsets) and parser_offsets[parser_index] <= start:
                parser_index += 1
            next_parser = parser_offsets[parser_index] if parser_index < len(parser_offsets) else None
            if next_parser is not None:
                end = max(end, next_parser)
            else:
                end = file_size
        elif next_offset is not None:
            end = next_offset
        elif index == len(ordered) - 1:
            end = file_size

        if index == len(ordered) - 1 and end == start:
            end = file_size
        elif end < start:
            end = start

        windows.append((obj, start, end))

    return windows


def _find_graph_block_for_object_cached(
    block_offsets: list[int],
    blocks: list[ImageBlock],
    start: int,
    end: int,
) -> ImageBlock | None:
    """Pick a block for an object range without re-sorting per call."""
    if start < 0 or end < start:
        return None

    idx = bisect.bisect_left(block_offsets, start)
    if idx > 0:
        candidate = blocks[idx - 1]
        if candidate.offset < end and candidate.offset + candidate.length > start:
            return candidate

    for candidate in blocks[idx:]:
        if candidate.offset >= end:
            break
        if candidate.offset < end and candidate.offset + candidate.length > start:
            return candidate
    return None


def _find_any_graph_block_for_object(
    *,
    valid_offsets: list[int],
    invalid_offsets: list[int],
    valid_blocks: list[ImageBlock],
    invalid_blocks: list[ImageBlock],
    start: int,
    end: int,
    allow_invalid: bool,
) -> ImageBlock | None:
    selected = _find_graph_block_for_object_cached(
        valid_offsets,
        valid_blocks,
        start,
        end,
    )
    if selected is not None:
        return selected
    if not allow_invalid:
        return None
    return _find_graph_block_for_object_cached(
        invalid_offsets,
        invalid_blocks,
        start,
        end,
    )


def _graph_preview_confidence(*, parser_backed: bool, malformed: bool, parser_confidence: float) -> float:
    if parser_backed:
        return parser_confidence
    if malformed:
        return 0.3
    return 0.8


def _graph_preview_kind(
    *,
    object_kind: str | None,
    malformed: bool,
    has_preview: bool,
) -> str:
    if object_kind in {"opju_preview", "opju_graph_payload"} and has_preview:
        return _PARSER_BACKED_PREVIEW_KIND
    if malformed:
        return _GRAPH_PREVIEW_MALFORMED_KIND
    return _GRAPH_PREVIEW_KIND


def _write_graph_metadata(
    output_path: Path,
    payload: dict[str, object],
    *,
    force: bool,
) -> tuple[bool, str]:
    sidecar = output_path.with_name("graph.metadata.json")
    if sidecar.exists() and not force:
        return False, sidecar.as_posix()

    with sidecar.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(payload, fp, indent=2, sort_keys=True)
        fp.write("\n")
    return True, sidecar.as_posix()


def _is_jpeg_salvage_candidate(payload: bytes) -> bool:
    if len(payload) < 4:
        return False
    if payload[0:2] != b"\xff\xd8":
        return False
    if b"\xff\xd9" not in payload[2:]:
        return False
    return True


def _unsupported_graph_collection_item(
    manifest: Manifest,
    *,
    collection_path: str,
    out_dir: Path,
    manifest_root: Path | None = None,
    error: str = "no_graph_objects",
    range_start: int | None = None,
    range_end: int | None = None,
    source_object_path: str | None = None,
) -> None:
    collection_dir = out_dir / collection_path
    collection_dir.mkdir(parents=True, exist_ok=True)
    collection_source_path = source_object_path if source_object_path else "graph_collection"
    manifest.add_item(
        ManifestItem(
            kind="graph",
            name="graph_collection",
            status="unsupported",
            confidence=0.7,
            discovery_type="parser_backed_hint",
            heuristic=False,
            path=_manifest_path(collection_dir, manifest_root or out_dir),
            source_object_path=collection_source_path,
            error=error,
            range_start=range_start,
            range_end=range_end,
        )
    )


def _derive_graph_unsupported_range(
    file_data: bytes | None,
    *,
    input_path: Path,
    graph_objects: list[OriginObject],
) -> tuple[int, int, str | None] | None:
    spans: list[tuple[int, int, str | None]] = []
    for obj in graph_objects:
        if obj.object_kind not in {"graph", "layer", "opju_preview", "opju_graph_payload"}:
            continue
        if obj.offset < 0 or obj.length <= 0:
            continue
        spans.append((obj.offset, obj.offset + obj.length, obj.source_object_path))

    if not spans:
        data = file_data
        if data is None:
            data = input_path.read_bytes()
        if not data:
            return None
        try:
            parsed = parse_opju_records(data, path=input_path)
        except Exception:
            return None

        for region in parsed.regions:
            if region.kind not in {
                OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH,
                OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,
            }:
                continue
            if region.length <= 0:
                continue
            spans.append((region.offset, region.offset + region.length, region.source_object_path))

    if not spans:
        return None

    starts, ends, sources = zip(*spans, strict=False)
    range_start = min(starts)
    range_end = max(ends)
    source_candidates = [source for start, _, source in spans if start == range_start and source is not None]
    if not source_candidates:
        source_candidates = [source for source in sources if source is not None]
    source_object_path = min(source_candidates) if source_candidates else None
    return range_start, range_end, source_object_path


def extract_graph_previews(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    image_blocks: list[ImageBlock] | None = None,
    objects: list[OriginObject] | None = None,
    owned_image_blocks: list[ImageBlock] | None = None,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
) -> int:
    """Emit best-effort graph preview images for graph and OPJU preview objects."""
    discovered_objects = list(objects or [])
    graph_object_kinds = {"graph", "layer", "opju_preview", "opju_graph_payload"}
    graph_objects = [obj for obj in discovered_objects if obj.object_kind in graph_object_kinds]
    ordered_graph_objects = sorted(graph_objects, key=lambda item: item.offset)
    parser_graph_objects = [obj for obj in ordered_graph_objects if obj.parser_confirmed]
    unsupported_graph_range = _derive_graph_unsupported_range(
        file_data,
        input_path=input_path,
        graph_objects=graph_objects,
    )
    if not graph_objects:
        _unsupported_graph_collection_item(
            manifest,
            collection_path="graphs",
            out_dir=out_dir,
            manifest_root=manifest_root or out_dir,
            range_start=unsupported_graph_range[0] if unsupported_graph_range is not None else None,
            range_end=unsupported_graph_range[1] if unsupported_graph_range is not None else None,
            source_object_path=(unsupported_graph_range[2] if unsupported_graph_range is not None else None),
        )
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    graphs_root = out_dir / "graphs"
    discovered_blocks = find_all_blocks(input_path, allow_invalid_jpeg=True) if image_blocks is None else image_blocks
    ordered_blocks = sorted(discovered_blocks, key=lambda item: item.offset)
    valid_blocks = [item for item in ordered_blocks if item.valid]
    invalid_blocks = [item for item in ordered_blocks if not item.valid]
    valid_offsets = [item.offset for item in valid_blocks]
    invalid_offsets = [item.offset for item in invalid_blocks]
    file_size = input_path.stat().st_size
    opj_window_metadata = (
        {window.name: window for window in parse_opj_window_metadata(file_data)}
        if file_data is not None and input_path.suffix.lower() == ".opj"
        else {}
    )

    exported = 0
    duplicate_parser_windows: list[tuple[int, int]] = []
    for obj in parser_graph_objects:
        duplicate_parser_windows.append((obj.offset, max(obj.offset + max(0, obj.length), obj.offset + 1)))
    duplicate_parser_windows.sort(key=lambda window: window[0])
    parser_window_index = 0

    for obj, start, end in _iter_graph_object_windows(
        ordered_graph_objects,
        file_size,
    ):
        if (
            selected_object_keys is not None
            and (obj.offset, obj.name, obj.source_object_path) not in selected_object_keys
        ):
            continue
        if not obj.parser_confirmed:
            while (
                parser_window_index < len(duplicate_parser_windows)
                and duplicate_parser_windows[parser_window_index][1] <= obj.offset
            ):
                parser_window_index += 1
            if (
                parser_window_index < len(duplicate_parser_windows)
                and duplicate_parser_windows[parser_window_index][0] <= obj.offset
            ):
                continue

        parser_backed = obj.parser_confirmed
        discovery_type = "parser_window" if parser_backed else "heuristic_object_scan"
        heuristic = not parser_backed
        confidence = getattr(obj, "parser_confidence", 0.88) if parser_backed else 0.88
        if confidence <= 0:
            confidence = 0.88

        block = _find_any_graph_block_for_object(
            valid_offsets=valid_offsets,
            invalid_offsets=invalid_offsets,
            valid_blocks=valid_blocks,
            invalid_blocks=invalid_blocks,
            start=start,
            end=end,
            allow_invalid=True,
        )
        malformed = block is not None and block.error is not None
        target_dir = _book_dir(graphs_root, obj.source_object_path)
        target_dir.mkdir(parents=True, exist_ok=True)

        graph_metadata: dict[str, object] = {
            "graph_name": obj.name,
            "source_object_path": obj.source_object_path,
            "object_kind": obj.object_kind,
            "object_offset": obj.offset,
            "object_length": obj.length,
            "window_start": start,
            "window_end": end,
            "preview_status": "absent" if block is None else "present",
        }
        native_graph_metadata = opj_window_metadata.get(obj.name)
        if parser_backed:
            graph_metadata["unsupported_graph_attributes"] = list(
                _NATIVE_UNSUPPORTED_GRAPH_ATTRIBUTES
                if native_graph_metadata is not None
                else _UNSUPPORTED_GRAPH_ATTRIBUTES
            )
        if native_graph_metadata is not None:
            graph_metadata["parsed_graph_attributes"] = list(_PARSED_GRAPH_ATTRIBUTES)
            graph_metadata["opj_semantics"] = native_graph_metadata.to_dict()

        preview_target = target_dir / f"graph.{block.extension}" if block is not None else None
        metadata_target = target_dir / "graph.bin"
        preview_status = "skipped"
        preview_error: str | None = "no_embedded_image_block"
        graph_status = "partial"
        graph_error = "graph_definition_partial" if parser_backed else "graph_definition_unverified"
        graph_confidence = confidence if parser_backed else 0.45

        if block is None:
            graph_metadata["preview_found"] = False
            graph_metadata["preview_error"] = "no_embedded_image_block"
            graph_metadata["preview_unavailable"] = True
            preview_kind = _graph_preview_kind(
                object_kind=obj.object_kind,
                malformed=False,
                has_preview=False,
            )
            preview_confidence = _graph_preview_confidence(
                parser_backed=parser_backed,
                malformed=False,
                parser_confidence=confidence,
            )
            if native_graph_metadata is not None:
                graph_confidence = max(graph_confidence, 0.95)
            preview_status = "skipped"
            preview_error = "no_embedded_image_block"
        else:
            preview_kind = _graph_preview_kind(
                object_kind=obj.object_kind,
                malformed=malformed,
                has_preview=True,
            )
            preview_confidence = _graph_preview_confidence(
                parser_backed=parser_backed,
                malformed=malformed,
                parser_confidence=confidence,
            )
            if (
                owned_image_blocks is not None
                and obj.object_kind in graph_object_kinds
                and block not in owned_image_blocks
            ):
                owned_image_blocks.append(block)
            graph_metadata["preview_found"] = True
            graph_metadata["preview_extension"] = block.extension
            graph_metadata["preview_kind"] = block.kind
            graph_metadata["preview_offset"] = block.offset
            graph_metadata["preview_length"] = block.length
            preview_payload: bytes | None = None
            if block.error is None:
                preview_payload = (
                    file_data[block.offset : block.offset + block.length]
                    if file_data is not None
                    else dump_range(input_path, block.offset, block.length)
                )
                if not is_displayable_image_block(preview_payload, block.kind):
                    graph_metadata["preview_error"] = "image_payload_unreadable"
                    preview_error = "image_payload_unreadable"
                    preview_payload = None
            else:
                graph_metadata["preview_error"] = block.error
                preview_error = block.error
                if block.kind == "jpeg":
                    graph_metadata["preview_recovery_error"] = block.error
                    if block.length > _MALFORMED_GRAPH_PREVIEW_MAX_BYTES:
                        graph_metadata["preview_error"] = "jpeg_salvage_too_large"
                        preview_error = graph_metadata["preview_error"]
                        graph_metadata["preview_recovery_skipped"] = True
                        graph_metadata["preview_recovery_size_limit"] = _MALFORMED_GRAPH_PREVIEW_MAX_BYTES
                    elif block.length <= _MALFORMED_GRAPH_PREVIEW_MAX_BYTES:
                        preview_payload = (
                            file_data[block.offset : block.offset + block.length]
                            if file_data is not None
                            else dump_range(input_path, block.offset, block.length)
                        )
                        if not _is_jpeg_salvage_candidate(preview_payload):
                            preview_payload = None

            if preview_target is not None and preview_target.exists() and preview_payload is not None and not force:
                preview_status = "skipped"
                preview_error = "target_exists"
            elif (
                preview_payload is not None
                and preview_target is not None
                and (
                    graph_metadata.get("preview_error") is None
                    or (block is not None and block.kind == "jpeg" and _is_jpeg_salvage_candidate(preview_payload))
                )
            ):
                preview_target.write_bytes(preview_payload)
                if block is not None and block.kind == "jpeg" and block.error is not None:
                    # Keep preview error to preserve unsupported-structure evidence.
                    preview_status = "partial"
                    preview_error = block.error
                else:
                    preview_status = "extracted"
                    preview_error = None
                exported += 1
            else:
                preview_status = "partial"
                metadata_error = graph_metadata.get("preview_error")
                preview_error = metadata_error if isinstance(metadata_error, str) else None

        manifest_preview_path = (
            _manifest_path(preview_target, manifest_root or out_dir)
            if preview_target is not None and preview_target.exists()
            else None
        )

        metadata_written, metadata_path = _write_graph_metadata(
            metadata_target,
            graph_metadata,
            force=force,
        )
        manifest_metadata_path = _manifest_path(Path(metadata_path), manifest_root or out_dir)

        manifest.add_item(
            ManifestItem(
                kind=preview_kind,
                name=obj.name,
                status=preview_status,
                confidence=preview_confidence,
                discovery_type=discovery_type,
                heuristic=heuristic,
                path=manifest_preview_path,
                source_object_path=obj.source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                content_class="absent" if block is None else "image",
                preview_status="absent" if block is None else "present",
                completeness=(
                    "complete" if preview_status == "extracted" or (block is None and parser_backed) else "partial"
                ),
                verification="exact" if block is not None or parser_backed else "unverified",
                error=preview_error,
            )
        )

        manifest.add_item(
            ManifestItem(
                kind="graph",
                name=obj.name,
                status=graph_status,
                confidence=graph_confidence,
                discovery_type=discovery_type,
                heuristic=heuristic,
                path=manifest_metadata_path,
                source_object_path=obj.source_object_path,
                object_kind=obj.object_kind,
                preview_status="absent" if block is None else "present",
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                completeness="partial",
                verification="exact" if parser_backed else "unverified",
                error=graph_error,
            )
        )

        manifest.add_item(
            ManifestItem(
                kind="graph_metadata",
                name=f"{obj.name}_metadata",
                status="extracted" if metadata_written else "skipped",
                confidence=(
                    preview_confidence if metadata_written and parser_backed else (0.9 if metadata_written else 0.4)
                ),
                discovery_type=discovery_type,
                heuristic=heuristic,
                path=manifest_metadata_path,
                source_object_path=obj.source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                error=None if metadata_written else "target_exists",
            )
        )

    return exported
