"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from deopjufier.cli import NATIVE_BACKEND
from deopjufier.detect import detect_file
from deopjufier.discovery import (
    _OPJ_DISCOVERY_STREAM_CHUNK_SIZE,
    _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES,
    _OPJ_PARSER_BOUNDARY_MAX_BYTES,
)
from deopjufier.extract import (
    list_items,
)
from deopjufier.extract.path_helpers import (
    unique_output_path as _unique_path,
)
from deopjufier.extract.raw_regions import RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY
from deopjufier.inventory import (
    HeuristicDiscoveryRecord,
    OpjObjectBoundary,
    OriginObject,
    ParserBackedDiscoveryRecord,
    _merge_parser_and_heuristic_objects,
    discover_origin_objects,
)
from deopjufier.io import dump_range, iter_file_chunks, read_cached_bytes, sanitize_name, sha256_file
from deopjufier.manifest import ManifestItem, make_manifest
from deopjufier.session import ExtractionSession
from tests.test_core_unit_coverage_utils import _repo_root, _resolve_tests_fixture

REPO_ROOT = _repo_root(Path(__file__))
SYNTHETIC_BINARY_FIXTURE = _resolve_tests_fixture(
    Path(__file__),
    Path("fixtures") / "synthetic" / "synthetic-cpyua-binary.opju",
)
SYNTHETIC_FIXTURE = _resolve_tests_fixture(Path(__file__), Path("fixtures") / "synthetic" / "synthetic-cpyua.opju")


def test_detect_file_opju_extension_stays_opju(tmp_path: Path) -> None:
    path = tmp_path / "sample.opju"
    path.write_bytes(b"not-binary")

    payload = detect_file(path)
    assert payload.detected_type == "opju"
    assert payload.reason == "extension"


def test_detect_file_extension_is_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "sample.OPJ"
    path.write_bytes(b"not-binary")

    payload = detect_file(path)
    assert payload.detected_type == "opj"
    assert payload.reason == "extension"


def test_detect_file_opj_extension_stays_opj(tmp_path: Path) -> None:
    path = tmp_path / "sample.opj"
    path.write_bytes(b"abc")

    payload = detect_file(path)
    assert payload.detected_type == "opj"
    assert payload.reason == "extension"


def test_detect_file_unknown_magic_only(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"\x00\x01\x02\x03\x04")

    payload = detect_file(path)
    assert payload.detected_type == "unknown"
    assert payload.reason == "no-match"


def test_detect_file_magic_samples(tmp_path: Path) -> None:
    zip_sample = tmp_path / "zip.bin"
    zip_sample.write_bytes(b"PK\x03\x04" + b"\x00" * 20)
    assert detect_file(zip_sample).detected_type == "zip_container"

    opju_magic = tmp_path / "opju_magic.bin"
    opju_magic.write_bytes(b"CPYUA" + b"\x00" * 20)
    assert detect_file(opju_magic).detected_type == "opju"

    opj_magic = tmp_path / "opj_magic.bin"
    opj_magic.write_bytes(b"CPYA" + b"\x00" * 20)
    assert detect_file(opj_magic).detected_type == "opj"

    sqlite_sample = tmp_path / "sqlite.bin"
    sqlite_sample.write_bytes(b"SQLite format 3\x00" + b"\x00" * 20)
    assert detect_file(sqlite_sample).detected_type == "sqlite_db"

    jpeg_sample = tmp_path / "jpeg.bin"
    jpeg_sample.write_bytes(b"\xff\xd8\xff\xd9")
    assert detect_file(jpeg_sample).detected_type == "jpeg"


def test_detect_extension_mismatch_still_records_magic_type(tmp_path: Path) -> None:
    sample = tmp_path / "mismatch.opju"
    sample.write_bytes(b"CPYA" + b"\x00" * 20)

    detected = detect_file(sample)
    assert detected.detected_type == "opj"
    assert detected.reason == "magic"
    assert detected.magic_type == "opj"
    assert detected.magic_offset == 0


