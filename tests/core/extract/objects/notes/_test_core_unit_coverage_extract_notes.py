"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import cast

import pytest

from deopjufier.extract import (
    extract_notes,
)
from deopjufier.inventory import (
    OpjNoteSection,
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


def test_extract_notes_creates_note_files(tmp_path: Path) -> None:
    sample = tmp_path / "notes.opj"
    sample.write_bytes(b"Note1\nThis is a note with text." + b"Graph1")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 1
    assert manifest.items
    assert manifest.items[0].kind == "note"
    assert manifest.items[0].name == "Note1"
    assert manifest.items[0].status == "extracted"
    note_path = Path(manifest.items[0].path or "")
    assert (out_dir / note_path).exists()


def test_extract_notes_formats_markdown_and_html_when_detected(tmp_path: Path) -> None:
    sample = tmp_path / "notes_formats.opj"
    sample.write_bytes(b"Note1\n# heading\n\nSome *markdown* text.\nNote2\n<html>note</html>\nNoMarker")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count >= 1
    assert manifest.items
    assert manifest.items[0].kind == "note"
    assert manifest.items[0].status in {"extracted", "partial"}

    note_files = sorted((out_dir / "notes").rglob("note.*"))
    assert len(note_files) >= 1
    exts = {file.suffix for file in note_files}
    assert ".md" in exts or ".html" in exts


def test_extract_notes_records_note_payload_type(tmp_path: Path) -> None:
    sample = tmp_path / "notes_payload.opj"
    sample.write_bytes(
        b"CPYA 4.2673 552#\n" + b"\nNote\0\n" + b"<html><body><p>Note body</p></body></html>\r\n\r\n\0\n"
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
    )

    assert count == 1
    note_items = [item for item in manifest.items if item.kind == "note"]
    assert note_items
    assert note_items[0].note_payload_type == "html_like"
    note_path = Path(note_items[0].path or "")
    assert (out_dir / note_path).read_text(encoding="utf-8").startswith("<html")


def test_extract_notes_trim_neighboring_object_markers(tmp_path: Path) -> None:
    sample = tmp_path / "notes_bleed.opj"
    sample.write_bytes(b"Note1\nThis is a note that should stop.\nGraph1\nBook1_A\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 1
    note_items = [item for item in manifest.items if item.kind == "note"]
    first = next(item for item in note_items if item.name == "Note1")

    first_path = Path(first.path or "")
    first_text = (out_dir / first_path).read_text(encoding="utf-8")

    assert "Graph1" not in first_text
    assert "Book1_A" not in first_text
    assert first_text.endswith("This is a note that should stop.")


def test_extract_notes_uses_parser_note_sections_without_bleed(tmp_path: Path) -> None:
    sample = tmp_path / "notes_structural.opj"
    sample.write_bytes(
        b"CPYA 4.2673 552#\n" + b"\nNote\0\n" + b"Parsed notes should stay scoped.\r\n\r\n\0\n" + b"Graph1\n"
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
    )

    assert count == 1
    note_items = [item for item in manifest.items if item.kind == "note" and item.name == "Note"]
    assert note_items
    note_item = note_items[0]
    assert note_item.discovery_type == "opj_note_section"
    assert note_item.heuristic is False
    assert note_item.confidence >= 0.9
    assert note_item.note_payload_type == "plain_text"
    assert note_item.status == "extracted"
    note_path = Path(note_item.path or "")
    note_text = (out_dir / note_path).read_text(encoding="utf-8")
    assert "Graph1" not in note_text
    assert note_text == "Parsed notes should stay scoped."


def test_extract_notes_emits_parser_notes_without_discovered_note_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "notes_parser_only.opj"
    sample.write_bytes(b"X" * 64)

    monkeypatch.setattr(
        "deopjufier.extract.objects.parse_opj_note_sections",
        lambda *_args, **_kwargs: [
            OpjNoteSection(
                name="Results",
                text="Data1 Temperature:\t25.10242",
                offset=10,
                length=30,
            ),
            OpjNoteSection(
                name="ResultsLog",
                text="Chi^2/DoF = 3008",
                offset=40,
                length=18,
            ),
        ],
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        OriginObject(
            offset=0,
            name="Graph1",
            length=3,
            object_kind="graph",
            source_object_path="Graph/Graph1",
        )
    ]
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=objects,
    )

    assert count == 2
    note_items = [item for item in manifest.items if item.kind == "note"]
    assert len(note_items) == 2
    results_item = next(item for item in note_items if item.name == "Results")
    log_item = next(item for item in note_items if item.name == "ResultsLog")
    assert results_item.discovery_type == "opj_note_section"
    assert results_item.heuristic is False
    assert log_item.discovery_type == "opj_note_section"
    assert log_item.heuristic is False
    assert results_item.status == "extracted"
    assert log_item.status == "extracted"

    results_path = Path(results_item.path or "")
    log_path = Path(log_item.path or "")
    assert (out_dir / results_path).exists()
    assert (out_dir / log_path).exists()
    assert (out_dir / results_path).read_text(encoding="utf-8") == "Data1 Temperature:\t25.10242"
    assert (out_dir / log_path).read_text(encoding="utf-8") == "Chi^2/DoF = 3008"


def test_extract_notes_emits_parser_backed_opju_note_payloads(tmp_path: Path) -> None:
    sample = tmp_path / "opju_note_payload.opju"
    prefix = b"CPYUA 4.0 552#\0"
    note_region = b"<OriginStorage><Note>Fixture parser-backed OPJU note payload.</Note></OriginStorage>"
    sample.write_bytes(prefix + note_region)
    sample_bytes = sample.read_bytes()

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(prefix),
            name="origin_storage_note_000",
            length=len(note_region),
            object_kind="opju_note_payload",
            source_object_path="origin_storage/origin_storage_note_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=cast(list[OriginObject], objects),
        file_data=sample_bytes,
    )

    assert count == 1
    note_items = [item for item in manifest.items if item.kind == "note"]
    assert len(note_items) == 1
    note_item = note_items[0]
    assert note_item.name == "origin_storage_note_000"
    assert note_item.status == "extracted"
    assert note_item.object_kind == "opju_note_payload"
    assert note_item.discovery_type == "parse_opju_origin_storage_records"
    assert note_item.heuristic is False
    note_path = Path(note_item.path or "")
    assert (out_dir / note_path).exists()
    assert (out_dir / note_path).read_text(
        encoding="utf-8"
    ) == "<OriginStorage><Note>Fixture parser-backed OPJU note payload.</Note></OriginStorage>"


