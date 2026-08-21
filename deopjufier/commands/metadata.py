"""CLI metadata and failure-payload helpers."""

from __future__ import annotations

from pathlib import Path

from deopjufier import __version__
from deopjufier.catalog import CATALOG_SCHEMA_VERSION, document_payload
from deopjufier.detect import DetectedFile
from deopjufier.errors import CorruptedInputError, UnsupportedFileError
from deopjufier.inventory import (
    OPJU_HINTS_MAX_BLOCKS,
    extract_origin_storage_blocks,
    parse_opj_note_sections,
    parse_opj_parameters,
    parse_opj_signature,
    parse_opju_description,
    parse_opju_origin_storage_reports,
)
from deopjufier.session import ExtractionSession

from .support import (
    _FORMAT_HINTS_MAX_SIZE,
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
    NATIVE_BACKEND,
    SUPPORTED_TYPES,
    _command_state,
    _safe_signature_summary,
    _support_class,
    _support_scope,
)


def _inspect_failure_payload(
    path: Path, exc: Exception, detection: DetectedFile | None
) -> tuple[dict[str, object], int]:
    if isinstance(exc, CorruptedInputError):
        parser_status = "error"
        exit_code = EXIT_CORRUPTED
    elif isinstance(exc, UnsupportedFileError):
        parser_status = "unsupported"
        exit_code = EXIT_UNSUPPORTED
    elif isinstance(exc, ValueError):
        parser_status = "unsupported"
        exit_code = EXIT_USAGE
    else:
        parser_status = "unsupported"
        exit_code = EXIT_GENERAL

    detected_type = detection.detected_type if detection is not None else "unknown"
    is_supported_type = detected_type in SUPPORTED_TYPES and detection is not None
    warnings: list[str] = [str(exc)]
    parser_warnings = [{"code": "command-exec-error", "message": str(exc)}]
    signatures = _safe_signature_summary(path)

    payload: dict[str, object] = {
        "path": str(path),
        "size_bytes": 0,
        "sha256": "",
        "detected_type": detected_type,
        "confidence": detection.confidence if detection else 0.0,
        "reason": detection.reason if detection else "command-init-failed",
        "format_hints": _format_hints(detection) if detection is not None else {},
        "support_class": _support_class(
            detected_type,
            parser_status,
            status="unsupported",
            warnings=warnings,
            warning_codes=[warning["code"] for warning in parser_warnings],
        ),
        **dict(
            zip(
                ["coverage_scope", "verification"],
                _support_scope(
                    detected_type,
                    parser_status,
                    status="unsupported",
                    warnings=warnings,
                    warning_codes=[warning["code"] for warning in parser_warnings],
                    items=[],
                ),
                strict=True,
            )
        ),
        "parser_status": parser_status,
        "warnings": warnings,
        "parser_warnings": parser_warnings,
        "embedded_signatures": signatures,
        "status": _command_state(
            is_supported=is_supported_type,
            parser_status=parser_status,
            has_items=False,
        ),
        "tool": {
            "name": "deopjufy",
            "version": __version__,
            "backend": NATIVE_BACKEND,
        },
        "counts": {
            "items": 0,
            "images": 0,
            "artifact_counts": {},
        },
    }
    return payload, exit_code


def _list_failure_payload(path: Path, exc: Exception, detection: DetectedFile | None) -> tuple[dict[str, object], int]:
    if isinstance(exc, CorruptedInputError):
        parser_status = "error"
        exit_code = EXIT_CORRUPTED
    elif isinstance(exc, UnsupportedFileError):
        parser_status = "unsupported"
        exit_code = EXIT_UNSUPPORTED
    elif isinstance(exc, ValueError):
        parser_status = "unsupported"
        exit_code = EXIT_USAGE
    else:
        parser_status = "unsupported"
        exit_code = EXIT_GENERAL

    detected_type = detection.detected_type if detection is not None else "unknown"
    is_supported_type = detected_type in SUPPORTED_TYPES and detection is not None
    message = str(exc)
    warnings: list[str] = [message]
    parser_warnings = [{"code": "command-exec-error", "message": message}]
    signatures = _safe_signature_summary(path)

    payload: dict[str, object] = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "document": document_payload(
            path=str(path),
            size_bytes=0,
            sha256="",
            detected_type=detected_type,
        ),
        "file": str(path),
        "detected_type": detected_type,
        "support_class": _support_class(
            detected_type,
            parser_status,
            status="unsupported",
            warnings=warnings,
            warning_codes=[warning["code"] for warning in parser_warnings],
        ),
        **dict(
            zip(
                ["coverage_scope", "verification"],
                _support_scope(
                    detected_type,
                    parser_status,
                    status="unsupported",
                    warnings=warnings,
                    warning_codes=[warning["code"] for warning in parser_warnings],
                    items=[],
                ),
                strict=True,
            )
        ),
        "status": _command_state(
            is_supported=is_supported_type,
            parser_status=parser_status,
            has_items=False,
        ),
        "parser_status": parser_status,
        "format_hints": _format_hints(detection) if detection is not None else {},
        "parser_warnings": parser_warnings,
        "embedded_signatures": signatures,
        "warnings": warnings,
        "tool": {
            "name": "deopjufy",
            "version": __version__,
            "backend": NATIVE_BACKEND,
        },
        "items": [],
    }
    return payload, exit_code


