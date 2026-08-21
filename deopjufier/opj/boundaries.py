"""Parser-backed OPJ object boundary recovery."""

from __future__ import annotations

from .columns import split_opj_dataset_name
from .records import (
    OpjDataSection,
    OpjNoteSection,
    OpjObjectBoundary,
    _decode_name,
    _decode_opj_text,
    is_opj_signature,
)
from .stream import OpjStreamError
from .structures.semantics import _walk_semantic_elements, parse_opj_attachments, parse_opj_project_nodes
from .tree import (
    _extract_tree_reference_map,
    _parse_tree_ownership_index,
    _sanitize_opj_name,
    parse_opj_tree_references,
)
from .walker import OpjWalkElement

_OPJ_WINDOW_NAME_OFFSET = 0x02
_OPJ_WINDOW_NAME_SIZE = 25
_OPJ_WINDOW_LABEL_OFFSET = 0xC3
_OPJ_WINDOW_TITLE_OFFSET = 0x69
_OPJ_WINDOW_KIND_SUFFIXES = ("_fit", "_mt", "_xmt", "_xt")
_OPJ_MATRIX_WINDOW_SUFFIXES = ("_mt", "_xmt", "_xt")
_OPJ_EXCEL_EXTENSIONS = (".xlsx", ".xls", ".xlsm", ".xlsb")
_OPJ_GRAPH_NAME_PREFIXES = ("graph", "layer")
_OPJ_FUNCTION_PREFIXES = ("function", "f_")
_OPJ_EXCEL_PREFIXES = ("excel", "e_")
_OPJ_MATRIX_PREFIXES = ("msheet", "mmatrix", "mbook", "matrix", "pdm")
_OPJ_NOTE_PREFIXES = ("note",)
_OPJ_WORKSHEET_PREFIXES = (
    "book",
    "sheet",
    "data",
    "n2n",
    "o2o",
    "spread",
    "mbook",
)


def _normalize_opj_lookup_name(name: str) -> str:
    if not name:
        return ""
    normalized = name.strip().split("@", 1)[0]
    if "\\" in normalized:
        normalized = normalized.rsplit("\\", 1)[-1]
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return _sanitize_opj_name(normalized).lower()


def _iter_opj_name_candidates(name: str) -> list[str]:
    if not name:
        return []

    values = {_normalize_opj_lookup_name(name)}
    if "@" in name:
        values.add(_normalize_opj_lookup_name(name.split("@", 1)[0]))
    if "_" in name:
        head = name.split("_", 1)[0]
        values.add(_normalize_opj_lookup_name(head))

    if name.startswith(("MBook", "MSheet", "PdM")):
        candidate = _normalize_opj_lookup_name(name)
        if candidate.startswith("pdm") and len(candidate) > 3:
            stripped = candidate[3:]
            if stripped:
                values.add(f"m{stripped}")
            if stripped.startswith("sheet"):
                values.add(stripped)

    return [value for value in values if value]


def _extract_matrix_aliases(name: str) -> set[str]:
    aliases: set[str] = set()
    normalized = _normalize_opj_lookup_name(name)
    if not normalized:
        return aliases

    if normalized.startswith("pdm") and len(normalized) > 3:
        stripped = normalized[3:]
        if stripped:
            aliases.add(stripped)
            if not stripped.startswith("m"):
                aliases.add(f"m{stripped}")
            suffix = stripped[1:] if stripped.startswith("m") else stripped
            if suffix.isdigit():
                aliases.add(f"mbook{suffix}")

    if normalized.startswith("msheet"):
        suffix = normalized[6:]
        if suffix.isdigit():
            aliases.add(f"mbook{suffix}")
    if normalized.startswith("mbook"):
        suffix = normalized[5:]
        if suffix.isdigit():
            aliases.add(f"msheet{suffix}")

    if normalized.startswith("m") and normalized[1:].isdigit():
        aliases.add(f"mbook{normalized[1:]}")

    return aliases


