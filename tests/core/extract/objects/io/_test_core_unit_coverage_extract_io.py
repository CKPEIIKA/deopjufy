"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import cast

import pytest

from deopjufier.blocks import ImageBlock
from deopjufier.extract import (
    extract_graph_previews,
    extract_images,
    extract_origin_inventory,
    extract_origin_storage_reports,
    extract_strings,
)
from deopjufier.inventory import (
    OriginObject,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
)
from tests.test_core_unit_coverage_utils import _make_manifest, _resolve_tests_fixture

_VALID_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    + b"\x90wS\xde"
    + b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x17"
    + b"8U"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_VALID_JPEG_1X1 = (
    b"\xff\xd8"
    + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    + b"\x01\x02"
    + b"\xff\xd9"
)


def _discover_objects(path: Path) -> list[OriginObject]:
    return discover_origin_objects(path)


def _opj_matrix_data_section_payload(
    name: str,
    values: list[float],
    *,
    value_size: int = 8,
    data_type: int = 0,
) -> bytes:
    header = bytearray(123)
    name_bytes = f"{name}\x00".encode("ascii")
    header[0x58 : 0x58 + len(name_bytes)] = name_bytes[:25]
    header[0x16:0x18] = data_type.to_bytes(2, "little")
    header[0x18] = 0
    header[0x19:0x1D] = len(values).to_bytes(4, "little")
    header[0x1D:0x21] = (1).to_bytes(4, "little")
    header[0x21:0x25] = len(values).to_bytes(4, "little")
    header[0x3D] = value_size
    header[0x3F] = 0
    header[0x71:0x73] = (0).to_bytes(2, "little")

    payload = b"".join(struct.pack("<d", float(value)) for value in values)
    return (
        struct.pack("<I", len(header))
        + b"\n"
        + bytes(header)
        + b"\n"
        + struct.pack("<I", len(payload))
        + b"\n"
        + payload
        + b"\n"
    )


def _build_opj_matrix_payload_file(
    sections: list[tuple[str, list[float]]],
) -> bytes:
    payload = b"CPYA 6.0 552#\n"
    for index, (name, values) in enumerate(sections):
        payload += _opj_matrix_data_section_payload(name, values)
        if index + 1 < len(sections):
            payload += b"\x00\x00\x00\x00\n"
    return payload


SYNTHETIC_PREVIEW_FIXTURE = _resolve_tests_fixture(
    Path(__file__),
    Path("fixtures") / "synthetic" / "synthetic-opju-preview-report-with-valid-image.opju",
)


def test_extract_images_emits_manifest_records(tmp_path: Path) -> None:
    sample = tmp_path / "img.opju"
    sample.write_bytes(b"xx" + _VALID_PNG_1X1 + b"yy")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "images"

    result = extract_images(sample, out_dir, manifest)
    assert result is True
    assert len(manifest.items) == 1
    assert manifest.items[0].kind == "image"
    assert manifest.items[0].status == "extracted"
    assert manifest.items[0].signature == "png"
    assert manifest.items[0].extraction_method == "carved"
    assert manifest.items[0].source_ranges == [{"start": 2, "end": 2 + len(_VALID_PNG_1X1)}]
    assert any(path.exists() for path in out_dir.glob("img_png_off_*_len_*.png"))


def test_extract_images_marks_skipped_when_output_exists(tmp_path: Path) -> None:
    sample = tmp_path / "img2.opju"
    sample.write_bytes(_VALID_PNG_1X1)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "images"
    out_dir.mkdir()
    expected_len = f"{len(sample.read_bytes()):012d}"
    expected_name = f"img_png_off_000000000000_len_{expected_len}.png"
    existing = out_dir / expected_name
    existing.write_bytes(b"old")

    result = extract_images(sample, out_dir, manifest)
    assert result is True
    assert manifest.items
    assert manifest.items[0].status == "skipped"
    assert manifest.items[0].error == "target_exists"
    assert manifest.items[0].extraction_method == "carved"
    assert manifest.items[0].signature == "png"
    assert manifest.items[0].source_ranges == [{"start": 0, "end": len(_VALID_PNG_1X1)}]
    assert manifest.items[0].source_object_path is not None


