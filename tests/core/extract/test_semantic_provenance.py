"""Canonical OPJU semantic-provenance regression tests."""

from __future__ import annotations

import csv
import json
import struct
from pathlib import Path
from typing import cast

from deopjufier.detect import detect_file
from deopjufier.extract.semantic_provenance import extract_opju_semantic_provenance
from deopjufier.manifest import ManifestItem, make_manifest
from deopjufier.opju.decoded import iter_opju_decoded_regions
from deopjufier.opju.decoded.payloads import (
    MSER_STRINGS_PSET_MAGIC,
    STYLE_HOLDER_SOURCE_INFO_MAGIC,
    STYLE_HOLDER_SUBRECORD_MAGIC,
)


def _varuint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _descriptor(name: bytes, value: float) -> bytes:
    payload = bytes.fromhex("0a 05 01 00 00 50") + struct.pack("<d", value) + b"\xce"
    header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
    return bytes((len(name),)) + name + header + b"12345678" + payload


def _integer_descriptor(name: bytes, values: list[int]) -> bytes:
    payload = (
        b"\x0a\x04"
        + _varuint(len(values))
        + b"\xff\xff"
        + _varuint(len(values))
        + b"\x01"
        + _varuint(2 * len(values) - 1)
        + b"".join(_varuint(value) for value in values)
        + b"\xce"
    )
    header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
    return bytes((len(name),)) + name + header + b"12345678" + payload


def _system_envelope(*, sheet_long_name: bytes) -> bytes:
    body = b"\x0bSYSTEM\x03\x00\x8e\x02\x01" + b"\xcc\x02\x03" + bytes((len(sheet_long_name),))
    body += sheet_long_name
    return b"\xfa" + _varuint(len(body)) + b"\x01" + body


def _metadata(ordinal: int, name: bytes, designation: int, long_name: bytes) -> bytes:
    label = b"\x9a\x01\x00\x0a" + bytes((len(long_name) + 2, len(long_name) + 1)) + long_name + b"\0"
    return (
        b"\x10\x80\x03"
        + ordinal.to_bytes(2, "little")
        + b"\x09\x81\x02\xc3\x01\x82\x01"
        + name
        + b"\x88\x01\x09\x81\x04\x01\x00\x21"
        + bytes((designation,))
        + label
    )


def _semantic_opju() -> bytes:
    analysis = (
        b'<OriginStorage><Calculation AnalysisName="LinearFit">'
        b"<Equation>y = offset + slope*x</Equation>"
        b"<Input><X>[Book1]theta!A</X><Y>[Book1]theta!B</Y></Input>"
        b"<Parameters><Slope><Value>2.5</Value></Slope></Parameters>"
        b"<Operation><UID>7</UID></Operation>"
        b"</Calculation></OriginStorage>"
    )
    return (
        b"CPYUA 4.3445 200\n"
        + _descriptor(b"Book1_A", 1.0)
        + _system_envelope(sheet_long_name=b"theta")
        + _descriptor(b"Book1_B", 2.0)
        + _metadata(1, b"A", 0x51, b"time")
        + _metadata(2, b"B", 0x61, b"signal")
        + analysis
    )


def _storage_reference_envelope(uid: int) -> bytes:
    payload = bytearray(struct.pack("<II", 0, 3))
    for ordinal in range(3):
        payload.extend(struct.pack("<IIIiII", 16, 0x00000702, ordinal, -999, uid, 0))
    payload.extend(struct.pack("<I", 0))
    stream = bytes((0xF0, len(payload) - 15)) + payload
    body = len(payload).to_bytes(4, "little") + stream
    return b"\xfa" + _varuint(len(body)) + b"\x01" + body


def _decoded_envelope(payload: bytes) -> bytes:
    extension = bytearray()
    remaining = len(payload) - 15
    while remaining >= 255:
        extension.append(255)
        remaining -= 255
    extension.append(remaining)
    stream = b"\xf0" + bytes(extension) + payload
    body = len(payload).to_bytes(4, "little") + stream
    return b"\xfa" + _varuint(len(body)) + b"\x01" + body


def _mser_strings(values: list[str]) -> bytes:
    blob = b"".join(value.encode("utf-8") + b"\0" for value in values)
    return struct.pack("<IHHIIII", MSER_STRINGS_PSET_MAGIC, 2, 1, 4, 8, len(blob), len(values)) + blob + b"\0\0\0\0"


