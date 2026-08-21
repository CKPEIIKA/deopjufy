"""Contracts for decoded OPJU regions and the OPJU structural walk."""

from __future__ import annotations

import base64
import csv
import json
import struct
from pathlib import Path

from deopjufier.detect import detect_file
from deopjufier.extract import extract_opju_decoded_regions, extract_opju_tagged_envelopes
from deopjufier.manifest import ManifestItem, make_manifest
from deopjufier.opju import (
    decode_opju_column_payload,
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
    iter_opju_decoded_regions,
    iter_opju_decoded_strings,
    iter_opju_tagged_envelopes,
    iter_tagged_scalars,
    iter_tagged_strings,
    parse_opju_column_identity,
    walk_opju_file,
)


def _literal_lz4_opju(payload: bytes) -> bytes:
    assert 15 <= len(payload) < 270
    header = b"CPYUA 4.3318 0\x00"
    stream = bytes((0xF0, len(payload) - 15)) + payload
    return header + len(payload).to_bytes(4, "little") + stream


def test_iter_opju_decoded_regions_preserves_exact_payload_and_source_span() -> None:
    payload = b'<OriginStorage Label="Layout"><Col>2</Col><Row>1</Row></OriginStorage>'
    data = _literal_lz4_opju(payload)

    regions = iter_opju_decoded_regions(data)

    assert len(regions) == 1
    region = regions[0]
    assert region.payload == payload
    assert region.decoded_length == len(payload)
    assert data[region.source_start + 2 : region.source_end] == payload
    assert region.compressed_length == len(payload) + 2
    assert region.region_kind == "origin_storage_report"
    assert region.label == "Layout"
    assert region.extension == "xml"
    assert region.compression == "lz4-block"
    assert region.declared_decoded_length == len(payload)
    assert region.family_marker is None
    assert region.marker_offset is None
    assert region.header_offset == len(b"CPYUA 4.3318 0\x00")
    assert region.stream_offset == 4
    assert region.framing_rule == "origin_storage_anchor"
    assert region.classification.family == "origin_storage_xml"
    assert region.classification.verification == "exact"


def test_iter_opju_decoded_strings_exposes_compressed_text() -> None:
    payload = b"<OriginStorage><Notes>compressed-only text</Notes></OriginStorage>"
    data = _literal_lz4_opju(payload)

    strings = iter_opju_decoded_strings(data, min_length=8)

    assert len(strings) == 1
    assert strings[0].region_index == 0
    assert strings[0].source_start == len(b"CPYUA 4.3318 0\x00") + 4
    assert strings[0].value == payload.decode("ascii")


def test_walk_opju_file_reports_decoded_region_lengths() -> None:
    payload = b'<OriginStorage Label="Layout"><Col>2</Col><Row>1</Row></OriginStorage>'
    data = _literal_lz4_opju(payload)

    elements = walk_opju_file(data)

    assert elements[0].kind == "opju_container"
    decoded = next(element for element in elements if element.metadata.get("source_kind") == "decoded")
    assert decoded.name == "Layout"
    assert decoded.metadata["decoded_length"] == len(payload)
    assert decoded.metadata["compressed_length"] == len(payload) + 2
    assert decoded.metadata["compression"] == "lz4-block"
    assert decoded.metadata["declared_decoded_length"] == len(payload)
    assert decoded.metadata["header_offset"] == len(b"CPYUA 4.3318 0\x00")
    assert decoded.metadata["stream_offset"] == 4
    assert decoded.metadata["framing_rule"] == "origin_storage_anchor"


def test_iter_tagged_strings_decodes_only_exact_length_framed_utf8() -> None:
    payload = b"prefix" + b"\x05\x80\x2aName\0" + b"\x05\x80\x2bbad\x01\0"

    strings = iter_tagged_strings(payload, source_start=100)

    assert len(strings) == 1
    assert strings[0].offset == 109
    assert strings[0].length == 5
    assert strings[0].tag_code == 0x2A
    assert strings[0].value == "Name"


