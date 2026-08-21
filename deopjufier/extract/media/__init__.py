"""Media and text extractors for deopjufier."""

from __future__ import annotations

from pathlib import Path

from deopjufier.blocks import ImageBlock, find_all_blocks, is_displayable_image_block
from deopjufier.extract.path_helpers import manifest_relative_path as _manifest_path
from deopjufier.extract.path_helpers import unique_output_path as _unique_path
from deopjufier.inventory import OriginObject, iter_object_windows
from deopjufier.io import dump_range
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.strings import iter_strings


def _find_image_owner(
    block: ImageBlock,
    object_windows: list[tuple[OriginObject, int, int]],
) -> tuple[OriginObject | None, tuple[int, int] | None, bool]:
    """Find the best object owning an image block.

    Prefer parser-backed windows first; if not present, fall back to any owning object.
    """
    block_start = block.offset
    block_end = block.offset + block.length
    parser_candidate: tuple[OriginObject, int, int] | None = None
    heuristic_candidate: tuple[OriginObject, int, int] | None = None

    for obj, start, end in object_windows:
        if start <= block_start and block_end <= end:
            if obj.parser_confirmed and parser_candidate is None:
                parser_candidate = (obj, start, end)
                break
            if heuristic_candidate is None:
                heuristic_candidate = (obj, start, end)

    if parser_candidate is not None:
        obj, start, end = parser_candidate
        return obj, (start, end), True
    if heuristic_candidate is not None:
        obj, start, end = heuristic_candidate
        return obj, (start, end), False
    return None, None, False


def _discovery_metadata(
    owner_object: OriginObject | None,
    owner_parser_backed: bool,
) -> tuple[str, bool]:
    """Derive discovery type and heuristic flag for image items."""
    if owner_parser_backed:
        return "parser_window", False
    if owner_object is not None:
        return "object_scan", True
    return "carved", True


def _carved_source_ranges(block: ImageBlock) -> list[dict[str, int]]:
    """Exact source ranges for the carved image bytes."""
    return [{"start": block.offset, "end": block.offset + block.length}]