def _style_subrecord(index: int, y_column: str) -> bytes:
    typed_y = (1 << 16) | ord(y_column)
    typed_x = (1 << 16) | ord("A")
    payload = bytearray(struct.pack("<IHHI", STYLE_HOLDER_SUBRECORD_MAGIC, 1, 1, index))
    payload.extend(struct.pack("<7I", 0, 0, 0, 12, 0, 0, 0))
    payload.extend(struct.pack("<I", 3))
    descriptors = (
        (1, 0, index + 1, 0x7FFFFFFF, typed_y, 0, 0, 0, 0, 0),
        (2, 2, index + 1, 0x7FFFFFFF, typed_y, 0, 0, 0, 0, 0),
        (2, 1, 0, 0x7FFFFFFF, typed_x, 0, 0, 0, 0, 0),
    )
    for descriptor in descriptors:
        payload.extend(struct.pack("<10I", *descriptor))
    payload.extend(struct.pack("<3IB", 0, 1, 0, 0))
    payload.extend(b"Sheet1\0")
    payload.extend(struct.pack("<4I", 2, 0, 2, 16))
    payload.extend(b"\xff" * 16)
    payload.extend(struct.pack("<IBIH4I4d", 55, 1, 8, 0, 3, 1, 3, 1, 1.0, 0.0, 1.0, 0.0))
    return bytes(payload)


def _style_info() -> bytes:
    return (
        struct.pack("<4I", STYLE_HOLDER_SOURCE_INFO_MAGIC, 0x00010000, 0, 1)
        + _style_subrecord(0, "B")
        + struct.pack("<I", 0)
    )


