"""Strict recovery for byte-run encoded OriginStorage XML streams."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal

_ORIGIN_STORAGE_OPEN = b"<OriginStorage"
_ORIGIN_STORAGE_CLOSE = b"</OriginStorage>"
_MAX_DECODED_BYTES = 16 * 1024 * 1024


class OpjuByteRunError(ValueError):
    """Raised when an OriginStorage byte-run stream is malformed."""


@dataclass(frozen=True)
class OpjuByteRunDecode:
    """Decoded bytes and their exact absolute source-byte mapping."""

    decoded: bytes
    source_map: tuple[int, ...]
    input_end: int
    stop_reason: str


@dataclass(frozen=True)
class OpjuRecoveredXml:
    """One complete XML record recovered from an encoded source window."""

    xml: bytes
    source_map: tuple[int, ...]
    source_start: int
    source_end: int
    marker_offset: int
    phase: int
    stop_reason: str
    family: str
    classification: str
    calculation_label: str | None
    calculation_uid: int | None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.xml).hexdigest()


def decode_origin_storage_byte_runs(
    data: bytes,
    first_control_offset: int,
    *,
    source_start: int = 0,
    allow_truncated_final_literal: bool = True,
    out_of_band_control_policy: Literal["error", "stop"] = "error",
) -> OpjuByteRunDecode:
    """Decode the observed literal/repeat byte-run grammar.

    Bytes before ``first_control_offset`` belong to an already-open literal run
    and are copied directly. Controls ``0x00`` and ``0x80..0xbf`` are not codec
    operations. Strict decoding rejects them; forensic recovery may stop at one
    when the parent envelope owns the remaining bytes.
    """
    if not 0 <= first_control_offset <= len(data):
        raise OpjuByteRunError("first control offset is outside the source window")
    if out_of_band_control_policy not in ("error", "stop"):
        raise OpjuByteRunError(f"invalid out-of-band control policy {out_of_band_control_policy!r}")

    output = bytearray(data[:first_control_offset])
    source_map = list(range(source_start, source_start + first_control_offset))
    cursor = first_control_offset
    stop_reason = "eof"

    while cursor < len(data) and len(output) <= _MAX_DECODED_BYTES:
        control = data[cursor]
        if 0x01 <= control <= 0x7F:
            cursor, stop_reason = _decode_literal_run(
                data,
                cursor,
                output,
                source_map,
                source_start=source_start,
                allow_truncated=allow_truncated_final_literal,
            )
            if stop_reason != "continue":
                break
            continue
        if 0xC0 <= control <= 0xFF:
            cursor, stop_reason = _decode_repeat_run(
                data,
                cursor,
                output,
                source_map,
                source_start=source_start,
            )
            if stop_reason != "continue":
                break
            continue
        if out_of_band_control_policy == "error":
            raise OpjuByteRunError(
                f"unassigned OriginStorage control 0x{control:02x} at source offset "
                f"{source_start + cursor}; the field is malformed, uses an unsupported codec version, "
                "or was not bounded by its parent envelope"
            )
        stop_reason = f"out_of_band_control_0x{control:02x}"
        break

    if len(output) > _MAX_DECODED_BYTES:
        raise OpjuByteRunError("decoded byte-run output exceeds the safety limit")
    return OpjuByteRunDecode(
        decoded=bytes(output),
        source_map=tuple(source_map),
        input_end=source_start + cursor,
        stop_reason=stop_reason,
    )


def _decode_literal_run(
    data: bytes,
    cursor: int,
    output: bytearray,
    source_map: list[int],
    *,
    source_start: int,
    allow_truncated: bool,
) -> tuple[int, str]:
    count = data[cursor]
    literal_start = cursor + 1
    literal_end = literal_start + count
    if literal_end > len(data):
        if not allow_truncated:
            raise OpjuByteRunError("truncated byte-run literal")
        literal_end = len(data)
        stop_reason = "truncated_final_literal"
    else:
        stop_reason = "continue"
    output.extend(data[literal_start:literal_end])
    source_map.extend(source_start + offset for offset in range(literal_start, literal_end))
    return literal_end, stop_reason


def _decode_repeat_run(
    data: bytes,
    cursor: int,
    output: bytearray,
    source_map: list[int],
    *,
    source_start: int,
) -> tuple[int, str]:
    if cursor + 1 >= len(data):
        return len(data), "truncated_repeat"
    count = (data[cursor] & 0x3F) + 3
    value_offset = cursor + 1
    output.extend(bytes((data[value_offset],)) * count)
    source_map.extend([source_start + value_offset] * count)
    return cursor + 2, "continue"


def _iter_xml_prefixes(decoded: OpjuByteRunDecode) -> tuple[tuple[bytes, ET.Element, tuple[int, ...]], ...]:
    records: list[tuple[bytes, ET.Element, tuple[int, ...]]] = []
    cursor = 0
    while (close_at := decoded.decoded.find(_ORIGIN_STORAGE_CLOSE, cursor)) >= 0:
        xml_end = close_at + len(_ORIGIN_STORAGE_CLOSE)
        xml = decoded.decoded[:xml_end]
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            cursor = close_at + 1
            continue
        if _local_name(root.tag) == "OriginStorage":
            records.append((xml, root, decoded.source_map[:xml_end]))
        cursor = close_at + 1
    return tuple(records)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(root: ET.Element, name: str) -> ET.Element | None:
    return next((element for element in root.iter() if _local_name(element.tag) == name), None)


def _child_text(root: ET.Element, name: str) -> str | None:
    element = _child(root, name)
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _record_metadata(root: ET.Element) -> tuple[str, str, str | None, int | None]:
    calculation = _child(root, "Calculation")
    creator = root.attrib.get("Creator")
    family = creator or _child_text(root, "NLFitXFName") or _child_text(root, "xfName")
    uid: int | None = None
    analysis_name: str | None = None
    calculation_label: str | None = None
    if calculation is not None:
        analysis_name = calculation.attrib.get("AnalysisName")
        calculation_label = calculation.attrib.get("Label")
        uid_text = calculation.attrib.get("UID")
        if uid_text is not None:
            try:
                uid = int(uid_text)
            except ValueError:
                uid = None
    family = family or analysis_name or "origin_storage"
    is_function = bool(creator or root.attrib.get("OperationVersionNum") or calculation is not None)
    return family, "function" if is_function else "related_origin_storage", calculation_label, uid


def _suspicious_character_count(payload: bytes) -> int:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return 1_000_000
    return sum(
        character not in "\t\n\r" and (ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F) for character in text
    )


def _candidate_for_phase(
    data: bytes,
    phase: int,
    *,
    source_start: int,
    marker_offset: int,
) -> tuple[tuple[int, int, int, int], OpjuRecoveredXml] | None:
    decoded = decode_origin_storage_byte_runs(
        data,
        phase,
        source_start=source_start,
        out_of_band_control_policy="stop",
    )
    prefix = next(iter(_iter_xml_prefixes(decoded)), None)
    if prefix is None:
        return None
    xml, root, source_map = prefix
    family, classification, calculation_label, uid = _record_metadata(root)
    priority = 0 if data[phase] == 0x7F else (1 if data[phase] >= 0xC0 else 2)
    score = (_suspicious_character_count(xml), priority, classification != "function", phase)
    record = OpjuRecoveredXml(
        xml=xml,
        source_map=source_map,
        source_start=min(source_map),
        source_end=max(source_map) + 1,
        marker_offset=marker_offset,
        phase=phase,
        stop_reason=decoded.stop_reason,
        family=family,
        classification=classification,
        calculation_label=calculation_label,
        calculation_uid=uid,
    )
    return score, record


def recover_origin_storage_xml(
    data: bytes,
    *,
    source_start: int = 0,
    marker_offset: int = 0,
    phase_scan_limit: int = 512,
) -> OpjuRecoveredXml | None:
    """Recover the best complete XML record from one encoded marker window."""
    scan_end = min(len(data), max(0, phase_scan_limit))
    full_literal_phases = [offset for offset in range(scan_end) if data[offset] == 0x7F]
    repeat_phases = [offset for offset in range(scan_end) if data[offset] >= 0xC0]
    preferred_set = {*full_literal_phases, *repeat_phases}
    fallback = [offset for offset in range(scan_end) if offset not in preferred_set]
    candidates: list[tuple[tuple[int, int, int, int], OpjuRecoveredXml]] = []
    for phases in (full_literal_phases, repeat_phases, fallback):
        for phase in phases:
            candidate = _candidate_for_phase(
                data,
                phase,
                source_start=source_start,
                marker_offset=marker_offset,
            )
            if candidate is None:
                continue
            candidates.append(candidate)
            score, record = candidate
            # Phases are grouped by score priority and sorted by offset. A
            # clean function record is therefore unbeatable once encountered.
            if score[0] == 0 and score[2] is False:
                return record
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def recover_origin_storage_xml_records(
    data: bytes,
    *,
    source_start: int = 0,
    phase_scan_limit: int = 512,
) -> tuple[OpjuRecoveredXml, ...]:
    """Recover all unique complete XML roots visible in one encoded window."""
    records: list[OpjuRecoveredXml] = []
    seen: set[tuple[str, int | None, int]] = set()
    marker = 0
    while (marker := data.find(_ORIGIN_STORAGE_OPEN, marker)) >= 0:
        record = recover_origin_storage_xml(
            data[marker:],
            source_start=source_start + marker,
            marker_offset=marker,
            phase_scan_limit=phase_scan_limit,
        )
        if record is not None:
            key = (record.sha256, record.calculation_uid, marker)
            if key not in seen:
                seen.add(key)
                records.append(record)
        marker += 1
    return tuple(sorted(records, key=lambda item: (item.source_start, item.classification != "function")))


__all__ = [
    "OpjuByteRunDecode",
    "OpjuByteRunError",
    "OpjuRecoveredXml",
    "decode_origin_storage_byte_runs",
    "recover_origin_storage_xml",
    "recover_origin_storage_xml_records",
]
