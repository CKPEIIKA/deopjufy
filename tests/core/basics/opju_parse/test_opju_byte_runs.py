from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from deopjufier.opju.recovery.byte_runs import (
    OpjuByteRunError,
    decode_origin_storage_byte_runs,
    recover_origin_storage_xml,
    recover_origin_storage_xml_records,
)


def _encoded_xml(prefix: bytes, suffix: bytes) -> bytes:
    assert len(suffix) <= 0x7F
    return prefix + bytes((len(suffix),)) + suffix + b"\x00"


def test_byte_run_decoder_maps_literal_and_repeat_output_to_source() -> None:
    raw = b"<x>" + bytes((3,)) + b"abc" + bytes((0xC2,)) + b"9" + b"\x00tail"

    decoded = decode_origin_storage_byte_runs(
        raw,
        3,
        source_start=100,
        out_of_band_control_policy="stop",
    )

    assert decoded.decoded == b"<x>abc99999"
    assert decoded.stop_reason == "out_of_band_control_0x00"
    assert decoded.source_map[-5:] == (108, 108, 108, 108, 108)


@pytest.mark.parametrize(
    ("control", "expected_count"),
    ((0xC0, 3), (0xCB, 14), (0xCC, 15)),
)
def test_byte_run_decoder_uses_three_based_repeat_counts(control: int, expected_count: int) -> None:
    decoded = decode_origin_storage_byte_runs(bytes((control, ord("9"))), 0)

    assert decoded.decoded == b"9" * expected_count


@pytest.mark.parametrize("control", (0x00, 0x86))
def test_byte_run_decoder_rejects_out_of_band_controls_by_default(control: int) -> None:
    with pytest.raises(OpjuByteRunError, match=rf"control 0x{control:02x}"):
        decode_origin_storage_byte_runs(b"abc" + bytes((control,)), 3)


def test_byte_run_decoder_can_stop_at_parent_framing_for_recovery() -> None:
    decoded = decode_origin_storage_byte_runs(
        b"abc\x86\x01envelope",
        3,
        out_of_band_control_policy="stop",
    )

    assert decoded.decoded == b"abc"
    assert decoded.input_end == 3
    assert decoded.stop_reason == "out_of_band_control_0x86"


def test_byte_run_decoder_rejects_out_of_range_phase() -> None:
    with pytest.raises(OpjuByteRunError):
        decode_origin_storage_byte_runs(b"abc", 4)


def test_byte_run_phase_discovery_recovers_valid_function_xml() -> None:
    prefix = b'<OriginStorage Creator="smooth">'
    raw = _encoded_xml(prefix, b"</OriginStorage>")

    record = recover_origin_storage_xml(raw, source_start=200)

    assert record is not None
    assert record.phase == len(prefix)
    assert record.family == "smooth"
    assert record.classification == "function"
    assert record.source_start == 200
    assert ET.fromstring(record.xml).tag == "OriginStorage"
    assert len(record.source_map) == len(record.xml)


def test_byte_run_window_can_own_multiple_logical_functions() -> None:
    first = _encoded_xml(b'<OriginStorage Creator="smooth">', b"</OriginStorage>")
    second_suffix = b'<Calculation AnalysisName="FitLinear" UID="41001"/></OriginStorage>'
    second = _encoded_xml(b"<OriginStorage>", second_suffix)

    records = recover_origin_storage_xml_records(first + b"envelope" + second, source_start=500)

    assert len(records) == 2
    assert [record.family for record in records] == ["smooth", "FitLinear"]
    assert [record.calculation_uid for record in records] == [None, 41001]
    assert all(record.classification == "function" for record in records)


def test_byte_run_recovery_preserves_calculation_label() -> None:
    suffix = b'<Calculation AnalysisName="FitLinear" Label="Fit Result"/></OriginStorage>'

    record = recover_origin_storage_xml(_encoded_xml(b"<OriginStorage>", suffix))

    assert record is not None
    assert record.calculation_label == "Fit Result"
