from __future__ import annotations

from deopjufier.manifest import Manifest

_KIND_COLLECTION_NAME_OVERRIDES: dict[str, set[str]] = {
    "worksheet": {"book", "worksheet"},
}


def _collection_names_for_kind(kind: str) -> set[str]:
    return _KIND_COLLECTION_NAME_OVERRIDES.get(kind, {kind})


def _is_collection_item_name(kind: str, item) -> bool:
    collection_names = _collection_names_for_kind(kind)
    collection_markers = {f"{name}_collection" for name in collection_names}
    return str(item.name) in collection_markers or (
        isinstance(item.source_object_path, str) and item.source_object_path in collection_markers
    )


def _has_unsupported_collection_item(manifest: Manifest, kind: str) -> bool:
    return any(
        item.kind == kind and item.status == "unsupported" and _is_collection_item_name(kind, item)
        for item in manifest.items
    )


def _has_real_payload_for_kind(manifest: Manifest, kind: str) -> bool:
    for item in manifest.items:
        if item.kind != kind:
            continue
        if str(item.name).endswith("_collection"):
            continue
        if item.heuristic is True:
            continue
        if item.status not in {"extracted", "partial", "skipped"}:
            continue
        if kind == "excel" and item.status == "partial" and (item.rows or 0) == 0 and (item.columns or 0) == 0:
            continue
        if kind == "graph" and item.status == "partial" and item.error == "no_embedded_image_block":
            continue
        return True
    return False


def should_warn_for_missing_artifact(
    manifest: Manifest,
    kind: str,
    *,
    detected_type: str | None = None,
    has_parser_backed_artifacts: bool = True,
) -> bool:
    if kind == "excel" and detected_type == "opju" and not has_parser_backed_artifacts:
        return False

    if kind == "matrix" and detected_type == "opju" and not has_parser_backed_artifacts:
        return False

    if kind == "function" and detected_type == "opju" and not has_parser_backed_artifacts:
        return False

    if kind == "function" and detected_type == "opj" and not has_parser_backed_artifacts:
        return False

    if not _has_unsupported_collection_item(manifest, kind):
        return True
    return _has_real_payload_for_kind(manifest, kind)


def has_malformed_graph_preview(manifest: Manifest) -> bool:
    return any(item.kind == "malformed_graph_preview" and item.status == "partial" for item in manifest.items)
