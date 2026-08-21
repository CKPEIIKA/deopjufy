"""Shared CLI support helpers and constants."""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

from deopjufier.blocks import ImageBlock, find_all_blocks
from deopjufier.detect import DetectedFile, detect_file
from deopjufier.inventory import OriginObject
from deopjufier.session import ExtractionSession

EXIT_SUCCESS = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3
EXIT_PARTIAL = 4
EXIT_MISSING_DEPENDENCY = 5
EXIT_CORRUPTED = 6
SUPPORTED_TYPES = {"opj", "opju"}
NATIVE_BACKEND = "native-parser"
_ARTIFACT_KIND_MAP = {
    "png": "image",
    "jpeg": "image",
    "gif": "image",
    "bmp": "image",
    "image": "image",
    "svg": "image",
    "origin_object": "origin_object",
    "raw_dump": "raw_dump",
    "text_region": "text_region",
}
_EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES = 1 << 20
_EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND = 24
_INVENTORY_MAX_SIZE_FOR_IMAGES = 10 * 1024 * 1024
_FORMAT_HINTS_MAX_SIZE = 8 * 1024 * 1024
_DEFAULT_OPJU_HEURISTIC_KIND_LIMIT = 24
_DEFAULT_OPJ_HEURISTIC_KIND_LIMIT = 24
_OPJ_HEURISTIC_KIND_LIMIT_BYTES = 32 * 1024 * 1024
_OPJU_EXHAUSTIVE_HEURISTIC_KIND_LIMIT = None
_OPJU_PARSER_BACKED_EVIDENCE_KIND_PREFIX = "opju_"
_TREE_MATRIX_REFERENCE_MARKER_RE = re.compile(
    r"^MBook\d+/MSheet\d+(?:__\d+)?$",
    re.IGNORECASE,
)
_TREE_WORKSHEET_REFERENCE_MARKER_RE = re.compile(
    r"^(?:Book\d+/[A-Za-z0-9_.@-]+|Sheet/Sheet\d+)$",
    re.IGNORECASE,
)
_SUPPORT_CLASS_PARSER = "parser"
_SUPPORT_CLASS_HEURISTIC = "heuristic"
_SUPPORT_CLASS_FAILED = "failed"
_SUPPORT_CLASS_PARTIAL = "partial"

_COVERAGE_SCOPE_RECOGNIZED = "recognized"
_COVERAGE_SCOPE_RECOVERED = "recovered"
_COVERAGE_SCOPE_PARTIAL = "partial"
_COVERAGE_SCOPE_VERIFIED = "verified"
_COVERAGE_SCOPE_FAILED = "failed"

_VERIFICATION_UNVERIFIED = "unverified"
_VERIFICATION_SYNTHETIC = "synthetic"
_VERIFICATION_EXTERNAL_PARITY = "external-parity"


def _coerce_default_heuristic_kind_limit(detection_type: str, file_size: int | None = None) -> int | None:
    if detection_type == "opj" and file_size is not None:
        if file_size > _OPJ_HEURISTIC_KIND_LIMIT_BYTES:
            return _DEFAULT_OPJ_HEURISTIC_KIND_LIMIT
        return None
    if detection_type == "opju":
        return _DEFAULT_OPJU_HEURISTIC_KIND_LIMIT
    return None


def _coerce_list_heuristic_kind_limit(
    detection_type: str,
    file_size: int | None,
    should_exhaust: bool,
) -> int | None:
    if should_exhaust:
        return None
    return _coerce_default_heuristic_kind_limit(detection_type, file_size)


def _limit_extract_objects(
    objects: list[OriginObject],
    *,
    per_kind_limit: int = _EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND,
) -> list[OriginObject]:
    """Keep extract-mode work bounded on large heuristic-only inventories."""
    if per_kind_limit <= 0:
        return [obj for obj in objects if obj.parser_confirmed]

    limited: list[OriginObject] = []
    heuristic_counts: Counter[str] = Counter()
    for obj in objects:
        if obj.parser_confirmed:
            limited.append(obj)
            continue

        kind = obj.object_kind or "unclassified"
        if heuristic_counts[kind] >= per_kind_limit:
            continue
        heuristic_counts[kind] += 1
        limited.append(obj)
    return limited


