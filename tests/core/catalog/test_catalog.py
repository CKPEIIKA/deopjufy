from __future__ import annotations

from deopjufier.catalog import CATALOG_SCHEMA_VERSION, catalog_items, find_catalog_item


def test_catalog_ids_are_document_bound_order_independent_and_opaque() -> None:
    parent = {
        "kind": "origin_object",
        "object_kind": "workbook",
        "name": "Book1",
        "source_object_path": "Book1",
        "offset": 10,
        "length": 5,
    }
    child = {
        "kind": "origin_object",
        "object_kind": "worksheet",
        "name": "Sheet1",
        "source_object_path": "Book1/Sheet1",
        "offset": 20,
        "length": 7,
    }

    forward = catalog_items([parent, child], "a" * 64)
    reverse = catalog_items([child, parent], "a" * 64)

    forward_ids = {item["name"]: item["id"] for item in forward}
    reverse_ids = {item["name"]: item["id"] for item in reverse}
    assert forward_ids == reverse_ids
    assert all(str(item_id).startswith(f"item:v{CATALOG_SCHEMA_VERSION}:") for item_id in forward_ids.values())
    assert forward[1]["parent_id"] == forward[0]["id"]
    assert catalog_items([parent], "b" * 64)[0]["id"] != forward[0]["id"]


def test_catalog_retrieval_formats_and_lookup_are_explicit() -> None:
    source = {
        "kind": "origin_object",
        "object_kind": "worksheet",
        "name": "Sheet1",
        "source_object_path": "Book1/Sheet1",
        "offset": 20,
        "length": 7,
    }
    item = catalog_items([source], "c" * 64)[0]

    assert item["retrieval_formats"] == ["json", "jsonl", "csv", "tsv", "xlsx"]
    assert find_catalog_item([item], str(item["id"])) == item
    assert find_catalog_item([item], "item:v1:missing") is None


def test_catalog_links_exact_page_preview_and_declares_image_export() -> None:
    preview = {
        "kind": "png",
        "name": "embedded:10:20",
        "source_object_path": "embedded/png/10",
        "offset": 10,
        "length": 20,
        "extension": "png",
    }
    page = {
        "kind": "origin_object",
        "object_kind": "project_page",
        "name": "Graph1",
        "source_object_path": "page_directory/Graph1",
        "offset": 36,
        "length": 6,
        "preview_offset": 10,
        "preview_length": 20,
        "preview_extension": "png",
    }

    catalog = catalog_items([preview, page], "d" * 64)

    assert catalog[0]["retrieval_formats"] == ["json", "png"]
    assert catalog[1]["retrieval_formats"] == ["json", "png"]
    assert catalog[1]["preview_item_id"] == catalog[0]["id"]