def test_make_manifest_and_write_has_stable_payload(tmp_path: Path) -> None:
    project = tmp_path / "tiny.opj"
    project.write_bytes(b"\x50\x4b\x03\x04")
    detection = detect_file(project)
    manifest = make_manifest(
        project,
        detection,
        NATIVE_BACKEND,
        size_bytes=project.stat().st_size,
        sha256=sha256_file(project),
    )

    manifest.add_item(
        ManifestItem(
            kind="image",
            name="x",
            status="extracted",
            confidence=0.1,
            object_kind="graph",
            path="out/x.bin",
            rows=1,
            columns=2,
            offset=1,
            length=2,
        )
    )
    manifest.add_warning("plan")
    payload_path = tmp_path / "manifest.json"
    manifest.write(payload_path)

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["tool"]["backend"] == NATIVE_BACKEND
    assert payload["input"]["detected_type"] == "opj"
    assert payload["items"][0]["path"] == "out/x.bin"
    assert payload["items"][0]["object_kind"] == "graph"
    assert payload["warnings"] == ["plan"]


def test_manifest_write_uses_lf_line_endings(tmp_path: Path) -> None:
    project = tmp_path / "tiny.opj"
    project.write_bytes(b"\x50\x4b\x03\x04")
    detection = detect_file(project)
    manifest = make_manifest(
        project,
        detection,
        NATIVE_BACKEND,
        size_bytes=project.stat().st_size,
        sha256=sha256_file(project),
    )
    payload_path = tmp_path / "manifest.json"
    manifest.write(payload_path)

    raw = payload_path.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


def test_extraction_session_caches_file_data(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"Book1_A\n1 2 3")

    session = ExtractionSession.from_path(sample)
    assert session.size_bytes == sample.stat().st_size
    first = session.file_data()
    second = session.file_data()
    assert first == second


def test_sha256_file_uses_stat_keyed_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "cache.bin"
    sample.write_bytes(b"abc")

    calls = {"count": 0}
    original = iter_file_chunks

    def _counting_chunks(path: Path, chunk_size: int = 1 << 20):
        calls["count"] += 1
        yield from original(path, chunk_size)

    monkeypatch.setattr("deopjufier.io.iter_file_chunks", _counting_chunks)

    first = sha256_file(sample)
    second = sha256_file(sample)

    assert first == second
    assert calls["count"] == 1


def test_read_cached_bytes_uses_stat_keyed_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "bytes-cache.bin"
    sample.write_bytes(b"payload")

    calls = {"count": 0}
    original = Path.read_bytes

    def _counting_read_bytes(self: Path) -> bytes:
        calls["count"] += 1
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", _counting_read_bytes)

    first = read_cached_bytes(sample)
    second = read_cached_bytes(sample)

    assert first == second == b"payload"
    assert calls["count"] == 1


def test_extraction_session_caches_objects_and_tables(tmp_path: Path) -> None:
    sample = tmp_path / "session.opj"
    sample.write_bytes(b"Book1_A\n1 2 3")

    session = ExtractionSession.from_path(sample)
    objects_first = session.objects()
    objects_second = session.objects()
    assert objects_first == objects_second

    rows_first = session.table_rows(min_rows=1, min_columns=2)
    rows_second = session.table_rows(min_rows=1, min_columns=2)
    assert rows_first == rows_second


def test_extraction_session_caches_list_items(tmp_path: Path) -> None:
    sample = tmp_path / "session_items.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\nGraph1\n")

    session = ExtractionSession.from_path(sample)
    first = session.list_items()
    second = session.list_items()

    assert first == second


def test_manifest_items_are_stably_sorted_before_write(tmp_path: Path) -> None:
    target = tmp_path / "tiny.opju"
    target.write_bytes(b"abc")
    detection = detect_file(target)
    manifest = make_manifest(
        target,
        detection,
        NATIVE_BACKEND,
        size_bytes=10,
        sha256="0" * 64,
    )
    manifest.add_item(ManifestItem(kind="table_scan", name="z", status="extracted", confidence=0.1, path="b"))
    manifest.add_item(ManifestItem(kind="image", name="a", status="extracted", confidence=0.1, path="a"))
    manifest.add_item(ManifestItem(kind="image", name="b", status="extracted", confidence=0.1, path="a"))

    payload = manifest.to_dict()
    paths = [item["path"] for item in payload["items"]]
    assert paths == ["a", "a", "b"]


