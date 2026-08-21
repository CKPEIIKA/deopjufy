"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import builtins
import json
import struct
from pathlib import Path
from typing import cast

from deopjufier.blocks import ImageBlock
from deopjufier.extract import (
    extract_graph_previews,
)
from deopjufier.extract import graphs as graph_extract_module
from deopjufier.inventory import (
    HeuristicDiscoveryRecord,
    OriginObject,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
)
from tests.test_core_unit_coverage_utils import _make_manifest

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

_VALID_PDF_PREVIEW = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


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


def test_extract_graph_previews_uses_embedded_image_block(tmp_path: Path) -> None:
    sample = tmp_path / "graphs.opj"
    sample.write_bytes(b"Graph1" + b"\x00" + _VALID_PNG_1X1)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 1
    assert manifest.items
    preview_item = next(item for item in manifest.items if item.kind == "graph_preview")
    assert preview_item.name == "Graph1"
    assert preview_item.status == "extracted"
    assert preview_item.preview_status == "present"
    preview_path = Path(preview_item.path or "")
    assert (out_dir / preview_path).exists()
    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.name == "Graph1"
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_unverified"
    assert graph_item.preview_status == "present"
    graph_path = Path(graph_item.path or "")
    assert (out_dir / graph_path).exists()
    assert graph_path.name == "graph.metadata.json"

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata_path = Path(metadata_item.path or "")
    assert metadata_item.status == "extracted"
    assert metadata_path.suffix == ".json"
    assert (out_dir / metadata_path).exists()

    metadata = json.loads((out_dir / metadata_path).read_text(encoding="utf-8"))
    assert metadata["graph_name"] == "Graph1"
    assert metadata["preview_found"] is True
    assert metadata["preview_status"] == "present"
    assert metadata["preview_extension"] == "png"
    assert metadata["window_start"] == 0
    assert metadata["window_end"] == len(sample.read_bytes())
    assert metadata_item.source_object_path == "Graph/Graph1"


def test_extract_graph_previews_records_partial_without_embedded_block(tmp_path: Path) -> None:
    sample = tmp_path / "graphs_partial.opj"
    sample.write_bytes(b"Graph1")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        objects=_discover_objects(sample),
    )

    assert count == 0
    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_unverified"
    assert graph_item.preview_status == "absent"

    preview_item = next(item for item in manifest.items if item.kind == "graph_preview")
    assert preview_item.status == "skipped"
    assert preview_item.error == "no_embedded_image_block"
    assert preview_item.content_class == "absent"
    assert preview_item.preview_status == "absent"

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata_path = Path(metadata_item.path or "")
    assert metadata_item.status == "extracted"
    assert metadata_item.name == "Graph1_metadata"
    assert metadata_path.suffix == ".json"
    assert (out_dir / metadata_path).exists()

    metadata = json.loads((out_dir / metadata_path).read_text(encoding="utf-8"))
    assert metadata["graph_name"] == "Graph1"
    assert metadata["preview_found"] is False
    assert metadata["preview_status"] == "absent"
    assert metadata["preview_error"] == "no_embedded_image_block"
    collection_items = [item for item in manifest.items if item.kind == "graph" and item.name == "graph_collection"]
    assert not collection_items


