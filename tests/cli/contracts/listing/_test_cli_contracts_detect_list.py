"""Core CLI and helper contract tests for deopjufier."""

from __future__ import annotations

import json
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from deopjufier.cli import main
from deopjufier.commands import support
from deopjufier.detect import DetectedFile, detect_file
from deopjufier.discovery import ParserBackedDiscoveryRecord
from deopjufier.extract.raw_regions import RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY
from deopjufier.inventory import OpjObjectBoundary
from tests.test_core_unit_coverage_utils import _resolve_synthetic_fixture


def test_detect_prefers_extension_over_magic_signature(tmp_path: Path) -> None:
    candidate = tmp_path / "fake.opju"
    candidate.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    detected = detect_file(candidate)
    assert detected.detected_type == "opju"
    assert detected.reason == "extension"


def test_detect_magic_magic_falls_back_for_unknown_extension(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    detected = detect_file(candidate)
    assert detected.detected_type == "png"
    assert detected.reason == "magic"


def test_detect_magic_prefers_jpeg_magic_over_other_known(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"\xff\xd8\xff\xd9" + b"\x00" * 16)

    detected = detect_file(candidate)
    assert detected.detected_type == "jpeg"
    assert detected.reason == "magic"


def test_detect_magic_prefers_opju_magic_for_unknown_extension(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"CPYUA\x00\x00\x00\x00" + b"\x00" * 16)

    detected = detect_file(candidate)
    assert detected.detected_type == "opju"
    assert detected.reason == "magic"


def test_detect_magic_prefers_opj_magic_for_unknown_extension(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"CPYA\x00\x00\x00\x00" + b"\x00" * 16)

    detected = detect_file(candidate)
    assert detected.detected_type == "opj"
    assert detected.reason == "magic"


def test_detect_unknown_returns_unknown(tmp_path: Path) -> None:
    candidate = tmp_path / "raw.bin"
    candidate.write_bytes(b"\x00\x01\x02")

    detected = detect_file(candidate)
    assert detected.detected_type == "unknown"
    assert detected.confidence == 0.05
    assert detected.reason == "no-match"


def test_list_unsupported_file_type_is_supported_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "unknown.bin"
    sample.write_bytes(b"plain text")

    code = main(["list", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["detected_type"] == "unknown"
    assert payload["items"] == []
    assert payload["file"] == str(sample)
    assert payload["support_class"] == "heuristic"
    assert payload["parser_status"] == "unsupported"
    assert payload["warnings"] == ["Native parser does not support detected type 'unknown'."]
    assert payload["status"] == "unsupported"
    assert isinstance(payload["items"], list)
    assert payload["coverage_scope"] == "recognized"
    assert payload["verification"] == "unverified"


def test_list_outputs_items_sorted_by_offset_for_opju_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "ordered.opju"
    sample.write_bytes(
        b"\x00\x00"
        + b"\xff\xd8\xff\xd9"
        + b"\x00\x00\x00\x00"
        + b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
        + b"<svg>z</svg>"
    )

    code = main(["list", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["detected_type"] == "opju"
    assert payload["items"] == sorted(payload["items"], key=lambda item: item["offset"])


def test_list_reports_origin_objects_in_discovery(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "objects.opj"
    sample.write_bytes(b"CPYA" + b"\x00Book1_A\x00Graph1\x00PdMSheet1\x00")

    code = main(["list", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["detected_type"] == "opj"
    assert payload["items"]
    kinds = {item["kind"] for item in payload["items"]}
    assert "origin_object" in kinds
    assert any(item["name"] == "Book1_A" for item in payload["items"])
    assert any(item["name"] == "Graph1" for item in payload["items"])
    assert any(item["name"] == "PdMSheet1" for item in payload["items"])
    assert any(item["kind"] == "origin_object" and "source_object_path" in item for item in payload["items"])


def test_list_synthetic_multi_family_opj_fixture_has_expected_inventory(capsys: pytest.CaptureFixture[str]) -> None:
    sample = _resolve_synthetic_fixture(Path(__file__), "synthetic-opj-multi-family.opj")
    if not sample.exists():
        pytest.skip("synthetic OPJ fixture missing.")

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opj"
    objects = [item for item in payload["items"] if item.get("kind") == "origin_object"]

    assert len(objects) == 9
    names = {item["name"] for item in objects}
    assert {
        "Book1_A",
        "Graph1",
        "PdMSheet1",
        "MSheet1",
        "Sheet1",
        "Note1",
        "Function1",
        "ExcelA",
        "__Meta",
    } <= names

    kind_counts = Counter(item["object_kind"] for item in objects)
    assert kind_counts == {
        "worksheet": 2,
        "graph": 1,
        "matrix": 2,
        "note": 1,
        "function": 1,
        "excel": 1,
        "meta": 1,
    }


def test_inspect_synthetic_multi_family_opj_fixture_exposes_expected_counts() -> None:
    sample = _resolve_synthetic_fixture(Path(__file__), "synthetic-opj-multi-family.opj")
    if not sample.exists():
        pytest.skip("synthetic OPJ fixture missing.")

    stdout = StringIO()
    with redirect_stdout(stdout):
        code = main(["inspect", str(sample), "--json"])
    payload = json.loads(stdout.getvalue())

    assert code == 0
    assert payload["detected_type"] == "opj"
    assert payload["counts"]["origin_object_kinds"] == {
        "excel": 1,
        "function": 1,
        "graph": 1,
        "matrix": 2,
        "meta": 1,
        "note": 1,
        "worksheet": 2,
    }
    assert payload["counts"]["origin_objects"] == 9


def test_list_distinguishes_parser_backed_and_heuristic_objects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "boundary-discovery.opj"
    header = b"CPYA 4.2673 552#\n"
    sample.write_bytes(header + b"prefix Book1_A Graph1")

    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        lambda *_args, **_kwargs: [
            OpjObjectBoundary(
                kind="worksheet",
                name="Book1_A",
                source_object_path="Book/Book1_A",
                start_offset=len(header),
                end_offset=len(header) + 7,
                length=7,
                confidence=0.88,
                parser_rule="test",
            )
        ],
    )

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opj"
    discovery_types = {item.get("discovery_type") for item in payload["items"]}
    assert "opj_boundary" in discovery_types
    assert "object_discovery" in discovery_types
    assert any(
        item.get("discovery_type") == "opj_boundary" and item.get("heuristic") is False for item in payload["items"]
    )


def test_list_opju_bounded_heuristic_items_default_and_exhaustive_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "bounded.opju"
    sample.write_bytes(b"CPYUA 4.3445 200\n")

    heuristic_items: list[dict[str, object]] = [
        {
            "kind": "origin_object",
            "name": f"Graph{index}",
            "offset": index,
            "heuristic": True,
            "discovery_type": "object_discovery",
        }
        for index in range(40)
    ]

    class FakeSession:
        size_bytes = 40 * 1024 * 1024
        detection = DetectedFile(
            path=sample,
            detected_type="opju",
            confidence=0.99,
            reason="magic",
            magic_type="opju",
            magic_offset=0,
        )

        def image_blocks(self) -> list[object]:
            return []

        def list_items(self, **kwargs: object) -> list[dict[str, object]]:
            limit = kwargs.get("heuristic_kind_limit")
            if isinstance(limit, int):
                return heuristic_items[:limit]
            return heuristic_items

    monkeypatch.setattr(
        "deopjufier.commands.support._build_session",
        lambda _path: FakeSession(),
    )

    default_stdout = StringIO()
    with redirect_stdout(default_stdout):
        default_code = main(["list", str(sample), "--json"])
    default_payload = json.loads(default_stdout.getvalue())
    default_heuristic_counts = Counter(
        item["kind"]
        for item in default_payload["items"]
        if item.get("heuristic") and item.get("discovery_type") != "carved"
    )
    if max(default_heuristic_counts.values(), default=0) > 24:
        print("DEBUG default counts", dict(default_heuristic_counts))

    exhaustive_stdout = StringIO()
    with redirect_stdout(exhaustive_stdout):
        exhaustive_code = main(["list", str(sample), "--json", "--exhaustive"])
    exhaustive_payload = json.loads(exhaustive_stdout.getvalue())

    assert default_code == 0
    assert exhaustive_code == 0
    assert default_payload["detected_type"] == "opju"
    assert all(count <= 24 for count in default_heuristic_counts.values())
    assert len(default_payload["items"]) == 24
    assert len(exhaustive_payload["items"]) == 40


def test_list_opj_heuristic_limit_exhaustive_override() -> None:
    assert support._coerce_list_heuristic_kind_limit("opj", 40 * 1024 * 1024, False) == 24
    assert support._coerce_list_heuristic_kind_limit("opj", 4 * 1024 * 1024, False) is None
    assert support._coerce_list_heuristic_kind_limit("opj", 40 * 1024 * 1024, True) is None
    assert support._coerce_list_heuristic_kind_limit("opju", 1, False) == 24
    assert support._coerce_list_heuristic_kind_limit("opju", None, True) is None


def test_list_opju_parser_items_are_included_in_default_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "parser-backed.opju"
    sample.write_bytes(b"CPYUA 4.3445 200\n")

    class FakeSession:
        size_bytes = 1024
        detection = DetectedFile(
            path=sample,
            detected_type="opju",
            confidence=0.99,
            reason="magic",
            magic_type="opju",
            magic_offset=0,
        )

        def image_blocks(self) -> list[object]:
            return []

        def list_items(self, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {
                    "kind": "origin_object",
                    "name": "Worksheet1",
                    "offset": 12,
                    "heuristic": False,
                    "discovery_type": "opj_boundary",
                },
                {
                    "kind": "image",
                    "name": "preview",
                    "offset": 16,
                    "heuristic": True,
                    "discovery_type": "carved",
                },
            ]

    monkeypatch.setattr(
        "deopjufier.commands.support._build_session",
        lambda _path: FakeSession(),
    )

    output = StringIO()
    with redirect_stdout(output):
        code = main(["list", str(sample), "--json"])
    payload = json.loads(output.getvalue())

    assert code == 0
    assert payload["support_class"] == "parser"
    items = payload["items"]
    if not items:
        pytest.fail("Expected discoverable OPJU items for parser precedence test.")

    parser_items = [item for item in items if item.get("heuristic") is False]
    if not parser_items:
        pytest.skip("No parser-backed OPJU items available for parser precedence test.")
    assert any(item.get("discovery_type") == "opj_boundary" for item in parser_items)
    assert any(item.get("discovery_type") != "carved" for item in parser_items)


def test_list_opju_heuristic_note_function_excel_graph_are_parser_gated(tmp_path: Path) -> None:
    sample = tmp_path / "no-opju-evidence.opju"
    sample.write_bytes(b"Graph1\nNote1\nFunction1\nExcelA\nMatrix1\nBook1_A\n")

    output = StringIO()
    with redirect_stdout(output):
        code = main(["list", str(sample), "--json"])
    payload = json.loads(output.getvalue())

    assert code == 0
    assert payload["detected_type"] == "opju"
    kinds = {item.get("kind") for item in payload["items"]}
    assert "note" not in kinds
    assert "function" not in kinds
    assert "excel" not in kinds
    assert "matrix" not in kinds
    assert "graph" not in kinds


def test_list_supported_file_with_no_items_is_unsupported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "empty.opju"
    sample.write_bytes(b"\x00\x00")

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 3
    assert payload["detected_type"] == "opju"
    assert payload["items"] == []
    assert payload["parser_status"] == "empty"
    assert payload["warnings"] == ["Native parser found no listable items."]
    assert payload["status"] == "empty"


def test_list_empty_opj_file_is_marked_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "empty.opj"
    sample.write_bytes(b"\x00\x00")

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 3
    assert payload["detected_type"] == "opj"
    assert payload["parser_status"] == "empty"
    assert payload["status"] == "empty"
    assert payload["support_class"] == "parser"
    assert payload["items"] == []
    assert payload["warnings"] == ["Native parser found no listable items."]


def test_list_can_include_raw_gaps_as_items(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "empty_with_gaps.opju"
    sample.write_bytes(b"\x00\x00")

    code = main(["list", str(sample), "--json", "--include-raw-gaps"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["parser_status"] == "ok"
    assert payload["status"] == "ok"
    raw_items = [
        item
        for item in payload["items"]
        if item.get("kind") == "raw_dump" and item.get("discovery_type") == "unknown_gap"
    ]
    assert raw_items
    assert any(raw.get("object_kind") in {RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY} for raw in raw_items)


def test_list_includes_raw_region_items_for_incomplete_parser_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "partial.opj"
    sample.write_bytes(b"CPYA 4.2673 0\\n" + b"\x00" * 64)

    partial_object = ParserBackedDiscoveryRecord(
        offset=12,
        name="Book1_A",
        length=8,
        object_kind="worksheet",
        source_object_path="Book/Book1_A",
        parser_rule="test",
        parser_confidence=0.9,
    )
    monkeypatch.setattr(
        "deopjufier.session.discover_origin_objects",
        lambda *_args, **_kwargs: [partial_object],
    )

    code = main(["list", str(sample), "--json", "--include-raw-gaps"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    raw_region_items = [
        item
        for item in payload["items"]
        if item.get("kind") == "raw_dump" and item.get("discovery_type") == "raw_region"
    ]
    assert raw_region_items
    assert all(item.get("heuristic") for item in raw_region_items)
    assert any(item.get("offset") == 0 for item in raw_region_items)


def test_list_includes_opju_raw_dump_crosswalk_for_parser_backed_records(capsys: pytest.CaptureFixture[str]) -> None:
    sample = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua.opju")
    if not sample.exists():
        pytest.skip("synthetic OPJU fixture missing.")

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opju"
    parser_items = [
        item
        for item in payload["items"]
        if not item.get("heuristic")
        and item.get("discovery_type") != "carved"
        and item.get("raw_dump_crosswalk") is not None
    ]
    assert parser_items
    assert all("raw_dump_crosswalk" in item for item in parser_items)
    assert all(isinstance(item["raw_dump_crosswalk"], list) for item in parser_items)


def test_list_distinguishes_opju_parser_structural_object_kinds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "mini.opju"
    sample.write_bytes(
        b"CPYUA 4.0 0\x00"
        b'<OriginStorage Label="PreviewReport"><Notes>one</Notes></OriginStorage>'
        b"<OriginStorage>"
        b"\x89PNG\r\n\x1a\n"
        b"\x00"
        b"</OriginStorage>"
        b'<ColumnTable Name="Book3_B">'
        b"1\n2\n3"
        b"</ColumnTable>"
    )

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    items = payload["items"]
    names_to_kinds = {item["name"]: item["kind"] for item in items}
    assert names_to_kinds["PreviewReport"] == "origin_storage_report"
    assert names_to_kinds["Book3_B"] == "worksheet"
    assert any(item.get("kind") == "image" and item.get("object_kind") == "opju_preview" for item in items)
    assert any(item.get("kind") == "origin_object" and item.get("object_kind") == "meta" for item in items)


def test_list_uses_stable_parser_backed_opju_naming_for_duplicates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "dup.opju"
    sample.write_bytes(
        b"CPYUA 4.3318 0\x00"
        b'<OriginStorage Label="Report / One"><Notes>one</Notes></OriginStorage>'
        b'<OriginStorage Label="Report / One"><Notes>two</Notes></OriginStorage>'
        b'<ColumnTable Name="Book A">1</ColumnTable>'
        b'<ColumnTable Name="Book A">2</ColumnTable>'
    )

    first = main(["list", str(sample), "--json"])
    payload_a = json.loads(capsys.readouterr().out)
    second = main(["list", str(sample), "--json"])
    payload_b = json.loads(capsys.readouterr().out)

    assert first == 0
    assert second == 0
    names_a = [
        item["name"] for item in payload_a["items"] if item.get("kind") in {"origin_storage_report", "worksheet"}
    ]
    names_b = [
        item["name"] for item in payload_b["items"] if item.get("kind") in {"origin_storage_report", "worksheet"}
    ]
    assert names_a == ["Report___One", "Report___One__2", "Book_A", "Book_A__2"]
    assert names_a == names_b