def test_manifest_schema_is_strict_and_status_is_valid(tmp_path: Path) -> None:
    project = tmp_path / "tiny.opj"
    project.write_bytes(b"\x50\x4b\x03\x04")
    detection = detect_file(project)
    manifest = make_manifest(
        project,
        detection,
        NATIVE_BACKEND,
        size_bytes=project.stat().st_size,
        sha256=sha256_file(project),
    )

    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Data",
            status="extracted",
            confidence=0.99,
            object_kind="worksheet",
            path="tables/Data.csv",
            source_object_path="Book/Book1/Data",
            rows=2,
            columns=3,
            offset=0,
            length=12,
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="table_scan",
            name="scan",
            status="partial",
            confidence=0.35,
            path="tables/scan.csv",
            source_object_path="Scan/scan",
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="raw_dump",
            name="gap",
            status="skipped",
            confidence=0.0,
            source_object_path="raw/gap",
            error="target_exists",
        )
    )

    payload = manifest.to_dict()
    assert set(payload.keys()) >= {"input", "tool", "items", "warnings"}
    assert "status" not in payload or payload["status"] in {"ok", "partial", "unsupported"}
    assert payload["input"]["path"] == str(project)
    assert payload["tool"]["name"] == "deopjufy"
    assert payload["tool"]["backend"] == NATIVE_BACKEND
    assert payload["tool"]["version"]
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) == 3
    assert payload["warnings"] == []

    required_item_keys = {"kind", "name", "status", "confidence"}
    allowed_statuses = {"extracted", "partial", "skipped"}
    for item in payload["items"]:
        assert required_item_keys <= set(item.keys())
        assert item["kind"]
        assert item["name"]
        assert item["status"] in allowed_statuses
        assert 0.0 <= item["confidence"] <= 1.0
        if "path" in item:
            assert item["path"] == "tables/Data.csv" or item["path"] == "tables/scan.csv"
            assert not Path(item["path"]).is_absolute()
        if "offset" in item:
            assert isinstance(item["offset"], int)
            assert item["offset"] >= 0
        if "length" in item:
            assert isinstance(item["length"], int)
            assert item["length"] >= 0
        if "rows" in item:
            assert isinstance(item["rows"], int)
            assert item["rows"] > 0
        if "columns" in item:
            assert isinstance(item["columns"], int)
            assert item["columns"] > 0


def test_manifest_item_auto_ranges_and_methods_are_emitted() -> None:
    item_from_offset = ManifestItem(
        kind="worksheet",
        name="A",
        status="extracted",
        confidence=1.0,
        offset=10,
        length=7,
        discovery_type="parser_window",
    )
    item_from_range = ManifestItem(
        kind="worksheet",
        name="B",
        status="partial",
        confidence=0.6,
        range_start=100,
        range_end=125,
        offset=1_000,
        length=50,
        discovery_type="heuristic_object_scan",
    )

    assert item_from_offset.source_ranges == [{"start": 10, "end": 17}]
    assert item_from_range.source_ranges == [{"start": 100, "end": 125}]
    assert item_from_offset.discovery_method == "parser_window"
    assert item_from_range.discovery_method == "heuristic_object_scan"


def test_iter_file_chunks_respects_chunk_size(tmp_path: Path) -> None:
    sample = tmp_path / "chunk.bin"
    sample.write_bytes(b"abcdef")

    chunks = list(iter_file_chunks(sample, chunk_size=2))
    assert chunks == [b"ab", b"cd", b"ef"]


def test_sanitize_name_keeps_safe_and_replaces_unsafe() -> None:
    assert sanitize_name("a b") == "a_b"
    assert sanitize_name("a/b\\c") == "a_b_c"
    assert sanitize_name(".") == "item"
    assert sanitize_name("CON") == "_CON"
    assert sanitize_name("con.txt") == "_con.txt"
    assert sanitize_name("   ") == "item"
    assert sanitize_name("LPT1 ") == "_LPT1"
    assert sanitize_name("Name.") == "Name"
    assert sanitize_name("пример") == "______"
    assert sanitize_name("ノート") == "___"