def test_extract_images_marks_malformed_png_as_partial(tmp_path: Path) -> None:
    sample = tmp_path / "img_bad.opju"
    sample.write_bytes(b"xx" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND" + b"\x00\x00\x00\x00" + b"yy")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "images"

    result = extract_images(sample, out_dir, manifest)
    assert result is False
    assert manifest.items
    item = manifest.items[0]
    assert item.kind == "image"
    assert item.status == "partial"
    assert item.error == "png_chunk_crc_mismatch"
    assert item.extraction_method == "carved"
    assert item.signature == "png"
    assert item.offset is not None
    assert item.length is not None
    assert item.source_ranges == [
        {"start": item.offset, "end": item.offset + item.length},
    ]
    assert not any(out_dir.iterdir())


def test_graph_preview_blocks_are_excluded_from_generic_image_exports(tmp_path: Path) -> None:
    sample = tmp_path / "graph_and_image.opj"
    png = _VALID_PNG_1X1
    sample.write_bytes(b"Graph1\x00" + png + b"extra" + png)

    manifest = _make_manifest(sample)
    objects = [
        OriginObject(
            offset=0,
            name="Graph1",
            length=sample.stat().st_size,
            object_kind="graph",
            source_object_path="Graph/Graph1",
        )
    ]
    image_blocks = [
        ImageBlock(
            offset=len(b"Graph1\x00"),
            length=len(png),
            kind="png",
            extension="png",
        ),
        ImageBlock(
            offset=len(b"Graph1\x00") + len(png) + len(b"extra"),
            length=len(png),
            kind="png",
            extension="png",
        ),
    ]
    owned_image_blocks: list[ImageBlock] = []
    out_dir = tmp_path / "out"

    graph_count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        image_blocks=image_blocks,
        objects=objects,
        owned_image_blocks=owned_image_blocks,
        manifest_root=out_dir,
    )
    assert graph_count == 1
    assert len(owned_image_blocks) == 1
    assert owned_image_blocks[0] == image_blocks[0]

    image_count = extract_images(
        sample,
        out_dir / "images",
        manifest,
        force=True,
        image_blocks=[block for block in image_blocks if block not in owned_image_blocks],
    )
    assert image_count is True

    graph_path = Path(next(item.path or "" for item in manifest.items if item.kind == "graph"))
    assert graph_path.as_posix().startswith("graphs/")
    assert (out_dir / graph_path).exists()
    image_items = [item for item in manifest.items if item.kind == "image"]
    assert len(image_items) == 1
    assert image_items[0].path is not None
    assert image_items[0].source_object_path == (f"embedded:{image_blocks[1].offset}:{image_blocks[1].length}")
    assert f"off_{image_blocks[1].offset:012d}" in image_items[0].path
    assert not any(
        item.source_object_path == f"embedded:{image_blocks[0].offset}:{image_blocks[0].length}" for item in image_items
    )