def _collect_window_kind_hints(
    data: bytes,
    *,
    data_sections: list[OpjDataSection] | None = None,
    note_sections: list[OpjNoteSection] | None = None,
) -> dict[str, set[str]]:
    worksheet_names: set[str] = set()
    matrix_names: set[str] = set()
    excel_names: set[str] = set()
    function_names: set[str] = set()
    graph_names: set[str] = set()
    note_names: set[str] = set()

    sections = _iter_opj_data_sections(data) if data_sections is None else data_sections
    excel_roots = {
        _normalize_opj_lookup_name(workbook_name)
        for section in sections
        for workbook_name, column_name, sheet_index in [split_opj_dataset_name(section.name)]
        if column_name and sheet_index > 1
    }

    for section in sections:
        candidates = _iter_opj_name_candidates(section.name)
        if not candidates:
            continue
        kind = _classify_opj_data_section_kind(section)
        for candidate in candidates:
            if kind == "worksheet":
                if candidate in excel_roots:
                    excel_names.add(candidate)
                else:
                    worksheet_names.add(candidate)
                continue
            if kind == "matrix":
                matrix_names.add(candidate)
                matrix_names.update(_extract_matrix_aliases(candidate))
                continue
            if kind == "excel":
                excel_names.add(candidate)
                continue
            if kind == "function":
                function_names.add(candidate)
                continue

            if candidate.startswith("function"):
                function_names.add(candidate)

            if kind == "graph":
                graph_names.add(candidate)

    if is_opj_signature(data):
        parsed_notes = _parse_opj_note_sections(data) if note_sections is None else note_sections
        for section in parsed_notes:
            for candidate in _iter_opj_name_candidates(section.name):
                if candidate:
                    note_names.add(candidate)

        for tree_reference in parse_opj_tree_references(data):
            for candidate in _iter_opj_name_candidates(tree_reference.child_name):
                if candidate.startswith("graph") or candidate.startswith("layer"):
                    graph_names.add(candidate)

    return {
        "worksheet": worksheet_names,
        "matrix": matrix_names,
        "excel": excel_names,
        "function": function_names,
        "graph": graph_names,
        "note": note_names,
    }


def _collect_matrix_evidence_names(
    data_sections: list[OpjDataSection],
) -> set[str]:
    matrix_names: set[str] = set()
    for section in data_sections:
        if _classify_opj_data_section_kind(section) != "matrix":
            continue
        candidates = _iter_opj_name_candidates(section.name)
        matrix_names.update(candidates)
        for candidate in candidates:
            matrix_names.update(_extract_matrix_aliases(candidate))

    return matrix_names


def _classify_window_by_context(name: str, hints: dict[str, set[str]]) -> str:
    candidates = _iter_opj_name_candidates(name)
    if any(candidate in hints["matrix"] for candidate in candidates):
        return "matrix"
    if any(candidate in hints["excel"] for candidate in candidates):
        return "excel"
    if any(candidate in hints["worksheet"] for candidate in candidates):
        return "worksheet"
    if any(candidate in hints["function"] for candidate in candidates):
        return "function"
    if any(candidate in hints["graph"] for candidate in candidates):
        return "graph"
    if any(candidate in hints["note"] for candidate in candidates):
        return "note"
    return _classify_opj_object_kind(name)


def _iter_opj_data_sections(data: bytes, *, max_sections: int | None = None) -> list[OpjDataSection]:
    from . import iter_opj_data_sections as exported_iter_opj_data_sections

    return list(exported_iter_opj_data_sections(data, max_sections=max_sections))


def _parse_opj_note_sections(data: bytes) -> list[OpjNoteSection]:
    from . import parse_opj_note_sections as exported_parse_opj_note_sections

    return list(exported_parse_opj_note_sections(data))