def test_extract_graph_previews_emits_malformed_preview_item(tmp_path: Path) -> None:
    sample = tmp_path / "graphs_bad_preview.opj"
    sample.write_bytes(b"Graph1\x00" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND" + b"\x00\x00\x00\x00")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 0
    preview_item = next(item for item in manifest.items if item.kind == "malformed_graph_preview")
    assert preview_item.status == "partial"
    assert preview_item.error == "png_chunk_crc_mismatch"
    assert preview_item.path is None

    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_unverified"

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["preview_found"] is True
    assert metadata["preview_error"] == "png_chunk_crc_mismatch"


def test_extract_graph_previews_recovers_unsupported_jpeg_with_eoi(tmp_path: Path) -> None:
    sample = tmp_path / "graphs_unsupported_jpeg_with_eoi.opj"
    sample.write_bytes(b"Graph1\x00" + b"\xff\xd8" + b"\xff\x23\x00\x03\x00" + _VALID_JPEG_1X1[2:])

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 1
    preview_item = next(item for item in manifest.items if item.kind == "malformed_graph_preview")
    assert preview_item.status == "partial"
    assert preview_item.error == "jpeg_unsupported_marker"
    preview_path = Path(preview_item.path or "")
    assert (out_dir / preview_path).exists()

    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_unverified"

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["preview_error"] == "jpeg_unsupported_marker"
    assert metadata["preview_found"] is True


def test_extract_graph_previews_marks_parser_backed_graph_metadata(tmp_path: Path) -> None:
    sample = tmp_path / "graph_parser_backed.opj"
    sample.write_bytes(b"Graph1\x00" + _VALID_PNG_1X1)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=0,
            name="Graph1",
            length=len(sample.read_bytes()),
            object_kind="graph",
            source_object_path="Graph/Graph1",
            parser_rule="opj_graph_payload",
            parser_confidence=0.92,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.heuristic is False
    assert graph_item.discovery_type == "parser_window"
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_partial"
    assert graph_item.confidence == 0.92
    preview_item = next(item for item in manifest.items if item.kind == "graph_preview")
    assert preview_item.confidence == 0.92
    assert preview_item.heuristic is False

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata_path = Path(metadata_item.path or "")
    metadata = json.loads((out_dir / metadata_path).read_text(encoding="utf-8"))
    assert metadata["unsupported_graph_attributes"] == [
        "axes",
        "data_binding",
        "legend_configuration",
        "series_metadata",
        "style_attributes",
        "template_settings",
    ]


def test_extract_graph_previews_expands_parser_window_for_parser_duplicates(tmp_path: Path) -> None:
    sample = tmp_path / "graph_parser_window_gap.opj"
    payload = b"Graph1" + b"\x00" * 4 + b"Graph1__2" + b"\x00" * 4 + _VALID_PNG_1X1
    sample.write_bytes(payload)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=0,
            name="Graph1",
            length=10,
            object_kind="graph",
            source_object_path="Graph/Graph1",
            parser_rule="opj_graph_payload",
            parser_confidence=0.91,
        ),
        HeuristicDiscoveryRecord(
            offset=9,
            name="Graph1__2",
            length=7,
            object_kind="graph",
            source_object_path="Graph/Graph1__2",
            heuristic_signal="dup",
        ),
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=payload,
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.name == "Graph1"
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_partial"
    preview_item = next(item for item in manifest.items if item.kind == "graph_preview")
    assert preview_item.status == "extracted"
    assert preview_item.source_object_path == "Graph/Graph1"


def test_extract_graph_previews_treats_layer_objects_as_graph_output(tmp_path: Path) -> None:
    sample = tmp_path / "layer_graph.opj"
    sample.write_bytes(b"Layer1\x00" + _VALID_PNG_1X1)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=0,
            name="Layer1",
            length=len(sample.read_bytes()),
            object_kind="layer",
            source_object_path="Layer/Layer1",
            parser_rule="opj_graph_payload",
            parser_confidence=0.9,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    assert any(item.kind == "graph" and item.name == "Layer1" for item in manifest.items)
    assert any(item.kind == "graph_preview" and item.source_object_path == "Layer/Layer1" for item in manifest.items)