def test_extract_images_uses_parser_owned_window_metadata(tmp_path: Path) -> None:
    sample = tmp_path / "owned_images.opj"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
    sample.write_bytes(b"Graph1\x00" + png + b"trail" + png)
    file_data = sample.read_bytes()

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "images"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=0,
            length=len(file_data),
            name="Graph1",
            object_kind="graph",
            source_object_path="Graph/Graph1",
            parser_rule="graph_window",
            parser_confidence=0.95,
        )
    ]
    image_blocks = [
        ImageBlock(
            offset=len(b"Graph1\x00"),
            length=len(png),
            kind="png",
            extension="png",
        ),
        ImageBlock(
            offset=len(b"Graph1\x00") + len(png) + len(b"trail"),
            length=len(png),
            kind="png",
            extension="png",
        ),
    ]
    extract_images(
        sample,
        out_dir,
        manifest,
        force=True,
        image_blocks=image_blocks,
        objects=cast(list[OriginObject], objects),
        file_data=file_data,
    )

    image_items = [item for item in manifest.items if item.kind == "image"]
    assert len(image_items) == 2
    for item in image_items:
        assert item.source_object_path == "Graph/Graph1"
        assert item.discovery_type == "parser_window"
        assert item.heuristic is False
        assert item.extraction_method == "carved"
        assert item.signature == "png"
        assert item.offset is not None
        assert item.length is not None
        assert item.source_ranges == [
            {"start": item.offset, "end": item.offset + item.length},
        ]
        assert item.range_start == 0
        assert item.range_end == len(file_data)
        assert item.object_kind == "graph"


def test_extract_images_uses_parser_backed_opju_preview_source_object_path(tmp_path: Path) -> None:
    sample = tmp_path / "preview_image.opju"
    sample.write_bytes(SYNTHETIC_PREVIEW_FIXTURE.read_bytes())

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "images"
    objects = discover_origin_objects(sample)

    extract_images(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=objects,
        file_data=sample.read_bytes(),
    )

    image_items = [item for item in manifest.items if item.kind == "image"]
    assert len(image_items) == 1
    assert image_items[0].source_object_path == "previews/origin_storage_preview_000"
    assert image_items[0].discovery_type == "parser_window"
    assert image_items[0].heuristic is False


def test_extract_unlabeled_preview_report_items_link_to_preview_source_and_image(tmp_path: Path) -> None:
    sample = tmp_path / "preview_report.opju"
    sample.write_bytes(SYNTHETIC_PREVIEW_FIXTURE.read_bytes())

    report_root = tmp_path / "reports"
    report_manifest = _make_manifest(sample)
    report_count = extract_origin_storage_reports(sample, report_root, report_manifest, force=True)

    assert report_count == 1
    report_items = [
        item
        for item in report_manifest.items
        if item.kind == "origin_storage_report" and item.name.startswith("origin_storage_report_")
    ]
    assert len(report_items) == 1
    report_item = report_items[0]
    assert report_item.source_object_path == "previews/origin_storage_preview_000"
    report_file = report_root / "origin_storage_reports" / f"{report_item.name}.txt"
    assert report_file.exists()

    image_root = tmp_path / "images"
    image_manifest = _make_manifest(sample)
    extract_images(
        sample,
        image_root,
        image_manifest,
        force=True,
        objects=discover_origin_objects(sample),
        file_data=sample.read_bytes(),
    )
    preview_image_items = [
        item
        for item in image_manifest.items
        if item.kind == "image" and item.source_object_path == report_item.source_object_path
    ]
    assert preview_image_items
    assert any(item.status == "extracted" for item in preview_image_items)


def test_extract_strings_writes_file_and_records_status(tmp_path: Path) -> None:
    sample = tmp_path / "strings.opju"
    sample.write_text("hello 1234 56\naBcde", encoding="utf-8")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "strings"
    count = extract_strings(sample, out_dir, manifest, min_length=4)

    assert count >= 1
    assert manifest.items[0].kind == "strings"
    assert manifest.items[0].status == "extracted"
    assert (out_dir / "strings.txt").exists()


def test_extract_strings_marks_partial_when_no_data(tmp_path: Path) -> None:
    sample = tmp_path / "strings_empty.opju"
    sample.write_bytes(b"\x00\x01\x02\x03")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "strings"
    count = extract_strings(sample, out_dir, manifest, min_length=8)

    assert count == 0
    assert manifest.items[0].status == "partial"