def test_semantic_provenance_links_exact_symbols_equations_and_parameters(tmp_path: Path) -> None:
    data = _semantic_opju()
    sample = tmp_path / "semantic.opju"
    sample.write_bytes(data)
    out_dir = tmp_path / "out"
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")

    count = extract_opju_semantic_provenance(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        manifest_root=out_dir,
    )

    assert count == 2
    payload = json.loads((out_dir / "provenance/semantic_index.json").read_text(encoding="utf-8"))
    assert payload["summary"] == {
        "analysis_count": 1,
        "analysis_alias_count": 1,
        "analysis_linked_report_table_count": 0,
        "calculation_link_count": 0,
        "equation_count": 1,
        "external_code_mapping": "not_assessed",
        "graph_binding_count": 0,
        "linked_symbol_count": 2,
        "report_cell_reference_count": 0,
        "report_table_count": 0,
        "resolved_calculation_link_count": 0,
        "resolved_analysis_alias_count": 1,
        "resolved_graph_binding_count": 0,
        "resolved_report_table_count": 0,
        "state_table_count": 0,
        "symbol_count": 2,
        "unresolved_reference_count": 0,
        "worksheet_identity_count": 1,
    }
    assert [symbol["symbol"] for symbol in payload["symbols"]] == ["time", "signal"]
    assert {symbol["equation_status"] for symbol in payload["symbols"]} == {"attributable_equation_recovered"}
    assert {symbol["provenance_status"] for symbol in payload["symbols"]} == {"linked_to_analysis"}
    assert {symbol["analysis_links"][0]["reference"] for symbol in payload["symbols"]} == {
        "[Book1]theta!A",
        "[Book1]theta!B",
    }

    analysis = payload["analyses"][0]
    assert analysis["semantic_status"] == "equation_with_source_references"
    assert analysis["equations"][0]["value"] == "y = offset + slope*x"
    assert analysis["parameter_fields"][0]["path"] == "OriginStorage/Calculation/Parameters/Slope/Value"
    assert {reference["status"] for reference in analysis["references"]} == {"resolved_exact"}
    equation_range = analysis["equations"][0]["source_range"]
    assert data[equation_range["start"] : equation_range["end"]] == b"y = offset + slope*x"

    with (out_dir / "provenance/symbols.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["symbol"] for row in rows] == ["time", "signal"]
    assert all(row["equations"] == "y = offset + slope*x" for row in rows)
    assert all(row["external_code_status"] == "not_assessed" for row in rows)

    items = [item for item in manifest.items if item.kind == "semantic_provenance"]
    assert len(items) == 3
    assert all(item.verification == "exact" for item in items)
    assert all(item.completeness == "partial" for item in items)
    assert all(item.error is None for item in items)


def test_semantic_provenance_links_bounded_column_envelope_to_calculation_uid(tmp_path: Path) -> None:
    uid = 41001
    data = b"CPYUA 4.3445 200\n" + _descriptor(b"Book1_A", 1.0) + _storage_reference_envelope(uid)
    sample = tmp_path / "calculated.opju"
    sample.write_bytes(data)
    out_dir = tmp_path / "out"
    function_target = out_dir / "functions/fit_linear.xml"
    function_target.parent.mkdir(parents=True)
    function_target.write_bytes(
        b'<OriginStorage><Calculation AnalysisName="FitLinear" UID="41001">'
        b"<Equation>y = a + b*x</Equation></Calculation></OriginStorage>"
    )
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    manifest.add_item(
        ManifestItem(
            kind="function",
            name="fit_linear",
            status="extracted",
            confidence=0.98,
            path="functions/fit_linear.xml",
            source_object_path="functions/fit_linear",
            function_name="FitLinear",
            calculation_uid=uid,
            extraction_method="origin_storage_byte_run_decode",
            verification="exact",
        )
    )

    extract_opju_semantic_provenance(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        manifest_root=out_dir,
    )

    payload = json.loads((out_dir / "provenance/semantic_index.json").read_text(encoding="utf-8"))
    assert payload["summary"]["calculation_link_count"] == 1
    assert payload["summary"]["resolved_calculation_link_count"] == 1
    link = payload["calculation_links"][0]
    assert link["status"] == "resolved_exact"
    assert link["symbol_id"] == "worksheet:[Book1]Sheet1!A"
    assert link["function_analysis_ids"] == ["function:fit_linear"]
    assert link["dependency_ordinals_zero_based"] == [0, 1, 2]
    symbol = payload["symbols"][0]
    assert symbol["provenance_status"] == "linked_to_calculation"
    assert symbol["equation_status"] == "attributable_equation_recovered"
    assert symbol["analysis_links"][0]["equations"] == ["y = a + b*x"]


def test_semantic_provenance_recovers_report_identity_cells_and_state_fields(tmp_path: Path) -> None:
    report_cells = _mser_strings(
        [
            "cell://[ReportBook]Result!Notes.Equation",
            "cell://[ReportBook]Result!Parameters.Slope.Value",
        ]
    )
    state = (
        bytes.fromhex("00 04 8c 01 33 c0 11 01")
        + b"\x11\x80\x01COKOGrid_SetTree\0"
        + b"\x0c\x80\x02_TableRange\0"
        + bytes.fromhex("28 c0 11 06 00 00 01 00 4b")
    )
    analysis = (
        b"<OriginStorage><Calculation>"
        b"<Input><Y>[ReportBook]Result!B</Y></Input>"
        b"</Calculation><GUI><Output><Report><BookName>ReportBook</BookName>"
        b"<SheetName>Result</SheetName></Report></Output></GUI></OriginStorage>"
    )
    data = (
        b"CPYUA 4.3445 200\n"
        + state
        + _descriptor(b"Archive_A", 1.0)
        + _decoded_envelope(report_cells)
        + _descriptor(b"Archive_B", 2.0)
        + analysis
    )
    sample = tmp_path / "report_state.opju"
    sample.write_bytes(data)
    out_dir = tmp_path / "out"
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")

    extract_opju_semantic_provenance(sample, out_dir, manifest, force=True, file_data=data)

    payload = json.loads((out_dir / "provenance/semantic_index.json").read_text(encoding="utf-8"))
    assert payload["summary"]["report_table_count"] == 1
    assert payload["summary"]["report_cell_reference_count"] == 2
    assert payload["summary"]["analysis_linked_report_table_count"] == 1
    report = payload["report_tables"][0]
    assert report["ownership_status"] == "resolved_exact"
    assert report["owner_worksheet_ids"] == ["Archive/Sheet1"]
    assert report["analysis_ids"] == ["origin_storage_analysis:000"]
    assert [cell["cell_path"] for cell in report["cells"]] == [
        "Notes.Equation",
        "Parameters.Slope.Value",
    ]
    assert payload["analyses"][0]["references"][0]["status"] == "resolved_exact"
    identity = payload["worksheet_identities"][0]
    assert any(
        alias["workbook"] == "ReportBook"
        and alias["sheet"] == "Result"
        and alias["evidence_kind"] == "descriptor_owned_report_cell_uri"
        for alias in identity["address_aliases"]
    )
    state_table = payload["state_tables"][0]
    assert state_table["operations"] == ["COKOGrid_SetTree", "_TableRange"]
    assert any(field["little_endian_unsigned"] == 75 for field in state_table["scalar_fields"])


def test_semantic_provenance_materializes_exact_resolved_report_table(tmp_path: Path) -> None:
    left_values = ["cell://[ResultBook]Fit!Notes.Equation", "localized result"]
    right_values = ["cell://[ResultBook]Fit!Parameters.Slope", "second result value"]
    left_offsets = [1, len(left_values[0].encode("utf-8")) + 2]
    right_offsets = [1, len(right_values[0].encode("utf-8")) + 2]
    data = (
        b"CPYUA 4.3445 200\n"
        + _integer_descriptor(b"Table_A", left_offsets)
        + _decoded_envelope(_mser_strings(left_values))
        + _integer_descriptor(b"Table_B", right_offsets)
        + _decoded_envelope(_mser_strings(right_values))
    )
    sample = tmp_path / "resolved_report.opju"
    sample.write_bytes(data)
    out_dir = tmp_path / "out"
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")

    extract_opju_semantic_provenance(sample, out_dir, manifest, force=True, file_data=data)

    payload = json.loads((out_dir / "provenance/semantic_index.json").read_text(encoding="utf-8"))
    assert payload["summary"]["resolved_report_table_count"] == 1
    report = payload["report_tables"][0]
    assert report["resolution_status"] == "resolved_exact"
    assert report["completeness"] == "complete"
    assert report["structural_name"] == "report_table"
    assert report["semantic_alias"] == "analysis_report_placeholder_reference_table"
    assert report["semantic_confidence"] == "corpus_high"
    with (out_dir / "report_tables/Table/Sheet1/report_table.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["A", "B"], [left_values[0], right_values[0]], [left_values[1], right_values[1]]]
    item = next(item for item in manifest.items if item.kind == "report_table")
    assert item.verification == "exact"
    assert item.completeness == "complete"
    assert item.structural_name == "report_table"
    assert item.semantic_alias == "analysis_report_placeholder_reference_table"
    assert item.semantic_confidence == "corpus_high"


def test_semantic_provenance_recovers_graph_source_binding_with_exact_candidates(tmp_path: Path) -> None:
    data = (
        b"CPYUA 4.3445 200\n"
        + _descriptor(b"Archive_A", 1.0)
        + _descriptor(b"Archive_B", 2.0)
        + _decoded_envelope(_style_info())
    )
    regions = iter_opju_decoded_regions(data)
    style_region = next(region for region in regions if region.classification.family == "style_holder_source_info_v1")
    sample = tmp_path / "graph_binding.opju"
    sample.write_bytes(data)
    out_dir = tmp_path / "out"
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    manifest.add_item(
        ManifestItem(
            kind="graph",
            name="Graph1",
            status="extracted",
            confidence=0.98,
            heuristic=False,
            source_object_path="graphs/Graph1",
            source_ranges=[{"start": style_region.source_start, "end": style_region.source_end}],
            verification="exact",
        )
    )

    extract_opju_semantic_provenance(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        decoded_regions=regions,
    )

    payload = json.loads((out_dir / "provenance/semantic_index.json").read_text(encoding="utf-8"))
    assert payload["summary"]["graph_binding_count"] == 1
    assert payload["summary"]["resolved_graph_binding_count"] == 1
    binding = payload["graph_bindings"][0]
    assert binding["dataset_binding_status"] == "resolved_exact"
    assert binding["graph_owner_status"] == "resolved_exact"
    assert binding["dataset_candidates"] == [
        {
            "worksheet_id": "Archive/Sheet1",
            "x_symbol_id": "worksheet:[Archive]Sheet1!A",
            "y_symbol_id": "worksheet:[Archive]Sheet1!B",
        }
    ]
    source = cast(dict[str, object], binding["source"])
    assert source["worksheet"] == "Sheet1"
    assert source["x_column_short_name"] == "A"
    assert source["y_column_short_name"] == "B"