def _coerce_counts_by_artifact(items: list[dict]) -> dict[str, int]:
    artifact_counts: Counter[str] = Counter()
    for item in items:
        kind = item.get("kind")
        if not isinstance(kind, str):
            continue
        artifact_counts[_ARTIFACT_KIND_MAP.get(kind, kind)] += 1

    return dict(sorted(artifact_counts.items(), key=lambda item: item[0]))


def _add_parser_warning(
    warnings: list[str],
    warnings_struct: list[dict[str, str]],
    code: str,
    message: str,
) -> None:
    warnings.append(message)
    warnings_struct.append({"code": code, "message": message})


def _signature_inventory_from_blocks(
    blocks: list[ImageBlock],
) -> dict[str, object]:
    counts: Counter[str] = Counter(block.kind for block in blocks)
    return {
        "count": len(blocks),
        "counts": dict(sorted(counts.items(), key=lambda item: item[0])),
        "blocks": [
            {"offset": block.offset, "length": block.length, "kind": block.kind}
            for block in sorted(blocks, key=lambda item: item.offset)
        ],
    }


def _signature_inventory(path: Path) -> dict[str, object]:
    return _signature_inventory_from_blocks(find_all_blocks(path))


def _signature_hits_summary_from_blocks(blocks: list[ImageBlock], kind_limit: int = 25) -> dict[str, object]:
    inventory = _signature_inventory_from_blocks(blocks)
    blocks_payload = cast(list[dict[str, object]], inventory["blocks"])
    return {
        "total_blocks": inventory["count"],
        "counts_by_kind": inventory["counts"],
        "sampled_blocks": blocks_payload[:kind_limit],
    }


def _signature_hits_summary(path: Path, kind_limit: int = 25) -> dict[str, object]:
    inventory = _signature_inventory(path)
    blocks_payload = cast(list[dict[str, object]], inventory["blocks"])
    return {
        "total_blocks": inventory["count"],
        "counts_by_kind": inventory["counts"],
        "sampled_blocks": blocks_payload[:kind_limit],
    }


def _safe_signature_summary(path: Path, kind_limit: int = 25) -> dict[str, object]:
    """Collect signature inventory for JSON payloads while handling missing/unreadable inputs."""
    try:
        return _signature_hits_summary(path, kind_limit=kind_limit)
    except OSError:
        return {"total_blocks": 0, "counts_by_kind": {}, "sampled_blocks": []}


def _safe_detect_file(path: Path) -> DetectedFile:
    """Return a best-effort detection payload for error-reporting paths."""
    return detect_file(path)


def _log(msg: str, *, enabled: bool, quiet: bool = False) -> None:
    if not enabled or quiet:
        return
    print(msg, file=sys.stderr)


def _ensure_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")


