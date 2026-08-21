"""Bounded OPJU external-workbook reference recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path

_EXTERNAL_WORKBOOK_PATH_RE = re.compile(
    rb"\[[^\]\x00\r\n]{1,4096}\.(?:xlsx|xlsm|xls)\]",
    re.IGNORECASE,
)
_EXTERNAL_WORKBOOK_MARKER = b"[excel]"
_EXTERNAL_WORKBOOK_REFERENCE_MAX_BYTES = 8192


def find_external_workbook_reference(
    payload: bytes,
    *,
    source_offset: int,
) -> tuple[str, str, int, int] | None:
    """Find a bounded, NUL-terminated OPJU external workbook reference."""

    payload_lower = payload.lower()
    marker_offset = payload_lower.find(_EXTERNAL_WORKBOOK_MARKER)
    while marker_offset >= 0:
        run_start = payload.rfind(b"\x00", 0, marker_offset) + 1
        run_end = payload.find(b"\x00", marker_offset)
        if run_end >= 0 and 0 < run_end - run_start <= _EXTERNAL_WORKBOOK_REFERENCE_MAX_BYTES:
            encoded_reference = payload[run_start:run_end]
            if encoded_reference.startswith(b"\n"):
                encoded_reference = encoded_reference[1:]
                run_start += 1
            workbook_match = _EXTERNAL_WORKBOOK_PATH_RE.search(encoded_reference)
            try:
                reference = encoded_reference.decode("utf-8")
            except UnicodeDecodeError:
                reference = ""
            if workbook_match is not None and reference and not any(ord(char) < 0x20 for char in reference):
                workbook_path = workbook_match.group(0).decode("utf-8")
                return (
                    reference,
                    workbook_path,
                    source_offset + run_start,
                    source_offset + run_end,
                )
        marker_offset = payload_lower.find(_EXTERNAL_WORKBOOK_MARKER, marker_offset + 1)
    return None


def write_external_workbook_reference(
    target: Path,
    *,
    advertised_filename: str,
    reference: str,
    workbook_path: str,
    source_start: int,
    source_end: int,
) -> None:
    """Write one deterministic external-workbook reference sidecar."""

    payload = {
        "advertised_filename": advertised_filename,
        "embedded_payload": False,
        "reference": reference,
        "source_range": {"end": source_end, "start": source_start},
        "workbook_path": workbook_path,
    }
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


__all__ = ["find_external_workbook_reference", "write_external_workbook_reference"]
