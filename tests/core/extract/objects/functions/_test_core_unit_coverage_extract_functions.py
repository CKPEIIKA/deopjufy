"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import cast

import pytest

from deopjufier.extract import (
    extract_functions,
    extract_raw_blocks,
    extract_tables,
)
from deopjufier.inventory import (
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


def test_extract_functions_creates_function_directory_and_text(tmp_path: Path) -> None:
    sample = tmp_path / "functions.opj"
    sample.write_bytes(b"Function1" + b"\n1 2 3\n4 5 6\n" + b"Graph1\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        objects=_discover_objects(sample),
    )

    assert count == 1
    assert manifest.items
    assert manifest.items[0].kind == "function"
    assert manifest.items[0].name == "Function1"
    assert manifest.items[0].status == "extracted"
    assert manifest.items[0].columns is not None
    assert manifest.items[0].rows == 3
    assert manifest.items[0].columns >= 3
    assert manifest.items[0].function_formula is None
    assert manifest.items[0].function_range is None
    assert manifest.items[0].function_total_points is None
    assert (out_dir / "functions" / "Function" / "Function1" / "function.txt").exists()


def test_extract_functions_records_function_metadata_when_present(tmp_path: Path) -> None:
    sample = tmp_path / "functions_metadata.opj"
    sample_payload = b"Function1\0<formula> y = a*x + b </formula><x1>0.0</x1><x2>5.0</x2><nx>32</nx>\r\nGraph1\0"
    sample.write_bytes(sample_payload)
    sample_bytes = sample.read_bytes()

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=0,
            name="Function1",
            length=len(sample_bytes),
            object_kind="function",
            source_object_path="Function/Function1",
            parser_rule="opj_function_payload",
            parser_confidence=0.9,
        ),
        OriginObject(
            offset=len(sample_bytes),
            name="Graph1",
            length=0,
            object_kind="graph",
            source_object_path="Graph/Graph1",
        ),
    ]
    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample_bytes,
        objects=objects,
    )

    assert count == 1
    function_items = [item for item in manifest.items if item.kind == "function"]
    assert len(function_items) == 1
    item = function_items[0]
    assert item.name == "Function1"
    assert item.status == "extracted"
    assert item.function_name == "Function1"
    assert item.function_formula == "y = a*x + b"
    assert item.function_range == ("0.0", "5.0")
    assert item.function_total_points == 32
    metadata_items = [
        item for item in manifest.items if item.kind == "function_metadata" and item.name == "Function1_metadata"
    ]
    assert len(metadata_items) == 1
    metadata_item = metadata_items[0]
    assert metadata_item.status == "extracted"
    assert metadata_item.source_object_path == "Function/Function1"
    assert metadata_item.path is not None

    metadata_path = out_dir / Path(metadata_item.path)
    assert metadata_path.exists()
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["function_name"] == "Function1"
    assert payload["function_formula"] == "y = a*x + b"
    assert payload["function_range"] == ["0.0", "5.0"]
    assert payload["function_total_points"] == 32
    assert payload["parser_rule"] == "opj_function_payload"
    assert payload["parser_confidence"] == 0.9
    assert payload["source_object_path"] == "Function/Function1"


def test_extract_functions_exports_parser_backed_function_payload(tmp_path: Path) -> None:
    function_payload = (
        b'<functionlist _XF_VAR_IO="0" _XF_VAR_TYPE="1">NewFunction (User)</functionlist>'
        b'<oy HideNodeName="1" _XF_VAR_IO="1" _XF_VAR_TYPE="5">[Book4]Sheet1!(A"X",B"Y")</oy>'
        b"<x1>-10.</x1><x2>10.</x2><nx>100</nx>"
    )
    header = b"CPYA 4.2673 552#\n"
    sample = tmp_path / "functions_parser_payload.opj"
    sample.write_bytes(header + function_payload)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(header),
            name="Function",
            length=len(function_payload),
            object_kind="function",
            source_object_path="Function/Function",
            parser_rule="opj_function_payload",
            parser_confidence=0.9,
        )
    ]

    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    payload_path = out_dir / "functions" / "Function" / "Function" / "function.payload.txt"
    assert payload_path.exists()
    payload_text = payload_path.read_text(encoding="utf-8")
    assert "functionlist: NewFunction (User)" in payload_text
    assert 'oy: [Book4]Sheet1!(A"X",B"Y")' in payload_text
    metadata_items = [
        item for item in manifest.items if item.kind == "function_metadata" and item.name == "Function_metadata"
    ]
    assert len(metadata_items) == 1
    metadata_item = metadata_items[0]
    assert metadata_item.status == "extracted"
    metadata_path = out_dir / Path(metadata_item.path or "")
    metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata_payload["function_formula"] == "NewFunction (User)"
    assert metadata_payload["function_range"] == ["-10.", "10."]
    assert metadata_payload["parser_rule"] == "opj_function_payload"