def _default_output_dir(file_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    return file_path.with_suffix("")


def _build_session(path: Path) -> ExtractionSession:
    _ensure_file(path)
    return ExtractionSession.from_path(path)


def _command_state(*, is_supported: bool, parser_status: str, has_items: bool) -> str:
    if not is_supported:
        return "unsupported"
    if parser_status == "error":
        return "unsupported"
    if not has_items:
        return parser_status
    return "ok"


def _support_class(
    detected_type: str,
    parser_status: str,
    *,
    status: str | None = None,
    warnings: list[str] | None = None,
    warning_codes: list[str] | None = None,
    items: Iterable[object] | None = None,
) -> str:
    if status is None:
        status = parser_status

    if parser_status == "error":
        return _SUPPORT_CLASS_FAILED

    if detected_type not in SUPPORTED_TYPES:
        return _SUPPORT_CLASS_HEURISTIC

    parsed_items = list(items or [])
    has_parser_backed, has_partial_or_failed_items = _summarize_items(parsed_items)
    if parser_status == "unsupported":
        return _SUPPORT_CLASS_HEURISTIC

    if detected_type == "opj":
        if parser_status == "empty":
            return _SUPPORT_CLASS_PARSER
        if (
            _is_full_supported_opj(
                parser_status=parser_status,
                status=status,
                warnings=warnings,
                warning_codes=warning_codes,
                items=parsed_items,
            )
            and has_parser_backed
        ):
            return _SUPPORT_CLASS_PARSER
        if has_parser_backed:
            return _SUPPORT_CLASS_PARTIAL
        return _SUPPORT_CLASS_HEURISTIC

    if detected_type == "opju":
        if has_partial_or_failed_items:
            return _SUPPORT_CLASS_PARTIAL
        if has_parser_backed:
            return _SUPPORT_CLASS_PARSER
        return _SUPPORT_CLASS_HEURISTIC

    return _SUPPORT_CLASS_HEURISTIC


def _summarize_items(items: list[object]) -> tuple[bool, bool]:
    has_parser_backed = False
    has_partial_or_failed_items = False

    for item in items:
        item_status = _coerce_item_status(item)
        if item_status in {"partial", "unsupported", "skipped"}:
            if not _is_recon_heuristic_item(
                kind=_coerce_item_kind(item),
                status=item_status,
                error=_coerce_item_error(item),
                source_object_path=_coerce_item_source_object_path(item),
                item_name=_coerce_item_name(item),
                discovery_type=_coerce_item_discovery_type(item),
            ):
                has_partial_or_failed_items = True
        if _is_parser_backed_item(item):
            has_parser_backed = True

    return has_parser_backed, has_partial_or_failed_items


def _support_scope(
    detected_type: str,
    parser_status: str,
    *,
    status: str | None = None,
    warnings: list[str] | None = None,
    warning_codes: list[str] | None = None,
    items: Iterable[object] | None = None,
) -> tuple[str, str]:
    """Return (coverage_scope, verification) for inspect/list/extract payloads."""
    if status is None:
        status = parser_status

    if parser_status == "error":
        return _COVERAGE_SCOPE_FAILED, _VERIFICATION_UNVERIFIED

    parsed_items = list(items or [])
    has_parser_backed, has_partial_or_failed_items = _summarize_items(parsed_items)
    if detected_type == "opju":
        has_partial_or_failed_items = any(
            _is_blocking_opju_scope_gap(
                kind=_coerce_item_kind(item),
                status=_coerce_item_status(item),
                error=_coerce_item_error(item),
                source_object_path=_coerce_item_source_object_path(item),
                item_name=_coerce_item_name(item),
                discovery_type=_coerce_item_discovery_type(item),
            )
            for item in parsed_items
        )
    if detected_type not in SUPPORTED_TYPES:
        return _COVERAGE_SCOPE_RECOGNIZED, _VERIFICATION_UNVERIFIED
    if status == "partial" or has_partial_or_failed_items:
        return _COVERAGE_SCOPE_PARTIAL, _VERIFICATION_UNVERIFIED
    if parser_status == "unsupported":
        return _COVERAGE_SCOPE_RECOGNIZED, _VERIFICATION_UNVERIFIED
    if status == "unsupported":
        return _COVERAGE_SCOPE_RECOGNIZED, _VERIFICATION_UNVERIFIED
    if has_parser_backed:
        return (
            _COVERAGE_SCOPE_VERIFIED
            if _supports_verified_coverage(
                detected_type=detected_type,
                parser_status=parser_status,
                status=status,
                warnings=warnings,
                warning_codes=warning_codes,
                items=parsed_items,
            )
            else _COVERAGE_SCOPE_RECOVERED,
            _VERIFICATION_UNVERIFIED,
        )
    if parsed_items:
        return _COVERAGE_SCOPE_RECOVERED, _VERIFICATION_UNVERIFIED
    return _COVERAGE_SCOPE_RECOGNIZED, _VERIFICATION_UNVERIFIED


def _is_blocking_opju_scope_gap(
    *,
    kind: str | None,
    status: str | None,
    error: str | None,
    source_object_path: str | None,
    item_name: str | None,
    discovery_type: str | None,
) -> bool:
    if status not in {"partial", "unsupported", "skipped"}:
        return False

    if _is_recon_heuristic_item(
        kind=kind,
        status=status,
        error=error,
        source_object_path=source_object_path,
        item_name=item_name,
        discovery_type=discovery_type,
    ):
        return True

    return True


def _supports_verified_coverage(
    detected_type: str,
    parser_status: str,
    status: str | None = None,
    warnings: list[str] | None = None,
    warning_codes: list[str] | None = None,
    items: list[object] | tuple[object, ...] | None = None,
) -> bool:
    if status is None:
        status = parser_status
    if detected_type != "opj":
        return False
    if items is None:
        items = []
    if any(not _is_parser_backed_item(item) for item in items):
        return False
    return (
        parser_status in {"ok", "empty"}
        and status in {"ok", "empty"}
        and warnings is not None
        and not warnings
        and (warning_codes is None or not warning_codes)
    )


def _is_parser_backed_item(item: object) -> bool:
    if isinstance(item, dict):
        return _is_dict_item_parser_backed(cast(Mapping[str, object], item))

    heuristic = getattr(item, "heuristic", None)
    if isinstance(heuristic, bool):
        return not heuristic

    parser_confirmed = getattr(item, "parser_confirmed", None)
    if isinstance(parser_confirmed, bool):
        return parser_confirmed

    status = getattr(item, "status", None)
    return isinstance(status, str) and status in {"extracted", "partial"}


def _coerce_item_status(item: object) -> str | None:
    if isinstance(item, dict):
        item_map = cast(Mapping[str, object], item)
        status = item_map.get("status")
        if isinstance(status, str):
            return status
        heuristic = item_map.get("heuristic")
        if isinstance(heuristic, bool):
            return "extracted" if not heuristic else "partial"
        return None

    status = getattr(item, "status", None)
    if isinstance(status, str):
        return status

    heuristic = getattr(item, "heuristic", None)
    if isinstance(heuristic, bool):
        return "extracted" if not heuristic else "partial"

    parser_confirmed = getattr(item, "parser_confirmed", None)
    if isinstance(parser_confirmed, bool):
        return "extracted" if parser_confirmed else "partial"
    return None


def _has_opj_partial_outputs(items: Iterable[object] | None) -> bool:
    if items is None:
        return False
    for item in items:
        status = _coerce_item_status(item)
        if status in {"partial", "unsupported", "skipped"} and not _is_recon_heuristic_item(
            kind=_coerce_item_kind(item),
            status=status,
            error=_coerce_item_error(item),
            source_object_path=_coerce_item_source_object_path(item),
            item_name=_coerce_item_name(item),
            discovery_type=_coerce_item_discovery_type(item),
        ):
            return True
    return False


def _coerce_item_error(item: object) -> str | None:
    if isinstance(item, dict):
        item_map = cast(Mapping[str, object], item)
        error = item_map.get("error")
        return error if isinstance(error, str) else None

    error = getattr(item, "error", None)
    return error if isinstance(error, str) else None


def _is_recon_heuristic_item(
    *,
    kind: str | None,
    status: str | None,
    error: str | None,
    source_object_path: str | None = None,
    item_name: str | None = None,
    discovery_type: str | None = None,
) -> bool:
    if kind is None and discovery_type is None and status in {"partial", "unsupported", "skipped"}:
        return True
    if discovery_type == "object_discovery" and status in {"partial", "unsupported", "skipped"}:
        return True
    if kind == "table_scan" and status == "partial":
        return True
    if (
        kind == "table_scan"
        and status == "skipped"
        and error in {"table_scan_disabled_by_option", "table_scan_disabled_by_scan_profile"}
    ):
        return True
    if (
        kind == "graph"
        and status in {"partial", "unsupported"}
        and error
        in {
            "no_graph_previews",
            "no_embedded_image_block",
        }
    ):
        return True
    if kind == "graph_preview" and status in {"partial", "unsupported"} and error == "no_embedded_image_block":
        return True
    if kind == "matrix" and status == "unsupported" and error == "no_matrix_objects":
        return True
    if kind == "function" and status == "unsupported" and error == "no_function_objects":
        return True
    if (
        kind == "matrix"
        and status == "partial"
        and error == "no_extracted_table_rows"
        and _is_tree_matrix_reference_marker(source_object_path, item_name)
        and discovery_type == "object_discovery"
    ):
        return True
    if (
        kind == "worksheet"
        and status in {"unsupported", "partial"}
        and error == "no_extracted_table_rows"
        and _is_tree_worksheet_reference_marker(source_object_path, item_name)
        and discovery_type == "object_discovery"
    ):
        return True
    if kind == "origin_object" and status in {"partial", "unsupported", "skipped"}:
        return True
    if kind == "excel" and status == "unsupported" and error == "no_excel_objects":
        return True
    if (
        kind == "excel"
        and status in {"unsupported", "partial"}
        and error == "no_extracted_table_rows"
        and item_name == "excel_collection"
    ):
        return True
    if kind == "note" and status == "unsupported" and error == "no_note_objects":
        return True
    if (
        kind == "worksheet"
        and status == "unsupported"
        and error == "no_extracted_table_rows"
        and source_object_path == "book_collection"
    ):
        return True
    if kind == "worksheet" and status in {"unsupported", "partial"} and error == "no_worksheet_objects":
        return True
    if (
        kind == "origin_storage_report"
        and error == "no_origin_storage_reports"
        and status
        in {
            "unsupported",
            "partial",
        }
    ):
        return True
    if status == "skipped" and error == "target_exists":
        return True
    if status == "skipped" and error == "excluded_by_text_extraction":
        return True
    return False


def _coerce_item_kind(item: object) -> str | None:
    if isinstance(item, dict):
        item_map = cast(Mapping[str, object], item)
        kind = item_map.get("kind")
        return kind if isinstance(kind, str) else None

    kind = getattr(item, "kind", None)
    return kind if isinstance(kind, str) else None


def _is_tree_matrix_reference_marker(
    source_object_path: str | None,
    item_name: str | None,
) -> bool:
    if source_object_path is not None and _TREE_MATRIX_REFERENCE_MARKER_RE.match(source_object_path):
        return True
    if item_name is not None and _TREE_MATRIX_REFERENCE_MARKER_RE.match(item_name):
        return True
    return False


def _is_tree_worksheet_reference_marker(
    source_object_path: str | None,
    item_name: str | None,
) -> bool:
    if source_object_path is not None and _TREE_WORKSHEET_REFERENCE_MARKER_RE.match(source_object_path):
        return True
    if item_name is not None and _TREE_WORKSHEET_REFERENCE_MARKER_RE.match(item_name):
        return True
    return False


def _coerce_item_name(item: object) -> str | None:
    if isinstance(item, dict):
        item_map = cast(Mapping[str, object], item)
        name = item_map.get("name")
        return name if isinstance(name, str) else None

    name = getattr(item, "name", None)
    return name if isinstance(name, str) else None


def _coerce_item_source_object_path(item: object) -> str | None:
    if isinstance(item, dict):
        item_map = cast(Mapping[str, object], item)
        source_object_path = item_map.get("source_object_path")
        return source_object_path if isinstance(source_object_path, str) else None

    source_object_path = getattr(item, "source_object_path", None)
    return source_object_path if isinstance(source_object_path, str) else None


def _coerce_item_discovery_type(item: object) -> str | None:
    if isinstance(item, dict):
        item_map = cast(Mapping[str, object], item)
        discovery_type = item_map.get("discovery_type")
        return discovery_type if isinstance(discovery_type, str) else None

    discovery_type = getattr(item, "discovery_type", None)
    return discovery_type if isinstance(discovery_type, str) else None


def _has_parser_backed_opju_artifacts(items: Iterable[object]) -> bool:
    return any(_is_parser_backed_opju_artifact(item) for item in items)


def _is_parser_backed_opju_artifact(item: object) -> bool:
    if isinstance(item, dict):
        return _is_dict_item_parser_backed(cast(dict[str, object], item))

    heuristic = getattr(item, "heuristic", None)
    if isinstance(heuristic, bool):
        return not heuristic

    parser_confirmed = getattr(item, "parser_confirmed", None)
    if isinstance(parser_confirmed, bool) and parser_confirmed:
        object_kind = getattr(item, "object_kind", None)
        if isinstance(object_kind, str):
            return object_kind.startswith(_OPJU_PARSER_BACKED_EVIDENCE_KIND_PREFIX)
        return True

    status = getattr(item, "status", None)
    discovery_type = getattr(item, "discovery_type", None)
    if status in {"extracted", "partial", "skipped"} and discovery_type != "carved":
        return True
    return False


def _is_dict_item_parser_backed(item: Mapping[str, object]) -> bool:
    heuristic = item.get("heuristic")
    if isinstance(heuristic, bool):
        return not heuristic

    parser_confirmed = item.get("parser_confirmed")
    if isinstance(parser_confirmed, bool):
        return parser_confirmed

    status = item.get("status")
    discovery_type = item.get("discovery_type")
    if status in {"extracted", "partial", "skipped"} and discovery_type != "carved":
        return True
    return False


_OPJ_WARNING_CODE_MAP = {
    "No worksheet data emitted to book exports.": "no-worksheet-data",
    "No matrix data emitted to matrix exports.": "no-matrix-data",
    "No excel data emitted to excel exports.": "no-excel-data",
    "No note data emitted to note exports.": "no-note-data",
    "No function data emitted to function exports.": "no-function-data",
    "No graph previews emitted to graph exports.": "no-graph-previews",
    "Native parser found no listable items.": "no-listable-items",
    "Unsupported raw region class discovered: text_region": "no-raw-region-text",
    "Unsupported raw region class discovered: unknown_low_entropy": "no-raw-region-unknown-low-entropy",
    "No raw byte ranges met minimum size threshold.": "no-raw-byte-ranges",
    "No raw blocks met export criteria.": "no-raw-blocks",
    "No text regions met minimum size threshold.": "no-text-regions",
    "No text regions met export criteria.": "no-text-regions",
    "No text regions met extraction criteria.": "no-text-regions",
}

_STRICT_OPJ_ALLOWED_WARNING_CODES = {
    "no-worksheet-data",
    "no-matrix-data",
    "no-excel-data",
    "no-note-data",
    "no-function-data",
    "no-graph-previews",
    "no-listable-items",
    "no-raw-region-text",
    "no-raw-region-unknown-low-entropy",
    "no-raw-byte-ranges",
    "no-raw-blocks",
    "no-text-regions",
}


def _is_full_supported_opj(
    *,
    parser_status: str,
    status: str,
    warnings: list[str] | None = None,
    warning_codes: list[str] | None = None,
    items: Iterable[object] | None = None,
) -> bool:
    """Return true when opj output is in the strict full-support profile.

    The current project definition for strict `.opj` support requires:
    - Parser contract is active (`ok` or `empty`).
    - Command status is not a hard failure (`ok` or `empty`).
    - Remaining warnings are in the documented allowlist.

    This predicate intentionally blocks unknown warning families from turning into
    implicit "supported" claims.
    """
    if parser_status not in {"ok", "empty"}:
        return False
    if status not in {"ok", "empty"}:
        return False
    if items is not None:
        for item in items:
            if not _is_parser_backed_item(item):
                return False
    if _has_opj_partial_outputs(items):
        return False
    if warning_codes:
        if not all(code in _STRICT_OPJ_ALLOWED_WARNING_CODES for code in warning_codes):
            return False
    if not warnings:
        return True
    for msg in warnings:
        code = _OPJ_WARNING_CODE_MAP.get(msg)
        if code is None or code not in _STRICT_OPJ_ALLOWED_WARNING_CODES:
            return False
    return True


def _has_origin_family_mismatch(detection: DetectedFile) -> bool:
    return detection.magic_type in SUPPORTED_TYPES and detection.magic_type != detection.detected_type
