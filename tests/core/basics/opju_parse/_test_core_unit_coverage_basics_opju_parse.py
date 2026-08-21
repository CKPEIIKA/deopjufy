"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from deopjufier.inventory import (
    OpjDataSection,
    parse_opj_function_metadata,
    parse_opj_function_payload,
    parse_opj_matrix_metadata,
    parse_opj_note_sections,
    parse_opj_worksheet_metadata,
    parse_opju_origin_storage_reports,
)
from tests.test_core_unit_coverage_utils import _repo_root, _resolve_synthetic_fixture

REPO_ROOT = _repo_root(Path(__file__))
SYNTHETIC_BINARY_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua-binary.opju")
SYNTHETIC_FIXTURE = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua.opju")


def test_parse_opju_origin_storage_reports_parses_case_and_ignores_invalid_bytes() -> None:
    sample = (
        b"CPYUA 4.3318 0\x00"
        + b"\x00\xff\x01"
        + b'<originstorage Label="Noisy">\x00<notes>\x7f\xff</notes>\x00</originstorage>\n'
    )
    reports = parse_opju_origin_storage_reports(sample, max_reports=1)
    assert len(reports) == 1

    report = reports[0]
    assert report.label == "Noisy"
    assert "�" not in report.raw_text
    assert all(ch.isprintable() or ch in {"\n", "\t"} for ch in report.raw_text)


def test_parse_opj_worksheet_metadata_recovers_window_long_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="Book1_A",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=3,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )

    payload = bytearray(0xC8)
    payload[2 : 2 + 25] = b"Book1_A".ljust(25, b"\x00")
    payload[0xC3:] = b"My Long Name@${metadata}\x00"
    block_size = len(payload)
    window_block = block_size.to_bytes(4, "little") + b"\n" + payload + b"\n"
    data = b"CPYA 6.0 552#\n" + window_block

    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"Book1_A"})
    assert metadata_by_name["Book1_A"].long_name == "My Long Name"


def test_parse_opj_worksheet_metadata_recovers_window_object_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="Book1_A",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=3,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )

    payload = bytearray(0x180)
    payload[0x02 : 0x02 + 25] = b"Book1_A".ljust(25, b"\x00")
    payload[0x32] = 0x01
    payload[0x69] = 0x08
    struct.pack_into("<d", payload, 0x73, 2451544.5)
    struct.pack_into("<d", payload, 0x7B, 2451545.25)
    payload[0xC3:] = b"My Label@${metadata}\x00"
    window_block = len(payload).to_bytes(4, "little") + b"\n" + bytes(payload) + b"\n"
    data = b"CPYA 6.0 552#\n" + window_block

    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"Book1_A"})
    metadata = metadata_by_name["Book1_A"]

    assert metadata.label == "My Label"
    assert metadata.long_name == "My Label"
    assert metadata.object_id == 0
    assert metadata.hidden is True
    assert metadata.state == "minimized"
    assert metadata.creation_time == int((2451544.5 - 2440587) * 86400 + 0.5)
    assert metadata.modification_time == int((2451545.25 - 2440587) * 86400 + 0.5)


def test_parse_opj_worksheet_metadata_recovers_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="Book1_A",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=3,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )

    block_body = b"Book1_A\x00units\x00V\x00"
    block_size = len(block_body)
    length_block = block_size.to_bytes(4, "little") + b"\n" + block_body + b"\n"
    data = b"CPYA 6.0 552#\n" + length_block
    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"Book1_A"})

    assert metadata_by_name["Book1_A"].units == "V"


def test_parse_opj_worksheet_metadata_recovers_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="Book1_A",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=3,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )

    block_body = b"Book1_A\x00comment\x00Here you go!\x00"
    block_size = len(block_body)
    length_block = block_size.to_bytes(4, "little") + b"\n" + block_body + b"\n"
    data = b"CPYA 6.0 552#\n" + length_block
    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"Book1_A"})

    assert metadata_by_name["Book1_A"].comments == "Here you go!"