def test_extract_functions_exports_parser_backed_opju_function_region(tmp_path: Path) -> None:
    payload = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><Operation><xfName>smooth</xfName><XFunctionName>smooth</XFunctionName></Operation></OriginStorage>"
    )
    sample = tmp_path / "opju_function_payload.opju"
    sample.write_bytes(payload)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(b"CPYUA 4.3318 0\x00"),
            name="origin_storage_function_000",
            length=len(payload) - len(b"CPYUA 4.3318 0\x00"),
            object_kind="function",
            source_object_path="origin_storage/origin_storage_function_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    function_items = [item for item in manifest.items if item.kind == "function"]
    assert len(function_items) == 1
    item = function_items[0]
    assert item.name == "origin_storage_function_000"
    assert item.status == "extracted"
    assert item.discovery_type == "parser_window"
    assert item.heuristic is False
    assert (out_dir / Path(item.path or "")).exists()


def test_extract_functions_preserves_non_lossless_opju_region_as_raw_bytes(tmp_path: Path) -> None:
    header = b"CPYUA 4.3318 0\x00"
    region = b"<OriginStorage><Operation><xfName>smooth\x7f</xfName><Value>1.2\xff3</Value></Operation></OriginStorage>"
    sample = tmp_path / "opju_non_lossless_function.opju"
    sample.write_bytes(header + region)
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(header),
            name="origin_storage_function_000",
            length=len(region),
            object_kind="function",
            source_object_path="origin_storage/origin_storage_function_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    item = manifest.items[0]
    assert item.status == "partial"
    assert item.error == "non_lossless_function_text"
    assert item.replacement_character_count == 1
    assert item.control_character_count == 1
    assert item.path is not None
    assert item.path.endswith("function.raw.bin")
    assert (out_dir / item.path).read_bytes() == region
    assert not (out_dir / "functions/origin_storage/origin_storage_function_000/function.txt").exists()


def test_extract_functions_decodes_multiple_byte_run_xml_records(tmp_path: Path) -> None:
    header = b"CPYUA 4.3318 0\x00"
    first_prefix = b'<OriginStorage Creator="smooth">'
    first_suffix = b"</OriginStorage>"
    first = first_prefix + bytes((len(first_suffix),)) + first_suffix + b"\x00"
    second_prefix = b"<OriginStorage>"
    second_suffix = b'<Calculation AnalysisName="FitLinear" UID="41001"/></OriginStorage>'
    second = second_prefix + bytes((len(second_suffix),)) + second_suffix + b"\x00"
    region = first + b"tagged-envelope" + second
    sample = tmp_path / "opju_encoded_functions.opju"
    sample.write_bytes(header + region)
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(header),
            name="origin_storage_function_000",
            length=len(region),
            object_kind="function",
            source_object_path="origin_storage/origin_storage_function_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
        include_provenance=True,
    )

    assert count == 2
    function_items = [item for item in manifest.items if item.kind == "function"]
    assert [item.function_name for item in function_items] == ["smooth", "FitLinear"]
    assert [item.calculation_uid for item in function_items] == [None, 41001]
    assert all(item.status == "extracted" for item in function_items)
    assert all(item.verification == "exact" for item in function_items)
    assert len([item for item in manifest.items if item.kind == "function_source_map"]) == 2
    assert len([item for item in manifest.items if item.kind == "function_encoded_source"]) == 1
    source = sample.read_bytes()
    for item in function_items:
        xml = (out_dir / Path(item.path or "")).read_bytes()
        source_map = json.loads((out_dir / Path(item.source_map_path or "")).read_text(encoding="utf-8"))
        assert bytes(source[offset] for offset in source_map["source_map"]) == xml


