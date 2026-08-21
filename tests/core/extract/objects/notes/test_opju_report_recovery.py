"""Regression coverage for exact byte-run analysis-report recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from deopjufier.detect import detect_file
from deopjufier.extract import extract_notes
from deopjufier.inventory import OriginObject, ParserBackedDiscoveryRecord
from deopjufier.manifest import ManifestItem, make_manifest
from deopjufier.opju.common import OPJU_REGION_KIND_TAGGED_BINARY
from deopjufier.opju.walker import OpjuWalkElement


def _encoded_report() -> bytes:
    prefix = b"<OriginStorage>"
    suffix = b'<Calculation AnalysisName="FitLinear" Label="Fit Result"/></OriginStorage>'
    return prefix + bytes((len(suffix),)) + suffix + b"\x00"


def test_extract_notes_decodes_and_attributes_encoded_analysis_report(tmp_path: Path) -> None:
    header = b"CPYUA 4.3445 200\n"
    encoded = _encoded_report()
    state = (
        bytes.fromhex("00 04 8c 01 33 c0 11 01")
        + b"\x11\x80\x01COKOGrid_SetTree\0"
        + bytes.fromhex("28 c0 11 06 00 00 01 00 4b")
    )
    note_start = len(header)
    note_end = note_start + len(encoded)
    sample = tmp_path / "encoded_report.opju"
    sample.write_bytes(header + encoded + state)
    manifest = make_manifest(sample, detect_file(sample), "native-parser", sample.stat().st_size, "fixture")
    manifest.add_item(
        ManifestItem(
            kind="function",
            name="fit_linear",
            status="extracted",
            confidence=0.98,
            path="functions/fit_linear.xml",
            source_object_path="functions/fit_linear",
            function_name="FitLinear",
            calculation_label="Fit Result",
            calculation_uid=41001,
            extraction_method="origin_storage_byte_run_decode",
            verification="exact",
        )
    )
    objects = [
        ParserBackedDiscoveryRecord(
            offset=note_start,
            name="origin_storage_note_000",
            length=len(encoded),
            object_kind="opju_note_payload",
            source_object_path="origin_storage/origin_storage_note_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        )
    ]
    walk_elements = [
        OpjuWalkElement(
            kind=OPJU_REGION_KIND_TAGGED_BINARY,
            name="state",
            start_offset=note_end,
            end_offset=note_end + len(state),
            metadata={
                "family": "tagged_00_04_8c",
                "semantic_status": "fields_partial",
            },
        )
    ]
    out_dir = tmp_path / "out"

    count = extract_notes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=sample.read_bytes(),
        objects=cast(list[OriginObject], objects),
        include_provenance=True,
        walk_elements=walk_elements,
    )

    assert count == 1
    assert not [item for item in manifest.items if item.kind == "note"]
    report = next(item for item in manifest.items if item.kind == "analysis_report")
    assert report.calculation_label == "Fit Result"
    assert report.calculation_uid == 41001
    assert report.verification == "exact"
    assert (out_dir / Path(report.path or "")).read_bytes().startswith(b"<OriginStorage>")
    source_map = json.loads((out_dir / Path(report.source_map_path or "")).read_text(encoding="utf-8"))
    source = sample.read_bytes()
    recovered_xml = (out_dir / Path(report.path or "")).read_bytes()
    assert bytes(source[offset] for offset in source_map["source_map"]) == recovered_xml
    metadata_item = next(item for item in manifest.items if item.kind == "analysis_report_metadata")
    metadata = json.loads((out_dir / Path(metadata_item.path or "")).read_text(encoding="utf-8"))
    assert metadata["linked_function"]["status"] == "resolved_exact"
    assert metadata["linked_state_envelope"]["operations"] == ["COKOGrid_SetTree"]
    state_item = next(item for item in manifest.items if item.kind == "analysis_report_state")
    assert (out_dir / Path(state_item.path or "")).read_bytes() == state