def test_parse_opj_worksheet_metadata_recovers_formulas(monkeypatch: pytest.MonkeyPatch) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="Book1_A",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=3,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )

    block_body = b"Book1_A\x00formula\x00y = m*x + b\x00Book1_A\x00formula\x00y = 2*x - c\x00"
    block_size = len(block_body)
    length_block = block_size.to_bytes(4, "little") + b"\n" + block_body + b"\n"
    data = b"CPYA 6.0 552#\n" + length_block
    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"Book1_A"})

    assert metadata_by_name["Book1_A"].formulas == ["y = m*x + b", "y = 2*x - c"]


def test_parse_opj_worksheet_metadata_recovers_column_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections = [
        OpjDataSection(
            offset=0,
            length=10,
            name="SheetA_X",
            data_type=0,
            data_type2=0,
            total_rows=10,
            first_row=1,
            last_row=2,
            value_size=8,
            data_type_u=0,
            data_type3=0,
            values=[1.0, 2.0],
        ),
        OpjDataSection(
            offset=0,
            length=10,
            name="SheetA_Y",
            data_type=0,
            data_type2=0,
            total_rows=12,
            first_row=3,
            last_row=4,
            value_size=8,
            data_type_u=0,
            data_type3=0,
            values=[3.0, 4.0],
        ),
    ]
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: sections,
    )

    data = b"CPYA 4.2673 552#\n"
    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"SheetA"})
    assert metadata_by_name["SheetA"].column_labels == ["X", "Y"]
    assert metadata_by_name["SheetA"].column_types == ["numeric", "numeric"]
    assert metadata_by_name["SheetA"].display_hints == ["float64", "float64"]
    assert metadata_by_name["SheetA"].formula_rows == (1, 4)
    assert metadata_by_name["SheetA"].long_name == "SheetA"


def test_parse_opj_worksheet_metadata_recovers_column_types_and_display_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections = [
        OpjDataSection(
            offset=0,
            length=10,
            name="SheetMix_A",
            data_type=0,
            data_type2=0,
            total_rows=2,
            first_row=1,
            last_row=1,
            value_size=8,
            data_type_u=0,
            data_type3=0,
            values=[1.0, 2.0],
        ),
        OpjDataSection(
            offset=0,
            length=10,
            name="SheetMix_B",
            data_type=0x1121,
            data_type2=0,
            total_rows=2,
            first_row=1,
            last_row=1,
            value_size=10,
            data_type_u=0,
            data_type3=0,
            values=["label", "value"],
        ),
        OpjDataSection(
            offset=0,
            length=10,
            name="SheetMix_C",
            data_type=0x1121,
            data_type2=0,
            total_rows=2,
            first_row=1,
            last_row=1,
            value_size=10,
            data_type_u=0,
            data_type3=0,
            values=["count", 3.14],
        ),
    ]
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: sections,
    )

    data = b"CPYA 4.2673 552#\n"
    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"SheetMix"})

    assert metadata_by_name["SheetMix"].column_labels == ["A", "B", "C"]
    assert metadata_by_name["SheetMix"].column_types == ["numeric", "text", "mixed"]
    assert metadata_by_name["SheetMix"].display_hints == ["float64", "text", "text"]


def test_parse_opj_matrix_metadata_recovers_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="MatrixA",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=2,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0, 3.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )
    data = b"CPYA 4.2673 552#\n"
    metadata_by_name = parse_opj_matrix_metadata(data, matrix_names={"MatrixA"})
    assert "MatrixA" in metadata_by_name
    assert metadata_by_name["MatrixA"].shape == (10, 1)
    assert metadata_by_name["MatrixA"].long_name == "MatrixA"
    assert metadata_by_name["MatrixA"].row_start == 1
    assert metadata_by_name["MatrixA"].row_end == 2