def test_iter_opju_tagged_envelopes_requires_exact_gap_family_signature() -> None:
    header = b"CPYUA 4.3445 200\n"
    tagged = bytes.fromhex("86 01 02 80 01 18 80 01") + b"\x05\x80\x2aName\0"
    bounded_payload = b"<OriginStorage/>"
    unrelated = b"not-a-tagged-envelope"
    data = header + tagged + bounded_payload + unrelated
    bounded_ranges = [
        (0, len(header)),
        (len(header) + len(tagged), len(header) + len(tagged) + len(bounded_payload)),
    ]

    envelopes = iter_opju_tagged_envelopes(data, bounded_ranges)

    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.family == "tagged_86_01"
    assert envelope.start_offset == len(header)
    assert envelope.end_offset == len(header) + len(tagged)
    assert [field.value for field in envelope.strings] == ["Name"]


def test_iter_opju_tagged_envelopes_classifies_bounded_xml_close_fragment() -> None:
    header = b"CPYUA 4.3445 200\n"
    bounded_payload = b"<OriginStorage/>"
    close_fragment = b"</INSERT_PAGE>"
    data = header + bounded_payload + close_fragment

    envelopes = iter_opju_tagged_envelopes(data, [(0, len(header) + len(bounded_payload))])

    assert len(envelopes) == 1
    assert envelopes[0].family == "xml_close_fragment"
    assert envelopes[0].semantic_status == "decoded_xml_framing"
    assert envelopes[0].start_offset == len(header) + len(bounded_payload)
    assert envelopes[0].end_offset == len(data)


def test_iter_opju_tagged_envelopes_preserves_malformed_xml_framing() -> None:
    header = b"CPYUA 4.3445 200\n"
    malformed = b"</EXPGRAP\x7fH><PLOTSTACKBROWSER>"

    envelopes = iter_opju_tagged_envelopes(header + malformed, [(0, len(header))])

    assert len(envelopes) == 1
    assert envelopes[0].family == "malformed_xml_close_fragment"
    assert envelopes[0].semantic_status == "corrupt_xml_framing_preserved"


def test_iter_opju_tagged_envelopes_owns_system_origin_storage_prelude() -> None:
    header = b"CPYUA 4.3445 200\n"
    prelude = b"\xfa\xbf\x08\x01\x0bSYSTEM\x03\0\x8e\x02\x01" + b"FitCurve\0"
    origin_storage = b"<OriginStorage><Bin /></OriginStorage>"
    data = header + prelude + origin_storage

    envelopes = iter_opju_tagged_envelopes(
        data,
        [(0, len(header)), (len(header) + len(prelude), len(data))],
    )

    assert len(envelopes) == 1
    assert envelopes[0].family == "tagged_system_prelude"
    assert envelopes[0].start_offset == len(header)
    assert envelopes[0].end_offset == len(header) + len(prelude)
    assert envelopes[0].semantic_status == "fields_partial"


def test_iter_tagged_scalars_decodes_only_exact_self_bounded_wire_frames() -> None:
    one_byte = bytes.fromhex("28 c0 11 06 00 00 01 00 4b")
    double_width = bytes.fromhex("2d c0 11 0d 01 00 01 00") + struct.pack("<d", 37.5)
    invalid_descriptor = bytes.fromhex("22 c0 11 05 00 00 00 00")

    fields = iter_tagged_scalars(one_byte + double_width + invalid_descriptor, source_start=100)

    assert len(fields) == 2
    assert fields[0].offset == 100
    assert fields[0].end_offset == 100 + len(one_byte)
    assert fields[0].field_code == 0x28
    assert fields[0].declared_size == 6
    assert fields[0].descriptor_hex == "00 00 01 00"
    assert fields[0].value_hex == "4b"
    assert fields[0].little_endian_unsigned == 0x4B
    assert fields[1].value_width == 8
    assert fields[1].value_hex == struct.pack("<d", 37.5).hex(" ")


def test_iter_opju_column_descriptors_decodes_observed_header_variants() -> None:
    first_name = b"N2N_A@3"
    first_header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + (4).to_bytes(8, "little")
    second_name = b"O2O_H@4"
    second_header = bytes.fromhex("8f 02 ca 10 83 01 02 96 18 18") + b"\0" * 7 + (3).to_bytes(8, "little")
    first_stored = b"12345678" + b"data"
    between = b"next-header"
    second_stored = b"abcdefgh" + b"raw"
    data = b"prefix" + first_name + first_header + first_stored + between + second_name + second_header + second_stored

    descriptors = iter_opju_column_descriptors(data)

    assert [(item.name, item.stored_payload_length) for item in descriptors] == [("N2N_A@3", 4), ("O2O_H@4", 3)]
    assert descriptors[0].start_offset == len(b"prefix")
    assert descriptors[0].stored_payload_length_offset == len(b"prefix") + len(first_name) + 14
    assert descriptors[0].payload_prelude == b"12345678".hex(" ")
    assert descriptors[0].payload_end == descriptors[0].payload_offset + 4
    assert descriptors[1].start_offset == descriptors[0].payload_end


