"""Manifest data model for extraction runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from deopjufier import __version__
from deopjufier.detect import DetectedFile


@dataclass
class ManifestInput:
    path: str
    size_bytes: int
    sha256: str
    detected_type: str


@dataclass
class ManifestTool:
    name: str
    version: str
    backend: str


@dataclass
class ManifestItem:
    kind: str
    name: str
    status: str
    confidence: float
    discovery_type: str | None = None
    heuristic: bool | None = None
    object_kind: str | None = None
    path: str | None = None
    signature: str | None = None
    source_object_path: str | None = None
    overlapping_objects: list[str] | None = None
    rows: int | None = None
    columns: int | None = None
    content_class: str | None = None
    function_name: str | None = None
    function_formula: str | None = None
    function_range: tuple[str, str] | None = None
    function_total_points: int | None = None
    calculation_label: str | None = None
    calculation_uid: int | None = None
    payload_family: str | None = None
    structural_name: str | None = None
    semantic_alias: str | None = None
    semantic_confidence: str | None = None
    preview_status: str | None = None
    embedded_payload: bool | None = None
    source_map_path: str | None = None
    replacement_character_count: int | None = None
    control_character_count: int | None = None
    note_payload_type: str | None = None
    offset: int | None = None
    length: int | None = None
    decoded_length: int | None = None
    compression: str | None = None
    declared_length: int | None = None
    family_marker: str | None = None
    marker_offset: int | None = None
    header_offset: int | None = None
    stream_offset: int | None = None
    framing_rule: str | None = None
    range_start: int | None = None
    range_end: int | None = None
    source_ranges: list[dict[str, int]] | None = None
    discovery_method: str | None = None
    extraction_method: str | None = None
    completeness: str | None = None
    verification: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.discovery_method is None:
            self.discovery_method = self.discovery_type

        if self.extraction_method is None:
            self.extraction_method = self.discovery_method

        if self.source_ranges is None:
            self.source_ranges = _source_range_list(
                range_start=self.range_start,
                range_end=self.range_end,
                offset=self.offset,
                length=self.length,
            )

        if self.completeness is None:
            self.completeness = _default_completeness(
                status=self.status,
                heuristic=self.heuristic,
            )

        if self.verification is None:
            self.verification = "unverified"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {k: v for k, v in payload.items() if v is not None}


def _source_range_list(
    range_start: int | None,
    range_end: int | None,
    offset: int | None,
    length: int | None,
) -> list[dict[str, int]] | None:
    if range_start is not None and range_end is not None:
        return [{"start": range_start, "end": range_end}]
    if offset is not None and length is not None:
        return [{"start": offset, "end": offset + length}]
    return None


def _default_completeness(status: str, heuristic: bool | None) -> str:
    if status == "extracted":
        return "partial" if heuristic else "complete"
    if status in {"partial", "skipped", "unsupported", "error"}:
        return "partial"
    return "partial"


@dataclass
class Manifest:
    input: ManifestInput
    tool: ManifestTool
    parser_status: str = field(default="unsupported", repr=False)
    coverage_scope: str | None = field(default=None, repr=False)
    verification: str | None = field(default=None, repr=False)
    support_class: str = field(default="heuristic", repr=False)
    status: str = field(default="ok", repr=False)
    parser_warnings: list[dict[str, str]] = field(default_factory=list, repr=False)
    items: list[ManifestItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_item(self, item: ManifestItem) -> None:
        self.items.append(item)

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def add_parser_warning(self, code: str, message: str) -> None:
        self.parser_warnings.append({"code": code, "message": message})
        self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        ordered_items = sorted(
            self.items,
            key=lambda item: (
                item.path or "",
                item.kind,
                item.name,
            ),
        )
        return {
            "input": asdict(self.input),
            "tool": asdict(self.tool),
            "parser_status": self.parser_status,
            **({"coverage_scope": self.coverage_scope} if self.coverage_scope is not None else {}),
            **({"verification": self.verification} if self.verification is not None else {}),
            "support_class": self.support_class,
            "status": self.status,
            "items": [item.to_dict() for item in ordered_items],
            "warnings": self.warnings,
            **({"parser_warnings": self.parser_warnings} if self.parser_warnings else {}),
        }

    def write(self, path: Path) -> None:
        data = self.to_dict()
        with path.open("w", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(data, indent=2, sort_keys=True))
            fp.write("\n")


def make_manifest(input_path: Path, detected: DetectedFile, backend: str, size_bytes: int, sha256: str) -> Manifest:
    manifest_input = ManifestInput(
        path=str(input_path),
        size_bytes=size_bytes,
        sha256=sha256,
        detected_type=detected.detected_type,
    )
    manifest_tool = ManifestTool(name="deopjufy", version=__version__, backend=backend)
    return Manifest(input=manifest_input, tool=manifest_tool)
