from __future__ import annotations

import struct
from typing import Any, cast

from deopjufier.opju.decoded.payloads import (
    MSER_STRINGS_PSET_MAGIC,
    STORAGE_CELL_REF_SENTINEL,
    STORAGE_CELL_REF_TYPE,
    STYLE_HOLDER_SOURCE_INFO_MAGIC,
    STYLE_HOLDER_SUBRECORD_MAGIC,
    classify_decoded_payload,
    parse_mser_strings_pset,
    parse_storage_cell_refs,
    parse_style_holder_source_info,
)


def _mser_strings(values: list[str]) -> bytes:
    blob = b"".join(value.encode("utf-8") + b"\x00" for value in values)
    return struct.pack("<IHHIIII", MSER_STRINGS_PSET_MAGIC, 2, 1, 4, 8, len(blob), len(values)) + blob + b"\0\0\0\0"


def _cell_refs(uid: int, count: int = 3) -> bytes:
    payload = bytearray(struct.pack("<II", 0, count))
    for ordinal in range(count):
        payload.extend(
            struct.pack(
                "<IIIiII",
                16,
                STORAGE_CELL_REF_TYPE,
                ordinal,
                STORAGE_CELL_REF_SENTINEL,
                uid,
                0,
            )
        )
    payload.extend(struct.pack("<I", 0))
    return bytes(payload)


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
    payload.extend(b"Sheet1\x00")
    payload.extend(struct.pack("<4I", 2, 0, 2, 16))
    payload.extend(b"\xff" * 16)
    payload.extend(struct.pack("<IBIH4I4d", 55, 1, 8, 0, 3, 1, 3, 1, 1.0, 0.0, 1.0, 0.0))
    assert len(payload) == 275
    return bytes(payload)


def _style_info() -> bytes:
    return (
        struct.pack("<4I", STYLE_HOLDER_SOURCE_INFO_MAGIC, 0x00010000, 0, 2)
        + _style_subrecord(0, "B")
        + _style_subrecord(1, "C")
        + struct.pack("<I", 0)
    )


def test_mser_string_property_set_consumes_exact_blob() -> None:
    parsed = parse_mser_strings_pset(_mser_strings(["cell://Sheet1!A", "row label"]))

    assert parsed is not None
    assert parsed["structural_name"] == "mser_strings_pset"
    assert parsed["semantic_alias"] == "origin_string_property_set"
    assert parsed["semantic_confidence"] == "wire_exact"
    assert parsed["version"] == 2
    assert parsed["strings"] == ["cell://Sheet1!A", "row label"]
    assert parsed["string_records"] == [
        {
            "decoded_range": {"start": 24, "end": 39},
            "index": 0,
            "nul_offset": 39,
            "value": "cell://Sheet1!A",
        },
        {
            "decoded_range": {"start": 40, "end": 49},
            "index": 1,
            "nul_offset": 49,
            "value": "row label",
        },
    ]
    assert parsed["terminator"] == 0


def test_storage_cell_references_retain_calculation_uid() -> None:
    parsed = parse_storage_cell_refs(_cell_refs(41001))

    assert parsed is not None
    assert parsed["structural_name"] == "storage_cell_ref_data"
    assert parsed["semantic_alias"] == "analysis_result_reference_array"
    assert parsed["semantic_confidence"] == "corpus_high"
    assert parsed["count"] == 3
    records = cast(list[dict[str, Any]], parsed["records"])
    assert [record["ordinal"] for record in records] == [0, 1, 2]
    assert [record["analysis_result_slot_ordinal"] for record in records] == [0, 1, 2]
    assert {record["calculation_uid"] for record in records} == {41001}
    assert {record["source_analysis_operation_uid"] for record in records} == {41001}
    assert {record["analysis_result_reference_type_code"] for record in records} == {"0x00000702"}
    assert {record["unresolved_or_not_applicable_index_sentinel"] for record in records} == {-999}


def test_style_holder_source_info_bounds_every_byte() -> None:
    payload = _style_info()
    parsed = parse_style_holder_source_info(payload)

    assert len(payload) == 570
    assert parsed is not None
    subrecords = cast(list[dict[str, Any]], parsed["subrecords"])
    assert [record["length"] for record in subrecords] == [275, 275]
    assert [record["reference_descriptors"][0]["character_hint"] for record in subrecords] == ["B", "C"]
    assert [record["reference_descriptors"][2]["character_hint"] for record in subrecords] == ["A", "A"]
    assert parsed["semantic_name"] == "data_plot_style_holder_source_info_v1"
    assert parsed["structural_name"] == "data_plot_style_holder_source_info"
    assert parsed["semantic_alias"] == "data_plot_style_prototype_source_binding"
    assert parsed["semantic_confidence"] == "corpus_high"
    assert parsed["object_role"] == "persistent graph-layer data-plot style-holder source metadata"
    source_slots = cast(list[dict[str, Any]], parsed["source_slots"])
    assert [slot["x_column_short_name"] for slot in source_slots] == ["A", "A"]
    assert [slot["y_column_short_name"] for slot in source_slots] == ["B", "C"]
    assert [descriptor["semantic_role"] for descriptor in subrecords[0]["reference_descriptors"]] == [
        "primary_plot_dataset_reference",
        "y_source_column_reference",
        "x_source_column_reference",
    ]
    assert subrecords[0]["reference_descriptors"][0]["semantic_confidence"] == "corpus_medium"
    assert subrecords[0]["reference_descriptors"][1]["semantic_confidence"] == "corpus_high"
    assert subrecords[0]["reference_descriptors"][0]["sentinel_interpretation"] == "unbounded_or_unspecified_index"
    assert subrecords[0]["tail"]["f64_values"] == [1.0, 0.0, 1.0, 0.0]


def test_decoded_payload_classifier_distinguishes_all_bounded_families() -> None:
    payloads = (
        (b"<OriginStorage/>\x00", "origin_storage_xml"),
        (_mser_strings(["one"]), "mser_strings_pset"),
        (_cell_refs(42), "storage_cell_ref_data"),
        (_style_info(), "style_holder_source_info_v1"),
        (b"not a known payload", "unknown"),
    )

    for payload, family in payloads:
        classified = classify_decoded_payload(payload)
        assert classified.family == family
        assert classified.known is (family != "unknown")