def test_parse_opj_matrix_metadata_recovers_multicolumn_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections = [
        OpjDataSection(
            offset=0,
            length=10,
            name="MatrixA_A",
            data_type=0,
            data_type2=0,
            total_rows=3,
            first_row=1,
            last_row=2,
            value_size=8,
            data_type_u=0,
            data_type3=0,
            values=[1.0, 2.0, 3.0],
        ),
        OpjDataSection(
            offset=20,
            length=10,
            name="MatrixA_B",
            data_type=0,
            data_type2=0,
            total_rows=2,
            first_row=1,
            last_row=2,
            value_size=8,
            data_type_u=0,
            data_type3=0,
            values=[10.0, 20.0],
        ),
    ]
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: sections,
    )

    data = b"CPYA 4.2673 552#\n"
    metadata_by_name = parse_opj_matrix_metadata(data, matrix_names={"MatrixA"})

    assert "MatrixA" in metadata_by_name
    assert metadata_by_name["MatrixA"].shape == (3, 2)
    assert metadata_by_name["MatrixA"].long_name == "MatrixA"
    assert metadata_by_name["MatrixA"].row_start == 1
    assert metadata_by_name["MatrixA"].row_end == 2
    assert metadata_by_name["MatrixA"].section_count == 2


def test_parse_opj_function_metadata_recovers_formula_range_and_points() -> None:
    payload = b"Function1<formula>\n   y = a*x + b  \n</formula><x1>   0.0</x1><x2> 10.0 </x2><nx>128</nx>"

    metadata = parse_opj_function_metadata(payload, function_name="Function1")
    assert metadata is not None
    assert metadata.name == "Function1"
    assert metadata.formula == "y = a*x + b"
    assert metadata.function_range == ("0.0", "10.0")
    assert metadata.total_points == 128


def test_parse_opj_function_metadata_decodes_native_dataset_header() -> None:
    header = bytearray(0x73)
    header[0x0A:0x0C] = (0x1194).to_bytes(2, "little")
    header[0x16:0x18] = (0x6081).to_bytes(2, "little")
    header[0x21:0x25] = (5).to_bytes(4, "little")
    struct.pack_into("<d", header, 0x25, -1.0)
    struct.pack_into("<d", header, 0x2D, 0.5)
    header[0x58 : 0x58 + len(b"Func1")] = b"Func1"
    formula = b"SIN(X)"
    payload = (
        len(header).to_bytes(4, "little")
        + b"\n"
        + header
        + b"\n"
        + len(formula).to_bytes(4, "little")
        + b"\n"
        + formula
        + b"\n"
    )

    metadata = parse_opj_function_metadata(payload, function_name="Func1")
    assert metadata is not None
    assert metadata.formula == "sin(x)"
    assert metadata.function_type == "polar"
    assert metadata.function_range == ("-1", "1")
    assert metadata.total_points == 5


def test_parse_opj_function_metadata_recovers_range_aliases() -> None:
    payload = (
        b"Function1"
        b"<formula>y = a*x + b</formula>"
        b"<Range1> 0.0 </Range1><Range2> 10.0 </Range2>"
        b"<TotalPoints>64</TotalPoints>"
    )

    metadata = parse_opj_function_metadata(payload, function_name="Function1")
    assert metadata is not None
    assert metadata.function_range == ("0.0", "10.0")


def test_parse_opj_function_metadata_recovers_range_attributes() -> None:
    metadata = parse_opj_function_metadata(
        (
            b'<data><Range1 RowRangeFrom="1" RowRangeTo="0" '
            b'XRangeFrom="2.5" XRangeTo="8.5" /><Range2 '
            b'XRangeFrom="3" XRangeTo="7" /></data>'
        ),
        function_name="Function1",
    )
    assert metadata is not None
    assert metadata.function_range == ("2.5", "8.5")


def test_parse_opj_function_metadata_recovers_xf_name_formula() -> None:
    metadata = parse_opj_function_metadata(
        b"<function><xfName>smooth</xfName><nx>64</nx></function>",
        function_name="Function1",
    )
    assert metadata is not None
    assert metadata.formula == "smooth"
    assert metadata.total_points == 64


