"""Name normalization and parser evidence helpers for tabular extraction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from deopjufier import inventory
from deopjufier.inventory import OriginObject, discover_origin_objects
from deopjufier.opj import (
    OpjMatrixMetadata,
    OpjWorksheetMetadata,
)
from deopjufier.opj.boundaries import _iter_opj_name_candidates

_SAFE_NAME_RX = re.compile(r"[^A-Za-z0-9._-]+")
_OPJU_EXCEL_ATTACHMENT_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlt", ".xltx", ".xltm"}
_OPJU_NON_TABULAR_ATTACHMENT_NAMES = {
    "RT_8to28_currents_3w.pdf",
    "Figure_7.jpg",
    "Excel",
}
_OPJU_PARSER_NAME_HINT_LIMIT = 24
_OPJU_WORKSHEET_HINT_NOISE_RX = re.compile(r"theme.*hint", re.IGNORECASE)


def _looks_like_excel_attachment(name: str) -> bool:
    base_name = re.sub(r"(__\d+)$", "", name)
    return Path(base_name).suffix.lower() in _OPJU_EXCEL_ATTACHMENT_EXTENSIONS


def _looks_like_opju_sheet_excel_attachment(name: str) -> bool:
    base_name = re.sub(r"(__\d+)$", "", name)
    lowered = base_name.lower()
    if not lowered.startswith("__e_"):
        return False
    return Path(base_name).suffix.lower() in _OPJU_EXCEL_ATTACHMENT_EXTENSIONS


def _looks_like_known_non_tabular_attachment(obj: OriginObject) -> bool:
    return obj.object_kind == "excel" and (
        obj.name in _OPJU_NON_TABULAR_ATTACHMENT_NAMES or _looks_like_excel_attachment(obj.name)
    )


def _safe_attachment_filename(name: str) -> str:
    safe_name = _SAFE_NAME_RX.sub("_", Path(name).name).strip("._-")
    return safe_name or "attachment"


def _payload_rows_from_parser_records(
    name: str,
    start_offset: int,
    parser_records: dict[str, list[list[str]]] | None,
    *,
    prefer_root: bool = True,
) -> list[tuple[int, int, int, list[str]]] | None:
    if parser_records is None:
        return None

    rows = None
    canonical_name = _resolve_parser_record_name(
        name,
        parser_records,
        prefer_root=prefer_root,
    )
    if canonical_name is not None:
        rows = parser_records.get(canonical_name)

    if rows is None:
        return None

    return [(1, row_index + 1, start_offset + row_index, row) for row_index, row in enumerate(rows)]


def _resolve_parser_record_name(
    requested_name: str, records: Mapping[str, object], *, prefer_root: bool = True
) -> str | None:
    """
    Return a parser-stable canonical name for a worksheet/matrix object.

    Parser recovery usually emits workbook-level names (e.g. ``Book1``) while
    object discovery can yield split column/window names (e.g. ``Book1_A``).
    This function prefers workbook-level names when they are known.
    """
    requested_at_split = requested_name.split("@", 1)[0]
    if not prefer_root:
        if requested_name in records:
            return requested_name
        return None

    if requested_name in records and "_" not in requested_at_split:
        return requested_name

    if "_" in requested_at_split and "__" not in requested_at_split:
        requested_root = requested_at_split.split("_", 1)[0]
        if requested_root in records:
            return requested_root

    if requested_at_split in records:
        return requested_at_split
    if requested_at_split in records and requested_at_split != requested_name:
        return requested_at_split

    if "_" in requested_name:
        requested_root = requested_name.split("_", 1)[0]
        if requested_root in records:
            return requested_root
    if requested_name in records:
        return requested_name

    candidate = requested_name
    while candidate.endswith("__"):
        candidate = candidate[:-1]
    if "__" in candidate:
        base_name, suffix = candidate.rsplit("__", 1)
        if suffix.isdigit() and base_name in records:
            return base_name
        if base_name in records:
            return base_name

    requested_root = requested_name.split("/", 1)[-1]
    if requested_root.startswith("PdM") and len(requested_root) > 3:
        stripped = requested_root[3:]
        if stripped in records:
            return stripped
        mapped = f"M{stripped}" if not stripped.startswith("M") else stripped
        if mapped in records:
            return mapped
        if m := re.search(r"(\d+)$", stripped):
            alias = f"MBook{m.group(1)}"
            if alias in records:
                return alias

    if requested_root.startswith("MSheet") or (
        requested_root.startswith("M") and not requested_root.startswith("MBook")
    ):
        if m := re.search(r"(\d+)$", requested_root):
            alias = f"MBook{m.group(1)}"
            if alias in records:
                return alias

    return None


def _normalize_opj_worksheet_source_path(source_object_path: str) -> str:
    if "/" not in source_object_path:
        return source_object_path

    root, leaf = source_object_path.split("/", 1)
    if root not in {"Book", "MBook"} or not leaf:
        return source_object_path

    workbook = leaf.split("_", 1)[0]
    if root == "MBook" and not workbook.startswith("M"):
        return source_object_path
    if not workbook:
        return source_object_path
    if root == "Book" and not workbook.startswith("Book"):
        return source_object_path
    return f"{workbook}/{leaf}"


def _is_matrix_like_candidate_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith("msheet")
        or lowered.startswith("mbook")
        or lowered.startswith("matrix")
        or lowered.startswith("pdm")
    )


def _looks_like_worksheet_object_name(name: str) -> bool:
    lowered = name.lower()
    if not lowered:
        return False
    if _OPJU_WORKSHEET_HINT_NOISE_RX.search(name):
        return False
    if lowered.startswith("origin_storage_family_"):
        return False
    if lowered == "_collection":
        return False
    return True


def _should_skip_matrix_like_worksheet_fallback(
    obj: OriginObject,
    *,
    parser_backed_payload: bool,
    rows: list[tuple[int, int, int, list[str]]] | None,
) -> bool:
    if obj.object_kind != "worksheet":
        return False
    if parser_backed_payload:
        return False
    if rows:
        return False

    for candidate in _iter_opj_name_candidates(obj.name):
        if _is_matrix_like_candidate_name(candidate):
            return True

    return False


def _parser_window_lookup(data: bytes, input_path: Path) -> set[str]:
    """Build parser window name lookup for worksheet windows."""
    lookup: set[str] = set()
    for boundary in inventory.parse_opj_boundaries(data, path=input_path):
        if boundary.kind == "worksheet":
            lookup.add(boundary.name)
            if "@" in boundary.name:
                lookup.add(boundary.name.split("@", 1)[0])
            if "_" in boundary.name:
                lookup.add(boundary.name.split("_", 1)[0])
    return lookup


def _parser_backed_name_lookup(matching_objects: list[OriginObject], parser_window_name_lookup: set[str]) -> set[str]:
    """Build canonical parser-backed object name set for worksheet extraction."""
    names: set[str] = set()
    candidate_names = set(parser_window_name_lookup)
    for obj in matching_objects:
        candidate_names.add(obj.name)
    for name in candidate_names:
        names.add(name)
        if "@" in name:
            names.add(name.split("@", 1)[0])
        if "__" in name:
            base_name = name.split("__", 1)[0]
            names.add(base_name)
    return names


def _metadata_dimensions(
    metadata: OpjWorksheetMetadata | OpjMatrixMetadata | None,
) -> tuple[int, int] | None:
    if metadata is None:
        return None
    if isinstance(metadata, OpjMatrixMetadata):
        return metadata.shape
    if metadata.formula_rows is not None:
        first_row, last_row = metadata.formula_rows
        if last_row < first_row:
            return None
        row_count = max(0, last_row - first_row + 1)
    else:
        row_count = 1
    if metadata.column_labels:
        return row_count, len(metadata.column_labels)
    if metadata.formula_rows is not None:
        return row_count, 1
    return None


def _tabular_headers(
    metadata: OpjWorksheetMetadata | OpjMatrixMetadata | None,
    row_width: int,
) -> list[str] | None:
    if row_width <= 0:
        return None
    if metadata is not None and isinstance(metadata, OpjWorksheetMetadata):
        if metadata.column_labels:
            labels = [label for label in metadata.column_labels if label.strip()]
            if labels:
                if len(labels) >= row_width:
                    return labels[:row_width]
                return labels + [f"col_{index}" for index in range(len(labels) + 1, row_width + 1)]
    return [f"col_{index}" for index in range(1, row_width + 1)]


def _normalize_opju_worksheet_source_path(source_object_path: str, obj_name: str) -> str:
    if not source_object_path.startswith("object/"):
        return source_object_path

    tail = source_object_path.split("/", 1)[1]
    suffix = ""
    if "__" in tail:
        base, candidate_suffix = tail.rsplit("__", 1)
        if base and candidate_suffix.isdigit():
            suffix = f"__{candidate_suffix}"

    sanitized_name = _SAFE_NAME_RX.sub("_", obj_name).strip("._-")
    if not sanitized_name:
        sanitized_name = "sheet"
    return f"Book/{sanitized_name}{suffix}"


def _worksheet_name_without_window_suffixes(name: str) -> str:
    """Return worksheet name without parser-specific duplicate/window suffixes."""
    base_name = name
    if "__" in base_name:
        base_candidate, _, tail = base_name.rpartition("__")
        if tail.isdigit():
            base_name = base_candidate
    return base_name.split("@", 1)[0]


def _collect_opju_worksheet_family_roots(names: set[str]) -> set[str]:
    """Collect conservative OPJU family roots used for window coalescing.

    A root is only included when all observed base names share one family root.
    This avoids collapsing distinct worksheet families such as ``N2N_D`` and
    ``N2N_E`` into one output while still enabling dedupe for single-family
    families where only one non-`@` base exists.
    """
    roots: set[str] = set()
    grouped_roots: dict[str, set[str]] = {}
    for name in names:
        stripped = _worksheet_name_without_window_suffixes(name)
        if "_" not in stripped:
            continue
        first_segment = stripped.split("_", 1)[0]
        if first_segment and not first_segment[-1].isdigit():
            grouped_roots.setdefault(first_segment, set()).add(stripped)

    for first_segment, base_names in grouped_roots.items():
        if len(base_names) == 1:
            roots.add(first_segment)

    return roots


def _opju_coalesce_worksheet_name_key(name: str, family_roots: set[str]) -> str:
    """Compute stable OPJU worksheet dedupe key from parser-backed evidence."""
    # Coalesce family fanout candidates (`name@N`) to a single family key when the
    # workbook marker is non-numeric (e.g., `Book1A_*`) while preserving explicit
    # parser-window suffixes (`__N`) and keeping explicit non-`@` identities.
    if "@" in name:
        base_without_window = name.split("@", 1)[0]
        first_segment = base_without_window.split("_", 1)[0]
        if (
            "_" in base_without_window
            and first_segment
            and first_segment in family_roots
            and not first_segment[-1].isdigit()
        ):
            return first_segment
        return name
    return name


def _augment_worksheet_matching_objects_with_hint_candidates(
    matching_objects: list[OriginObject],
    *,
    parser_backed_worksheet_name_hints: set[str] | None,
    input_path: Path,
) -> list[OriginObject]:
    if (
        parser_backed_worksheet_name_hints is not None
        and len(parser_backed_worksheet_name_hints) > _OPJU_PARSER_NAME_HINT_LIMIT
    ):
        parser_backed_worksheet_name_hints = None

    if not parser_backed_worksheet_name_hints:
        return matching_objects

    try:
        discovered_objects = discover_origin_objects(
            input_path,
            allowed_kinds=frozenset({"worksheet"}),
            total_limit=None,
        )
    except Exception:
        return matching_objects

    hint_records = {name: None for name in parser_backed_worksheet_name_hints}
    if not hint_records:
        return matching_objects

    candidates: list[OriginObject] = []
    used_hint_names: set[str] = set()
    for obj in sorted(
        discovered_objects,
        key=lambda item: (item.offset, item.source_object_path, item.name),
    ):
        if obj.object_kind != "worksheet":
            continue
        resolved_hint = _resolve_parser_record_name(
            obj.name,
            hint_records,
            prefer_root=True,
        )
        if resolved_hint is None:
            continue
        if resolved_hint in used_hint_names:
            continue
        candidates.append(obj)
        used_hint_names.add(resolved_hint)

    if not candidates:
        return matching_objects

    seen: set[tuple[str, int, str, int]] = {
        (obj.name, obj.offset, obj.source_object_path, obj.length) for obj in matching_objects
    }
    augmented = list(matching_objects)
    for obj in sorted(
        candidates,
        key=lambda item: (item.offset, item.source_object_path, item.name),
    ):
        key = (obj.name, obj.offset, obj.source_object_path, obj.length)
        if key in seen:
            continue
        augmented.append(obj)
        seen.add(key)
    return augmented


__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