def test_iter_opju_column_descriptors_owns_bounded_system_prelude() -> None:
    def record(name: bytes, payload: bytes) -> bytes:
        header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
        return bytes((len(name),)) + name + header + b"12345678" + payload

    empty = bytes.fromhex("0a 05 01 01 00 00 ce")
    first = record(b"Book_A", empty)
    system_prelude = b"\xfa\x11\x01\x0bSYSTEM" + b"\0" * 80
    data = first + system_prelude + record(b"Book_B", empty)

    descriptors = iter_opju_column_descriptors(data)

    assert len(descriptors) == 2
    assert descriptors[1].start_offset == descriptors[0].payload_end
    assert data[descriptors[1].start_offset : descriptors[1].name_offset - 1] == system_prelude
    assert data[descriptors[1].name_offset - 1] == len(b"Book_B")


def test_iter_opju_column_descriptors_decodes_confirmed_numeric_header() -> None:
    name = b"N2N_A@3"
    payload = bytes.fromhex("0a 05 01 ff ff 01 00 01 0c 07") + struct.pack("<d", 500.0) + b"\xce"
    header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
    data = b"prefix" + name + header + b"12345678" + payload

    descriptor = iter_opju_column_descriptors(data)[0]

    assert descriptor.row_capacity == 1
    assert descriptor.stored_value_count == 1
    assert descriptor.first_control_byte == 0x07
    assert descriptor.first_value == 500.0
    assert descriptor.decoded_payload is not None
    assert descriptor.decoded_payload.value_bits == ("407f400000000000",)


def test_group_opju_column_descriptors_uses_dataset_ownership_and_column_order() -> None:
    def record(name: bytes, payload: bytes) -> bytes:
        header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
        return bytes((len(name),)) + name + header + b"12345678" + payload

    numeric = bytes.fromhex("0a 05 02 00 00 50") + struct.pack("<d", 1.0) + bytes.fromhex("ff ff 01 01 02 00 ce")
    text = bytes.fromhex("0a 05 02 ff ff 02 01 01 01") + b"x" + bytes.fromhex("02 00 ce")
    empty = bytes.fromhex("0a 05 02 ff ff 02 01 04 00 ce")
    data = b"CPYUA 4.3445 200\n" + record(b"Book1_B", text) + record(b"Book1_A", numeric) + record(b"Book1_A@2", empty)

    tables = group_opju_column_descriptors(iter_opju_column_descriptors(data))

    assert parse_opju_column_identity("Book1_A@2") is not None
    assert [(table.name, [column.identity.column_name for column in table.columns]) for table in tables] == [
        ("Book1/Sheet1", ["A", "B"]),
        ("Book1/Sheet2", ["A"]),
    ]
    assert [column.display_name for column in tables[0].columns] == ["A", "B"]
    assert tables[0].text_rows() == [["1.0", "x"], ["", ""]]
    assert tables[0].has_values is True
    assert tables[1].has_values is False


