"""Tests for discovery record shaping and split semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from deopjufier.discovery import _bracket_offsets_from_file, _token_offsets_from_file
from deopjufier.inventory import (
    HeuristicDiscoveryRecord,
    OpjObjectBoundary,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
)
from deopjufier.opju import OpjuHeaderRecord, OpjuRecords, OpjuRegionRecord
from deopjufier.session import ExtractionSession
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))


def test_discover_origin_objects_returns_typed_parser_backed_and_heuristic_records(tmp_path: Path, monkeypatch) -> None:
    sample = tmp_path / "mixed_types.opj"
    sample.write_bytes(b"CPYA 6.0 552#\nBook1_A some payload Graph1")

    header = b"CPYA 6.0 552#\n"
    boundary = OpjObjectBoundary(
        kind="worksheet",
        name="Book1_A",
        source_object_path="Book/Book1_A",
        start_offset=len(header),
        end_offset=len(header) + 7,
        length=7,
        confidence=0.92,
        parser_rule="test",
    )
    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        lambda *_args, **_kwargs: [boundary],
    )

    discovered = discover_origin_objects(sample, include_redundant_tokens=True)
    assert any(isinstance(item, ParserBackedDiscoveryRecord) for item in discovered)
    assert any(isinstance(item, HeuristicDiscoveryRecord) for item in discovered)


def test_list_items_preserves_parser_vs_heuristic_discovery_type(tmp_path: Path, monkeypatch) -> None:
    sample = tmp_path / "mixed_list.opj"
    sample.write_bytes(b"CPYA 6.0 552#\nBook1_A Graph1 Graph2")

    header = b"CPYA 6.0 552#\n"
    boundary = OpjObjectBoundary(
        kind="worksheet",
        name="Book1_A",
        source_object_path="Book/Book1_A",
        start_offset=len(header),
        end_offset=len(header) + 7,
        length=7,
        confidence=0.92,
        parser_rule="test",
    )
    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        lambda *_args, **_kwargs: [boundary],
    )

    session = ExtractionSession.from_path(sample)
    items = session.list_items(include_images=False)

    discovery_types = {item.get("discovery_type") for item in items}
    assert "opj_boundary" in discovery_types
    assert "object_discovery" in discovery_types

    assert any(item.get("discovery_type") == "opj_boundary" and item.get("heuristic") is False for item in items)
    assert any(item.get("discovery_type") == "object_discovery" and item.get("heuristic") is True for item in items)


def test_discover_origin_objects_uses_matrix_parser_source_path_instead_of_heuristic_alias() -> None:
    sample = REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj"
    if not sample.exists():
        pytest.skip("Fixture missing: refs/github/Ropj/inst/test.opj")

    objects = discover_origin_objects(sample, include_redundant_tokens=True)
    m_sheet1_items = [obj for obj in objects if obj.object_kind == "matrix" and obj.name == "MSheet1"]

    assert m_sheet1_items
    assert all(item.source_object_path.startswith("MBook1/MSheet1") for item in m_sheet1_items)
    assert all(item.parser_confirmed is True for item in m_sheet1_items)
    assert all(not item.source_object_path.startswith("MSheet/MSheet1") for item in m_sheet1_items)


def test_discover_origin_objects_limits_large_opju_heuristics_when_parser_regions_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "large.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00" + b"\x00" * (256 * 1024))

    parser_records = OpjuRecords(
        container=OpjuHeaderRecord(
            marker="CPYUA",
            version="4.3318",
            declared_length=0,
            header_length=16,
            raw_header=b"CPYUA 4.3318 0",
        ),
        regions=(
            OpjuRegionRecord(
                kind="origin_storage_report",
                name="Report1",
                offset=64,
                length=48,
                parser_rule="test",
                source_object_path="origin_storage_reports/Report1",
            ),
        ),
        report_records=(),
        worksheet_records=(),
        reports=(),
        worksheets=(),
    )

    monkeypatch.setattr(
        "deopjufier.inventory.parse_opju_records",
        lambda *_args, **_kwargs: parser_records,
    )

    heuristic_items = [
        HeuristicDiscoveryRecord(
            offset=index,
            name=f"Book1_{index}",
            length=8,
            object_kind="worksheet",
            source_object_path=f"Book/Book1_{index}",
            heuristic_signal="test",
        )
        for index in range(40)
    ]
    seen_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        "deopjufier.discovery._token_offsets_from_file",
        lambda *_args, **_kwargs: seen_kwargs.update(_kwargs) or heuristic_items,
    )
    monkeypatch.setattr(
        "deopjufier.discovery._bracket_offsets_from_file",
        lambda *_args, **_kwargs: [],
    )

    objects = discover_origin_objects(sample)
    assert objects
    parser_objects = [item for item in objects if item.parser_confirmed]
    heuristic_objects = [item for item in objects if not item.parser_confirmed]
    assert parser_objects
    assert heuristic_objects
    assert seen_kwargs["allowed_kinds"] == frozenset({"worksheet", "graph", "matrix", "note", "function", "excel"})
    assert seen_kwargs["total_limit"] == 64


def test_token_offsets_from_file_uses_mmap_fast_path(tmp_path: Path) -> None:
    sample = tmp_path / "mapped.opj"
    sample.write_bytes(b"noise Book1_A Graph1")

    objects = _token_offsets_from_file(sample)

    assert [item.name for item in objects] == ["Book1_A", "Graph1"]
    assert [item.offset for item in objects] == [6, 14]


def test_token_offsets_from_file_falls_back_when_mmap_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "streamed.opj"
    sample.write_bytes(b"noise Book1_A Graph1")

    class _NoMap:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_args: object) -> bool:
            return False

    monkeypatch.setattr("deopjufier.discovery.open_mmap", lambda _path: _NoMap())

    objects = _token_offsets_from_file(sample, chunk_size=8)

    assert [item.name for item in objects] == ["Book1_A", "Graph1"]
    assert [item.offset for item in objects] == [6, 14]


def test_bracket_offsets_from_file_uses_mmap_fast_path(tmp_path: Path) -> None:
    sample = tmp_path / "mapped_bracket.opj"
    sample.write_bytes(b"noise [Book1]Sheet1 tail")

    objects = _bracket_offsets_from_file(sample)

    assert [item.name for item in objects] == ["Book1/Sheet1"]
    assert [item.offset for item in objects] == [6]
