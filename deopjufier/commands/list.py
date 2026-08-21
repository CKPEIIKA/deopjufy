"""List command handler."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from deopjufier import __version__
from deopjufier.catalog import CATALOG_SCHEMA_VERSION, catalog_items, document_payload
from deopjufier.commands.metadata import _list_failure_payload
from deopjufier.commands.render import _print_list_summary
from deopjufier.commands.support import (
    _coerce_list_heuristic_kind_limit,
    _command_state,
    _safe_detect_file,
    _support_class,
    _support_scope,
)
from deopjufier.detect import DetectedFile
from deopjufier.io import sha256_file


def _session_sha256(session: object, file_path: Path) -> str:
    value = getattr(session, "sha256", None)
    return value if isinstance(value, str) and value else sha256_file(file_path)


def _build_list_payload(
    file_path: Path,
    detection: DetectedFile,
    is_supported_type: bool,
    parser_status: str,
    status: str,
    warnings: list[str],
    parser_warnings: list[dict[str, str]],
    signatures: dict[str, object],
    items: list[dict],
    size_bytes: int,
    sha256: str,
) -> dict[str, object]:
    from deopjufier.commands.metadata import _format_hints

    support_items = items
    if detection.detected_type == "opju":
        support_items = [item for item in items if item.get("discovery_type") != "carved"]

    catalog = catalog_items(items, sha256)
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "document": document_payload(
            path=str(file_path),
            size_bytes=size_bytes,
            sha256=sha256,
            detected_type=detection.detected_type,
        ),
        "file": str(file_path),
        "detected_type": detection.detected_type,
        "support_class": _support_class(
            detection.detected_type,
            parser_status,
            status=status if is_supported_type else "unsupported",
            warnings=warnings,
            warning_codes=[warning["code"] for warning in parser_warnings],
            items=support_items,
        ),
        **dict(
            zip(
                ["coverage_scope", "verification"],
                _support_scope(
                    detection.detected_type,
                    parser_status,
                    status=status if is_supported_type else "unsupported",
                    warnings=warnings,
                    warning_codes=[warning["code"] for warning in parser_warnings],
                    items=support_items,
                ),
                strict=True,
            )
        ),
        "status": status if is_supported_type else "unsupported",
        "parser_status": parser_status,
        "format_hints": _format_hints(detection),
        "parser_warnings": parser_warnings,
        "embedded_signatures": signatures,
        "warnings": warnings
        if parser_status != "ok"
        else (["Native parser found no listable items."] if not items else []),
        "tool": {
            "name": "deopjufy",
            "version": __version__,
            "backend": "native-parser",
        },
        "items": catalog,
    }


def cmd_list(args: argparse.Namespace) -> int:
    file_path = cast(Path, args.file)
    should_exhaust = cast(bool, getattr(args, "exhaustive", False))
    include_raw_gaps = cast(bool, getattr(args, "include_raw_gaps", False))
    json_output = cast(bool, getattr(args, "json", False))
    quiet = cast(bool, getattr(args, "quiet", False))

    from deopjufier.commands.support import (
        _INVENTORY_MAX_SIZE_FOR_IMAGES,
        EXIT_CORRUPTED,
        EXIT_GENERAL,
        EXIT_SUCCESS,
        EXIT_UNSUPPORTED,
        SUPPORTED_TYPES,
        _add_parser_warning,
        _build_session,
        _has_origin_family_mismatch,
        _signature_hits_summary_from_blocks,
    )
    from deopjufier.errors import CorruptedInputError

    try:
        session = _build_session(file_path)
        session_sha256 = _session_sha256(session, file_path)
        detection = session.detection
        is_supported_type = detection.detected_type in SUPPORTED_TYPES
        signatures = _signature_hits_summary_from_blocks(session.image_blocks())
        if not is_supported_type:
            warnings: list[str] = [f"Native parser does not support detected type '{detection.detected_type}'."]
            parser_warnings: list[dict[str, str]] = [
                {
                    "code": "unsupported-input-type",
                    "message": f"Native parser does not support detected type '{detection.detected_type}'.",
                }
            ]
            if _has_origin_family_mismatch(detection):
                signature_message = (
                    f"Header signature indicates '{detection.magic_type}' while file "
                    f"extension maps to '{detection.detected_type}'."
                )
                warnings.insert(
                    0,
                    signature_message,
                )
                parser_warnings.insert(
                    0,
                    {
                        "code": "header-signature-mismatch",
                        "message": signature_message,
                    },
                )
            payload: dict[str, object] = {
                "file": str(file_path),
                "schema_version": CATALOG_SCHEMA_VERSION,
                "document": document_payload(
                    path=str(file_path),
                    size_bytes=session.size_bytes,
                    sha256=session_sha256,
                    detected_type=detection.detected_type,
                ),
                "detected_type": detection.detected_type,
                "support_class": _support_class(
                    detection.detected_type,
                    "unsupported",
                    status="unsupported",
                    warnings=warnings,
                    warning_codes=[warning["code"] for warning in parser_warnings],
                    items=[],
                ),
                **dict(
                    zip(
                        ["coverage_scope", "verification"],
                        _support_scope(
                            detection.detected_type,
                            "unsupported",
                            status="unsupported",
                            warnings=warnings,
                            warning_codes=[warning["code"] for warning in parser_warnings],
                            items=[],
                        ),
                        strict=True,
                    )
                ),
                "status": "unsupported",
                "parser_status": "unsupported",
                "format_hints": {},
                "warnings": warnings,
                "parser_warnings": parser_warnings,
                "embedded_signatures": signatures,
                "tool": {
                    "name": "deopjufy",
                    "version": __version__,
                    "backend": "native-parser",
                },
                "items": [],
            }
            if not quiet:
                _print_list_summary(payload, as_json=json_output)
            return EXIT_UNSUPPORTED

        items: list[dict] = []
        parser_status = "ok"
        warnings = []
        parser_warnings: list[dict[str, str]] = []
        exit_code = EXIT_SUCCESS
        has_origin_mismatch = _has_origin_family_mismatch(detection)
        list_heuristic_limit = _coerce_list_heuristic_kind_limit(
            detection.detected_type,
            session.size_bytes,
            should_exhaust,
        )

        try:
            include_images = session.size_bytes <= _INVENTORY_MAX_SIZE_FOR_IMAGES
            listed_items = session.list_items(
                include_images=include_images,
                include_raw_gaps=include_raw_gaps,
                include_raw_dump_crosswalk=detection.detected_type == "opju",
                heuristic_kind_limit=list_heuristic_limit,
                use_default_opju_limit=False,
            )
            items = sorted(
                listed_items,
                key=lambda item: (
                    item.get("offset", 0),
                    item.get("kind", ""),
                    item.get("source_object_path", ""),
                    item.get("name", ""),
                ),
            )
        except CorruptedInputError as exc:
            parser_status = "error"
            exit_code = EXIT_CORRUPTED
            _add_parser_warning(
                warnings,
                parser_warnings,
                "native-parser-error",
                f"Native parser error: {exc}",
            )
            items = []
        except Exception as exc:
            parser_status = "error"
            exit_code = EXIT_GENERAL
            _add_parser_warning(
                warnings,
                parser_warnings,
                "native-parser-error",
                f"Native parser error: {exc}",
            )
            items = []

        if is_supported_type and parser_status == "ok" and not items:
            parser_status = "empty"
            _add_parser_warning(
                warnings,
                parser_warnings,
                "no-listable-items",
                "Native parser found no listable items.",
            )
        if has_origin_mismatch and parser_status != "error":
            signature_message = (
                f"Header signature indicates '{detection.magic_type}' while file "
                f"extension maps to '{detection.detected_type}'."
            )
            _add_parser_warning(
                warnings,
                parser_warnings,
                "header-signature-mismatch",
                signature_message,
            )

        status = _command_state(
            is_supported=True,
            parser_status=parser_status,
            has_items=bool(items),
        )
        payload = _build_list_payload(
            file_path=file_path,
            detection=detection,
            is_supported_type=is_supported_type,
            parser_status=parser_status,
            status=status,
            warnings=warnings,
            parser_warnings=parser_warnings,
            signatures=signatures,
            items=items,
            size_bytes=session.size_bytes,
            sha256=session_sha256,
        )
        if not quiet or parser_status == "error" or not items:
            _print_list_summary(payload, as_json=json_output)
        if parser_status == "error":
            return exit_code
        if not items:
            return EXIT_UNSUPPORTED
        return EXIT_SUCCESS
    except FileNotFoundError as exc:
        payload, exit_code = _list_failure_payload(file_path, exc, None)
        _print_list_summary(payload, as_json=json_output)
        return exit_code
    except Exception as exc:
        detection_payload = _safe_detect_file(file_path)
        payload, exit_code = _list_failure_payload(file_path, exc, detection_payload)
        _print_list_summary(payload, as_json=json_output)
        return exit_code
