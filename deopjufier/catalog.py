"""Stable, document-local identities for CLI catalog items."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Final

CATALOG_SCHEMA_VERSION: Final[int] = 1

_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "kind",
    "object_kind",
    "name",
    "source_object_path",
    "offset",
    "length",
    "window_start",
    "window_end",
    "discovery_type",
)

_TABULAR_KINDS: Final[frozenset[str]] = frozenset({"excel", "matrix", "worksheet"})
_TEXT_KINDS: Final[frozenset[str]] = frozenset({"function", "note"})
_GRAPH_KINDS: Final[frozenset[str]] = frozenset({"graph", "layer", "opju_graph_payload", "opju_preview"})
_IMAGE_KINDS: Final[frozenset[str]] = frozenset({"bmp", "gif", "image", "jpeg", "jpg", "png", "svg"})


def _semantic_kind(item: Mapping[str, object]) -> str:
    object_kind = item.get("object_kind")
    if isinstance(object_kind, str) and object_kind:
        return object_kind
    kind = item.get("kind")
    return kind if isinstance(kind, str) else "unknown"


def retrieval_formats(item: Mapping[str, object]) -> list[str]:
    """Return supported retrieval formats for one catalog item."""
    semantic_kind = _semantic_kind(item)
    if semantic_kind in _TABULAR_KINDS:
        return ["json", "jsonl", "csv", "tsv", "xlsx"]
    preview_extension = item.get("preview_extension")
    if semantic_kind == "project_page" and isinstance(preview_extension, str):
        return ["json", preview_extension]
    if semantic_kind in _TEXT_KINDS or semantic_kind in _GRAPH_KINDS:
        return ["json"]
    kind = item.get("kind")
    if kind in _IMAGE_KINDS:
        extension = item.get("extension")
        return ["json", extension if isinstance(extension, str) and extension else str(kind)]
    if kind == "raw_dump":
        return ["json"]
    return ["json"]


def _identity_values(item: Mapping[str, object]) -> dict[str, object]:
    return {field: item[field] for field in _IDENTITY_FIELDS if field in item}


def _identity_key(item: Mapping[str, object]) -> str:
    return json.dumps(
        _identity_values(item),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def catalog_item_id(document_sha256: str, item: Mapping[str, object], occurrence: int = 1) -> str:
    """Create an opaque ID stable for the same item in the same input bytes."""
    identity = {
        "document_sha256": document_sha256,
        "item": _identity_values(item),
        "occurrence": occurrence,
        "schema_version": CATALOG_SCHEMA_VERSION,
    }
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"item:v{CATALOG_SCHEMA_VERSION}:{hashlib.sha256(encoded).hexdigest()}"


def _source_path(item: Mapping[str, object]) -> str | None:
    value = item.get("source_object_path")
    return value.strip("/") if isinstance(value, str) and value else None


def _exact_parent(
    item: dict[str, object],
    by_source_path: Mapping[str, list[dict[str, object]]],
) -> dict[str, object] | None:
    source_path = _source_path(item)
    if source_path is None:
        return None
    parent_path, separator, _leaf = source_path.rpartition("/")
    if not separator:
        return None
    candidates = [candidate for candidate in by_source_path.get(parent_path, []) if candidate is not item]
    return candidates[0] if len(candidates) == 1 else None


def _attach_parent_ids(items: list[dict[str, object]]) -> None:
    by_source_path: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        source_path = _source_path(item)
        if source_path is not None:
            by_source_path[source_path].append(item)

    for item in items:
        parent = _exact_parent(item, by_source_path)
        if parent is None:
            continue
        parent_id = parent.get("id")
        if isinstance(parent_id, str):
            item["parent_id"] = parent_id


def _attach_preview_ids(items: list[dict[str, object]]) -> None:
    previews: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for item in items:
        offset = item.get("offset")
        length = item.get("length")
        if item.get("kind") in _IMAGE_KINDS and isinstance(offset, int) and isinstance(length, int):
            previews[(offset, length)].append(item)
    for item in items:
        offset = item.get("preview_offset")
        length = item.get("preview_length")
        candidates = previews.get((offset, length), []) if isinstance(offset, int) and isinstance(length, int) else []
        if len(candidates) == 1 and isinstance(candidates[0].get("id"), str):
            item["preview_item_id"] = candidates[0]["id"]


def catalog_items(items: Iterable[Mapping[str, object]], document_sha256: str) -> list[dict[str, object]]:
    """Copy list items and add stable IDs plus exact parent links."""
    occurrences: Counter[str] = Counter()
    catalog: list[dict[str, object]] = []
    for source_item in items:
        item = dict(source_item)
        identity_key = _identity_key(item)
        occurrences[identity_key] += 1
        item["id"] = catalog_item_id(document_sha256, item, occurrences[identity_key])
        item["retrieval_formats"] = retrieval_formats(item)
        catalog.append(item)
    _attach_parent_ids(catalog)
    _attach_preview_ids(catalog)
    return catalog


def find_catalog_item(items: Iterable[Mapping[str, object]], item_id: str) -> dict[str, object] | None:
    """Return a copied catalog item by opaque ID."""
    for item in items:
        if item.get("id") == item_id:
            return dict(item)
    return None


def document_payload(*, path: str, size_bytes: int, sha256: str, detected_type: str) -> dict[str, object]:
    """Build the stable document identity envelope used by list/get clients."""
    return {
        "path": path,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "detected_type": detected_type,
    }


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "catalog_item_id",
    "catalog_items",
    "document_payload",
    "find_catalog_item",
    "retrieval_formats",
]