def _derive_source_path(name: str) -> str:
    if "\\" in name:
        if "/" in name:
            normalized_name = name.replace("\\", "/")
            parts = tuple(part for part in normalized_name.split("/") if part)
        else:
            return f"meta/{name}"

    elif "/" in name:
        normalized_name = name
        parts = tuple(part for part in normalized_name.split("/") if part)
    else:
        parts = tuple()

    if "\\" in name or "/" in name:
        if len(parts) >= 2:
            return "/".join(parts)
        return f"meta/{parts[0]}" if parts else "object/item"

    prefixed = _split_opj_liborigin_prefixed_name(name)
    if prefixed is not None:
        prefixed_kind, prefixed_name = prefixed
        if not prefixed_name:
            return f"{prefixed_kind}/{_sanitize_opj_name(name)}"
        return f"{prefixed_kind}/{_sanitize_opj_name(prefixed_name)}"

    if name.startswith("__"):
        return f"meta/{_sanitize_opj_name(name)}"
    if "_" in name:
        head, _tail = name.split("_", 1)
        if head:
            return f"{_sanitize_opj_name(head)}/{_sanitize_opj_name(name)}"

    for prefix in ("Book", "Graph", "Sheet", "Page", "Note", "Function", "Excel", "MBook", "MSheet", "Matrix"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return f"{prefix}/{_sanitize_opj_name(name)}"
    if name and name[0].isalpha():
        return f"object/{_sanitize_opj_name(name)}"
    return f"object/item_{_sanitize_opj_name(name)}"


def _infer_parser_source_path(name: str, tree_reference_map: dict[str, list[str]]) -> str:
    sanitized_name = _sanitize_opj_name(name)
    explicit_parent = tree_reference_map.get(sanitized_name)
    if explicit_parent:
        return f"{explicit_parent[0]}/{_sanitize_opj_name(name)}"
    return _derive_source_path(name)


def _infer_parser_source_path_with_tree(
    name: str,
    tree_ownership_map: dict[str, list[str]],
    tree_reference_map: dict[str, list[str]],
    project_paths_by_name: dict[str, list[str]] | None = None,
) -> str:
    for candidate in _iter_opj_name_candidates(name):
        project_paths = (project_paths_by_name or {}).get(candidate, [])
        if len(project_paths) != 1:
            continue
        project_path = project_paths[0]
        if _normalize_opj_lookup_name(name) == candidate:
            return project_path
        return f"{project_path}/{_sanitize_opj_name(name)}"
    explicit_parent = tree_ownership_map.get(_sanitize_opj_name(name))
    if explicit_parent:
        return f"{_sanitize_opj_name(explicit_parent[0])}/{_sanitize_opj_name(name)}"
    return _infer_parser_source_path(name, tree_reference_map)


def _split_opj_liborigin_prefixed_name(name: str) -> tuple[str, str] | None:
    if not name or len(name) < 3 or name[1] != "_":
        return None
    prefix = name[0].lower()
    if prefix == "t":
        return "worksheet", name[2:].strip()
    if prefix == "m":
        return "matrix", name[2:].strip()
    if prefix == "e":
        return "excel", name[2:].strip()
    if prefix == "f":
        return "function", name[2:].strip()
    return None


def _classify_opj_object_kind(name: str) -> str:
    lowered = name.lower()
    if not lowered:
        return "worksheet"

    if "/" in name or "\\" in name:
        return "meta"

    if any(lowered.endswith(suffix) for suffix in _OPJ_WINDOW_KIND_SUFFIXES):
        if "fit" in lowered:
            return "function"
        if any(lowered.endswith(suffix) for suffix in _OPJ_MATRIX_WINDOW_SUFFIXES):
            return "matrix"

    prefixed = _split_opj_liborigin_prefixed_name(name)
    if prefixed is not None:
        return prefixed[0]

    if lowered.startswith(_OPJ_GRAPH_NAME_PREFIXES):
        if lowered.startswith("layer"):
            return "layer"
        return "graph"
    if lowered.startswith(_OPJ_FUNCTION_PREFIXES):
        return "function"
    if lowered.startswith(_OPJ_EXCEL_PREFIXES) or lowered.endswith(_OPJ_EXCEL_EXTENSIONS):
        return "excel"
    if lowered.startswith(_OPJ_MATRIX_PREFIXES):
        return "matrix"
    if len(name) > 1 and name[0] == "m" and name[1].isupper():
        return "matrix"
    if lowered.startswith(_OPJ_NOTE_PREFIXES):
        return "note"

    if lowered.startswith(("msheet", "matrix")):
        return "matrix"
    if "_" in lowered:
        return "worksheet"
    if any(lowered.startswith(prefix) for prefix in _OPJ_WORKSHEET_PREFIXES):
        return "worksheet"
    if lowered.startswith("mbook"):
        return "worksheet"
    return "meta"


def _classify_opj_data_section_kind(section: OpjDataSection) -> str:
    """Classify a dataset from record fields before considering its label.

    OPJ worksheet column names use ``Book_Column``. Column labels such as
    ``Xt``, ``Mt``, and ``Fit`` are not object-type suffixes; treating them as
    such turns ordinary worksheet columns into matrix/function objects. Matrix
    datasets carry the 0x4000 family bit in the secondary signature on the
    audited OPJ versions.
    """

    if "_" in section.name:
        return "worksheet"
    if section.data_type == 0x6081:
        return "function"
    if section.data_type3 & 0x4000:
        return "matrix"
    name_kind = _classify_opj_object_kind(section.name)
    if name_kind in {"function", "matrix"}:
        return name_kind
    return "meta"


def _decode_opj_window_label(payload: bytes) -> str | None:
    if len(payload) <= _OPJ_WINDOW_LABEL_OFFSET:
        return None
    label = _decode_opj_text(payload[_OPJ_WINDOW_LABEL_OFFSET : _OPJ_WINDOW_LABEL_OFFSET + 512]).strip()
    if not label:
        return None
    label = label.split("@${", 1)[0].strip()
    return label or None


def _decode_opj_window_title_mode(payload: bytes) -> str | None:
    if len(payload) <= _OPJ_WINDOW_TITLE_OFFSET:
        return None
    mask = payload[_OPJ_WINDOW_TITLE_OFFSET]
    if mask & 0x01:
        return "label"
    if mask & 0x02:
        return "name"
    return "both"


def _decode_opj_window_name(payload: bytes) -> str | None:
    if len(payload) < _OPJ_WINDOW_NAME_OFFSET + _OPJ_WINDOW_NAME_SIZE:
        return None
    name = _decode_opj_text(payload[_OPJ_WINDOW_NAME_OFFSET : _OPJ_WINDOW_NAME_OFFSET + _OPJ_WINDOW_NAME_SIZE]).strip()
    if not name:
        return None
    decoded = _decode_name(name.encode("utf-8", errors="replace"))
    return decoded


def _parse_window_header(payload: bytes) -> tuple[str, str | None]:
    name = _decode_opj_window_name(payload) or "window"
    label = _decode_opj_window_label(payload)
    return name, label


def _iter_opj_windows(
    data: bytes,
    *,
    elements: list[OpjWalkElement] | None = None,
) -> list[tuple[int, int, str, str | None, str | None]]:
    if not is_opj_signature(data):
        return []

    from . import walker as opj_walker

    windows: list[tuple[int, int, str, str | None, str | None]] = []

    if elements is None:
        parsed_elements: list[OpjWalkElement] = []
        try:
            walk_elements = opj_walker.walk_opj_file(data, tolerant=False)
        except OpjStreamError:
            walk_elements = []
        else:
            parsed_elements = [element for element in walk_elements if element.kind == "window"]

        if not parsed_elements:
            try:
                walk_elements = opj_walker.walk_opj_file(data, tolerant=True)
            except OpjStreamError:
                walk_elements = []
            parsed_elements = [element for element in walk_elements if element.kind == "window"]
    else:
        parsed_elements = [element for element in elements if getattr(element, "kind", None) == "window"]

    for element in parsed_elements:
        header_size = element.metadata.get("header_size")
        if not isinstance(header_size, int) or header_size <= 0:
            windows.append(
                (
                    element.start_offset,
                    element.end_offset,
                    element.name or "window",
                    None,
                    None,
                )
            )
            continue

        header_start = element.start_offset + 5
        header_end = header_start + header_size
        if header_end > len(data):
            windows.append(
                (
                    element.start_offset,
                    element.end_offset,
                    element.name or "window",
                    None,
                    None,
                )
            )
            continue

        header_payload = data[header_start:header_end]
        name = element.name or _decode_opj_window_name(header_payload) or "window"
        label = element.metadata.get("window_label")
        if not isinstance(label, str):
            label = _decode_opj_window_label(header_payload)
        title_mode = element.metadata.get("window_title_mode")
        if not isinstance(title_mode, str):
            title_mode = _decode_opj_window_title_mode(header_payload)
        windows.append((element.start_offset, element.end_offset, name, label, title_mode))

    return windows


def parse_opj_boundaries(
    data: bytes, *, max_sections: int | None = None, disable_heavy_scans: bool = False
) -> list[OpjObjectBoundary]:
    if not is_opj_signature(data):
        return []

    tree_reference_map = _extract_tree_reference_map(data)
    tree_ownership_map = _parse_tree_ownership_index(data)
    tree_references = parse_opj_tree_references(data)
    semantic_elements = _walk_semantic_elements(data)
    project_paths_by_name: dict[str, list[str]] = {}
    for node in parse_opj_project_nodes(data, elements=semantic_elements):
        if node.kind == "folder":
            continue
        normalized_name = _normalize_opj_lookup_name(node.name)
        if normalized_name:
            project_paths_by_name.setdefault(normalized_name, []).append(node.path)
    del disable_heavy_scans

    boundaries: list[OpjObjectBoundary] = []
    data_sections = _iter_opj_data_sections(data, max_sections=max_sections)
    note_sections = _parse_opj_note_sections(data)
    window_kind_hints = _collect_window_kind_hints(
        data,
        data_sections=data_sections,
        note_sections=note_sections,
    )
    matrix_reference_evidence = _collect_matrix_evidence_names(data_sections)

    for section in data_sections:
        boundaries.append(
            OpjObjectBoundary(
                kind=_classify_opj_data_section_kind(section),
                name=section.name,
                source_object_path=_infer_parser_source_path_with_tree(
                    section.name,
                    tree_ownership_map,
                    tree_reference_map,
                    project_paths_by_name,
                ),
                start_offset=section.offset,
                end_offset=section.offset + section.length,
                length=max(0, section.length),
                confidence=0.88,
                parser_rule="opj_data_section",
            )
        )

    for section in note_sections:
        boundaries.append(
            OpjObjectBoundary(
                kind="note",
                name=section.name,
                source_object_path=_infer_parser_source_path_with_tree(
                    section.name,
                    tree_ownership_map,
                    tree_reference_map,
                    project_paths_by_name,
                ),
                start_offset=section.offset,
                end_offset=section.offset + section.length,
                length=max(0, section.length),
                confidence=0.72,
                parser_rule="opj_note_section",
            )
        )

    for start, end, name, label, title_mode in _iter_opj_windows(data, elements=semantic_elements):
        preferred_name = name
        if title_mode == "label" and label:
            preferred_name = label

        windows_source_path = _infer_parser_source_path_with_tree(
            preferred_name,
            tree_ownership_map,
            tree_reference_map,
            project_paths_by_name,
        )
        boundaries.append(
            OpjObjectBoundary(
                kind=_classify_window_by_context(name, window_kind_hints),
                name=name,
                source_object_path=windows_source_path,
                start_offset=start,
                end_offset=end,
                length=max(0, end - start),
                confidence=0.91,
                parser_rule="opj_window",
                label=label,
            )
        )

    seen_matrix_references: set[tuple[str, str]] = set()
    for reference in tree_references:
        if _classify_opj_object_kind(reference.child_name) != "matrix":
            continue
        reference_candidates = _iter_opj_name_candidates(reference.child_name)
        if not reference_candidates:
            continue
        if not matrix_reference_evidence.intersection(reference_candidates):
            continue

        explicit_parents = tree_ownership_map.get(_sanitize_opj_name(reference.child_name))
        if not explicit_parents or len(explicit_parents) != 1:
            continue
        parent_name = explicit_parents[0]
        ref_key = (_sanitize_opj_name(reference.child_name), parent_name)
        if ref_key in seen_matrix_references:
            continue
        seen_matrix_references.add(ref_key)

        source_object_path = _infer_parser_source_path_with_tree(
            reference.child_name,
            tree_ownership_map,
            tree_reference_map,
            project_paths_by_name,
        )
        boundaries.append(
            OpjObjectBoundary(
                kind="matrix",
                name=reference.child_name,
                source_object_path=source_object_path,
                start_offset=reference.start,
                end_offset=reference.end,
                length=max(0, reference.end - reference.start),
                confidence=0.96,
                parser_rule="opj_tree_reference",
            )
        )

    for attachment in parse_opj_attachments(data, elements=semantic_elements):
        if attachment.data_size <= 0:
            continue
        attachment_name = _sanitize_opj_name(attachment.name)
        boundaries.append(
            OpjObjectBoundary(
                kind="attachment",
                name=attachment.name,
                source_object_path=f"attachments/group_{attachment.group}/{attachment_name}",
                start_offset=attachment.data_offset,
                end_offset=attachment.data_offset + attachment.data_size,
                length=attachment.data_size,
                confidence=0.98,
                parser_rule="opj_attachment",
            )
        )

    ordered = sorted(boundaries, key=lambda item: (item.start_offset, item.end_offset, item.kind))
    merged: list[OpjObjectBoundary] = []
    seen: set[tuple[int, int, str, str]] = set()
    for boundary in ordered:
        if boundary.length <= 0 or boundary.end_offset <= boundary.start_offset:
            continue
        key = (
            boundary.start_offset,
            boundary.end_offset,
            boundary.kind,
            boundary.name,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(boundary)
    return merged