def test_extract_strings_uses_streaming_scan_not_read_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "strings_stream.opju"
    sample.write_text("alpha beta\ngamma delta", encoding="utf-8")

    def _fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("extract_strings should not call Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", _fail_read_bytes)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "strings"

    count = extract_strings(sample, out_dir, manifest, min_length=4)

    assert count == 2
    assert out_dir.joinpath("strings.txt").exists()


def test_extract_images_reads_only_by_ranges_when_file_data_not_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "image_stream.opju"
    sample.write_bytes(b"xx" + _VALID_PNG_1X1 + b"yy")

    def _fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("extract_images should not call Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", _fail_read_bytes)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "images"

    result = extract_images(sample, out_dir, manifest, force=True)

    assert result is True
    assert any(path.exists() for path in out_dir.glob("img_png_off_*_len_*.png"))


def test_extract_origin_inventory_writes_metadata_file(tmp_path: Path) -> None:
    sample = tmp_path / "objects.opj"
    sample.write_bytes(b"CPYA\0Book1_A\0Graph1\0PdMSheet1\0")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "metadata"
    count = extract_origin_inventory(
        sample,
        out_dir,
        manifest,
        objects=_discover_objects(sample),
    )

    assert count >= 3
    assert manifest.items[0].kind == "origin_object_inventory"
    assert manifest.items[0].status == "extracted"
    assert (out_dir / "origin_objects.json").exists()

    payload = json.loads((out_dir / "origin_objects.json").read_text(encoding="utf-8"))
    assert any(item["name"] == "Book1_A" for item in payload)
    assert any(item["name"] == "Graph1" for item in payload)
    kinds = {item.get("object_kind") for item in payload}
    assert "worksheet" in kinds
    assert "graph" in kinds


def test_extract_origin_storage_reports_writes_manifest_files(tmp_path: Path) -> None:
    sample = tmp_path / "report.opju"
    sample.write_bytes(
        b"CPYUA 4.3318 113\0"
        + b"".join(
            (
                b'<OriginStorage NodeID="1 0 " Label="Wilcoxon Signed Ranks Test (7/18/2016 11:58:20)">',
                b'<Notes NodeID="2097157" Label="Notes"><xf NodeID="868" Label="X-Function">'
                b"Wilcoxon Signed Ranks Test</xf>",
                b'<User NodeID="869" Label="User Name">developer</User><T ime NodeID="870" Label="Time">'
                b"7/18/2016 11:58:20</Time>",
                b'<DataFilter NodeID="22100" Label="Data Filter">No</DataFilter></Notes>',
                b'<IODT0 NodeID="8860" Label="Input Data"><IDTR1><IDTC1 Label="Data" '
                b"EscTransl='[Book3]Sheet1!B\"August\"'>?A</IDTC1>",
                b'<IDTC2 EscTransl="[1*:13*]">?B</IDTC2></IDTR1></IODT0>',
                b"<Stats><C1>29</C1><C2>-1.1181704925</C2><C3>0.2734375</C3><C4>0.2634941841411</C4></Stats>",
                b"<Footer><![CDATA[Null Hypothesis: F(x) = G(y)\nAlternative Hypothesis: F(x) <> G(y)\n",
                b"At the 0.05 level, the two distributions are NOT significantly different.]]></Footer>",
                b"</OriginStorage>",
            )
        )
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_origin_storage_reports(
        sample,
        out_dir,
        manifest,
        force=True,
    )

    assert count == 1
    report_items = [
        item
        for item in manifest.items
        if item.kind == "origin_storage_report" and item.path is not None and item.path.endswith(".txt")
    ]
    assert len(report_items) == 1
    report_path_item = report_items[0]
    assert report_path_item.path is not None
    report_path = Path(report_path_item.path)
    assert (out_dir / report_path).exists()
    assert (out_dir / "origin_storage_reports" / "origin_storage_reports.json").exists()
    assert any(item.kind == "origin_storage_report" for item in manifest.items)
    assert any(item.kind == "origin_storage_report_summary" for item in manifest.items)
