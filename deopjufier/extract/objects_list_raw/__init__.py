from deopjufier.extract.objects_extractors import *


def extract_project_tree(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    project_nodes: list[OpjProjectNode] | None = None,
) -> int:
    """Export project tree metadata as a mirrored folder hierarchy."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tree_root = out_dir / "tree"
    if not _is_opj_like(file_data, input_path):
        return 0

    data = file_data if file_data is not None else input_path.read_bytes()
    binary_nodes = parse_opj_project_nodes(data) if project_nodes is None else project_nodes
    nodes = [*binary_nodes, *parse_opj_tree_nodes(data)]
    if not nodes:
        return 0

    exported = 0
    seen_paths: set[str] = set()
    for node in nodes:
        if node.path in seen_paths:
            continue
        seen_paths.add(node.path)

        node_path = _project_tree_path(tree_root, node.path)
        node_path.mkdir(parents=True, exist_ok=True)
        target = node_path / "node.json"
        confidence, discovery_type, node_length = _project_tree_node_contract(node)

        if target.exists() and not force:
            manifest.add_item(
                ManifestItem(
                    kind="project_tree",
                    name=node.name,
                    status="skipped",
                    confidence=confidence,
                    discovery_type=discovery_type,
                    heuristic=False,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=f"Tree/{node.path}",
                    object_kind="project_tree",
                    offset=node.start_offset,
                    length=node_length,
                    range_start=node.start_offset,
                    range_end=node.end_offset,
                    error="target_exists",
                )
            )
            continue

        target.write_text(
            json.dumps(_project_tree_payload(node), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.add_item(
            ManifestItem(
                kind="project_tree",
                name=node.name,
                status="extracted",
                confidence=confidence,
                discovery_type=discovery_type,
                heuristic=False,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=f"Tree/{node.path}",
                object_kind="project_tree",
                offset=node.start_offset,
                length=node_length,
                range_start=node.start_offset,
                range_end=node.end_offset,
                rows=1,
                columns=1,
            )
        )
        exported += 1

    return exported


def extract_origin_inventory(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    objects: list[OriginObject] | None = None,
) -> int:
    """Export a minimal JSON inventory for best-effort Origin object names."""
    discovered_objects = list(objects or [])
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "origin_objects.json"

    if target.exists() and not force:
        manifest.add_item(
            ManifestItem(
                kind="origin_object_inventory",
                name="origin_objects",
                status="skipped",
                confidence=0.5,
                discovery_type="parser_backed_hint",
                heuristic=True,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path="origin_objects",
                error="target_exists",
            )
        )
        return 0

    payload = [
        {
            "name": obj.name,
            "object_kind": obj.object_kind,
            "offset": obj.offset,
            "length": obj.length,
            "source_object_path": obj.source_object_path,
        }
        for obj in discovered_objects
    ]
    with target.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(payload, fp, indent=2, sort_keys=True)
        fp.write("\n")

    manifest.add_item(
        ManifestItem(
            kind="origin_object_inventory",
            name="origin_objects",
            status="extracted" if payload else "partial",
            confidence=0.7 if payload else 0.4,
            discovery_type="object_discovery",
            heuristic=True,
            path=_manifest_path(target, manifest_root or out_dir),
            source_object_path="origin_objects",
            error="no_objects_found" if not payload else None,
        )
    )
    return len(payload)


def list_items(input_path: Path):
    """Return a lightweight inventory of discoverable items."""
    from deopjufier.session import ExtractionSession

    session = ExtractionSession.from_path(input_path)
    return session.list_items(include_raw_gaps=False)


def list_items_with_gaps(
    input_path: Path,
    include_gaps: bool = False,
    *,
    file_data: bytes | None = None,
):
    """Return list items, optionally including unknown gap entries."""
    from deopjufier.session import ExtractionSession

    _ = file_data
    session = ExtractionSession.from_path(input_path)
    return session.list_items(include_raw_gaps=include_gaps)


def _find_overlap_objects(
    object_windows: list[tuple[OriginObject, int, int]],
    offset: int,
    length: int,
) -> list[str]:
    """Return source object paths that overlap a raw byte range."""
    if not object_windows or length <= 0:
        return []

    gap_start = offset
    gap_end = offset + length
    seen: set[str] = set()
    overlaps: list[str] = []
    for obj, start, end in object_windows:
        if start >= gap_end or end <= gap_start:
            continue
        source_object_path = obj.source_object_path
        if source_object_path in seen:
            continue
        seen.add(source_object_path)
        overlaps.append(source_object_path)

    return overlaps


def extract_raw_blocks(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    min_size: int = 1024,
    manifest_root: Path | None = None,
    image_blocks: list[ImageBlock] | None = None,
    objects: list[OriginObject] | None = None,
    file_data: bytes | None = None,
    gap_ranges: list[tuple[int, int]] | None = None,
    gap_classifications: list[RawRegionClassification] | None = None,
    excluded_region_classes: set[str] | None = None,
) -> int:
    """Write byte ranges not covered by recognized image and object-backed regions."""
    file_size = input_path.stat().st_size
    if file_size <= 0:
        manifest.add_item(
            ManifestItem(
                kind="raw_dump",
                name="full_file",
                status="partial",
                confidence=0.2,
                discovery_type="unknown_gap",
                heuristic=True,
                path=None,
                length=0,
                range_start=0,
                range_end=0,
                source_object_path="full_file",
                error="empty_file",
            )
        )
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    if gap_ranges is not None:
        ranges = gap_ranges
    else:
        ranges = _unknown_gap_ranges(
            input_path,
            min_size=min_size,
            image_blocks=image_blocks,
            objects=objects,
        )
    if not ranges:
        manifest.add_warning("No raw byte ranges met minimum size threshold.")
        return 0

    if gap_classifications is not None:
        region_classes = gap_classifications
    else:
        data = file_data if file_data is not None else input_path.read_bytes()
        region_classes = _classify_unknown_gap_regions(data, ranges, image_blocks=image_blocks)

    object_windows = list(iter_object_windows(objects, file_size)) if objects is not None else []

    discovered_classes = {item.region_class for item in region_classes}
    excluded_region_classes = excluded_region_classes or set()
    if excluded_region_classes:
        range_by_offset = {(item.offset, item.length): item for item in region_classes}
        included_ranges: list[tuple[int, int]] = []
        excluded_ranges: list[tuple[int, int]] = []
        included_classes: list[RawRegionClassification] = []

        for offset, length in ranges:
            classification = range_by_offset.get((offset, length))
            if classification is not None and classification.region_class in excluded_region_classes:
                excluded_ranges.append((offset, length))
                continue

            included_ranges.append((offset, length))
            if classification is not None:
                included_classes.append(classification)

        for offset, length in excluded_ranges:
            target = out_dir / f"raw_off_{offset:012d}_len_{length:012d}.bin"
            classification = range_by_offset.get((offset, length))
            manifest.add_item(
                ManifestItem(
                    kind="raw_dump",
                    name=f"offset:{offset}_length:{length}",
                    status="skipped",
                    confidence=(classification.confidence if classification is not None else 0.35),
                    discovery_type="unknown_gap",
                    heuristic=True,
                    path=None,
                    offset=offset,
                    length=length,
                    range_start=offset,
                    range_end=offset + length,
                    source_object_path=f"offset:{offset}_length:{length}",
                    overlapping_objects=_find_overlap_objects(
                        object_windows,
                        offset,
                        length,
                    ),
                    object_kind=(
                        range_by_offset[(offset, length)].region_class
                        if (offset, length) in range_by_offset
                        else RAW_REGION_CLASS_TEXT
                    ),
                    error="excluded_by_text_extraction",
                )
            )

        ranges = included_ranges
        region_classes = included_classes

    _emit_unsupported_region_warnings(manifest, discovered_classes, supported=set())

    if not ranges:
        return 0

    region_by_offset = {item.offset: item for item in region_classes}
    with input_path.open("rb") as fh:
        written = 0
        for offset, length in ranges:
            classification = region_by_offset.get(offset)
            item_confidence = 0.35 if classification is None else classification.confidence
            item_class = classification.region_class if classification else "unknown_low_entropy"
            target = out_dir / f"raw_off_{offset:012d}_len_{length:012d}.bin"
            if target.exists() and not force:
                manifest.add_item(
                    ManifestItem(
                        kind="raw_dump",
                        name=f"offset:{offset}_length:{length}",
                        status="skipped",
                        confidence=item_confidence,
                        discovery_type="unknown_gap",
                        heuristic=True,
                        path=_manifest_path(target, manifest_root or out_dir),
                        offset=offset,
                        length=length,
                        range_start=offset,
                        range_end=offset + length,
                        source_object_path=f"offset:{offset}_length:{length}",
                        overlapping_objects=_find_overlap_objects(
                            object_windows,
                            offset,
                            length,
                        ),
                        object_kind=item_class,
                        error="target_exists",
                    )
                )
                continue

            fh.seek(offset)
            target.write_bytes(fh.read(length))
            manifest.add_item(
                ManifestItem(
                    kind="raw_dump",
                    name=f"offset:{offset}_length:{length}",
                    status="extracted",
                    confidence=item_confidence,
                    discovery_type="unknown_gap",
                    heuristic=True,
                    path=_manifest_path(target, manifest_root or out_dir),
                    offset=offset,
                    length=length,
                    range_start=offset,
                    range_end=offset + length,
                    source_object_path=f"offset:{offset}_length:{length}",
                    overlapping_objects=_find_overlap_objects(
                        object_windows,
                        offset,
                        length,
                    ),
                    object_kind=item_class,
                )
            )
            written += 1

    return written


def extract_text_regions(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    min_size: int = 1024,
    min_length: int = 4,
    manifest_root: Path | None = None,
    image_blocks: list[ImageBlock] | None = None,
    objects: list[OriginObject] | None = None,
    file_data: bytes | None = None,
    gap_ranges: list[tuple[int, int]] | None = None,
    gap_classifications: list[RawRegionClassification] | None = None,
) -> int:
    """Export likely text fragments from unknown byte regions as plain-text recon artifacts."""
    file_size = input_path.stat().st_size
    if file_size <= 0:
        manifest.add_item(
            ManifestItem(
                kind="text_region",
                name="full_file",
                status="partial",
                confidence=0.2,
                discovery_type="raw_recon",
                heuristic=True,
                path=None,
                length=0,
                range_start=0,
                range_end=0,
                source_object_path="full_file",
                error="empty_file",
            )
        )
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    if gap_ranges is not None:
        ranges = gap_ranges
    else:
        ranges = _unknown_gap_ranges(
            input_path,
            min_size=min_size,
            image_blocks=image_blocks,
            objects=objects,
        )
    if not ranges:
        manifest.add_warning("No text regions met minimum size threshold.")
        return 0

    if gap_classifications is not None:
        classifications = gap_classifications
    else:
        data = file_data if file_data is not None else input_path.read_bytes()
        classifications = _classify_unknown_gap_regions(
            data,
            ranges,
            image_blocks=image_blocks,
        )
    if gap_classifications is None:
        data = file_data if file_data is not None else input_path.read_bytes()
    elif file_data is not None:
        data = file_data
    else:
        data = input_path.read_bytes()
    discovered_classes = {item.region_class for item in classifications}
    _emit_unsupported_region_warnings(
        manifest,
        discovered_classes,
        supported={RAW_REGION_CLASS_TEXT, RAW_REGION_CLASS_EMBEDDED_IMAGE},
    )
    classification_by_offset = {item.offset: item for item in classifications}

    written = 0
    for offset, length in ranges:
        classification = classification_by_offset.get(offset)
        item_confidence = classification.confidence if classification is not None else 0.35
        item_class = classification.region_class if classification is not None else RAW_REGION_CLASS_TEXT

        raw_slice = _sample_region_bytes(data[offset : offset + length])
        ascii_rows = list(_iter_ascii_strings_from_bytes(raw_slice, min_length=min_length))
        utf16_rows = list(_iter_utf16_strings_from_bytes(raw_slice, min_length=min_length))
        rows = _dedupe(ascii_rows + utf16_rows)
        if not rows:
            continue

        target = out_dir / f"text_off_{offset:012d}_len_{length:012d}.txt"
        if target.exists() and not force:
            manifest.add_item(
                ManifestItem(
                    kind="text_region",
                    name=f"offset:{offset}_length:{length}",
                    status="skipped",
                    confidence=item_confidence,
                    discovery_type="raw_recon",
                    heuristic=True,
                    path=_manifest_path(target, manifest_root or out_dir),
                    source_object_path=f"unknown_gap:{offset}:{length}",
                    range_start=offset,
                    range_end=offset + length,
                    offset=offset,
                    length=length,
                    object_kind=item_class,
                    error="target_exists",
                )
            )
            continue

        target.write_text(
            "\n".join(rows),
            encoding="utf-8",
            newline="\n",
        )
        manifest.add_item(
            ManifestItem(
                kind="text_region",
                name=f"offset:{offset}_length:{length}",
                status="extracted",
                confidence=item_confidence,
                discovery_type="raw_recon",
                heuristic=True,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=f"unknown_gap:{offset}:{length}",
                range_start=offset,
                range_end=offset + length,
                offset=offset,
                length=length,
                object_kind=item_class,
                rows=len(rows),
                columns=1,
            )
        )
        written += 1

    if written == 0:
        manifest.add_warning("No printable text found inside extracted raw ranges.")
    return written


__all__ = [
    *[name for name in globals() if not name.startswith("_") and name != "__builtins__"],
    "extract_origin_inventory",
    "extract_project_tree",
    "extract_raw_blocks",
    "extract_text_regions",
    "list_items",
    "list_items_with_gaps",
]

__all__ = sorted(set(__all__))