def test_opju_column_metadata_binds_ordinals_system_fields_and_formula() -> None:
    def varuint(value: int) -> bytes:
        encoded = bytearray()
        while value >= 0x80:
            encoded.append((value & 0x7F) | 0x80)
            value >>= 7
        encoded.append(value)
        return bytes(encoded)

    def envelope(body: bytes) -> bytes:
        return b"\xfa" + varuint(len(body)) + b"\x01" + body

    def record(name: bytes, payload: bytes) -> bytes:
        header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
        return bytes((len(name),)) + name + header + b"12345678" + payload

    def metadata_record(ordinal: int, name: bytes, designation: int, label: bytes) -> bytes:
        label_frame = b"\x9a\x01\x00\x0a" + bytes((len(label) + 2, len(label) + 1)) + label + b"\0"
        return (
            b"\x10\x80\x03"
            + ordinal.to_bytes(2, "little")
            + b"\x09\x81\x02\xc3\x01\x82\x01"
            + name
            + b"\x88\x01\x09\x81\x04\x01\x00\x21"
            + bytes((designation,))
            + label_frame
        )

    numeric = bytes.fromhex("0a 05 01 00 00 50") + struct.pack("<d", 1.25) + b"\xce"
    text = bytes.fromhex("0a 05 01 ff ff 01 01 01 01") + b"x\x00\x00\xce"
    system_body = (
        b"\x0bSYSTEM\x03\x00\x8e\x02\x01"
        + b"\xa8\x02\x03\x01s"
        + b"\xaa\x02\x03\x09synthetic"
        + b"\xb0\x02\x03\x01A"
        + b"\xc8\x02\x03\x05Book1"
        + b"\xcc\x02\x03\x06Sheet1"
    )
    formula = b"=A*2\0"
    property_payload = b"\xa2\x77\x11\x11\x11\x02\x00\x01\x00\x04\x00\x01\x00\xf0\x05"
    property_payload += len(formula).to_bytes(4, "little") + (1).to_bytes(4, "little") + formula
    formula_body = (
        b"_Storage_Cell_Ref_Data_"
        + b"#_MSER_STRINGS_PSET\x05\x01"
        + (len(property_payload) + 3).to_bytes(2, "little")
        + len(property_payload).to_bytes(4, "little")
        + property_payload
    )
    data = (
        b"CPYUA 4.3445 200\n"
        + record(b"Book1_A", numeric)
        + envelope(system_body)
        + record(b"Book1_B", text)
        + envelope(formula_body)
        + metadata_record(1, b"A", 0x51, b"Time")
        + metadata_record(2, b"B", 0x61, b"Signal")
    )

    descriptors = iter_opju_column_descriptors(data)
    metadata = iter_opju_column_metadata(data, descriptors)
    table = group_opju_column_descriptors(descriptors, metadata)[0]

    assert [(item.descriptor_ordinal, item.display_name) for item in metadata] == [(1, "A"), (2, "B")]
    assert [column.designation for column in table.columns] == ["X", "Y"]
    assert [column.long_name for column in table.columns] == ["Time", "Signal"]
    assert [column.units for column in table.columns] == ["s", None]
    assert [column.formula for column in table.columns] == [None, "=A*2"]
    assert table.columns[0].metadata is not None
    assert table.columns[0].metadata.comment == "synthetic"


def test_decode_opju_column_payload_decodes_fpc_predictors_and_trailing_blanks() -> None:
    bits = [struct.unpack("<Q", struct.pack("<d", value))[0] for value in (500.0, 1000.0, 1500.0)]
    stream = (
        b"\xe7"
        + bits[0].to_bytes(8, "little")
        + (bits[1] ^ bits[0]).to_bytes(8, "little")[:7]
        + b"\x0e"
        + (bits[2] ^ bits[1]).to_bytes(8, "little")[:7]
    )
    payload = bytes.fromhex("0a 05 04 ff ff 03 00 05 0c") + stream + bytes.fromhex("ff ff 01 01 02 00 ce")

    decoded = decode_opju_column_payload(payload)

    assert decoded is not None
    assert decoded.encoding == "fpc-fcm-dfcm"
    assert decoded.values == (500.0, 1000.0, 1500.0, None)
    assert decoded.trailing_missing_count == 1
    assert decoded.first_control_byte == 0xE7


def test_decode_opju_column_payload_decodes_constant_prefix_and_empty_variants() -> None:
    literal = struct.pack("<d", 0.5)
    fpc_suffix = b"\x07" + literal
    repeated = (
        bytes.fromhex("0a 05 04 ff ff 03 00 04 1a f0 3f 01 0c") + fpc_suffix + bytes.fromhex("ff ff 01 01 02 00 ce")
    )

    decoded_repeated = decode_opju_column_payload(repeated)
    decoded_empty = decode_opju_column_payload(bytes.fromhex("0a 05 20 ff ff 20 01 40 00 ce"))
    decoded_singleton_empty = decode_opju_column_payload(bytes.fromhex("0a 05 01 01 00 00 ce"))

    assert decoded_repeated is not None
    assert decoded_repeated.encoding == "constant-one-prefix-fpc-fcm-dfcm"
    assert decoded_repeated.repeated_prefix_count == 2
    assert decoded_repeated.values == (1.0, 1.0, 0.5, None)
    assert decoded_empty is not None
    assert decoded_empty.values == (None,) * 32
    assert decoded_singleton_empty is not None
    assert decoded_singleton_empty.values == (None,)