def _session_format_hints(
    session: ExtractionSession, detection: DetectedFile
) -> dict[str, str | bool | int | float | dict[str, object] | list[object]]:
    if session.size_bytes > _FORMAT_HINTS_MAX_SIZE:
        return _format_hints(detection)
    return _format_hints(
        detection,
        file_data=session.file_data(),
        file_path=session.input_path,
    )


def _format_hints(
    detection: DetectedFile,
    *,
    file_data: bytes | None = None,
    file_path: Path | None = None,
) -> dict[str, str | bool | int | float | dict[str, object] | list[object]]:
    hints: dict[str, str | bool | int | float | dict[str, object] | list[object]] = {}
    if detection.magic_type:
        hints["magic_type"] = detection.magic_type
        hints["magic_offset"] = detection.magic_offset or 0
        hints["magic_verified"] = detection.magic_type in {"opj", "opju"}
        if detection.magic_type == "opju":
            hints["family_hint"] = "legacy-opju"
        elif detection.magic_type == "opj":
            hints["family_hint"] = "legacy-opj"
        else:
            hints["family_hint"] = "other"
        if file_data is not None:
            signature = parse_opj_signature(file_data)
            if signature is not None:
                hints["opj_magic"] = signature.magic
                hints["opj_file_version"] = signature.file_version
                hints["opj_build"] = signature.build
                if signature.origin_version is not None:
                    hints["opj_origin_version"] = signature.origin_version
            if detection.magic_type == "opj":
                parameters = parse_opj_parameters(file_data)
                hints["opj_parameter_count"] = len(parameters)
                if parameters:
                    hints["opj_parameters"] = [{"name": p.name, "value": p.value} for p in parameters[:5]]
                note_sections = parse_opj_note_sections(file_data, path=file_path)
                hints["opj_note_section_count"] = len(note_sections)
                if note_sections:
                    hints["opj_note_sections"] = [
                        {"name": section.name, "text": section.text} for section in note_sections[:5]
                    ]
            if detection.magic_type == "opju":
                description = parse_opju_description(file_data)
                if description:
                    hints["opju_description"] = description
                storage_reports = parse_opju_origin_storage_reports(
                    file_data,
                    max_reports=OPJU_HINTS_MAX_BLOCKS,
                    path=file_path,
                )
                if storage_reports:
                    hints["origin_storage_report_count"] = len(storage_reports)
                    hints["origin_storage_reports"] = [
                        {
                            "index": report.index,
                            "label": report.label,
                            "function": report.function,
                            "user": report.user,
                            "time": report.time,
                            "data_filter": report.data_filter,
                            "input_data": report.input_data[:6],
                        }
                        for report in storage_reports
                    ]
                storage_blocks = extract_origin_storage_blocks(file_data)
                if storage_blocks:
                    hints["origin_storage_blocks"] = len(storage_blocks)
                    hints["origin_storage_preview"] = str(storage_blocks[0].get("preview", ""))
        return hints
    return hints


_HELP_MASCOT = """\
  ____              _
 |  _ \\  ___   ___ | |__
 | | | |/ _ \\ / _ \\| '_ \\
 | |_| | (_) | (_) | |_) |
 |____/ \\___/ \\___/|_.__/
      deopjufy
"""


def _format_help_epilog() -> str:
    return """\
deopjufy is a small Unix-style Origin project extractor.

It uses a native parser and is intentionally partial: unsupported structures remain
explicit in manifest status fields and warnings.

Examples:
  deopjufy inspect sample.opj
  deopjufy list sample.opj --json
  deopjufy get sample.opj item:v1:ID --json
  deopjufy inspect sample.opju
  deopjufy extract sample.opj -o out/
  deopjufy strings sample.opj --min-length 4
  deopjufy images sample.opj -o images/
  deopjufy table-scan sample.bin --format json
  deopjufy walk sample.opju --json
  deopjufy dump-block sample.opju --offset 0 --length 4096
  deopjufy compare path/to/left result/path

Commands:
  inspect      Print detection report
  list         List discoverable artifacts
  get          Materialize one catalog item by ID
  extract      Recover content and write manifest
  strings      Extract visible text strings
  images       Extract embedded image blocks
  table-scan   Scan for numeric tables
  walk         Walk parser-known OPJ/OPJU source ranges
  dump-block   Dump a byte range from file offset
  compare      Compare two manifest-backed outputs
"""
