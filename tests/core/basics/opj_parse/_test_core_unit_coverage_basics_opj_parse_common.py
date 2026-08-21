"""Unit-level coverage tests for core modules and uncovered branches."""

# ruff: noqa: F401

from __future__ import annotations

import json
import struct
from collections.abc import Iterable
from pathlib import Path

import pytest

import deopjufier.inventory
from deopjufier.discovery import (
    _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES,
    _OPJ_PARSER_BOUNDARY_MAX_BYTES,
    _classify_object_kind,
    _derive_source_path,
    _ensure_unique_paths,
)
from deopjufier.inventory import (
    OpjDataSection,
    OpjObjectBoundary,
    OriginObject,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
    iter_object_windows,
    parse_opj_boundaries,
    parse_opj_note_sections,
    parse_opj_parameters,
    parse_opj_worksheet_metadata,
)
from deopjufier.opj import (
    OpjTreeOwnership,
    OpjWalkElement,
    iter_opj_data_sections,
    parse_opj_tree_nodes,
    parse_opj_tree_ownership_links,
    parse_opj_tree_references,
    walk_opj_file,
)
from deopjufier.opj.recovery import recover_matrix_metadata_from_opj_sections
from deopjufier.opj.stream import OpjStream, OpjStreamError
from tests.test_core_unit_coverage_utils import (
    _repo_root,
    _resolve_synthetic_fixture,
)

REPO_ROOT = _repo_root(Path(__file__))
SYNTHETIC_BINARY_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua-binary.opju")
SYNTHETIC_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua.opju")
TREE_MATRIX_EVIDENCE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "opj-tree-matrix-ownership-evidence.json"


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _build_opj_walk_dataset(name: str) -> bytes:
    payload = bytearray(0x73)
    encoded = name.encode("ascii")
    payload[0x58 : 0x58 + len(encoded)] = encoded
    return _u32(len(payload)) + b"\n" + bytes(payload) + b"\n" + _u32(0) + b"\n" + _u32(0) + b"\n"


def _build_opj_note_window(name: str, label: str, text: str) -> bytes:
    header = bytearray(32)
    name_bytes = name.encode("ascii")[:25]
    header[: len(name_bytes)] = name_bytes

    label_bytes = (label + "\x00").encode("utf-8")
    text_bytes = text.encode("utf-8")
    return (
        _u32(len(header))
        + b"\n"
        + bytes(header)
        + b"\n"
        + _u32(len(label_bytes))
        + b"\n"
        + label_bytes
        + b"\n"
        + _u32(len(text_bytes))
        + b"\n"
        + text_bytes
        + b"\n"
    )


def _build_opj_note_window_with_raw_bytes(name_bytes: bytes, label: bytes, text: str) -> bytes:
    header = bytearray(32)
    header[: min(len(name_bytes), len(header))] = name_bytes[: len(header)]

    return (
        _u32(len(header))
        + b"\n"
        + bytes(header)
        + b"\n"
        + _u32(len(label))
        + b"\n"
        + label
        + b"\n"
        + _u32(len(text))
        + b"\n"
        + text.encode("utf-8")
        + b"\n"
    )


def _build_opj_global_header() -> bytes:
    return _u32(4) + b"\n" + b"HEAD" + b"\n" + _u32(0) + b"\n"


def _build_opj_walk_window(name: str, *, label: str | None = None) -> bytes:
    header = bytearray(0xC4)
    encoded = name.encode("ascii", errors="replace")[:25]
    header[0x02 : 0x02 + len(encoded)] = encoded
    if label:
        label_bytes = label.encode("utf-8", errors="replace")
        header[0xC3 : 0xC3 + len(label_bytes)] = label_bytes
    return _u32(len(header)) + b"\n" + bytes(header) + b"\n" + _u32(0) + b"\n"


def _build_opj_walk_window_with_title_mode(name: str, *, label: str | None = None, title_mode: int = 0) -> bytes:
    header = bytearray(0xC4)
    encoded = name.encode("ascii", errors="replace")[:25]
    header[0x02 : 0x02 + len(encoded)] = encoded
    if label:
        label_bytes = label.encode("utf-8", errors="replace")
        header[0xC3 : 0xC3 + len(label_bytes)] = label_bytes
    header[0x69] = title_mode
    return _u32(len(header)) + b"\n" + bytes(header) + b"\n" + _u32(0) + b"\n"


__all__ = [name for name in globals() if not name.startswith("__")]
