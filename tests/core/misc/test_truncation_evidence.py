"""Truncation evidence for OPJ object overruns and the OPJU end-of-file trailer."""

from __future__ import annotations

import struct
from pathlib import Path

from deopjufier.opj.walker import opj_truncation_offset
from deopjufier.opju.common import OPJU_END_TRAILER, opju_has_end_trailer
from deopjufier.session import ExtractionSession

_OPJ_SIGNATURE = b"CPYA 4.2673 552#\n"


def _opj_object(payload: bytes) -> bytes:
    return struct.pack("<I", len(payload)) + b"\n" + payload + b"\n"


def _opj_size(value: int) -> bytes:
    return struct.pack("<I", value) + b"\n"


def _complete_opj() -> bytes:
    return _OPJ_SIGNATURE + _opj_object(b"abcd") + _opj_size(0) + _opj_size(0)


def test_complete_opj_has_no_truncation_offset() -> None:
    assert opj_truncation_offset(_complete_opj()) is None


def test_opj_object_overrunning_end_of_file_reports_offset() -> None:
    header = _OPJ_SIGNATURE + _opj_object(b"abcd") + _opj_size(0)
    data = header + _opj_size(100) + b"short"

    assert opj_truncation_offset(data) == len(header) + 5


def test_opj_strict_parse_failure_is_not_truncation() -> None:
    data = _OPJ_SIGNATURE + b"\x04\x00\x00\x00X"

    assert opj_truncation_offset(data) is None


def test_opju_trailer_check_uses_last_bytes_only() -> None:
    assert opju_has_end_trailer(b"CPYUA 4.3445 200\n" + OPJU_END_TRAILER)
    assert not opju_has_end_trailer(b"CPYUA 4.3445 200\n" + OPJU_END_TRAILER[:-1])


def test_session_reports_definitive_opj_truncation(tmp_path: Path) -> None:
    sample = tmp_path / "cut.opj"
    sample.write_bytes(_OPJ_SIGNATURE + _opj_object(b"abcd") + _opj_size(0) + _opj_size(100) + b"short")

    evidence = ExtractionSession.from_path(sample).truncation_evidence()

    assert evidence is not None
    assert evidence.code == "input-truncated"
    assert evidence.definitive


def test_session_reports_missing_opju_trailer_as_non_definitive(tmp_path: Path) -> None:
    complete = tmp_path / "complete.opju"
    complete.write_bytes(b"CPYUA 4.3445 200\n" + OPJU_END_TRAILER)
    cut = tmp_path / "cut.opju"
    cut.write_bytes(b"CPYUA 4.3445 200\n" + OPJU_END_TRAILER[:20])

    assert ExtractionSession.from_path(complete).truncation_evidence() is None
    evidence = ExtractionSession.from_path(cut).truncation_evidence()
    assert evidence is not None
    assert evidence.code == "opju-trailer-missing"
    assert not evidence.definitive
