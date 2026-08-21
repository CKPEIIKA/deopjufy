"""Extractors for origin object-style content and inventories."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from types import ModuleType

from deopjufier import opj as opj_parser
from deopjufier import opju as opju_parser
from deopjufier.blocks import ImageBlock, find_all_blocks
from deopjufier.extract.discovery_helpers import (
    book_dir as _book_dir,
)
from deopjufier.extract.discovery_helpers import (
    gap_ranges as _gap_ranges,
)
from deopjufier.extract.metadata_helpers import (
    infer_note_format as _infer_note_format,
)
from deopjufier.extract.metadata_helpers import (
    write_note_file as _write_note_file,
)
from deopjufier.extract.objects_extractors.function_recovery import extract_encoded_opju_function_window
from deopjufier.extract.objects_extractors.report_recovery import (
    extract_encoded_opju_report_window,
    is_encoded_opju_report_candidate,
)
from deopjufier.extract.path_helpers import (
    manifest_relative_path as _manifest_path,
)
from deopjufier.extract.raw_regions import (
    RAW_REGION_CLASS_EMBEDDED_IMAGE,
    RAW_REGION_CLASS_TEXT,
    RawRegionClassification,
    _sample_region_bytes,
    classify_raw_regions,
    unsupported_region_classes,
)
from deopjufier.inventory import (
    MAGIC_OPJ,
    OriginObject,
    ParserBackedDiscoveryRecord,
    iter_object_windows,
    parse_opj_function_metadata,
    parse_opj_function_payload,
    parse_opju_records,
)
from deopjufier.io import dump_range
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opj import OpjProjectNode, OpjTreeNode, parse_opj_project_nodes, parse_opj_tree_nodes
from deopjufier.opju.common import OPJU_REGION_KIND_TAGGED_BINARY
from deopjufier.opju.tagged import OpjuTaggedEnvelope, iter_tagged_scalars, iter_tagged_strings
from deopjufier.opju.walker import OpjuWalkElement
from deopjufier.strings import (
    _iter_ascii_strings_from_bytes,
    _iter_utf16_strings_from_bytes,
)

parse_opj_note_sections = opj_parser.parse_opj_note_sections


def _objects_module() -> ModuleType:
    return importlib.import_module("deopjufier.extract.objects")


def _project_tree_path(base: Path, node_path: str) -> Path:
    """Build a stable node directory path under ``base``."""
    parts = tuple(part for part in node_path.split("/") if part)
    return base.joinpath(*parts)


def _project_tree_payload(node: OpjProjectNode | OpjTreeNode) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": node.name,
        "path": node.path,
        "start_offset": node.start_offset,
        "end_offset": node.end_offset,
        "length": node.end_offset - node.start_offset,
    }
    if isinstance(node, OpjProjectNode):
        payload.update(
            {
                "kind": node.kind,
                "parent_path": node.parent_path,
                "object_id": node.object_id,
                "file_type": node.file_type,
                "active": node.active,
                "creation_time": node.creation_time,
                "modification_time": node.modification_time,
                "parser_rule": "opj_binary_project_tree",
                "confidence": 0.98,
            }
        )
    else:
        payload.update(
            {
                "node_id": node.node_id,
                "parent_node_id": node.parent_node_id,
                "parser_rule": node.parser_rule,
                "confidence": node.confidence,
            }
        )
    return payload


def _project_tree_node_contract(node: OpjProjectNode | OpjTreeNode) -> tuple[float, str, int]:
    if isinstance(node, OpjProjectNode):
        return 0.98, "opj_binary_project_tree", node.end_offset - node.start_offset
    return node.confidence, node.parser_rule, node.length


def _parse_parser_note_sections(file_data: bytes, *, path: Path | None = None):
    parser_api = _objects_module()
    parser_func = getattr(parser_api, "parse_opj_note_sections", parse_opj_note_sections)
    del path
    return parser_func(file_data)


def _write_function_metadata_sidecar(
    target: Path,
    *,
    function_name: str,
    function_formula: str | None,
    function_range: tuple[str, str] | None,
    function_total_points: int | None,
    parser_rule: str,
    parser_confidence: float,
    source_object_path: str,
    payload_start: int,
    payload_end: int,
    force: bool,
) -> tuple[bool, str]:
    payload: dict[str, object] = {
        "function_name": function_name,
        "source_object_path": source_object_path,
        "payload_start": payload_start,
        "payload_end": payload_end,
        "payload_length": max(0, payload_end - payload_start),
        "parser_rule": parser_rule,
        "parser_confidence": parser_confidence,
    }
    if function_formula is not None:
        payload["function_formula"] = function_formula
    if function_range is not None:
        payload["function_range"] = list(function_range)
    if function_total_points is not None:
        payload["function_total_points"] = function_total_points

    sidecar = target.with_name("function.metadata.json")
    if sidecar.exists() and not force:
        return False, sidecar.as_posix()

    with sidecar.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(payload, fp, indent=2, sort_keys=True)
        fp.write("\n")
    return True, sidecar.as_posix()


def _dedupe(value: list[str]) -> list[str]:
    """Return deterministic values with duplicates removed while preserving order."""
    seen: set[str] = set()
    output: list[str] = []
    for item in value:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _trim_trailing_object_markers(lines: list[str], own_name: str, object_names: set[str]) -> list[str]:
    """Drop trailing lines that look like neighboring object starts.

    When windows are inferred from offsets, the next object's marker can leak into
    the previous extraction range. This trims only trailing marker-like rows.
    """
    text_lines = list(lines)
    while text_lines:
        candidate = text_lines[-1].strip()
        if candidate in {"", own_name}:
            break
        if candidate in object_names:
            text_lines.pop()
            continue
        break
    return text_lines


def _classify_note_payload_type(text: str) -> str:
    if not text:
        return "unknown_text"

    lowered = text.lower()
    if "<html" in lowered or "</html>" in lowered:
        return "html_like"

    if any(marker in text for marker in ("# ", "## ", "### ", "- ", "* ", "```", "> ")):
        return "markdown_like"

    return "plain_text"


def _unknown_gap_ranges(
    input_path: Path,
    min_size: int,
    image_blocks: list[ImageBlock] | None = None,
    objects: list[OriginObject] | None = None,
) -> list[tuple[int, int]]:
    """Return byte ranges not covered by known blocks or object windows."""
    file_size = input_path.stat().st_size
    if file_size <= 0:
        return []

    discovered_blocks = find_all_blocks(input_path) if image_blocks is None else image_blocks
    covered_ranges = [(block.offset, block.length) for block in discovered_blocks]
    object_windows = iter_object_windows(objects, file_size) if objects is not None else []
    covered_ranges.extend((start, max(0, end - start)) for _, start, end in object_windows if end > start)
    return _gap_ranges(file_size, covered_ranges, min_size=min_size)


def _is_opj_like(file_data: bytes | None, input_path: Path) -> bool:
    suffix = input_path.suffix.lower()
    if suffix == ".opju":
        return False
    if suffix == ".opj":
        return True
    if file_data is not None:
        return file_data.startswith(MAGIC_OPJ)
    return input_path.read_bytes()[: len(MAGIC_OPJ)].startswith(MAGIC_OPJ)


def _unsupported_object_collection_item(
    manifest: Manifest,
    *,
    kind: str,
    collection_name: str,
    collection_path: str,
    out_dir: Path,
    manifest_root: Path,
    error: str,
    range_start: int | None = None,
    range_end: int | None = None,
    source_object_path: str | None = None,
) -> None:
    collection_dir = out_dir / collection_path
    collection_dir.mkdir(parents=True, exist_ok=True)
    collection_source_path = source_object_path if source_object_path else f"{collection_name}_collection"
    manifest.add_item(
        ManifestItem(
            kind=kind,
            name=f"{collection_name}_collection",
            status="unsupported",
            confidence=0.7,
            discovery_type="parser_backed_hint",
            heuristic=False,
            path=_manifest_path(collection_dir, manifest_root),
            source_object_path=collection_source_path,
            error=error,
            range_start=range_start,
            range_end=range_end,
        )
    )


def _derive_opju_note_unsupported_range(
    file_data: bytes | None,
    *,
    input_path: Path,
    note_objects: list[OriginObject],
) -> tuple[int, int, str | None] | None:
    spans: list[tuple[int, int, str | None]] = []

    for obj in note_objects:
        if obj.object_kind not in {"note", "opju_note_payload"}:
            continue
        if obj.offset < 0 or obj.length <= 0:
            continue
        spans.append((obj.offset, obj.offset + obj.length, obj.source_object_path))

    data = file_data
    if data is None:
        data = input_path.read_bytes()
    if not data:
        return None

    try:
        parsed = parse_opju_records(data, path=input_path)
    except Exception:
        parsed = None

    if parsed is not None:
        for region in parsed.regions:
            if region.kind in {
                opju_parser.OPJU_REGION_KIND_CONTAINER,
                opju_parser.OPJU_REGION_KIND_FOLDER_DIRECTORY,
                opju_parser.OPJU_REGION_KIND_PAGE_DIRECTORY,
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
    source_candidates = sorted(source for start, _, source in spans if start == range_start and source is not None)
    if not source_candidates:
        source_candidates = sorted(source for source in sources if source is not None)
    source_object_path = source_candidates[0] if source_candidates else None
    return range_start, range_end, source_object_path


def _classify_unknown_gap_regions(
    file_data: bytes,
    ranges: list[tuple[int, int]],
    image_blocks: list[ImageBlock] | None = None,
) -> list[RawRegionClassification]:
    image_spans = [(block.offset, block.length) for block in image_blocks] if image_blocks is not None else []
    return classify_raw_regions(file_data, ranges, image_blocks=image_spans)


def _emit_unsupported_region_warnings(manifest: Manifest, region_classes: set[str], *, supported: set[str]) -> None:
    for region_class in sorted(unsupported_region_classes(list(region_classes)) - supported):
        message = f"Unsupported raw region class discovered: {region_class}"
        if message not in manifest.warnings:
            manifest.add_warning(message)


def _parser_note_sections(
    file_data: bytes | None,
    input_path: Path | None,
) -> dict[tuple[int, str], tuple[int, str]]:
    if file_data is None:
        return {}
    return {
        (section.offset, section.name): (section.length, section.text)
        for section in _parse_parser_note_sections(
            file_data,
            path=input_path,
        )
        if section.text
    }


def _parser_function_objects(
    file_data: bytes | None,
    input_path: Path | None,
) -> list[ParserBackedDiscoveryRecord]:
    if file_data is None:
        return []
    return opj_parser.recover_parser_function_records(file_data)


def _write_function_payload(
    function_txt_path: Path,
    function_payload: str,
    *,
    force: bool,
) -> bool:
    payload_path = function_txt_path.with_name("function.payload.txt")
    if payload_path.exists() and not force:
        return False

    payload_path.write_text(function_payload, encoding="utf-8", newline="\n")
    return True


def _text_issue_counts(payload: bytes) -> tuple[str, int, int]:
    decoded = payload.decode("utf-8", errors="replace")
    replacement_count = decoded.count("\ufffd")
    control_count = sum(1 for char in decoded if char not in "\n\r\t" and (ord(char) < 0x20 or ord(char) == 0x7F))
    return decoded, replacement_count, control_count


def _tagged_envelopes_by_start(
    data: bytes,
    walk_elements: Iterable[OpjuWalkElement] | None,
    accepted_starts: set[int],
) -> dict[int, OpjuTaggedEnvelope]:
    envelopes: dict[int, OpjuTaggedEnvelope] = {}
    for element in walk_elements or ():
        if element.kind != OPJU_REGION_KIND_TAGGED_BINARY or element.start_offset not in accepted_starts:
            continue
        payload = data[element.start_offset : element.end_offset]
        envelopes[element.start_offset] = OpjuTaggedEnvelope(
            family=str(element.metadata["family"]),
            start_offset=element.start_offset,
            end_offset=element.end_offset,
            sha256=sha256(payload).hexdigest(),
            strings=iter_tagged_strings(payload, source_start=element.start_offset),
            scalars=iter_tagged_scalars(payload, source_start=element.start_offset),
            semantic_status=str(element.metadata["semantic_status"]),
        )
    return envelopes


def extract_functions(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    objects: list[OriginObject] | None = None,
    allow_parser_recovery: bool | None = None,
    include_provenance: bool = False,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
) -> int:
    """Extract best-effort function-object payload slices."""
    discovered_objects = list(objects or [])
    function_objects = [obj for obj in discovered_objects if obj.object_kind == "function"]
    parser_backed_function_objects = [obj for obj in function_objects if obj.parser_confirmed]
    is_opj = _is_opj_like(file_data, input_path)
    if not is_opj:
        if parser_backed_function_objects:
            function_objects = parser_backed_function_objects
    elif not function_objects and allow_parser_recovery:
        function_objects = _parser_function_objects(file_data, input_path)
    elif not function_objects and allow_parser_recovery is None:
        allow_parser_recovery = False

    if allow_parser_recovery is None:
        allow_parser_recovery = False
    out_dir.mkdir(parents=True, exist_ok=True)
    functions_root = out_dir / "functions"
    read_data = file_data is not None
    file_size = input_path.stat().st_size

    if not function_objects:
        if allow_parser_recovery:
            manifest.add_item(
                ManifestItem(
                    kind="function",
                    name="function_collection",
                    status="unsupported",
                    confidence=0.4,
                    discovery_type="heuristic_object_scan",
                    heuristic=True,
                    path=_manifest_path(functions_root, manifest_root or out_dir),
                    source_object_path="function_collection",
                    error="no_function_objects",
                )
            )
        return 0

    window_function_objects = list(function_objects)
    if selected_object_keys is not None:
        function_objects = [
            obj for obj in function_objects if (obj.offset, obj.name, obj.source_object_path) in selected_object_keys
        ]
    exported = 0
    all_object_names = {obj.name for obj in discovered_objects}
    all_object_names.update(obj.name for obj in function_objects)
    function_windows = {
        (window_obj.offset, window_obj.name, window_obj.source_object_path): (start, end)
        for window_obj, start, end in iter_object_windows(
            sorted(window_function_objects, key=lambda item: item.offset),
            file_size,
        )
    }
    for obj in sorted(function_objects, key=lambda item: item.offset):
        start, end = function_windows.get(
            (obj.offset, obj.name, obj.source_object_path),
            (obj.offset, obj.offset + max(0, obj.length)),
        )
        parser_backed = obj.parser_confirmed
        parser_rule = getattr(obj, "parser_rule", "")
        parser_rule_lower = parser_rule.lower()
        is_opj_parser_rule = parser_rule_lower.startswith("opj")
        discovery_type = "parser_window" if parser_backed else "heuristic_object_scan"
        confidence = getattr(obj, "parser_confidence", 0.5)
        if confidence <= 0:
            confidence = 0.5

        target_dir = _book_dir(functions_root, obj.source_object_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "function.txt"

        if target.exists() and not force:
            manifest.add_item(
                ManifestItem(
                    kind="function",
                    name=obj.name,
                    status="skipped",
                    confidence=confidence,
                    discovery_type=discovery_type,
                    heuristic=not parser_backed,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=obj.source_object_path,
                    object_kind=obj.object_kind,
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    error="target_exists",
                )
            )
            continue

        raw_slice = file_data[start:end] if read_data else dump_range(input_path, start, end - start)
        function_metadata = (
            parse_opj_function_metadata(raw_slice, function_name=obj.name) if is_opj_parser_rule else None
        )
        text, replacement_count, control_count = _text_issue_counts(raw_slice)
        if not is_opj and parser_backed and (replacement_count or control_count):
            recovered = extract_encoded_opju_function_window(
                raw_slice,
                target_dir,
                manifest,
                object_name=obj.name,
                source_object_path=obj.source_object_path,
                source_start=start,
                source_end=end,
                manifest_root=manifest_root or out_dir,
                force=force,
                include_provenance=include_provenance,
            )
            if recovered is not None:
                exported += recovered
                continue
            raw_target = target.with_name("function.raw.bin")
            if raw_target.exists() and not force:
                status = "skipped"
                error = "target_exists"
            else:
                raw_target.write_bytes(raw_slice)
                status = "partial"
                error = "non_lossless_function_text"
            manifest.add_item(
                ManifestItem(
                    kind="function",
                    name=obj.name,
                    status=status,
                    confidence=0.4,
                    discovery_type=discovery_type,
                    heuristic=False,
                    path=_manifest_path(raw_target, manifest_root or out_dir),
                    source_object_path=obj.source_object_path,
                    object_kind=obj.object_kind,
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    extraction_method="raw_region_preservation",
                    completeness="partial",
                    replacement_character_count=replacement_count,
                    control_character_count=control_count,
                    error=error,
                )
            )
            if status == "partial":
                exported += 1
            continue
        text_rows = [line for line in text.replace("\r", "").split("\n") if line.strip()]
        while text_rows and text_rows[-1] in all_object_names and text_rows[-1] != obj.name:
            text_rows.pop()
        text = "\n".join(text_rows)
        target.write_text(text, encoding="utf-8", newline="\n")
        if parser_backed and is_opj_parser_rule:
            function_payload = parse_opj_function_payload(raw_slice)
            if function_payload:
                _write_function_payload(target, function_payload, force=force)
        manifest.add_item(
            ManifestItem(
                kind="function",
                name=obj.name,
                status="extracted" if text_rows else "partial",
                confidence=confidence if text_rows else 0.4,
                discovery_type=discovery_type,
                heuristic=not parser_backed,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=obj.source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                function_name=function_metadata.name if function_metadata else obj.name,
                function_formula=function_metadata.formula if function_metadata else None,
                function_range=function_metadata.function_range if function_metadata else None,
                function_total_points=(function_metadata.total_points if function_metadata else None),
                rows=len(text_rows),
                columns=max((len(line.split()) for line in text_rows), default=0),
            )
        )
        if parser_backed and is_opj_parser_rule and function_metadata is not None:
            function_metadata_written, function_metadata_path = _write_function_metadata_sidecar(
                target,
                function_name=function_metadata.name,
                function_formula=function_metadata.formula,
                function_range=function_metadata.function_range,
                function_total_points=function_metadata.total_points,
                parser_rule=getattr(obj, "parser_rule", "opj_function_metadata"),
                parser_confidence=confidence,
                source_object_path=obj.source_object_path,
                payload_start=obj.offset,
                payload_end=obj.offset + obj.length,
                force=force,
            )
            manifest.add_item(
                ManifestItem(
                    kind="function_metadata",
                    name=f"{obj.name}_metadata",
                    status="extracted" if function_metadata_written else "skipped",
                    confidence=0.95 if function_metadata_written else 0.85,
                    discovery_type=discovery_type,
                    heuristic=not parser_backed,
                    path=_manifest_path(Path(function_metadata_path), manifest_root or out_dir),
                    source_object_path=obj.source_object_path,
                    object_kind=obj.object_kind,
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    error=None if function_metadata_written else "target_exists",
                )
            )
        if text_rows:
            exported += 1

    return exported


def extract_notes(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    objects: list[OriginObject] | None = None,
    selected_names: set[str] | None = None,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
    include_provenance: bool = False,
    walk_elements: Iterable[OpjuWalkElement] | None = None,
) -> int:
    """Extract note-like objects and emit note payloads as plain text/Markdown/HTML."""
    out_dir.mkdir(parents=True, exist_ok=True)
    discovered_objects = list(objects or [])
    supported_note_kinds = {"note", "opju_note_payload"}
    is_opj = _is_opj_like(file_data, input_path)
    if is_opj:
        note_objects = [obj for obj in discovered_objects if obj.object_kind == "note"]
    else:
        note_objects = [obj for obj in discovered_objects if obj.object_kind in supported_note_kinds]
    parser_note_sections_by_location = _parser_note_sections(file_data, input_path) if is_opj else {}
    unsupported_note_range = (
        _derive_opju_note_unsupported_range(
            file_data,
            input_path=input_path,
            note_objects=note_objects,
        )
        if not is_opj
        else None
    )
    unsupported_range = (
        (
            unsupported_note_range[0],
            unsupported_note_range[1],
        )
        if unsupported_note_range is not None
        else None
    )
    unsupported_source = unsupported_note_range[2] if unsupported_note_range is not None else None
    if not is_opj:
        parser_only_note_objects = [obj for obj in note_objects]
        for (offset, name), (_length, text) in parser_note_sections_by_location.items():
            if selected_names is not None and name not in selected_names:
                continue
            parser_only_note_objects.append(
                ParserBackedDiscoveryRecord(
                    offset=offset,
                    name=name,
                    length=max(1, len(text.encode("utf-8"))),
                    object_kind="note",
                    source_object_path=f"Note/{name}",
                    parser_rule="opj_note_section",
                    parser_confidence=0.95,
                )
            )
        if parser_only_note_objects:
            note_objects = parser_only_note_objects
        else:
            _unsupported_object_collection_item(
                manifest,
                kind="note",
                collection_name="note",
                collection_path="notes",
                out_dir=out_dir,
                manifest_root=manifest_root or out_dir,
                error="no_note_objects" if not note_objects else "no_parser_backed_note_records",
                range_start=unsupported_range[0] if unsupported_range else None,
                range_end=unsupported_range[1] if unsupported_range else None,
                source_object_path=unsupported_source,
            )
            return 0

    read_data = file_data is not None
    file_size = input_path.stat().st_size
    if is_opj:
        for (
            offset,
            name,
        ), (
            length,
            _text,
        ) in parser_note_sections_by_location.items():
            if selected_names is not None and name not in selected_names:
                continue
            if any(obj.offset == offset and obj.name == name for obj in note_objects):
                continue
            note_objects.append(
                ParserBackedDiscoveryRecord(
                    offset=offset,
                    name=name,
                    length=max(1, length),
                    object_kind="note",
                    source_object_path=f"Note/{name}",
                    parser_rule="opj_note_section",
                    parser_confidence=0.95,
                )
            )

    if not note_objects:
        _unsupported_object_collection_item(
            manifest,
            kind="note",
            collection_name="note",
            collection_path="notes",
            out_dir=out_dir,
            manifest_root=manifest_root or out_dir,
            error="no_note_objects",
            range_start=unsupported_range[0] if unsupported_range else None,
            range_end=unsupported_range[1] if unsupported_range else None,
            source_object_path=unsupported_source,
        )
        return 0

    window_note_objects = list(note_objects)
    if selected_object_keys is not None:
        note_objects = [
            obj for obj in note_objects if (obj.offset, obj.name, obj.source_object_path) in selected_object_keys
        ]
    exported = 0
    notes_root = out_dir / "notes"

    all_object_names = {obj.name for obj in discovered_objects} | {obj.name for obj in note_objects}
    note_windows = {
        (window_obj.offset, window_obj.name, window_obj.source_object_path): (start, end)
        for window_obj, start, end in iter_object_windows(
            sorted(window_note_objects, key=lambda item: item.offset),
            file_size,
        )
    }
    encoded_report_ends = {
        end
        for obj in note_objects
        if (window := note_windows.get((obj.offset, obj.name, obj.source_object_path))) is not None
        for start, end in (window,)
        if file_data is not None and is_encoded_opju_report_candidate(file_data[start:end])
    }
    tagged_by_start = (
        _tagged_envelopes_by_start(file_data or b"", walk_elements, encoded_report_ends)
        if not is_opj and encoded_report_ends
        else {}
    )
    for obj in sorted(note_objects, key=lambda item: item.offset):
        start, end = note_windows.get(
            (obj.offset, obj.name, obj.source_object_path),
            (obj.offset, obj.offset + max(0, obj.length)),
        )
        parser_note_entry = parser_note_sections_by_location.get((obj.offset, obj.name))
        parser_note_text = parser_note_entry[1] if parser_note_entry is not None else None
        parser_backed = obj.parser_confirmed
        parser_backed_discovery_type = getattr(obj, "parser_rule", None) or (
            "opj_note_section" if parser_backed else None
        )
        target_dir = _book_dir(notes_root, obj.source_object_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        if parser_note_text is not None:
            note_text = parser_note_text
            ext = _infer_note_format(note_text)
            payload_type = _classify_note_payload_type(note_text)
            discovery_type = "opj_note_section"
            confidence = 0.95
            heuristic = False
            note_rows = [line for line in note_text.splitlines() if line]
        elif parser_backed:
            raw_slice = file_data[start:end] if read_data else dump_range(input_path, start, end - start)
            if not is_opj:
                adjacent_state = tagged_by_start.get(end)
                recovered = extract_encoded_opju_report_window(
                    raw_slice,
                    _book_dir(out_dir / "reports", obj.source_object_path),
                    manifest,
                    object_name=obj.name,
                    source_object_path=obj.source_object_path,
                    source_start=start,
                    source_end=end,
                    manifest_root=manifest_root or out_dir,
                    force=force,
                    include_provenance=include_provenance,
                    adjacent_state=adjacent_state,
                    adjacent_state_bytes=(
                        file_data[adjacent_state.start_offset : adjacent_state.end_offset]
                        if file_data is not None and adjacent_state is not None
                        else None
                    ),
                )
                if recovered is not None:
                    exported += recovered
                    continue
            note_text, replacement_count, control_count = _text_issue_counts(raw_slice)
            if not is_opj and (replacement_count or control_count):
                raw_target = target_dir / "note.raw.bin"
                status, error = (
                    ("skipped", "target_exists")
                    if raw_target.exists() and not force
                    else ("partial", "non_lossless_note_text")
                )
                if status == "partial":
                    raw_target.write_bytes(raw_slice)
                manifest.add_item(
                    ManifestItem(
                        kind="note",
                        name=obj.name,
                        status=status,
                        confidence=0.4,
                        discovery_type=parser_backed_discovery_type,
                        heuristic=False,
                        path=_manifest_path(raw_target, manifest_root or out_dir),
                        source_object_path=obj.source_object_path,
                        object_kind=obj.object_kind,
                        range_start=start,
                        range_end=end,
                        extraction_method="raw_region_preservation",
                        completeness="partial",
                        replacement_character_count=replacement_count,
                        control_character_count=control_count,
                        error=error,
                    )
                )
                exported += int(status == "partial")
                continue
            note_rows = [line for line in note_text.splitlines() if line]
            note_text = "\n".join(note_rows)
            ext = _infer_note_format(note_text)
            payload_type = _classify_note_payload_type(note_text)
            discovery_type = parser_backed_discovery_type
            confidence = max(getattr(obj, "parser_confidence", 0.0), 0.6)
            heuristic = False
        else:
            raw_slice = file_data[start:end] if read_data else dump_range(input_path, start, end - start)
            note_rows = [line for line in raw_slice.decode("utf-8", errors="replace").splitlines() if line]
            note_rows = _trim_trailing_object_markers(note_rows, obj.name, all_object_names)
            note_text = "\n".join(note_rows)
            ext = _infer_note_format(note_text)
            payload_type = _classify_note_payload_type(note_text)
            discovery_type = "heuristic_object_scan"
            confidence = 0.65 if note_rows else 0.3
            heuristic = True

        if not is_opj:
            ext = "txt"

        target = target_dir / f"note.{ext}"
        if target.exists() and not force:
            manifest.add_item(
                ManifestItem(
                    kind="note",
                    name=obj.name,
                    status="skipped",
                    confidence=confidence,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=obj.source_object_path,
                    object_kind=obj.object_kind,
                    offset=obj.offset,
                    length=obj.length,
                    range_start=start,
                    range_end=end,
                    error="target_exists",
                )
            )
            continue

        rows_written = _write_note_file(target, note_text)
        manifest.add_item(
            ManifestItem(
                kind="note",
                name=obj.name,
                status="extracted" if rows_written > 0 else "partial",
                confidence=confidence if rows_written > 0 else 0.3,
                discovery_type=discovery_type,
                heuristic=heuristic,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=obj.source_object_path,
                object_kind=obj.object_kind,
                offset=obj.offset,
                length=obj.length,
                range_start=start,
                range_end=end,
                rows=rows_written,
                note_payload_type=payload_type,
                columns=1,
            )
        )
        if rows_written > 0:
            exported += 1

    return exported


__all__ = [name for name in globals() if not name.startswith("__")]
