from __future__ import annotations

import base64
from pathlib import Path

from deopjufy_view.presentation import (
    SHORTCUT_ROWS,
    about_text,
    export_summary,
    property_rows,
    recovered_image,
    status_detail,
    unreadable_item_summary,
)


def test_recovered_image_accepts_graph_preview_path_and_preserves_format() -> None:
    payload = {
        "artifacts": [
            {
                "kind": "graph_preview",
                "path": "graphs/Graph1/graph.png",
                "content_encoding": "base64",
                "content": base64.b64encode(b"png bytes").decode("ascii"),
            }
        ]
    }

    image = recovered_image(payload)

    assert image is not None
    assert image.data == b"png bytes"
    assert image.suffix == ".png"
    assert image.output_format == "png"


def test_properties_are_sectioned_human_rows_and_summarize_content() -> None:
    rows = property_rows(
        {"name": "Sheet1", "source_object_path": "Book1/Sheet1"},
        {
            "status": "ok",
            "content_encoding": "base64",
            "content": "aW1hZ2U=",
            "artifacts": [{"kind": "image", "content": "aW1hZ2U="}],
        },
    )

    assert ("Catalog", "Name", "Sheet1") in {(row.section, row.name, row.value) for row in rows}
    assert any(row.section == "Recovery" and row.name == "Content" and "Recovered content" in row.value for row in rows)
    assert all("aW1hZ2U=" not in row.value for row in rows)


def test_about_text_includes_identity_license_and_major_versions() -> None:
    text = about_text("4.2-test")

    assert "deopjufier" in text
    assert "Version" in text
    assert "GNU General Public License v3.0 or later" in text
    assert "Python" in text
    assert "wxPython 4.2-test" in text
    assert "openpyxl" in text


def test_shortcuts_are_structured_for_accessible_table_presentation() -> None:
    assert all(len(row) == 3 for row in SHORTCUT_ROWS)
    assert ("Export", "Ctrl+Shift+S", "Export all content from the active project") in SHORTCUT_ROWS
    assert len({key for _section, key, _action in SHORTCUT_ROWS}) == len(SHORTCUT_ROWS)


def test_export_summary_separates_extracted_from_omitted_items() -> None:
    manifest = {
        "status": "partial",
        "items": [
            {"status": "extracted"},
            {"status": "extracted"},
            {"status": "skipped", "error": "human profile omits unverified recovery"},
        ],
    }

    assert export_summary(manifest, Path("/tmp/out")) == (
        "Exported 2 item(s) to /tmp/out; 1 not extracted (see manifest.json)"
    )
    assert export_summary({"items": [{"status": "extracted"}]}, Path("out")) == "Exported 1 item(s) to out"


def test_unreadable_item_summary_explains_missing_content() -> None:
    payload = {
        "status": "partial",
        "item": {"name": "pfit2l", "object_kind": "opju_report", "kind": "origin_storage_report"},
        "artifacts": [{"error": "catalog_item_has_no_materializer"}, {"error": None}],
    }

    summary = unreadable_item_summary(payload)
    assert summary is not None
    title, detail = summary

    assert title == "No readable content for pfit2l"
    assert detail.splitlines() == [
        "Kind: opju_report  ·  Status: partial",
        "Reason: catalog_item_has_no_materializer",
        "View ▸ Properties lists the recovered fields; Export ▸ JSON saves the full response.",
    ]
    assert unreadable_item_summary({"content": "text", "item": {}}) is None


def test_status_detail_describes_tables_images_and_text() -> None:
    times = "\N{MULTIPLICATION SIGN}"
    assert status_detail({"status": "ok"}, table_shape=(32, 3)) == f"32 rows {times} 3 columns"
    assert status_detail({"status": "ok"}, table_shape=(1, 1)) == f"1 row {times} 1 column"
    image_detail = status_detail({"status": "ok"}, image_shape=("png", 200, 150))
    assert image_detail == f"PNG · 200 {times} 150 px · +/- zoom, 0 fit"
    assert status_detail({"status": "ok", "content": "a\nb\n"}) == "2 lines"
    assert status_detail({"status": "partial"}) == "partial"