def test_decode_opju_column_payload_decodes_segmented_numeric_and_missing_runs() -> None:
    missing = struct.pack("<d", -1.23456789e-300)
    payload = (
        bytes.fromhex("0a 05 04 ff ff 02 00 02 1a f0 3f 01 0c 07")
        + missing
        + bytes.fromhex("01 00 00 ff ff 01 01 02 00 ce")
    )

    decoded = decode_opju_column_payload(payload)

    assert decoded is not None
    assert decoded.encoding == "segmented-fpc-fcm-dfcm"
    assert decoded.values == (1.0, None, None, None)
    assert decoded.missing_count == 3
    assert decoded.cell_kinds == ("float64", "missing", "missing", "missing")


def test_decode_opju_column_payload_decodes_all_observed_compact_scalar_widths() -> None:
    separators = b"\0\0"
    scalars = (
        b"\x64",
        bytes.fromhex("1a f0 3f"),
        bytes.fromhex("23 c0 57 40"),
        bytes.fromhex("3e 00 00 00 00 f0 3f"),
        bytes.fromhex("47 00 00 00 00 00 f0 3f"),
        b"\x50" + struct.pack("<d", 2.0),
    )
    payload = bytes.fromhex("0a 05 07 00 00") + separators.join(scalars) + bytes.fromhex("ff ff 01 01 02 00 ce")

    decoded = decode_opju_column_payload(payload)

    assert decoded is not None
    assert decoded.encoding == "compact-double-sequence"
    assert decoded.values == (0.0, 1.0, 95.0, 1.0, 1.0, 2.0, None)


def test_decode_opju_column_payload_decodes_utf8_cells_and_empty_string() -> None:
    payload = bytes.fromhex("0a 05 04 ff ff 04 01 05 05") + b"alpha\x00\x04beta" + bytes.fromhex("02 00 ce")

    decoded = decode_opju_column_payload(payload)

    assert decoded is not None
    assert decoded.encoding == "utf8-string-sequence"
    assert decoded.values == ("alpha", "", "beta", None)
    assert decoded.cell_kinds == ("utf8", "utf8", "utf8", "missing")
    assert decoded.stored_value_count == 3


def test_decode_opju_column_payload_decodes_multibyte_varuint_counts_and_values() -> None:
    def varuint(value: int) -> bytes:
        encoded = bytearray()
        while value >= 0x80:
            encoded.append((value & 0x7F) | 0x80)
            value >>= 7
        encoded.append(value)
        return bytes(encoded)

    row_count = 130
    payload = (
        b"\x0a\x04"
        + varuint(row_count)
        + b"\xff\xff"
        + varuint(row_count)
        + b"\x01"
        + varuint(2 * row_count - 1)
        + b"".join(varuint(value) for value in range(row_count))
        + b"\xce"
    )

    decoded = decode_opju_column_payload(payload)

    assert decoded is not None
    assert decoded.encoding == "unsigned-varint-sequence"
    assert decoded.values == tuple(range(row_count))
    assert decoded.cell_kinds == ("unsigned_integer",) * row_count


def test_decode_opju_column_payload_decodes_varints_with_trailing_missing_cells() -> None:
    payload = bytes.fromhex("0a 04 1e ff ff 1e 01 05 01 00 00 36 00 ce")

    decoded = decode_opju_column_payload(payload)

    assert decoded is not None
    assert decoded.encoding == "unsigned-varint-sequence"
    assert decoded.row_capacity == 30
    assert decoded.stored_value_count == 3
    assert decoded.values == (1, 0, 0, *((None,) * 27))
    assert decoded.cell_kinds == ("unsigned_integer",) * 3 + ("missing",) * 27


