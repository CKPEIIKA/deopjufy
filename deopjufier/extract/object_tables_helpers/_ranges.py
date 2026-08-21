"""Helpers for unsupported-range and manifest bookkeeping."""

from __future__ import annotations

from pathlib import Path

from deopjufier.extract.path_helpers import manifest_relative_path as _manifest_path
from deopjufier.inventory import parse_opju_records
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju import OPJU_REGION_KIND_CONTAINER


def _coalesce_partial_source_key(path: str | None) -> str:
    if not path:
        return ""

    if "__" not in path:
        return path

    base, suffix = path.rsplit("__", 1)
    if suffix.isdigit():
        return base
    return path


def _unsupported_tabular_collection_item(
    *,
    manifest: Manifest,
    manifest_item_kind: str,
    collection_name: str,
    collection_path: str,
    manifest_root: Path,
    out_dir: Path,
    error: str = "no_parser_backed_table_artifacts",
    range_start: int | None = None,
    range_end: int | None = None,
    source_object_path: str | None = None,
) -> None:
    collection_dir = out_dir / collection_path
    collection_dir.mkdir(parents=True, exist_ok=True)
    collection_range_start = range_start if range_start is not None else None
    collection_range_end = range_end if range_end is not None else None
    collection_source_path = source_object_path if source_object_path else f"{collection_name}_collection"

    manifest.add_item(
        ManifestItem(
            kind=manifest_item_kind,
            name=f"{collection_name}_collection",
            status="unsupported",
            confidence=0.7,
            discovery_type="parser_backed_hint",
            heuristic=False,
            path=_manifest_path(collection_dir, manifest_root or out_dir),
            source_object_path=collection_source_path,
            error=error,
            range_start=collection_range_start,
            range_end=collection_range_end,
        )
    )


def _derive_opju_worksheet_unsupported_range(
    data: bytes,
    *,
    input_path: Path,
    worksheet_objects: list,
    max_tables: int = 200,
    include_decoded: bool = False,
) -> tuple[int, int, str | None] | None:
    spans: list[tuple[int, int, str | None]] = []

    if not spans:
        for obj in worksheet_objects:
            if obj.object_kind != "worksheet" or obj.offset < 0:
                continue
            if obj.length > 0:
                spans.append((obj.offset, obj.offset + obj.length, obj.source_object_path))

    if not spans:
        try:
            parsed = parse_opju_records(
                data,
                path=input_path,
                max_reports=0,
                max_tables=max_tables,
                max_rows=0,
                include_decoded=include_decoded,
            )
        except Exception:
            parsed = None

        if parsed is not None:
            for region in parsed.regions:
                if region.kind == OPJU_REGION_KIND_CONTAINER:
                    continue
                if region.length <= 0:
                    continue
                spans.append(
                    (
                        region.offset,
                        region.offset + region.length,
                        region.source_object_path,
                    )
                )

    if not spans:
        return None

    starts, ends, sources = zip(*spans, strict=False)
    range_start = min(starts)
    range_end = max(ends)
    source_candidates = sorted(source for start, _, source in spans if start == range_start and source)
    if not source_candidates:
        source_candidates = sorted(source for source in sources if source)
    source_object_path = source_candidates[0] if source_candidates else None

    return range_start, range_end, source_object_path


def _dedupe_partial_tabular_items_with_extracted_names(
    manifest: Manifest,
    *,
    manifest_item_kind: str,
    collection_name: str,
    out_dir: Path | None = None,
) -> None:
    extracted_paths = {
        item.path
        for item in manifest.items
        if item.kind == manifest_item_kind
        and item.status == "extracted"
        and not item.name.endswith("_collection")
        and item.path
    }
    partial_or_skipped_paths = {
        item.path
        for item in manifest.items
        if item.kind == manifest_item_kind
        and item.status in {"partial", "skipped"}
        and not item.name.endswith("_collection")
        and item.path
    }
    partial_pathless_items = [
        item
        for item in manifest.items
        if item.kind == manifest_item_kind and item.status == "partial" and item.error == "no_extracted_table_rows"
    ]
    has_pathless_partial_no_rows = any(
        (
            item.kind == manifest_item_kind
            and item.status == "partial"
            and item.error == "no_extracted_table_rows"
            and item.path is None
            and not item.name.endswith("_collection")
            and item.rows == 0
        )
        for item in manifest.items
    )
    extracted_item_names = {
        item.name
        for item in manifest.items
        if item.kind == manifest_item_kind
        and item.status == "extracted"
        and not item.name.endswith("_collection")
        and item.path
    }
    if not extracted_paths and not partial_or_skipped_paths and not partial_pathless_items:
        return

    collection_name_key = f"{collection_name}_collection"

    kept_partial_paths: set[str] = set()
    kept_partial_keys: set[tuple[str, str | None, str | None]] = set()
    kept_name_keys: dict[tuple[str, str | None], int] = {}
    kept_items: list = []

    def _status_rank(item: ManifestItem) -> int:
        return {
            "extracted": 4,
            "unsupported": 3,
            "partial": 2,
            "skipped": 1,
        }.get(item.status, 0)

    for item in manifest.items:
        if item.kind != manifest_item_kind:
            kept_items.append(item)
            continue

        if item.name == collection_name_key and has_pathless_partial_no_rows:
            continue

        if item.name.endswith("_collection"):
            kept_items.append(item)
            continue

        source_key = _coalesce_partial_source_key(item.source_object_path)
        name_key = (item.name, source_key)

        if (
            item.status == "partial"
            and item.error == "no_extracted_table_rows"
            and item.path is None
            and item.name in extracted_item_names
        ):
            continue

        if item.status == "partial" and item.error == "no_extracted_table_rows" and item.path is not None:
            if item.path in kept_partial_paths:
                continue
            partial_key = (item.name, source_key, item.discovery_type)
            if partial_key in kept_partial_keys:
                continue
            kept_partial_paths.add(item.path)
            kept_partial_keys.add(partial_key)
            kept_items.append(item)
            kept_name_keys.setdefault(name_key, len(kept_items) - 1)
            continue

        if item.status == "partial" and item.error == "no_extracted_table_rows":
            partial_key = (item.name, source_key, item.discovery_type)
            if partial_key in kept_partial_keys:
                continue
            kept_partial_keys.add(partial_key)
            kept_items.append(item)
            kept_name_keys.setdefault(name_key, len(kept_items) - 1)
            continue

        if (
            item.status == "skipped"
            and item.error == "target_exists"
            and item.path is not None
            and item.path in extracted_paths
        ):
            continue

        existing_index = kept_name_keys.get(name_key)
        if existing_index is not None:
            existing = kept_items[existing_index]
            if _status_rank(item) > _status_rank(existing):
                kept_items[existing_index] = item
            continue

        kept_items.append(item)
        kept_name_keys[name_key] = len(kept_items) - 1

    if out_dir is not None:
        retained_paths = {item.path for item in kept_items if item.path}
        root = out_dir.resolve(strict=False)
        for item in manifest.items:
            if item in kept_items or item.status not in {"extracted", "partial"} or not item.path:
                continue
            target = out_dir / item.path
            resolved_target = target.resolve(strict=False)
            try:
                resolved_target.relative_to(root)
            except ValueError:
                continue
            if item.path not in retained_paths and target.is_file():
                target.unlink()

    manifest.items = kept_items


__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