def test_parse_opj_function_metadata_returns_none_without_known_fields() -> None:
    metadata = parse_opj_function_metadata(
        b"Function1\n1 2 3\n4 5 6\n",
        function_name="Function1",
    )
    assert metadata is None


def test_parse_opj_function_payload_extracts_tag_payload() -> None:
    payload = (
        b'<functionlist _XF_VAR_IO="0" _XF_VAR_TYPE="1">NewFunction (User)</functionlist>'
        b'<oy HideNodeName="1" _XF_VAR_IO="1" _XF_VAR_TYPE="5">[Book4]Sheet1!(A"X",B"Y")</oy>'
        b"<x1> -10. </x1><x2>10.0</x2><nx>100</nx>"
    )
    parsed = parse_opj_function_payload(payload)
    assert parsed is not None
    assert "functionlist: NewFunction (User)" in parsed
    assert 'oy: [Book4]Sheet1!(A"X",B"Y")' in parsed
    assert "x1: -10." in parsed


def test_parse_opj_note_sections_recovers_results_blocks() -> None:
    data = (
        b"CPYA 4.2673 552#\n"
        + b"\nResults\0\nData1 Temperature:\t25.10242\r\n\r\n\0\n"
        + b'\nResultsLog\0\n\x95\0\0\0\n[3/5/2009 13:32 "/DeltaH" (2454895)]\r\n'
        b"Data: Data1_NDH\r\nModel: OneSites\r\nChi^2/DoF = 3008\r\nN\t0.800\t0.0346\r\n\r\n\0\n"
    )

    sections = parse_opj_note_sections(data, max_sections=4, max_chars=1000)
    names = [section.name for section in sections]
    assert names == ["Results", "ResultsLog"]
    assert sections[0].text == "Data1 Temperature:\t25.10242"
    assert "Chi^2/DoF = 3008" in sections[1].text


def test_parse_opju_origin_storage_reports_extracts_report_metadata() -> None:
    block = b"".join(
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
            b"<DescStats><R1 Label='\"August\"'><N>13</N><Min>4.5</Min><Q1>5.25</Q1><Median>8.0</Median>"
            b"<Q3>26.64</Q3><Max>58.7</Max></R1></DescStats>",
            b'<Ranks><R1 Label=\'"November"-"August"\'><N>9</N><Mean>6.89</Mean><Sum>62</Sum></R1>',
            b'<R2 Label=\'"November"-"August"\'><N>4</N><Mean>7.25</Mean><Sum>29</Sum></R2></Ranks>',
            b"<Stats><C1>29</C1><C2>-1.1181704925</C2><C3>0.2734375</C3><C4>0.2634941841411</C4></Stats>",
            b"<Footer><![CDATA[Null Hypothesis: F(x) = G(y)\nAlternative Hypothesis: F(x) <> G(y)\n",
            b"At the 0.05 level, the two distributions are NOT significantly different.]]></Footer>",
            b"</OriginStorage>",
        )
    )
    data = b"CPYUA 4.3318 113\0" + block + b"\x00"

    reports = parse_opju_origin_storage_reports(data, max_reports=1)
    assert len(reports) == 1
    report = reports[0]
    assert report.label == "Wilcoxon Signed Ranks Test (7/18/2016 11:58:20)"
    assert report.function == "Wilcoxon Signed Ranks Test"
    assert report.user == "developer"
    assert report.time == "7/18/2016 11:58:20"
    assert report.data_filter == "No"
    assert report.input_data == ['[Book3]Sheet1!B"August"; [1*:13*]']
    assert report.descriptive_stats['"August"']["Median"] == "8.0"
    assert report.ranks['"November"-"August"']["N"] == "9"
    assert report.test_statistics["footer"].startswith("Null Hypothesis: F(x) = G(y)")