def test_extract_opju_tagged_envelopes_writes_exact_bytes_and_fields(tmp_path: Path) -> None:
    header = b"CPYUA 4.3445 200\n"
    scalar = bytes.fromhex("28 c0 11 06 00 00 01 00 4b")
    tagged = bytes.fromhex("86 01 02 80 01 18 80 01") + b"\x05\x80\x2aName\0" + scalar
    origin_storage = b"<OriginStorage><Note>ok</Note></OriginStorage>"
    data = header + tagged + origin_storage
    sample = tmp_path / "tagged.opju"
    sample.write_bytes(data)
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    out_dir = tmp_path / "out"

    count = extract_opju_tagged_envelopes(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        manifest_root=out_dir,
    )

    assert count == 1
    item = next(item for item in manifest.items if item.kind == "opju_tagged_index")
    assert item.completeness == "partial"
    assert item.verification == "exact"
    assert item.source_ranges == [{"start": len(header), "end": len(header) + len(tagged)}]
    assert item.path is not None
    rows = json.loads((out_dir / item.path).read_text(encoding="utf-8"))
    assert rows[0]["semantic_status"] == "fields_partial"
    assert rows[0]["string_fields"] == [
        {
            "length": 5,
            "offset": len(header) + 11,
            "tag_code": 42,
            "value": "Name",
        }
    ]
    assert rows[0]["scalar_fields"] == [
        {
            "declared_size": 6,
            "descriptor_hex": "00 00 01 00",
            "end_offset": len(header) + len(tagged),
            "field_code": 40,
            "little_endian_unsigned": 75,
            "offset": len(header) + len(tagged) - len(scalar),
            "value_hex": "4b",
            "value_width": 1,
        }
    ]
    assert (out_dir / rows[0]["path"]).read_bytes() == tagged


def test_extract_opju_tagged_envelopes_ignores_broad_object_manifest_ranges(tmp_path: Path) -> None:
    header = b"CPYUA 4.3445 200\n"
    tagged = bytes.fromhex("86 01 02 80 01 18 80 01") + b"\x05\x80\x2aName\0"
    origin_storage = b"<OriginStorage><Note>ok</Note></OriginStorage>"
    data = header + tagged + origin_storage
    sample = tmp_path / "tagged.opju"
    sample.write_bytes(data)
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    manifest.add_item(
        ManifestItem(
            kind="note",
            name="broad-parser-object",
            status="partial",
            confidence=0.7,
            heuristic=False,
            range_start=len(header),
            range_end=len(data),
        )
    )
    out_dir = tmp_path / "out"

    extract_opju_tagged_envelopes(sample, out_dir, manifest, force=True, file_data=data, manifest_root=out_dir)

    item = next(item for item in manifest.items if item.kind == "opju_tagged_index")
    assert item.rows == 1


def test_extract_opju_tagged_envelopes_writes_decoded_column_values(tmp_path: Path) -> None:
    payload = bytes.fromhex("0a 05 01 ff ff 01 00 01 0c 07") + struct.pack("<d", 500.0) + b"\xce"
    record_header = bytes.fromhex("8f 02 ca 10 9d 18 18") + b"\0" * 7 + len(payload).to_bytes(8, "little")
    data = b"CPYUA 4.3445 200\n" + b"N2N_A@3" + record_header + b"12345678" + payload
    sample = tmp_path / "column.opju"
    sample.write_bytes(data)
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    out_dir = tmp_path / "out"

    extract_opju_tagged_envelopes(sample, out_dir, manifest, force=True, file_data=data, manifest_root=out_dir)

    item = next(item for item in manifest.items if item.kind == "opju_column_descriptor_index")
    assert item.completeness == "complete"
    assert item.verification == "exact"
    assert item.path is not None
    rows = json.loads((out_dir / item.path).read_text(encoding="utf-8"))
    assert rows[0]["payload_encoding"] == "fpc-fcm-dfcm"
    assert rows[0]["semantic_status"] == "decoded_numeric_values"
    assert rows[0]["values"] == [500.0]
    assert rows[0]["value_bits"] == ["407f400000000000"]
    assert rows[0]["cell_kinds"] == ["float64"]
    assert rows[0]["missing_count"] == 0


