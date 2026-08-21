"""Small presentation records derived directly from get JSON payloads."""

from __future__ import annotations

import base64
import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from deopjufy_view.presentation import recovered_image


@dataclass(frozen=True)
class TabularView:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    metadata_rows: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def column_count(self) -> int:
        return max(len(self.headers), max((len(row) for row in self.rows), default=0))

    @property
    def grid_row_count(self) -> int:
        return len(self.metadata_rows) + len(self.rows)

    def value(self, row: int, column: int) -> str:
        if row < len(self.metadata_rows):
            values = self.metadata_rows[row][1]
        else:
            values = self.rows[row - len(self.metadata_rows)]
        return values[column] if column < len(values) else ""

    def row_label(self, row: int) -> str:
        if row < len(self.metadata_rows):
            return self.metadata_rows[row][0]
        return str(row - len(self.metadata_rows) + 1)

    def column_is_numeric(self, column: int) -> bool:
        values = [row[column] for row in self.rows[:100] if column < len(row) and row[column].strip()]
        if not values:
            return False
        try:
            for value in values:
                float(value)
        except ValueError:
            return False
        return True


def _row_values(row: object) -> tuple[str, ...] | None:
    row_payload = cast(dict[str, object], row) if isinstance(row, dict) else None
    values = row_payload.get("values") if row_payload is not None else row
    if not isinstance(values, list):
        return None
    return tuple("" if value is None else str(value) for value in values)


def _metadata_payload(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not str(artifact.get("kind", "")).endswith("_metadata"):
            continue
        content = artifact.get("content")
        if isinstance(content, dict):
            return content
    return {}


def _column_payloads(metadata: dict[str, Any], width: int) -> list[dict[str, Any]]:
    columns = metadata.get("columns")
    result = [column if isinstance(column, dict) else {} for column in columns] if isinstance(columns, list) else []
    return (result + [{} for _index in range(width)])[:width]


def _metadata_values(
    metadata: dict[str, Any],
    columns: list[dict[str, Any]],
    key: str,
    width: int,
) -> tuple[str, ...]:
    values = [str(column.get(key, "") or "") for column in columns]
    fallback_key = {"comment": "comments", "formula": "formulas", "value_type": "column_types"}.get(key)
    fallback = metadata.get(fallback_key) if fallback_key is not None else None
    if isinstance(fallback, list):
        for index, value in enumerate(fallback[:width]):
            if not values[index] and value is not None:
                values[index] = str(value)
    return tuple(values)


def _table_headers(headers: tuple[str, ...], metadata: dict[str, Any], width: int) -> tuple[str, ...]:
    labels = metadata.get("column_labels")
    columns = _column_payloads(metadata, width)
    result: list[str] = []
    for index in range(width):
        header = headers[index] if index < len(headers) else f"Column {index + 1}"
        if isinstance(labels, list) and index < len(labels) and labels[index]:
            header = str(labels[index])
        designation = columns[index].get("designation")
        if isinstance(designation, str) and designation and not header.endswith(f"({designation})"):
            header = f"{header}({designation})"
        result.append(header)
    return tuple(result)


def _table_metadata_rows(metadata: dict[str, Any], width: int) -> tuple[tuple[str, tuple[str, ...]], ...]:
    columns = _column_payloads(metadata, width)
    rows = (
        ("Long", _metadata_values(metadata, columns, "long_name", width)),
        ("Units", _metadata_values(metadata, columns, "units", width)),
        ("Comm.", _metadata_values(metadata, columns, "comment", width)),
        ("Formula", _metadata_values(metadata, columns, "formula", width)),
        ("Type", _metadata_values(metadata, columns, "value_type", width)),
    )
    return tuple((label, values) for label, values in rows if any(values))


def tabular_view(payload: dict[str, Any]) -> TabularView | None:
    """Map the canonical table artifact to a grid-oriented immutable view."""
    content = payload.get("content")
    if isinstance(content, dict):
        headers_value = content.get("headers", [])
        rows_value = content.get("rows", [])
    elif isinstance(content, list):
        headers_value = []
        rows_value = content
    else:
        return None
    if not isinstance(headers_value, list) or not isinstance(rows_value, list):
        return None
    rows = tuple(values for row in rows_value if (values := _row_values(row)) is not None)
    headers = tuple(str(header) for header in headers_value)
    if not headers:
        width = max((len(row) for row in rows), default=0)
        headers = tuple(f"Column {index + 1}" for index in range(width))
    width = max(len(headers), max((len(row) for row in rows), default=0))
    metadata = _metadata_payload(payload)
    return TabularView(
        headers=_table_headers(headers, metadata, width),
        rows=rows,
        metadata_rows=_table_metadata_rows(metadata, width),
    )


def table_region_text(
    table: TabularView,
    top: int,
    left: int,
    bottom: int,
    right: int,
    *,
    delimiter: str = "\t",
) -> str:
    """Serialize a rectangular visible-grid selection as CSV or TSV."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    for row in range(max(0, top), min(bottom + 1, table.grid_row_count)):
        writer.writerow(table.value(row, column) for column in range(max(0, left), min(right + 1, table.column_count)))
    return stream.getvalue()


def find_next_label(labels: tuple[str, ...], query: str, start: int = -1) -> int | None:
    """Find the next case-insensitive tree label, wrapping once."""
    needle = query.strip().casefold()
    if not needle or not labels:
        return None
    for step in range(1, len(labels) + 1):
        index = (start + step) % len(labels)
        if needle in labels[index].casefold():
            return index
    return None


def payload_bytes(payload: dict[str, Any]) -> bytes | None:
    """Serialize the primary inline payload without interpreting its domain meaning."""
    content = payload.get("content")
    encoding = payload.get("content_encoding")
    if encoding == "base64" and isinstance(content, str):
        try:
            return base64.b64decode(content, validate=True)
        except ValueError:
            return None
    if encoding == "text" and isinstance(content, str):
        return content.encode("utf-8")
    if encoding == "json":
        return (json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return None


def default_artifact_suffix(payload: dict[str, Any]) -> str:
    """Return a safe suggested suffix for the primary recovered artifact."""
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("content") is None:
                continue
            path = artifact.get("path")
            suffix = Path(path).suffix if isinstance(path, str) else ""
            if suffix:
                return suffix
    return ".bin"


def payload_text(payload: dict[str, Any]) -> str:
    """Return text content when available, otherwise stable formatted JSON."""
    content = payload.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def image_bytes(payload: dict[str, Any]) -> bytes | None:
    """Return the first extracted image payload from a get response."""
    image = recovered_image(payload)
    return image.data if image is not None else None


__all__ = [
    "TabularView",
    "default_artifact_suffix",
    "find_next_label",
    "image_bytes",
    "payload_bytes",
    "payload_text",
    "table_region_text",
    "tabular_view",
]