def test_unique_path_avoids_case_insensitive_collision(tmp_path: Path) -> None:
    base = tmp_path / "out"
    base.mkdir()
    (base / "Book.csv").write_text("seed", encoding="utf-8")
    assert _unique_path(base, "book.csv").name == "book__2.csv"


def test_dump_range_read_past_end_and_negative_offsets(tmp_path: Path) -> None:
    sample = tmp_path / "r.bin"
    sample.write_bytes(b"abcde")

    assert dump_range(sample, 10, 10) == b""
    with pytest.raises(ValueError, match="non-negative"):
        dump_range(sample, -1, 2)
    with pytest.raises(ValueError, match="non-negative"):
        dump_range(sample, 1, -2)


def test_list_items_matches_block_inventory(tmp_path: Path) -> None:
    valid_jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + b"\x01\x02"
        + b"\xff\xd9"
    )

    sample = tmp_path / "blocks.opju"
    data = (
        b"\x00\x00"
        + b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
        + valid_jpeg
        + b"\x00"
        + b"<svg>x</svg>"
    )
    sample.write_bytes(data)

    items = list_items(sample)
    kinds = {item["kind"] for item in items}
    assert {"png", "jpeg", "svg"} <= kinds
    assert len(items) == 3
    assert all(item["offset"] >= 0 for item in items)


def test_session_list_items_can_include_raw_gaps(tmp_path: Path) -> None:
    sample = tmp_path / "raw_gaps.opju"
    sample.write_bytes(b"\x00" * 6)
    session = ExtractionSession.from_path(sample)

    without_gaps = session.list_items()
    with_gaps = session.list_items(include_raw_gaps=True)

    assert without_gaps == []
    assert any(item.get("discovery_type") == "unknown_gap" and item.get("kind") == "raw_dump" for item in with_gaps)
    raw_items = [
        item for item in with_gaps if item.get("discovery_type") == "unknown_gap" and item.get("kind") == "raw_dump"
    ]
    assert raw_items
    assert raw_items[0].get("object_kind") in {
        RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY,
    }
    assert len(with_gaps) >= 1


def test_session_prefers_opj_matrix_sheet_over_duplicate_book_and_token_objects(tmp_path: Path) -> None:
    sample = tmp_path / "matrix-book.opj"
    sample.write_bytes(b"CPYA 6.0 552#\n")
    session = ExtractionSession.from_path(sample)
    supplied: list[OriginObject] = [
        ParserBackedDiscoveryRecord(0, "MBook1", 10, "matrix", "MBook/MBook1", parser_rule="opj_window"),
        ParserBackedDiscoveryRecord(
            10,
            "MSheet1",
            10,
            "matrix",
            "MBook1/MSheet1",
            parser_rule="opj_tree_reference",
        ),
        HeuristicDiscoveryRecord(20, "PdMSheet1", 10, "matrix", "PdM/PdMSheet1"),
    ]

    objects, allow_parser_recovery = session.objects_for_tabular_extraction(
        sample.read_bytes(),
        object_kind="matrix",
        supplied_objects=supplied,
    )

    assert [item.name for item in objects if item.object_kind == "matrix"] == ["MSheet1"]
    assert allow_parser_recovery is True


def test_list_items_marks_object_kind_for_origin_objects(tmp_path: Path) -> None:
    sample = tmp_path / "objects_for_kind.opj"
    sample.write_text("Book1_A Graph1 PdMSheet1 O2O_A", encoding="utf-8")

    items = list_items(sample)
    origin_items = [item for item in items if item["kind"] == "origin_object"]
    assert origin_items
    kinds = {item.get("object_kind") for item in origin_items}
    assert "worksheet" in kinds


def test_discover_origin_objects_from_name_tokens(tmp_path: Path) -> None:
    sample = tmp_path / "inventory.opju"
    data = b"Header" + b"Book1_A" + b"\x00" + b"Graph1" + b"\x00" + b"PdMSheet1" + b"\x00"
    sample.write_bytes(data)

    objects = discover_origin_objects(sample)
    names = [obj.name for obj in objects]

    assert "Book1_A" in names
    assert "Graph1" in names
    assert "PdMSheet1" in names
    assert all(obj.offset >= 0 for obj in objects)
    assert any(obj.object_kind for obj in objects)
    assert next(obj.source_object_path for obj in objects if obj.name == "Book1_A").startswith("Book/Book1_A")


