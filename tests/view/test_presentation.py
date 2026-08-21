from __future__ import annotations

import base64

from deopjufy_view.presentation import SHORTCUT_ROWS, about_text, property_rows, recovered_image


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
