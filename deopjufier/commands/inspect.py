"""Inspect command handler."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import cast

from deopjufier import __version__
from deopjufier.commands.metadata import (
    _format_hints,
    _inspect_failure_payload,
    _session_format_hints,
)
from deopjufier.commands.render import _print_inspect_summary
from deopjufier.commands.support import (
    _INVENTORY_MAX_SIZE_FOR_IMAGES,
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    NATIVE_BACKEND,
    SUPPORTED_TYPES,
    _add_parser_warning,
    _build_session,
    _coerce_default_heuristic_kind_limit,
    _command_state,
    _has_origin_family_mismatch,
    _safe_detect_file,
    _signature_hits_summary_from_blocks,
    _support_class,
    _support_scope,
)
from deopjufier.detect import DetectedFile
from deopjufier.errors import CorruptedInputError
from deopjufier.inventory import OriginObject
from deopjufier.session import (
    _list_kind_for_origin_object,
)

_INSPECT_OPJU_FORMAT_HINT_LIMIT_BYTES = 4 * 1024 * 1024


def _build_inspect_payload(
    file_path: Path,
    detection: DetectedFile,
    session,
    is_supported_type: bool,
    parser_status: str,
    warnings: list[str],
    parser_warnings: list[dict[str, str]],
    signatures: dict[str, object],
    origin_objects: list[OriginObject],
    list_items: list[dict[str, object]],
    image_count: int,
    opju_raw_crosswalk: list[dict[str, object]],
) -> dict[str, object]:
    object_kind_counts = Counter(obj.object_kind or "unknown" for obj in origin_objects)
    discovery_type_counts = Counter(
        "opj_boundary" if obj.parser_confirmed else "object_discovery" for obj in origin_objects
    )
    kind_counts = Counter(
        _list_kind_for_origin_object(
            detection.detected_type,
            obj.object_kind,
            obj.parser_confirmed,
        )
        for obj in origin_objects
    )
    heuristic_count = sum(1 for obj in origin_objects if not obj.parser_confirmed)
    parser_evidence_counts = {
        "kind": kind_counts,
        "object_kind": Counter(object_kind_counts),
        "discovery_type": Counter(discovery_type_counts),
        "heuristic": Counter(
            {
                "true": heuristic_count,
                "false": len(origin_objects) - heuristic_count,
            }
        ),
    }
    boundary_object_kind_counts = Counter(
        obj.object_kind or "unknown" for obj in origin_objects if obj.parser_confirmed
    )
    heuristic_object_kind_counts = Counter(
        obj.object_kind or "unknown" for obj in origin_objects if not obj.parser_confirmed
    )

    item_count = len(list_items) if list_items else (len(origin_objects) + image_count)
    origin_item_count = len(list_items) - image_count if list_items else len(origin_objects)
    counts: dict[str, object] = {
        "items": item_count,
        "images": image_count,
    }
    counts["artifact_counts"] = (
        {}
        if not is_supported_type
        else {
            "image": image_count,
            "origin_object": max(0, origin_item_count),
        }
    )
    counts["embedded_signatures"] = signatures["counts_by_kind"]

    status = _command_state(
        is_supported=is_supported_type,
        parser_status=parser_status,
        has_items=item_count > 0,
    )
    if detection.detected_type == "opju" and session.size_bytes > _INSPECT_OPJU_FORMAT_HINT_LIMIT_BYTES:
        format_hints = _format_hints(detection)
    else:
        format_hints = _session_format_hints(session, detection)

    payload: dict[str, object] = {
        "path": str(file_path),
        "size_bytes": session.size_bytes,
        "sha256": session.sha256,
        "detected_type": detection.detected_type,
        "confidence": detection.confidence,
        "reason": detection.reason,
        "format_hints": format_hints,
        "support_class": _support_class(
            detection.detected_type,
            parser_status,
            status=status,
            warnings=warnings,
            warning_codes=[warning["code"] for warning in parser_warnings],
            items=(
                [item for item in list_items if item.get("discovery_type") != "carved"]
                if detection.detected_type == "opju"
                else origin_objects
            ),
        ),
        **dict(
            zip(
                ["coverage_scope", "verification"],
                _support_scope(
                    detection.detected_type,
                    parser_status,
                    status=status,
                    warnings=warnings,
                    warning_codes=[warning["code"] for warning in parser_warnings],
                    items=(
                        [item for item in list_items if item.get("discovery_type") != "carved"]
                        if detection.detected_type == "opju"
                        else origin_objects
                    ),
                ),
                strict=True,
            )
        ),
        "parser_status": parser_status,
        "warnings": warnings,
        "parser_warnings": parser_warnings,
        "embedded_signatures": signatures,
        "status": status,
        "tool": {
            "name": "deopjufy",
            "version": __version__,
            "backend": NATIVE_BACKEND,
        },
        "counts": counts,
        "opju_raw_crosswalk": opju_raw_crosswalk,
    }
    if is_supported_type:
        counts["origin_objects"] = len(origin_objects)
        counts["origin_object_kinds"] = {str(key): value for key, value in sorted(object_kind_counts.items())}
        counts["origin_object_discovery_types"] = {
            str(key): value for key, value in sorted(discovery_type_counts.items())
        }
        counts["parser_evidence_counts"] = {
            str(key): {
                (
                    "true"
                    if key == "heuristic" and inner_key is True
                    else "false"
                    if key == "heuristic" and inner_key is False
                    else str(inner_key)
                ): inner_value
                for inner_key, inner_value in sorted(inner_counts.items())
            }
            for key, inner_counts in parser_evidence_counts.items()
        }
        counts["origin_object_boundary_kinds"] = {
            str(key): value for key, value in sorted(boundary_object_kind_counts.items())
        }
        counts["origin_object_heuristic_kinds"] = {
            str(key): value for key, value in sorted(heuristic_object_kind_counts.items())
        }
    return payload


def cmd_inspect(args: argparse.Namespace) -> int:
    file_path = cast(Path, args.file)
    as_json = cast(bool, getattr(args, "json", False))
    quiet = cast(bool, getattr(args, "quiet", False))
    try:
        session = _build_session(file_path)
        detection = session.detection
        is_supported_type = detection.detected_type in SUPPORTED_TYPES
        origin_objects: list[OriginObject] = []
        list_items: list[dict[str, object]] = []
        image_count = 0
        parser_status = "ok"
        warnings: list[str] = []
        parser_warnings: list[dict[str, str]] = []
        exit_code = EXIT_SUCCESS
        image_blocks = session.image_blocks()
        signatures = _signature_hits_summary_from_blocks(image_blocks)
        has_origin_mismatch = _has_origin_family_mismatch(detection)
        include_images = session.size_bytes <= _INVENTORY_MAX_SIZE_FOR_IMAGES

        if is_supported_type:
            try:
                origin_objects = session.objects(
                    max_repeats_per_name=None,
                    include_redundant_tokens=True,
                    heuristic_kind_limit=(
                        _coerce_default_heuristic_kind_limit(
                            detection.detected_type,
                            session.size_bytes,
                        )
                    ),
                )
                list_items = session.list_items(
                    include_images=include_images,
                    include_raw_gaps=False,
                    include_raw_dump_crosswalk=False,
                    heuristic_kind_limit=(
                        _coerce_default_heuristic_kind_limit(
                            detection.detected_type,
                            session.size_bytes,
                        )
                    ),
                    use_default_opju_limit=False,
                )
                image_count = len([item for item in list_items if item.get("discovery_type") == "carved"])
            except CorruptedInputError as exc:
                parser_status = "error"
                exit_code = EXIT_CORRUPTED
                _add_parser_warning(
                    warnings,
                    parser_warnings,
                    "native-parser-error",
                    f"Native parser error: {exc}",
                )
            except Exception as exc:
                parser_status = "error"
                exit_code = EXIT_GENERAL
                _add_parser_warning(
                    warnings,
                    parser_warnings,
                    "native-parser-error",
                    f"Native parser error: {exc}",
                )
        else:
            parser_status = "unsupported"
            _add_parser_warning(
                warnings,
                parser_warnings,
                "unsupported-input-type",
                f"Native parser does not support detected type '{detection.detected_type}'.",
            )

        if parser_status == "ok" and detection.detected_type == "opj" and not list_items:
            parser_status = "empty"
            _add_parser_warning(
                warnings,
                parser_warnings,
                "no-listable-items",
                "Native parser found no listable items.",
            )
        if has_origin_mismatch and parser_status != "error":
            signature_message = (
                f"Header signature indicates '{detection.magic_type}' while file extension maps "
                f"to '{detection.detected_type}'."
            )
            _add_parser_warning(
                warnings,
                parser_warnings,
                "header-signature-mismatch",
                signature_message,
            )

        opju_raw_crosswalk: list[dict[str, object]] = []
        if parser_status == "ok" and is_supported_type and detection.detected_type == "opju":
            crosswalk_items = session.list_items(
                include_images=False,
                include_raw_gaps=False,
                include_raw_dump_crosswalk=True,
                use_default_opju_limit=True,
            )
            opju_raw_crosswalk = [
                {
                    "source_object_path": item["source_object_path"],
                    "name": item["name"],
                    "offset": item["offset"],
                    "length": item["length"],
                    "raw_dump_crosswalk": item.get("raw_dump_crosswalk", []),
                }
                for item in crosswalk_items
                if not item.get("heuristic")
                and item.get("discovery_type") != "carved"
                and item.get("raw_dump_crosswalk") is not None
            ]

        payload = _build_inspect_payload(
            file_path=file_path,
            detection=detection,
            session=session,
            is_supported_type=is_supported_type,
            parser_status=parser_status,
            warnings=warnings,
            parser_warnings=parser_warnings,
            signatures=signatures,
            origin_objects=origin_objects,
            list_items=list_items,
            image_count=image_count,
            opju_raw_crosswalk=opju_raw_crosswalk,
        )
        if not quiet or parser_status == "error" or not is_supported_type:
            _print_inspect_summary(payload, as_json=as_json)
        if parser_status == "error":
            return exit_code
        if not is_supported_type:
            return EXIT_UNSUPPORTED
        return EXIT_SUCCESS
    except Exception as exc:
        detection: DetectedFile | None
        try:
            detection = _safe_detect_file(file_path)
        except OSError:
            detection = None
        payload, exit_code = _inspect_failure_payload(file_path, exc, detection)
        from .render import _print_inspect_summary as _print

        _print(payload, as_json=as_json)
        return exit_code