def extract_images(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    file_data: bytes | None = None,
    image_blocks: list[ImageBlock] | None = None,
    objects: list[OriginObject] | None = None,
    manifest_root: Path | None = None,
) -> bool:
    """Extract image-like blocks and append manifest items."""
    blocks = image_blocks if image_blocks is not None else find_all_blocks(input_path)
    if not blocks:
        manifest.add_warning("No recognizable image blocks were found.")
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    valid_found = False
    invalid_found = False

    ordered_objects = sorted(objects or [], key=lambda item: item.offset)
    object_windows = (
        list(iter_object_windows(ordered_objects, input_path.stat().st_size)) if objects is not None else []
    )

    for block in blocks:
        source_object_path = f"embedded:{block.offset}:{block.length}"
        owner_object, owner_window, owner_parser_backed = _find_image_owner(
            block,
            object_windows,
        )
        owner_start = owner_end = None
        if owner_window is not None:
            owner_start, owner_end = owner_window
            source_object_path = owner_object.source_object_path if owner_object else source_object_path

        if not block.valid:
            invalid_found = True
            if owner_object is not None:
                source_object_path = owner_object.source_object_path
            discovery_type, heuristic = _discovery_metadata(owner_object, owner_parser_backed)
            manifest.add_item(
                ManifestItem(
                    kind="image",
                    name=f"embedded:{block.offset}:{block.length}",
                    status="partial",
                    confidence=0.35 if owner_parser_backed else 0.3,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    extraction_method="carved",
                    signature=block.kind,
                    source_ranges=_carved_source_ranges(block),
                    error=block.error,
                    source_object_path=source_object_path,
                    object_kind=owner_object.object_kind if owner_object is not None else None,
                    offset=block.offset,
                    length=block.length,
                    range_start=owner_start,
                    range_end=owner_end,
                )
            )
            continue

        filename = f"img_{block.kind}_off_{block.offset:012d}_len_{block.length:012d}.{block.extension}"
        name = out_dir / filename
        if name.exists() and not force:
            valid_found = True
            discovery_type, heuristic = _discovery_metadata(owner_object, owner_parser_backed)
            manifest.add_item(
                ManifestItem(
                    kind="image",
                    name=f"embedded:{block.offset}:{block.length}",
                    status="skipped",
                    confidence=0.95 if owner_parser_backed else 0.6,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    extraction_method="carved",
                    signature=block.kind,
                    source_ranges=_carved_source_ranges(block),
                    path=_manifest_path(name, manifest_root or out_dir),
                    offset=block.offset,
                    length=block.length,
                    source_object_path=source_object_path,
                    object_kind=owner_object.object_kind if owner_object is not None else None,
                    range_start=owner_start,
                    range_end=owner_end,
                    error="target_exists",
                )
            )
            continue

        name = _unique_path(out_dir, filename, force=force)
        payload = (
            file_data[block.offset : block.offset + block.length]
            if file_data is not None
            else dump_range(input_path, block.offset, block.length)
        )
        if not is_displayable_image_block(payload, block.kind):
            invalid_found = True
            if owner_object is not None:
                source_object_path = owner_object.source_object_path
            discovery_type, heuristic = _discovery_metadata(owner_object, owner_parser_backed)
            manifest.add_item(
                ManifestItem(
                    kind="image",
                    name=f"embedded:{block.offset}:{block.length}",
                    status="partial",
                    confidence=0.6 if owner_parser_backed else 0.35,
                    discovery_type=discovery_type,
                    heuristic=heuristic,
                    extraction_method="carved",
                    signature=block.kind,
                    source_ranges=_carved_source_ranges(block),
                    error="image_payload_unreadable",
                    source_object_path=source_object_path,
                    object_kind=owner_object.object_kind if owner_object is not None else None,
                    offset=block.offset,
                    length=block.length,
                    range_start=owner_start,
                    range_end=owner_end,
                )
            )
            continue
        extracted_length = len(payload)
        name.write_bytes(payload)
        valid_found = True
        discovery_type, heuristic = _discovery_metadata(owner_object, owner_parser_backed)
        manifest.add_item(
            ManifestItem(
                kind="image",
                name=f"embedded:{block.offset}:{block.length}",
                status="extracted",
                confidence=0.95 if owner_parser_backed else 0.8,
                discovery_type=discovery_type,
                heuristic=heuristic,
                extraction_method="carved",
                signature=block.kind,
                source_ranges=_carved_source_ranges(block),
                path=_manifest_path(name, manifest_root or out_dir),
                offset=block.offset,
                length=extracted_length,
                source_object_path=source_object_path,
                object_kind=owner_object.object_kind if owner_object is not None else None,
                range_start=owner_start,
                range_end=owner_end,
            )
        )

    if invalid_found and not valid_found:
        manifest.add_warning("No valid image blocks were extracted; malformed image blocks were detected.")
    return valid_found


def extract_strings(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    encoding: str = "ascii",
    min_length: int = 4,
    force: bool = False,
    file_data: bytes | None = None,
    manifest_root: Path | None = None,
) -> int:
    """Extract visible strings into a text file and append manifest items."""
    out_dir.mkdir(parents=True, exist_ok=True)

    target = _unique_path(out_dir, "strings.txt", force=force)
    source_object_path = "visible_strings"
    if target.exists() and not force:
        manifest.add_item(
            ManifestItem(
                kind="strings",
                name="visible_strings",
                status="skipped",
                confidence=0.7,
                discovery_type="strings_scan",
                heuristic=True,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path=source_object_path,
                error="target_exists",
            )
        )
        return 0

    count = 0
    with target.open("w", encoding="utf-8", newline="") as fp:
        for value in (
            iter_strings(input_path, encoding=encoding, min_length=min_length)
            if file_data is None
            else iter_strings(file_data, encoding=encoding, min_length=min_length)
        ):
            fp.write(value)
            fp.write("\n")
            count += 1

    status = "extracted" if count > 0 else "partial"
    manifest.add_item(
        ManifestItem(
            kind="strings",
            name="visible_strings",
            status=status,
            confidence=0.7 if count > 0 else 0.4,
            discovery_type="strings_scan",
            heuristic=True,
            path=_manifest_path(target, manifest_root or out_dir),
            source_object_path=source_object_path,
        )
    )
    return count