def test_merge_parser_and_heuristic_records_prefers_parser_confirmed_objects() -> None:
    parser_objects = [
        ParserBackedDiscoveryRecord(
            offset=10,
            name="Graph1",
            length=90,
            object_kind="graph",
            source_object_path="Graph/Graph1",
            parser_rule="opj_graph_payload",
            parser_confidence=0.92,
        ),
        ParserBackedDiscoveryRecord(
            offset=500,
            name="Layer1",
            length=80,
            object_kind="layer",
            source_object_path="Layer/Layer1",
            parser_rule="opj_graph_payload",
            parser_confidence=0.9,
        ),
        ParserBackedDiscoveryRecord(
            offset=700,
            name="Results",
            length=40,
            object_kind="note",
            source_object_path="object/Results",
            parser_rule="opj_note_section",
            parser_confidence=0.8,
        ),
    ]

    heuristic_objects = [
        HeuristicDiscoveryRecord(
            offset=10,
            name="Graph1",
            length=90,
            object_kind="graph",
            source_object_path="Graph/Graph1",
            heuristic_signal="token",
        ),
        HeuristicDiscoveryRecord(
            offset=120,
            name="Graph1",
            length=90,
            object_kind="graph",
            source_object_path="Graph/Graph1__2",
            heuristic_signal="token",
        ),
        HeuristicDiscoveryRecord(
            offset=700,
            name="Results",
            length=40,
            object_kind="note",
            source_object_path="object/Results",
            heuristic_signal="token",
        ),
        HeuristicDiscoveryRecord(
            offset=900,
            name="LayerGridStyle",
            length=20,
            object_kind="layer",
            source_object_path="Layer/LayerGridStyle",
            heuristic_signal="token",
        ),
    ]

    merged = _merge_parser_and_heuristic_objects(
        cast(list[OriginObject], parser_objects),
        cast(list[OriginObject], heuristic_objects),
    )
    merged_names = [(entry.object_kind, entry.name, entry.offset, entry.parser_confirmed) for entry in merged]

    assert len(merged) == 5
    assert ("graph", "Graph1", 10, True) in merged_names
    assert ("graph", "Graph1", 10, False) not in merged_names
    assert ("graph", "Graph1", 120, False) in merged_names
    assert ("note", "Results", 700, False) not in merged_names
    assert ("layer", "LayerGridStyle", 900, False) in merged_names
    assert ("layer", "Layer1", 500, True) in merged_names


def test_merge_parser_and_heuristic_records_prefers_parser_objects_on_overlap() -> None:
    parser_objects = [
        ParserBackedDiscoveryRecord(
            offset=120,
            name="Graph1",
            length=90,
            object_kind="graph",
            source_object_path="Graph/Graph1",
            parser_rule="opj_graph_payload",
            parser_confidence=0.92,
        ),
    ]

    heuristic_objects = [
        HeuristicDiscoveryRecord(
            offset=80,
            name="Graph1",
            length=90,
            object_kind="graph",
            source_object_path="Graph/Graph1",
            heuristic_signal="token",
        ),
        HeuristicDiscoveryRecord(
            offset=130,
            name="Graph1",
            length=90,
            object_kind="graph",
            source_object_path="Graph/Graph1__2",
            heuristic_signal="token",
        ),
        HeuristicDiscoveryRecord(
            offset=220,
            name="Graph1",
            length=40,
            object_kind="graph",
            source_object_path="Graph/Graph1__3",
            heuristic_signal="token",
        ),
    ]

    merged = _merge_parser_and_heuristic_objects(
        cast(list[OriginObject], parser_objects),
        cast(list[OriginObject], heuristic_objects),
    )
    merged_names = [(entry.object_kind, entry.name, entry.offset, entry.parser_confirmed) for entry in merged]

    assert len(merged_names) == 3
    assert ("graph", "Graph1", 120, True) in merged_names
    assert ("graph", "Graph1", 80, False) not in merged_names
    assert ("graph", "Graph1", 130, False) in merged_names
    assert ("graph", "Graph1", 220, False) in merged_names