def test_extract_graph_previews_emits_parser_backed_preview_object_item(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "preview_parser_backed.opju"
    payload = b"CPYUA 4.0 0\x00" + b"<OriginStorage>" + _VALID_PNG_1X1 + b"</OriginStorage>"
    sample.write_bytes(payload)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=12,
            name="origin_storage_preview_000",
            length=len(payload) - 12,
            object_kind="opju_preview",
            source_object_path="previews/origin_storage_preview_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=payload,
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    preview_item = next(item for item in manifest.items if item.kind == "parser_backed_graph_preview")
    assert preview_item.status == "extracted"
    assert preview_item.object_kind == "opju_preview"
    assert preview_item.confidence == 0.9
    assert preview_item.heuristic is False
    assert (out_dir / Path(preview_item.path or "")).exists()

    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.object_kind == "opju_preview"
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_partial"

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["object_kind"] == "opju_preview"
    assert metadata["preview_found"] is True


def test_extract_graph_previews_emits_parser_backed_graph_payload_object_item(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "preview_parser_backed_graph_payload.opju"
    payload = b"CPYUA 4.0 0\x00" + b"<OriginStorage>" + _VALID_PNG_1X1 + b"</OriginStorage>"
    sample.write_bytes(payload)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=12,
            name="origin_storage_graph_102",
            length=len(payload) - 12,
            object_kind="opju_graph_payload",
            source_object_path="origin_storage/origin_storage_graph_102",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.93,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=payload,
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    preview_item = next(item for item in manifest.items if item.kind == "parser_backed_graph_preview")
    assert preview_item.status == "extracted"
    assert preview_item.object_kind == "opju_graph_payload"
    assert preview_item.confidence == 0.93
    assert preview_item.heuristic is False
    assert (out_dir / Path(preview_item.path or "")).exists()

    graph_item = next(item for item in manifest.items if item.kind == "graph")
    assert graph_item.object_kind == "opju_graph_payload"
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_partial"

    metadata_item = next(item for item in manifest.items if item.kind == "graph_metadata")
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["object_kind"] == "opju_graph_payload"
    assert metadata["preview_found"] is True


def test_extract_graph_previews_marks_parser_backed_missing_preview_as_unavailable(tmp_path: Path) -> None:
    sample = tmp_path / "preview_parser_backed_missing.opju"
    sample.write_bytes(b"CPYUA 4.0 0\x00<OriginStorage>Graph1</OriginStorage>")
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=12,
            name="origin_storage_graph_000",
            length=19,
            object_kind="opju_preview",
            source_object_path="previews/origin_storage_graph_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.91,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 0
    graph_item = next(item for item in manifest.items if item.kind == "graph" and item.object_kind == "opju_preview")
    assert graph_item.status == "partial"
    assert graph_item.error == "graph_definition_partial"
    assert graph_item.discovery_type == "parser_window"

    preview_items = [item for item in manifest.items if item.kind == "parser_backed_graph_preview"]
    assert not preview_items

    preview_item = next(
        item for item in manifest.items if item.kind == "graph_preview" and item.object_kind == "opju_preview"
    )
    assert preview_item.status == "skipped"
    assert preview_item.error == "no_embedded_image_block"
    assert preview_item.content_class == "absent"
    assert preview_item.completeness == "complete"

    metadata_item = next(
        item for item in manifest.items if item.kind == "graph_metadata" and item.object_kind == "opju_preview"
    )
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["preview_found"] is False
    assert metadata["preview_unavailable"] is True


def test_extract_graph_previews_emits_parser_backed_jpeg_preview_object_item(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "preview_parser_backed_jpeg.opju"
    payload = b"CPYUA 4.0 0\x00" + b"<OriginStorage>" + _VALID_JPEG_1X1 + b"</OriginStorage>"
    sample.write_bytes(payload)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=12,
            name="origin_storage_preview_000",
            length=len(payload) - 12,
            object_kind="opju_preview",
            source_object_path="previews/origin_storage_preview_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=payload,
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    preview_item = next(item for item in manifest.items if item.kind == "parser_backed_graph_preview")
    assert preview_item.status == "extracted"
    assert preview_item.object_kind == "opju_preview"
    assert preview_item.confidence == 0.9
    assert preview_item.heuristic is False
    preview_path = Path(preview_item.path or "")
    assert preview_path.suffix == ".jpg"
    assert (out_dir / preview_path).exists()


def test_extract_graph_previews_emits_parser_backed_pdf_preview_object_item(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "preview_parser_backed_pdf.opju"
    payload = b"CPYUA 4.0 0\x00" + b"<OriginStorage>" + _VALID_PDF_PREVIEW + b"</OriginStorage>"
    sample.write_bytes(payload)
    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=12,
            name="origin_storage_preview_000",
            length=len(payload) - 12,
            object_kind="opju_preview",
            source_object_path="previews/origin_storage_preview_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.92,
        )
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=payload,
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    preview_item = next(item for item in manifest.items if item.kind == "parser_backed_graph_preview")
    assert preview_item.status == "extracted"
    assert preview_item.object_kind == "opju_preview"
    assert preview_item.confidence == 0.92
    preview_path = Path(preview_item.path or "")
    assert preview_path.suffix == ".pdf"
    assert (out_dir / preview_path).exists()

    metadata_item = next(
        item
        for item in manifest.items
        if item.kind == "graph_metadata" and item.source_object_path == "previews/origin_storage_preview_000"
    )
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["preview_extension"] == "pdf"


def test_extract_graph_previews_marks_invalid_jpeg_as_malformed_preview(tmp_path: Path) -> None:
    sample = tmp_path / "graphs_bad_jpeg.opj"
    sample.write_bytes(b"Graph1" + b"\x00" + b"\xff\xd8\x00\x00")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 0
    preview_item = next(item for item in manifest.items if item.kind == "malformed_graph_preview")
    assert preview_item.status == "partial"
    assert preview_item.error is not None
    assert preview_item.error.startswith("jpeg_")
    assert preview_item.path is None


def test_extract_graph_previews_skips_oversized_malformed_jpeg_salvage(tmp_path: Path) -> None:
    payload_size = 5 * 1024 * 1024
    jpeg_payload = b"\xff\xd8" + b"\x00" * 64 + b"\xff\xd9"
    sample = tmp_path / "graphs_large_malformed_jpeg.opj"
    sample.write_bytes(b"Graph1\x00" + jpeg_payload + b"\x00" * (payload_size - len(jpeg_payload)))
    file_data = sample.read_bytes()

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        OriginObject(
            offset=0,
            name="Graph1",
            length=len(file_data),
            object_kind="graph",
            source_object_path="Graph/Graph1",
        )
    ]
    image_blocks = [
        ImageBlock(
            offset=len(b"Graph1\x00"),
            length=len(file_data) - len(b"Graph1\x00"),
            kind="jpeg",
            extension="jpg",
            valid=False,
            error="jpeg_unsupported_marker",
        ),
    ]

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=file_data,
        image_blocks=image_blocks,
        objects=objects,
        manifest_root=out_dir,
    )

    assert count == 0
    malformed_items = [item for item in manifest.items if item.kind == "malformed_graph_preview"]
    assert malformed_items
    preview_item = malformed_items[0]
    assert preview_item.status == "partial"
    assert preview_item.error == "jpeg_salvage_too_large"
    graph_item = next(
        item for item in manifest.items if item.kind == "graph" and item.source_object_path == "Graph/Graph1"
    )
    assert graph_item.error == "graph_definition_unverified"
    assert preview_item.path is None


def test_extract_graph_previews_does_not_resort_blocks_per_object(
    tmp_path: Path,
    monkeypatch,
) -> None:
    preview_offset = 1024
    payload = b"x" * preview_offset + _VALID_PNG_1X1 + b"x" * 1024
    sample = tmp_path / "graphs_many_objects.opj"
    sample.write_bytes(payload)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    image_blocks = [
        ImageBlock(
            offset=preview_offset,
            length=len(_VALID_PNG_1X1),
            kind="png",
            extension="png",
        )
    ]
    objects = [
        HeuristicDiscoveryRecord(
            offset=0,
            name=f"Graph{index + 1}",
            length=len(payload),
            object_kind="graph",
            source_object_path=f"Graph/Graph{index + 1}",
        )
        for index in range(40)
    ]

    sort_calls = 0

    def _counting_sorted(*args, **kwargs):
        nonlocal sort_calls
        sort_calls += 1
        return builtins.sorted(*args, **kwargs)

    monkeypatch.setattr(graph_extract_module, "sorted", _counting_sorted, raising=False)

    count = extract_graph_previews(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=payload,
        image_blocks=image_blocks,
        objects=cast(list[OriginObject], objects),
    )

    assert count == len(objects)
    assert sort_calls <= 3, (
        f"Expected graph preview extraction to avoid per-object sorting, got {sort_calls} sort calls."
    )