def test_extract_notes_uses_opju_specific_note_path_for_cpyua_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "opju_note_payload_no_opj_parser.opju"
    prefix = b"CPYUA 4.3318 552#\x00"
    note_region = b"<OriginStorage><Note>OPJU note path test.</Note></OriginStorage>"
    sample.write_bytes(prefix + note_region)
    sample_bytes = sample.read_bytes()

    def _unexpected_note_parser(*_args: object, **_kwargs: object) -> list[OpjNoteSection]:
        raise AssertionError("OPJ note parser should not run for CPYUA files")

    monkeypatch.setattr(
        "deopjufier.extract.objects.parse_opj_note_sections",
        _unexpected_note_parser,
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(prefix),
            name="origin_storage_note_001",
            length=len(note_region),
            object_kind="opju_note_payload",
            source_object_path="origin_storage/origin_storage_note_001",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.91,
        )
    ]

    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=cast(list[OriginObject], objects),
        file_data=sample_bytes,
    )

    assert count == 1
    note_items = [item for item in manifest.items if item.kind == "note"]
    assert len(note_items) == 1
    assert note_items[0].object_kind == "opju_note_payload"
    assert note_items[0].discovery_type == "parse_opju_origin_storage_records"
    assert note_items[0].status == "extracted"
    assert note_items[0].heuristic is False


def test_extract_notes_marks_no_parser_notes_as_unsupported_for_opju(tmp_path: Path) -> None:
    sample = tmp_path / "no_note.opju"
    sample.write_bytes(b"X\\x00\\x00\\x01\\x02\\x03\\x04")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=[],
    )

    assert count == 0
    assert manifest.items
    note_item = manifest.items[0]
    assert note_item.kind == "note"
    assert note_item.name == "note_collection"
    assert note_item.status == "unsupported"
    assert note_item.error == "no_note_objects"
    assert note_item.path is not None
    note_collection = next(item for item in manifest.items if item.kind == "note" and item.name == "note_collection")
    assert note_collection.discovery_type == "parser_backed_hint"
    assert note_collection.heuristic is False


def test_extract_notes_extracts_heuristic_opju_notes(tmp_path: Path) -> None:
    sample = tmp_path / "heuristic_note.opju"
    sample.write_bytes(b"Note1\nThis is a note.\nFunction1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = _discover_objects(sample)
    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=objects,
    )

    assert count == 1
    note_items = [item for item in manifest.items if item.kind == "note"]
    assert len(note_items) == 1
    note_item = note_items[0]
    assert note_item.name == "Note1"
    assert note_item.status == "extracted"
    assert note_item.heuristic is True
    assert note_item.discovery_type == "heuristic_object_scan"
    note_path = Path(note_item.path or "")
    note_payload = (out_dir / note_path).read_text(encoding="utf-8")
    assert note_payload.startswith("Note1\nThis is a note.")
    assert "Function1" not in note_payload
