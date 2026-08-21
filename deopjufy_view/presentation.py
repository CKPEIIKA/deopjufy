"""Pure formatting helpers for viewer dialogs and recovered media."""

from __future__ import annotations

import base64
import json
import platform
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

_IMAGE_KINDS = frozenset(
    {
        "bmp",
        "gif",
        "graph_preview",
        "image",
        "jpeg",
        "jpg",
        "malformed_graph_preview",
        "parser_backed_graph_preview",
        "png",
        "svg",
    }
)
_IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg"})
_CONTENT_KEYS = frozenset({"content"})
_VALUE_LIMIT = 500

SHORTCUT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Project", "Ctrl+O", "Open one or more projects"),
    ("Project", "Ctrl+F", "Search the project tree"),
    ("Project", "Enter / Space", "Open the selected tree item"),
    ("Project", "Shift+F10", "Open the tree context menu"),
    ("Export", "Ctrl+S", "Export the current item"),
    ("Export", "Ctrl+Shift+S", "Export all content from the active project"),
    ("Table", "Ctrl+C", "Copy selected cells"),
    ("Navigation", "Ctrl+W", "Close the current workbook or item tab"),
    ("Navigation", "Ctrl+Tab", "Select the next document or workbook"),
    ("Navigation", "Ctrl+PageUp / PageDown", "Select the previous or next sheet"),
    ("Navigation", "F6", "Switch between the project tree and document"),
    ("View", "Ctrl+Shift+E", "Expand all project branches"),
    ("View", "Ctrl+Shift+C", "Collapse all project branches"),
    ("View", "Alt+Enter", "Show properties for the selected item"),
    ("Plot", "+ / - / 0", "Zoom in, zoom out, or fit the preview"),
    ("Help", "F1", "Show this keyboard reference"),
)


@dataclass(frozen=True)
class RecoveredImage:
    data: bytes
    suffix: str
    output_format: str


@dataclass(frozen=True)
class PropertyRow:
    section: str
    name: str
    value: str


def _decode_artifact_image(artifact: dict[str, Any]) -> RecoveredImage | None:
    if artifact.get("content_encoding") != "base64":
        return None
    path = artifact.get("path")
    suffix = Path(path).suffix.lower() if isinstance(path, str) else ""
    kind = str(artifact.get("kind", "")).lower()
    signature = str(artifact.get("signature", "")).lower()
    if kind not in _IMAGE_KINDS and signature not in _IMAGE_KINDS and suffix not in _IMAGE_SUFFIXES:
        return None
    content = artifact.get("content")
    if not isinstance(content, str):
        return None
    try:
        data = base64.b64decode(content, validate=True)
    except ValueError:
        return None
    effective_suffix = suffix if suffix in _IMAGE_SUFFIXES else f".{signature or kind}"
    if effective_suffix not in _IMAGE_SUFFIXES:
        effective_suffix = ".png"
    return RecoveredImage(data=data, suffix=effective_suffix, output_format=effective_suffix.removeprefix("."))


def recovered_image(payload: dict[str, Any]) -> RecoveredImage | None:
    """Return a validated inline image or graph-preview artifact."""
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if isinstance(artifact, dict) and (image := _decode_artifact_image(artifact)) is not None:
            return image
    return None


def _display_value(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value) if isinstance(value, (str, int, float)) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= _VALUE_LIMIT else f"{text[: _VALUE_LIMIT - 1]}…"


def _property_name(path: tuple[str, ...]) -> str:
    return " > ".join(part.replace("_", " ").strip().title() for part in path)


def _flatten(section: str, value: object, path: tuple[str, ...] = ()) -> list[PropertyRow]:
    if isinstance(value, dict):
        rows: list[PropertyRow] = []
        for key, child in value.items():
            key_text = str(key)
            child_path = (*path, key_text)
            if key_text in _CONTENT_KEYS:
                size = len(child) if isinstance(child, (str, bytes, list, dict)) else 0
                rows.append(PropertyRow(section, _property_name(child_path), f"Recovered content ({size} units)"))
            else:
                rows.extend(_flatten(section, child, child_path))
        return rows
    if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
        rows = []
        for index, child in enumerate(value, start=1):
            rows.extend(_flatten(section, child, (*path, str(index))))
        return rows
    return [PropertyRow(section, _property_name(path) or "Value", _display_value(value))]


def property_rows(catalog: dict[str, Any], retrieval: dict[str, Any] | None = None) -> tuple[PropertyRow, ...]:
    """Format catalog and retrieval metadata without dumping raw JSON content."""
    rows = _flatten("Catalog", catalog)
    if retrieval is not None:
        summary = {key: value for key, value in retrieval.items() if key not in {"item", "schema_version"}}
        rows.extend(_flatten("Recovery", summary))
    return tuple(rows)


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def about_text(wx_version: str) -> str:
    """Return complete application, license, and runtime dependency information."""
    return "\n".join(
        (
            "deopjufier",
            f"Version {_distribution_version('deopjufier')}",
            "Read-only Origin OPJ/OPJU recovery viewer",
            "",
            "License: GNU General Public License v3.0 or later",
            "",
            "Major runtime components:",
            f"Python {platform.python_version()}",
            f"wxPython {wx_version}",
            f"openpyxl {_distribution_version('openpyxl')}",
        )
    )


__all__ = [
    "SHORTCUT_ROWS",
    "PropertyRow",
    "RecoveredImage",
    "about_text",
    "property_rows",
    "recovered_image",
]