def test_extract_functions_ignores_opj_function_helpers_for_opju_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><Operation><xfName>smooth</xfName><XFunctionName>smooth</XFunctionName></Operation></OriginStorage>"
    )
    sample = tmp_path / "opju_function_payload_no_opj_extract.opju"
    sample.write_bytes(payload)

    def _unexpected(*_args: object, **_kwargs: object) -> str | None:
        raise AssertionError("OPJ-only function parser helper was called for OPJU data")

    monkeypatch.setattr("deopjufier.extract.objects.parse_opj_function_payload", _unexpected)
    monkeypatch.setattr("deopjufier.extract.objects.parse_opj_function_metadata", _unexpected)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    objects = [
        ParserBackedDiscoveryRecord(
            offset=len(b"CPYUA 4.3318 0\x00"),
            name="origin_storage_function_000",
            length=len(payload) - len(b"CPYUA 4.3318 0\x00"),
            object_kind="function",
            source_object_path="origin_storage/origin_storage_function_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]

    count = extract_functions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
    )

    assert count == 1
    function_items = [item for item in manifest.items if item.kind == "function"]
    assert len(function_items) == 1
    assert function_items[0].path is not None
    assert (out_dir / Path(function_items[0].path)).exists()


def test_extract_functions_without_objects_no_parser_recovery(tmp_path: Path) -> None:
    sample = tmp_path / "no_function.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "out"
    count = extract_functions(sample, out_dir, manifest, force=True)

    assert count == 0
    assert not manifest.items


def test_extract_tables_csv_and_json_formats(tmp_path: Path) -> None:
    sample = tmp_path / "tables.opju"
    sample.write_bytes(b"1 2 3\n4 5 6\nn/a\n7 8 9\n10 11 12\n")

    manifest_csv = _make_manifest(sample)
    out_csv = tmp_path / "table_csv"
    count_csv = extract_tables(
        sample,
        out_csv,
        manifest_csv,
        output_format="csv",
        min_rows=2,
        min_columns=2,
    )
    assert count_csv >= 4
    table_csv = out_csv / "guessed_tables.csv"
    assert table_csv.exists()
    assert b"\r\n" not in table_csv.read_bytes()
    assert manifest_csv.items[0].kind == "table_scan"

    manifest_json = _make_manifest(sample)
    out_json = tmp_path / "table_json"
    count_json = extract_tables(
        sample,
        out_json,
        manifest_json,
        output_format="json",
        min_rows=2,
        min_columns=2,
    )
    assert count_json >= 4
    assert (out_json / "guessed_tables.json").exists()
    assert manifest_json.items[0].kind == "table_scan"


def test_extract_tables_marks_skipped_when_output_locked(tmp_path: Path) -> None:
    sample = tmp_path / "tables.opju"
    sample.write_bytes(b"1 2 3\n" + b"4 5 6\n" + b"7 8 9\n")
    outdir = tmp_path / "tables"
    outdir.mkdir()
    (outdir / "guessed_tables.csv").write_text("old", encoding="utf-8")

    manifest = _make_manifest(sample)
    count = extract_tables(
        sample,
        outdir,
        manifest,
        output_format="csv",
    )

    assert count == 0
    assert manifest.items[0].status == "skipped"
    assert manifest.items[0].error == "target_exists"
    assert manifest.items[0].source_object_path is not None


def test_extract_tables_unknown_output_format_falls_back_to_json(tmp_path: Path) -> None:
    sample = tmp_path / "tables_unknown.opju"
    sample.write_bytes(b"1 2 3\n4 5 6\n7 8 9\n")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "table_unknown"
    count = extract_tables(
        sample,
        out_dir,
        manifest,
        output_format="yaml",
        min_rows=1,
        min_columns=2,
        force=True,
    )

    assert count >= 3
    assert (out_dir / "guessed_tables.json").exists()
    assert manifest.items[0].kind == "table_scan"


def test_extract_raw_blocks_empty_file_records_partial(tmp_path: Path) -> None:
    sample = tmp_path / "empty.opju"
    sample.write_bytes(b"")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "raw"
    count = extract_raw_blocks(sample, out_dir, manifest, min_size=10)

    assert count == 0
    assert manifest.items[0].kind == "raw_dump"
    assert manifest.items[0].status == "partial"
    assert manifest.items[0].error == "empty_file"


def test_extract_raw_blocks_skips_locked_output(tmp_path: Path) -> None:
    sample = tmp_path / "raw.opju"
    sample.write_bytes(b"hello" * 10)
    out_dir = tmp_path / "raw"
    out_dir.mkdir()

    # lock first writable path and force one extracted gap to be skipped.
    (out_dir / "raw_off_000000000000_len_000000000050.bin").write_bytes(b"existing")

    manifest = _make_manifest(sample)
    count = extract_raw_blocks(sample, out_dir, manifest, min_size=1)
    assert count == 0
    assert manifest.items[0].status == "skipped"
    assert manifest.items[0].error == "target_exists"
    assert manifest.items[0].source_object_path is not None


def test_extract_raw_blocks_records_relative_manifest_paths(tmp_path: Path) -> None:
    sample = tmp_path / "raw_relative.opju"
    sample.write_bytes(b"hello" * 20)
    raw_dir = tmp_path / "out" / "raw"
    manifest = _make_manifest(sample)

    extract_raw_blocks(
        sample,
        raw_dir,
        manifest,
        force=True,
        min_size=1,
    )

    assert manifest.items
    assert all(
        item.path is not None and not Path(item.path).is_absolute()
        for item in manifest.items
        if item.kind == "raw_dump"
    )
    assert (raw_dir / "raw_off_000000000000_len_000000000100.bin").exists()