def test_discovery_repeat_limit_reserves_parser_owned_cross_kind_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "parser-name-limit.opj"
    sample.write_bytes(b"CPYA 6.0 552#\nBook1\x00Book1\x00")
    parser_excel = ParserBackedDiscoveryRecord(
        offset=100,
        name="Book1",
        length=20,
        object_kind="excel",
        source_object_path="Book1",
        parser_rule="opj_window",
    )
    heuristics = [
        HeuristicDiscoveryRecord(10, "Book1", 5, "worksheet", "Book/Book1"),
        HeuristicDiscoveryRecord(20, "Book1", 5, "worksheet", "Book/Book1__2"),
    ]
    monkeypatch.setattr("deopjufier.inventory._parse_opj_objects", lambda *_args, **_kwargs: [parser_excel])
    monkeypatch.setattr("deopjufier.inventory.discovery_helpers._token_offsets", lambda *_args, **_kwargs: heuristics)
    monkeypatch.setattr("deopjufier.inventory.discovery_helpers._bracket_offsets", lambda *_args, **_kwargs: [])

    objects = discover_origin_objects(sample, max_repeats_per_name=2)

    book_objects = [item for item in objects if item.name == "Book1"]
    assert len(book_objects) == 2
    assert parser_excel in book_objects


def test_discover_origin_objects_from_bracketed_references(tmp_path: Path) -> None:
    sample = tmp_path / "inventory_bracket.opju"
    sample.write_bytes(b'left [Book4]Sheet1!(A"x",B"y") [MBook1]MSheet1 suffix')

    objects = discover_origin_objects(sample)
    names = [obj.name for obj in objects]
    assert "Book4/Sheet1" in names
    assert "MBook1/MSheet1" in names
    assert "Book4/Sheet1" in [obj.source_object_path for obj in objects if obj.name == "Book4/Sheet1"]


def test_discover_origin_objects_large_opj_uses_streaming(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    threshold = _OPJ_PARSER_BOUNDARY_MAX_BYTES + 1
    sample = tmp_path / "large.opj"
    sample.write_bytes(b"CPYA\0" + b"\x00" * (threshold - 1) + b"Graph1")

    calls = {"parse_count": 0}

    def count_parse_boundaries(*_args, **_kwargs) -> list[OpjObjectBoundary]:
        calls["parse_count"] += 1
        return []

    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        count_parse_boundaries,
    )

    objects = discover_origin_objects(sample)
    assert any(obj.name == "Graph1" for obj in objects)
    assert calls["parse_count"] == 1


def test_discover_origin_objects_medium_opj_uses_parser_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    threshold = _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
    sample = tmp_path / "medium_boundary.opj"
    sample.write_bytes(b"CPYA\0" + b"\x00" * (threshold - 1) + b"Graph1")

    calls = {"count": 0}

    def fake_parse_boundaries(*_args, **_kwargs) -> list[OpjObjectBoundary]:
        calls["count"] += 1
        return [
            OpjObjectBoundary(
                kind="graph",
                name="Graph1",
                source_object_path="Graph/Graph1",
                start_offset=0,
                end_offset=10,
                length=10,
                confidence=0.75,
                parser_rule="parser",
            )
        ]

    monkeypatch.setattr("deopjufier.inventory.parse_opj_boundaries", fake_parse_boundaries)

    objects = discover_origin_objects(sample)
    assert calls["count"] == 1
    assert any(obj.name == "Graph1" for obj in objects)


def test_discover_origin_objects_large_opj_scans_tokens_across_chunks(tmp_path: Path) -> None:
    chunk_size = _OPJ_DISCOVERY_STREAM_CHUNK_SIZE
    payload = bytearray(b"CPYA\0")
    payload.extend(b"\x00" * (chunk_size - len(payload) - 2))
    payload.extend(b"Bo")
    payload.extend(b"ok1_A")
    sample = tmp_path / "cross_boundary.opj"
    sample.write_bytes(payload)

    objects = discover_origin_objects(sample)
    assert "Book1_A" in [obj.name for obj in objects]
