"""Session-level state for repeated extraction operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deopjufier.blocks import ImageBlock, find_all_blocks
from deopjufier.detect import DetectedFile, detect_file
from deopjufier.discovery import (
    _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES,
    _OPJ_PARSER_BOUNDARY_MAX_BYTES,
)
from deopjufier.extract.discovery_helpers import gap_ranges as _gap_ranges
from deopjufier.extract.raw_regions import (
    RAW_REGION_CLASS_TEXT,
    RawRegionClassification,
    classify_raw_regions,
)
from deopjufier.extract.tables import scan_numeric_tables_from_file
from deopjufier.inventory import (
    MAGIC_OPJ,
    HeuristicDiscoveryRecord,
    OriginObject,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
    iter_object_windows,
    parse_opj_boundaries,
)
from deopjufier.io import read_cached_bytes, sha256_file
from deopjufier.opju.decoded import OpjuDecodedRegion, iter_opju_decoded_regions
from deopjufier.opju.directory import parse_opju_page_directory
from deopjufier.opju.tagged import (
    OpjuColumnDescriptor,
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
)
from deopjufier.opju.walker import OpjuWalkElement, walk_opju_file

_ObjectCacheKey = tuple[int | None, bool, int | None, bool, tuple[str, ...] | None, int | None]
_TableRowCacheKey = tuple[int, int]
_GapCacheKey = tuple[int, int, tuple[Any, ...], tuple[Any, ...], int, int, int, bool]
_DEFAULT_OPJU_HEURISTIC_KIND_LIMIT = 24
_WORKBOOK_SOURCE_PREFIXES = ("Book", "MBook")
_PNG_TERMINAL_BYTES = 8
_OPJU_DIRECTORY_SEMANTICS = {
    "opju_page_directory_name": ("project_page_directory_entry", "corpus_high"),
    "opju_folder_directory_name": ("project_folder_directory_entry", "corpus_high"),
}


def _raw_dump_name(offset: int, length: int) -> str:
    return f"raw_off_{offset:012d}_len_{length:012d}.bin"


def _raw_dump_crosswalk(
    target_offset: int,
    target_length: int,
    candidate_ranges: list[tuple[int, int]],
) -> list[dict[str, str | int]]:
    if target_length <= 0:
        return []
    target_end = target_offset + target_length
    crosswalk: list[dict[str, str | int]] = []
    for offset, length in candidate_ranges:
        if length <= 0:
            continue
        end = offset + length
        if end <= target_offset or offset >= target_end:
            continue
        crosswalk.append(
            {
                "offset": offset,
                "length": length,
                "name": f"unknown_gap:{offset}:{length}",
                "path": _raw_dump_name(offset, length),
            }
        )
    return crosswalk


def _list_kind_for_origin_object(file_type: str, object_kind: str | None, is_parser_confirmed: bool) -> str:
    """Map parser evidence classes to user-facing list kinds for OPJU.

    Keep legacy `.opj` list item kinds unchanged so existing contracts remain stable.
    """
    if file_type != "opju" or not is_parser_confirmed:
        if file_type == "opju" and not is_parser_confirmed:
            return object_kind or "origin_object"
        return "origin_object"

    if object_kind == "opju_report":
        return "origin_storage_report"
    if object_kind == "worksheet":
        return "worksheet"
    if object_kind == "opju_preview":
        return "image"
    return "origin_object"


def _coalesce_opj_parser_matrix_objects(objects: list[OriginObject]) -> list[OriginObject]:
    """Prefer parser-owned matrix sheets over duplicate book windows and token hints."""
    parser_matrices = [item for item in objects if item.object_kind == "matrix" and item.parser_confirmed]
    if not parser_matrices:
        return objects

    child_parent_names = {
        parts[-2]
        for item in parser_matrices
        for parts in [item.source_object_path.split("/")]
        if len(parts) >= 2 and parts[-1] == item.name and parts[-2] != item.name
    }
    return [
        item
        for item in objects
        if item.object_kind != "matrix" or (item.parser_confirmed and item.name not in child_parent_names)
    ]


def _normalize_opju_parser_object_kind(object_kind: str | None) -> str | None:
    if object_kind != "opju_raw_payload":
        return object_kind
    return "meta"


def _filter_parser_required_opju_objects(objects: list[OriginObject], object_kind: str) -> list[OriginObject]:
    """For OPJU outputs, suppress unsupported heuristic-only records of a kind."""
    parser_objects = [obj for obj in objects if obj.object_kind == object_kind and obj.parser_confirmed]
    if parser_objects:
        return [obj for obj in objects if obj.object_kind != object_kind or obj.parser_confirmed]
    return [obj for obj in objects if obj.object_kind != object_kind]


def _attach_opju_page_previews(
    items: list[dict[str, object]],
    image_blocks: list[ImageBlock],
    data: bytes,
) -> None:
    """Attach only parser-confirmed page-to-PNG preview relationships."""
    png_by_terminal = {
        block.offset + block.length - _PNG_TERMINAL_BYTES: block
        for block in image_blocks
        if block.kind == "png" and block.valid and block.length >= _PNG_TERMINAL_BYTES
    }
    page_items = {
        (item.get("offset"), item.get("name")): item
        for item in items
        if item.get("object_kind") == "project_page" and not item.get("heuristic", False)
    }
    for record in parse_opju_page_directory(data):
        terminal_offset = record.preview_terminal_offset
        block = png_by_terminal.get(terminal_offset) if terminal_offset is not None else None
        page = page_items.get((record.offset, record.name))
        if block is None or page is None:
            continue
        page.update(
            {
                "preview_offset": block.offset,
                "preview_length": block.length,
                "preview_kind": block.kind,
                "preview_extension": block.extension,
                "preview_source_object_path": f"embedded/{block.kind}/{block.offset}",
            }
        )


@dataclass
class ExtractionSession:
    """Cached extraction context for a single input file."""

    input_path: Path
    detection: DetectedFile
    size_bytes: int
    sha256: str
    _file_data: bytes | None = None
    _image_blocks: list[ImageBlock] | None = None
    _object_cache: dict[_ObjectCacheKey, list[OriginObject]] = field(default_factory=dict)
    _parser_boundaries_cache: list[OriginObject] | None = field(default=None, init=False)
    _items_cache: dict[tuple[bool, bool, bool, int | None, bool], list[dict[str, object]]] = field(default_factory=dict)
    _gap_cache: dict[
        _GapCacheKey,
        tuple[list[tuple[int, int]], list[RawRegionClassification]],
    ] = field(default_factory=dict)
    _table_row_cache: dict[_TableRowCacheKey, list[tuple[int, int, int, list[str]]]] = field(default_factory=dict)
    _opju_walk_cache: list[OpjuWalkElement] | None = field(default=None, init=False)
    _opju_column_descriptors_cache: tuple[OpjuColumnDescriptor, ...] | None = field(default=None, init=False)
    _opju_decoded_regions_cache: tuple[OpjuDecodedRegion, ...] | None = field(default=None, init=False)

    @classmethod
    def from_path(cls, path: Path) -> ExtractionSession:
        """Create a new session from an existing Origin input path."""
        detection = detect_file(path)
        size_bytes = path.stat().st_size
        sha256 = sha256_file(path)
        return cls(
            input_path=path,
            detection=detection,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    def file_data(self) -> bytes:
        """Load file bytes once and reuse them."""
        if self._file_data is None:
            self._file_data = read_cached_bytes(self.input_path)
        return self._file_data

    def image_blocks(self) -> list[ImageBlock]:
        """Lazily discover image-like blocks."""
        if self._image_blocks is None:
            self._image_blocks = find_all_blocks(self.input_path)
        return self._image_blocks

    def opju_walk(self) -> list[OpjuWalkElement]:
        """Return one cached structural walk for the current OPJU input."""
        if self._opju_walk_cache is None:
            self._opju_walk_cache = walk_opju_file(
                self.file_data(),
                column_descriptors=self.opju_column_descriptors(),
                decoded_regions=self.opju_decoded_regions(),
            )
        return [*self._opju_walk_cache]

    def opju_column_descriptors(self) -> tuple[OpjuColumnDescriptor, ...]:
        """Return descriptor records decoded once for this extraction command."""
        if self._opju_column_descriptors_cache is None:
            self._opju_column_descriptors_cache = iter_opju_column_descriptors(self.file_data())
        return self._opju_column_descriptors_cache

    def opju_decoded_regions(self) -> tuple[OpjuDecodedRegion, ...]:
        """Return framed decoded regions parsed once for this extraction command."""
        if self._opju_decoded_regions_cache is None:
            self._opju_decoded_regions_cache = iter_opju_decoded_regions(self.file_data())
        return self._opju_decoded_regions_cache

    def _opju_descriptor_table_items(self) -> list[dict[str, object]]:
        descriptors = self.opju_column_descriptors()
        metadata = iter_opju_column_metadata(self.file_data(), descriptors)
        items: list[dict[str, object]] = []
        for table in group_opju_column_descriptors(descriptors, metadata):
            source_ranges = table.source_ranges
            start = min(source_range["start"] for source_range in source_ranges)
            end = max(source_range["end"] for source_range in source_ranges)
            items.append(
                {
                    "discovery_type": "opju_column_descriptor_table",
                    "kind": "worksheet",
                    "name": table.name,
                    "offset": start,
                    "length": end - start,
                    "confidence": 0.99,
                    "extension": "meta",
                    "source_object_path": table.name,
                    "source_ranges": source_ranges,
                    "heuristic": False,
                    "object_kind": "worksheet",
                    "window_start": start,
                    "window_end": end,
                    "window_length": end - start,
                }
            )
        return items

    def objects(
        self,
        *,
        max_repeats_per_name: int | None = 2,
        include_redundant_tokens: bool = False,
        heuristic_kind_limit: int | None = None,
        collect_heuristics: bool = True,
        allowed_kinds: frozenset[str] | None = None,
        total_limit: int | None = None,
    ) -> list[OriginObject]:
        """Discover and cache origin objects for requested policy."""
        allowed_kinds_key = tuple(sorted(allowed_kinds)) if allowed_kinds is not None else None
        cache_key = (
            max_repeats_per_name,
            include_redundant_tokens,
            heuristic_kind_limit,
            collect_heuristics,
            allowed_kinds_key,
            total_limit,
        )
        cached = self._object_cache.get(cache_key)
        if cached is None:
            cached = discover_origin_objects(
                self.input_path,
                max_repeats_per_name=max_repeats_per_name,
                include_redundant_tokens=include_redundant_tokens,
                heuristic_kind_limit=heuristic_kind_limit,
                collect_heuristics=collect_heuristics,
                allowed_kinds=allowed_kinds,
                total_limit=total_limit,
            )
            self._object_cache[cache_key] = cached
        return [*cached]

    def _normalize_worksheet_source_path(self, source_object_path: str) -> str:
        """Convert generic workbook roots to explicit workbook-level paths."""
        if "/" not in source_object_path:
            return source_object_path

        root, leaf = source_object_path.split("/", 1)
        if root == "Book":
            return source_object_path
        if root == "MBook":
            return source_object_path
        if not (root.startswith("Book") or root.startswith("MBook")):
            return source_object_path
        if not leaf:
            return source_object_path
        if not leaf.startswith(root):
            return source_object_path

        if root.startswith("Book") and root[4:].isdigit():
            workbook = "Book"
        elif root.startswith("MBook") and root[5:].isdigit():
            workbook = "MBook"
        else:
            return source_object_path

        if not workbook:
            return source_object_path
        return f"{workbook}/{leaf}"

    def _parser_boundaries_as_objects(self, file_data: bytes) -> list[OriginObject]:
        if self._parser_boundaries_cache is not None:
            return [*self._parser_boundaries_cache]

        if not file_data.startswith(MAGIC_OPJ):
            self._parser_boundaries_cache = []
            return []

        self._parser_boundaries_cache = [
            ParserBackedDiscoveryRecord(
                offset=boundary.start_offset,
                name=boundary.name,
                length=boundary.length,
                object_kind=boundary.kind,
                source_object_path=boundary.source_object_path,
                parser_rule=boundary.parser_rule,
                parser_confidence=boundary.confidence,
            )
            for boundary in parse_opj_boundaries(
                file_data,
                path=self.input_path,
                disable_heavy_scans=self.size_bytes > _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES,
            )
        ]
        return [*self._parser_boundaries_cache]

    def objects_for_tabular_extraction(
        self,
        file_data: bytes,
        *,
        object_kind: str,
        supplied_objects: list[OriginObject] | None = None,
        prefer_supplied_objects: bool = False,
        trust_supplied_objects_on_large: bool = False,
        rewrite_worksheet_source_path: bool = False,
        filter_non_parser_worksheet_duplicates: bool = True,
    ) -> tuple[list[OriginObject], bool]:
        """Prepare tabular extraction objects and parser-backed recovery policy."""
        data_size = len(file_data)

        if (prefer_supplied_objects and supplied_objects is not None) or (
            trust_supplied_objects_on_large
            and data_size > _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
            and data_size > _OPJ_PARSER_BOUNDARY_MAX_BYTES
            and supplied_objects is not None
            and not any(item.parser_confirmed for item in supplied_objects)
        ):
            objects = list(supplied_objects)
        elif supplied_objects is None:
            objects = self.objects(
                max_repeats_per_name=(None if object_kind == "matrix" else 2),
            )
        elif any(item.parser_confirmed for item in supplied_objects) or (
            data_size <= _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
            and any(item.parser_confirmed for item in supplied_objects)
        ):
            objects = list(supplied_objects)
        else:
            parser_boundaries = self._parser_boundaries_as_objects(file_data)
            objects = parser_boundaries if parser_boundaries else list(supplied_objects)

        if (
            object_kind == "worksheet"
            and filter_non_parser_worksheet_duplicates
            and self.detection.detected_type == "opj"
        ):
            parser_worksheets = [item for item in objects if item.object_kind == "worksheet" and item.parser_confirmed]
            if parser_worksheets:
                objects = [item for item in objects if item.object_kind != "worksheet" or item.parser_confirmed]

        if object_kind == "matrix" and self.detection.detected_type == "opj":
            objects = _coalesce_opj_parser_matrix_objects(objects)

        if self.detection.detected_type == "opju" and object_kind != "worksheet":
            for parser_sensitive_kind in {"matrix", "note", "function", "excel"}:
                objects = _filter_parser_required_opju_objects(objects, parser_sensitive_kind)

        if (
            rewrite_worksheet_source_path
            and object_kind == "worksheet"
            and supplied_objects is None
            and self.detection.detected_type == "opju"
        ):
            objects = [
                OriginObject(
                    offset=item.offset,
                    name=item.name,
                    length=item.length,
                    object_kind=item.object_kind,
                    source_object_path=self._normalize_worksheet_source_path(item.source_object_path),
                    parser_confirmed=item.parser_confirmed,
                )
                for item in objects
            ]

        allow_parser_recovery = (
            file_data.startswith(MAGIC_OPJ)
            and bool(objects)
            and (
                (data_size <= _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES and object_kind != "matrix")
                or any(item.object_kind == object_kind and item.parser_confirmed for item in objects)
            )
        )

        return list(objects), allow_parser_recovery

    def list_items(
        self,
        *,
        include_images: bool = True,
        include_raw_gaps: bool = False,
        include_raw_dump_crosswalk: bool = False,
        heuristic_kind_limit: int | None = None,
        use_default_opju_limit: bool = True,
    ) -> list[dict[str, object]]:
        """Return discoverable items from cached primitives."""
        if heuristic_kind_limit is None and use_default_opju_limit and self.detection.detected_type == "opju":
            heuristic_kind_limit = _DEFAULT_OPJU_HEURISTIC_KIND_LIMIT
        if heuristic_kind_limit is not None and heuristic_kind_limit < 0:
            heuristic_kind_limit = None

        cache_key = (
            include_images,
            include_raw_gaps,
            include_raw_dump_crosswalk,
            heuristic_kind_limit,
            use_default_opju_limit,
        )
        cached = self._items_cache.get(cache_key)
        if cached is not None:
            return [*cached]

        objects = self.objects(
            max_repeats_per_name=None,
            include_redundant_tokens=True,
            heuristic_kind_limit=heuristic_kind_limit,
        )
        if self.detection.detected_type == "opju":
            for parser_sensitive_kind in ("graph", "matrix", "note", "function", "excel"):
                objects = _filter_parser_required_opju_objects(
                    objects,
                    parser_sensitive_kind,
                )
            parser_object_kinds = {obj.object_kind for obj in objects if obj.parser_confirmed and obj.object_kind}
            if parser_object_kinds:
                objects = [obj for obj in objects if obj.parser_confirmed or obj.object_kind not in parser_object_kinds]
        object_windows = list(iter_object_windows(objects, self.size_bytes))
        window_by_obj_id = {id(obj): (start, end) for obj, start, end in object_windows}

        crosswalk_ranges: list[tuple[int, int]] = []
        if include_raw_dump_crosswalk and self.detection.detected_type == "opju":
            image_blocks = self.image_blocks()
            covered_ranges = [(block.offset, block.length) for block in image_blocks]
            covered_ranges.extend((start, max(0, end - start)) for _, start, end in object_windows if end > start)
            if covered_ranges:
                crosswalk_ranges = _gap_ranges(self.size_bytes, covered_ranges, min_size=1)

        items: list[dict[str, object]] = []
        image_blocks = self.image_blocks() if include_images else []
        if include_images:
            for block in image_blocks:
                items.append(
                    {
                        "discovery_type": "carved",
                        "kind": block.kind,
                        "name": f"embedded:{block.offset}:{block.length}",
                        "offset": block.offset,
                        "length": block.length,
                        "confidence": 0.8,
                        "extension": block.extension,
                        "source_object_path": f"embedded/{block.kind}/{block.offset}",
                        "heuristic": True,
                    }
                )
        for obj in objects:
            is_parser_confirmed = not isinstance(obj, HeuristicDiscoveryRecord)
            normalized_object_kind = (
                _normalize_opju_parser_object_kind(obj.object_kind)
                if self.detection.detected_type == "opju"
                else obj.object_kind
            )
            item: dict[str, object] = {
                "discovery_type": (
                    "opj_boundary" if isinstance(obj, ParserBackedDiscoveryRecord) else "object_discovery"
                ),
                "kind": _list_kind_for_origin_object(
                    self.detection.detected_type,
                    obj.object_kind,
                    is_parser_confirmed,
                ),
                "name": obj.name,
                "offset": obj.offset,
                "length": obj.length,
                "confidence": 0.35,
                "extension": "meta",
                "source_object_path": obj.source_object_path,
                "heuristic": isinstance(obj, HeuristicDiscoveryRecord),
                **({"object_kind": normalized_object_kind} if normalized_object_kind else {}),
                **(
                    lambda _window: (
                        {
                            "window_start": _window[0],
                            "window_end": _window[1],
                            "window_length": max(0, _window[1] - _window[0]),
                        }
                        if (window := window_by_obj_id.get(id(obj))) is not None
                        else {}
                    )
                )(window_by_obj_id.get(id(obj))),
            }
            if isinstance(obj, ParserBackedDiscoveryRecord):
                semantic = _OPJU_DIRECTORY_SEMANTICS.get(obj.parser_rule)
                if semantic is not None:
                    item.update(
                        {
                            "structural_name": obj.parser_rule,
                            "semantic_alias": semantic[0],
                            "semantic_confidence": semantic[1],
                        }
                    )
            if include_raw_dump_crosswalk and self.detection.detected_type == "opju":
                if isinstance(obj, ParserBackedDiscoveryRecord) and obj.parser_confidence > 0:
                    item["raw_dump_crosswalk"] = _raw_dump_crosswalk(
                        obj.offset,
                        obj.length,
                        crosswalk_ranges,
                    )
            items.append(item)
        if self.detection.detected_type == "opju":
            items.extend(self._opju_descriptor_table_items())
        if include_raw_gaps:
            parser_objects: list[OriginObject] = [
                obj for obj in objects if isinstance(obj, ParserBackedDiscoveryRecord)
            ]
            use_parser_gaps = self.detection.detected_type == "opj" and bool(parser_objects)
            gap_source_objects = parser_objects if use_parser_gaps else objects
            gap_object_windows = list(iter_object_windows(gap_source_objects, self.size_bytes))
            if not image_blocks:
                image_blocks = self.image_blocks()
            covered_ranges = [(block.offset, block.length) for block in image_blocks]
            covered_ranges.extend((start, max(0, end - start)) for _, start, end in gap_object_windows if end > start)
            gap_ranges, classifications = self.classify_unknown_gaps(
                min_size=1,
                image_blocks=image_blocks,
                objects=gap_source_objects,
                min_rows=2,
                min_columns=2,
                text_min_length=4,
            )
            classified = {item.offset: item for item in classifications}
            discovery_type = "raw_region" if use_parser_gaps else "unknown_gap"
            for offset, length in gap_ranges:
                classification = classified.get(offset)
                gap_start = offset
                gap_end = offset + length
                overlapping_objects = [
                    obj.source_object_path
                    for obj, start, end in gap_object_windows
                    if start < gap_end and end > gap_start
                ]
                items.append(
                    {
                        "discovery_type": discovery_type,
                        "kind": "raw_dump",
                        "name": f"unknown_gap:{offset}:{length}",
                        "offset": offset,
                        "length": length,
                        "confidence": (classification.confidence if classification is not None else 0.25),
                        "heuristic": True,
                        "extension": None,
                        "source_object_path": f"unknown_gap:{offset}:{length}",
                        "object_kind": (
                            classification.region_class if classification is not None else RAW_REGION_CLASS_TEXT
                        ),
                        "overlapping_objects": overlapping_objects,
                    }
                )
        if include_images and self.detection.detected_type == "opju":
            _attach_opju_page_previews(items, image_blocks, self.file_data())
        self._items_cache[cache_key] = items
        return [*items]

    def _gap_input_signature(
        self,
        image_blocks: list[ImageBlock] | None,
        objects: list[OriginObject] | None,
    ) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        image_signature = tuple(
            (block.offset, block.length) for block in sorted(image_blocks or [], key=lambda item: item.offset)
        )
        object_signature = tuple(
            (obj.offset, obj.length, obj.name, obj.object_kind, obj.parser_confirmed)
            for obj in sorted(objects or [], key=lambda item: (item.offset, item.name))
        )
        return image_signature, object_signature

    def classify_unknown_gaps(
        self,
        *,
        min_size: int,
        image_blocks: list[ImageBlock] | None = None,
        objects: list[OriginObject] | None = None,
        min_rows: int = 2,
        min_columns: int = 2,
        text_min_length: int = 4,
        classify_numeric: bool = True,
    ) -> tuple[list[tuple[int, int]], list[RawRegionClassification]]:
        """Classify unknown byte spans once per option tuple and return cached results."""
        objects_to_use = (
            objects
            if objects is not None
            else self.objects(
                max_repeats_per_name=None,
                include_redundant_tokens=True,
            )
        )
        if image_blocks is None:
            image_blocks = self.image_blocks()
        image_signature, object_signature = self._gap_input_signature(image_blocks, objects_to_use)
        cache_key: _GapCacheKey = (
            self.size_bytes,
            min_size,
            image_signature,
            object_signature,
            min_rows,
            min_columns,
            text_min_length,
            classify_numeric,
        )
        cached = self._gap_cache.get(cache_key)
        if cached is not None:
            return [*cached[0]], [*cached[1]]

        object_windows = list(iter_object_windows(objects_to_use, self.size_bytes))
        covered_ranges = [(block.offset, block.length) for block in image_blocks]
        covered_ranges.extend((start, max(0, end - start)) for _, start, end in object_windows if end > start)
        gap_ranges = _gap_ranges(self.size_bytes, covered_ranges, min_size=min_size)
        file_data = self.file_data()
        classifications = classify_raw_regions(
            file_data,
            gap_ranges,
            image_blocks=[(block.offset, block.length) for block in image_blocks],
            min_rows=min_rows,
            min_columns=min_columns,
            text_min_length=text_min_length,
            classify_numeric=classify_numeric,
        )
        result = (gap_ranges, classifications)
        self._gap_cache[cache_key] = result
        return [*gap_ranges], [*classifications]

    def table_rows(self, min_rows: int = 5, min_columns: int = 2) -> list[tuple[int, int, int, list[str]]]:
        """Scan numeric tables once per parameter set and reuse."""
        key = (min_rows, min_columns)
        cached = self._table_row_cache.get(key)
        if cached is None:
            cached = scan_numeric_tables_from_file(
                self.input_path,
                min_rows=min_rows,
                min_columns=min_columns,
            )
            self._table_row_cache[key] = cached
        return [*cached]