def test_extract_opju_decoded_regions_writes_exact_payload_and_index(tmp_path: Path) -> None:
    payload = b'<OriginStorage Label="Layout"><Col>2</Col><Row>1</Row></OriginStorage>'
    data = _literal_lz4_opju(payload)
    sample = tmp_path / "sample.opju"
    sample.write_bytes(data)
    detected = detect_file(sample)
    manifest = make_manifest(sample, detected, "native-parser", len(data), "fixture")
    out_dir = tmp_path / "out"

    count = extract_opju_decoded_regions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        manifest_root=out_dir,
    )

    assert count == 1
    region_item = next(item for item in manifest.items if item.kind == "opju_decoded_region")
    assert region_item.status == "extracted"
    assert region_item.heuristic is False
    assert region_item.decoded_length == len(payload)
    assert region_item.path is not None
    assert region_item.payload_family == "origin_storage_xml"
    assert region_item.completeness == "complete"
    assert region_item.verification == "exact"
    assert (out_dir / region_item.path).read_bytes() == payload

    index_item = next(item for item in manifest.items if item.kind == "opju_decoded_index")
    assert index_item.path is not None
    index = json.loads((out_dir / index_item.path).read_text(encoding="utf-8"))
    assert index[0]["decoded_length"] == len(payload)
    assert index[0]["compressed_length"] == len(payload) + 2
    assert index[0]["declared_decoded_length"] == len(payload)
    assert index[0]["framing_rule"] == "origin_storage_anchor"
    assert index[0]["classification"]["family"] == "origin_storage_xml"
    assert index[0]["classification"]["verification"] == "exact"

    strings_item = next(item for item in manifest.items if item.kind == "opju_decoded_strings")
    assert strings_item.path is not None
    with (out_dir / strings_item.path).open(encoding="utf-8", newline="") as handle:
        string_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert string_rows[0]["region_index"] == "0"
    assert string_rows[0]["value"] == payload.decode("ascii")


def test_extract_opju_decoded_regions_resolves_calculation_references(tmp_path: Path) -> None:
    uid = 41001
    payload = bytearray(struct.pack("<II", 0, 3))
    for ordinal in range(3):
        payload.extend(struct.pack("<IIIiII", 16, 0x00000702, ordinal, -999, uid, 0))
    payload.extend(struct.pack("<I", 0))
    data = _literal_lz4_opju(bytes(payload))
    sample = tmp_path / "calculation_refs.opju"
    sample.write_bytes(data)
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    manifest.add_item(
        ManifestItem(
            kind="function",
            name="fit_linear",
            status="extracted",
            confidence=0.98,
            path="functions/fit_linear.xml",
            source_object_path="functions/fit_linear",
            calculation_uid=uid,
            verification="exact",
        )
    )
    out_dir = tmp_path / "out"

    extract_opju_decoded_regions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        manifest_root=out_dir,
        include_strings=False,
        include_numeric_runs=False,
    )

    region_item = next(item for item in manifest.items if item.kind == "opju_decoded_region")
    assert region_item.payload_family == "storage_cell_ref_data"
    assert region_item.structural_name == "storage_cell_ref_data"
    assert region_item.semantic_alias == "analysis_result_reference_array"
    assert region_item.semantic_confidence == "corpus_high"
    links_item = next(item for item in manifest.items if item.kind == "opju_calculation_links")
    assert links_item.status == "extracted"
    assert links_item.completeness == "complete"
    assert links_item.verification == "exact"
    links = json.loads((out_dir / Path(links_item.path or "")).read_text(encoding="utf-8"))
    assert links["all_references_resolved"] is True
    assert links["reference_count"] == 3
    assert all(reference["functions"][0]["name"] == "fit_linear" for reference in links["references"])


def test_extract_opju_decoded_regions_writes_numeric_blob_run_inventory(tmp_path: Path) -> None:
    encoded = base64.b64encode(struct.pack("<4d", 1.0, 2.0, 3.0, 4.0))
    payload = b'<OriginStorage><Counts BlobArrElementaryType="5">' + encoded + b"</Counts></OriginStorage>"
    data = _literal_lz4_opju(payload)
    sample = tmp_path / "numeric.opju"
    sample.write_bytes(data)
    manifest = make_manifest(sample, detect_file(sample), "native-parser", len(data), "fixture")
    out_dir = tmp_path / "out"

    extract_opju_decoded_regions(
        sample,
        out_dir,
        manifest,
        force=True,
        file_data=data,
        manifest_root=out_dir,
    )

    item = next(item for item in manifest.items if item.kind == "opju_numeric_run_inventory")
    assert item.rows == 1
    assert item.path is not None
    rows = json.loads((out_dir / item.path).read_text(encoding="utf-8"))
    assert rows == [
        {
            "family_marker": None,
            "first_values": ["1.0", "2.0", "3.0", "4.0"],
            "payload_offset": payload.index(encoded),
            "primitive": "f8",
            "primitive_size": 8,
            "run_length": 4,
            "source_end": len(data),
            "source_start": len(b"CPYUA 4.3318 0\x00") + 4,
            "tag": "Counts",
        }
    ]
