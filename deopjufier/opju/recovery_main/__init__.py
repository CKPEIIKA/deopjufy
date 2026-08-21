"""Recovery entry points for OPJU-derived tables."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from deopjufier.opj.records import OpjColumnMetadata, OpjWorksheetMetadata
from deopjufier.opju.common import MAGIC_OPJU, OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW
from deopjufier.opju.recovery_helpers_tokens import *
from deopjufier.opju.recovery_helpers_windows import *
from deopjufier.opju.tables import OpjuColumnTable, parse_opju_column_tables
from deopjufier.opju.tagged import (
    OpjuDescriptorTable,
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
)

_WORKSHEET_WINDOW_NAME_TOKEN_RX = re.compile(r"[A-Za-z0-9_./@-]+")


def _descriptor_tables(data: bytes, *, max_tables: int = 200) -> tuple[OpjuDescriptorTable, ...]:
    descriptors = iter_opju_column_descriptors(data)
    metadata = iter_opju_column_metadata(data, descriptors)
    return group_opju_column_descriptors(descriptors, metadata)[:max_tables]


def descriptor_table_metadata(table: OpjuDescriptorTable) -> OpjWorksheetMetadata:
    sheet_long_names = {
        column.metadata.sheet_long_name
        for column in table.columns
        if column.metadata is not None and column.metadata.sheet_long_name
    }
    column_units = {column.units for column in table.columns if column.units}
    unresolved_fields = []
    for field_name, values in (
        ("column_designations", [column.designation for column in table.columns]),
        ("column_long_names", [column.long_name for column in table.columns]),
        ("column_units", [column.units for column in table.columns]),
    ):
        if any(value is None for value in values):
            unresolved_fields.append(field_name)
    unresolved_fields.append("column_formulas")
    if len(sheet_long_names) != 1:
        unresolved_fields.append("sheet_long_name")
    return OpjWorksheetMetadata(
        name=table.name,
        long_name=next(iter(sheet_long_names)) if len(sheet_long_names) == 1 else None,
        formulas=[column.formula for column in table.columns if column.formula],
        units=next(iter(column_units)) if len(column_units) == 1 else None,
        column_labels=[column.display_name for column in table.columns],
        column_types=[column.value_type for column in table.columns],
        columns=[
            OpjColumnMetadata(
                name=column.display_name,
                sheet_index=table.sheet_index,
                designation=column.designation,
                long_name=column.long_name,
                units=column.units,
                value_type=column.value_type,
                comment=column.metadata.comment if column.metadata is not None else None,
                formula=column.formula,
            )
            for column in table.columns
        ],
        metadata_status="available_column_metadata_decoded",
        unresolved_fields=unresolved_fields,
    )


def recover_matrix_rows_from_opju(
    data: bytes,
    *,
    matrix_names: Iterable[str] | None = None,
    path: Path | None = None,
    max_tables: int = 200,
    include_family_binary: bool = True,
) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
    """Recover OPJU matrix rows from strict family tables.

    Returns rows and inferred dimensions by matrix name for parser-backed matrix
    evidence.
    """
    if not data.startswith(MAGIC_OPJU):
        return {}, {}, set()

    parsed_records = _parse_opju_records(
        data,
        path=path,
        max_reports=8,
        max_input_items=10,
        max_tables=max_tables,
        max_rows=256,
        include_family_binary=include_family_binary,
    )

    if not parsed_records.worksheets:
        return {}, {}, set()

    names_filter = {name for name in matrix_names} if matrix_names else None
    rows_by_name: dict[str, list[list[str]]] = {}
    dims_by_name: dict[str, tuple[int, int]] = {}

    supported_names: set[str] = set()
    for table in parsed_records.worksheets:
        if not table.name.startswith("origin_storage_family_"):
            continue
        table_name = table.name
        if not _is_proven_matrix_family_table(table_name, table.rows):
            continue
        if names_filter is not None and names_filter:
            # For now, matrix families are accepted when their parser name is
            # explicitly requested, otherwise all proven family tables are used.
            if table_name not in names_filter:
                continue

        rows_by_name[table_name] = table.rows
        dims_by_name[table_name] = (
            len(table.rows),
            max((len(row) for row in table.rows), default=0),
        )
        supported_names.add(table_name)

    if names_filter is not None and names_filter and not rows_by_name:
        # Fallback: explicit filter is currently narrow; do not force-family
        # emission when there is no supported family evidence.
        return {}, {}, set()

    # If explicit names were not provided and no family rows were produced,
    # keep behavior conservative and return no matrix evidence.
    if names_filter is None and not rows_by_name:
        return {}, {}, set()

    return rows_by_name, dims_by_name, supported_names


def recover_worksheet_metadata_from_opju(
    data: bytes,
    *,
    worksheet_names: Iterable[str] | None = None,
    path: Path | None = None,
    include_descriptor_tables: bool = True,
) -> dict[str, OpjWorksheetMetadata]:
    """Recover lightweight worksheet metadata for parser-anchored OPJU families.

    This surfaces only parser-visible metadata fields from OPJU column tables, so
    the evidence contract remains explicit and bounded.
    """
    if not data.startswith(MAGIC_OPJU):
        return {}

    requested_names = {name for name in worksheet_names} if worksheet_names else None
    rows_by_name, _dims_by_name, _supported_names = recover_worksheet_rows_from_opju(
        data,
        worksheet_names=requested_names or set(),
        path=path,
        include_descriptor_tables=include_descriptor_tables,
    )
    if not rows_by_name:
        return {}

    metadata_by_name: dict[str, OpjWorksheetMetadata] = {}
    if include_descriptor_tables:
        for table in _descriptor_tables(data, max_tables=300):
            if requested_names is not None and requested_names and table.name not in requested_names:
                continue
            metadata_by_name[table.name] = descriptor_table_metadata(table)
    for table in parse_opju_column_tables(
        data,
        include_decoded=True,
        include_family_binary=True,
        max_tables=300,
        max_rows=256,
    ):
        table_name = table.name
        if table_name.startswith("origin_storage_family_"):
            continue
        if requested_names is not None and requested_names and table_name not in requested_names:
            continue
        if table.label is None or table_name not in rows_by_name:
            continue

        metadata_by_name.setdefault(
            table_name,
            OpjWorksheetMetadata(
                name=table_name,
                label=table.label,
                long_name=table.label,
            ),
        )

    return metadata_by_name


def _nearest_window_distance(
    table: OpjuColumnTable,
    worksheet_windows: Iterable[tuple[str, int, int]],
    *,
    target_name: str,
) -> int | None:
    if table.length <= 0:
        return None

    table_start = table.offset
    table_end = table.offset + table.length
    best_distance: int | None = None

    for name, window_start, window_end in worksheet_windows:
        if name != target_name or window_end <= window_start:
            continue
        if table_end <= window_start:
            distance = window_start - table_end
        elif window_end <= table_start:
            distance = table_start - window_end
        else:
            distance = 0
        if best_distance is None or distance < best_distance:
            best_distance = distance

    return best_distance


def _pick_assigned_sheet_root_fallback(
    table: OpjuColumnTable,
    *,
    worksheet_windows: Iterable[tuple[str, int, int]] | None,
    target_name: str,
    explicit_supported_names: set[str] | None,
    assigned_names: set[str],
) -> str | None:
    if not worksheet_windows:
        return None

    if "/" not in target_name:
        return None

    target_sheet = _worksheet_name_sheet_token(target_name)
    if not target_sheet.startswith("sheet"):
        return None

    if explicit_supported_names is None or target_name not in explicit_supported_names:
        return None

    parent_name = _worksheet_root_name(target_name)
    if not parent_name or parent_name not in explicit_supported_names:
        parent_name = None
    if parent_name is None or parent_name in assigned_names:
        return None

    target_distance = _nearest_window_distance(
        table,
        worksheet_windows,
        target_name=target_name,
    )
    parent_distance = _nearest_window_distance(
        table,
        worksheet_windows,
        target_name=parent_name,
    )
    if target_distance is None or parent_distance is None:
        return None
    if parent_distance <= target_distance + 1:
        return parent_name

    return None


def _pick_unresolved_overlap_root_target(
    table: OpjuColumnTable,
    *,
    overlap_windows: Iterable[tuple[str, int, int]],
    worksheet_names: set[str],
    assigned_names: set[str],
    can_use_boundary_windows: bool,
) -> str | None:
    if not overlap_windows:
        return None

    overlap_candidates = _pick_family_target_names_by_window_overlap(
        table,
        overlap_windows,
        candidate_targets=worksheet_names,
        allow_zero_distance=can_use_boundary_windows,
    )
    if len(overlap_candidates) != 1:
        return None

    overlap_candidate = overlap_candidates[0]
    if "_" not in overlap_candidate:
        return None

    root_candidate = overlap_candidate.split("_", 1)[0]
    if root_candidate == overlap_candidate:
        return None

    if root_candidate == "" or overlap_candidate not in worksheet_names:
        return None

    # Versioned worksheet names such as ``Book1A_A@2`` are concrete parser
    # targets, not workbook-root aliases.  Promoting them to ``Book1A`` loses
    # the provenance encoded by the suffix and creates a false worksheet name.
    if "@" in overlap_candidate:
        if overlap_candidate not in assigned_names:
            return overlap_candidate
        return None

    if root_candidate in worksheet_names:
        if root_candidate in assigned_names:
            return None
        return root_candidate

    if overlap_candidate in worksheet_names and overlap_candidate not in assigned_names:
        return overlap_candidate

    return None


def _iter_short_window_name_markers(
    data: bytes,
    worksheet_windows: Iterable[tuple[str, int, int]],
    *,
    worksheet_name_lookup: dict[str, set[str]],
    max_payload_bytes: int,
    worksheet_window_lengths: dict[str, list[int]] | None = None,
) -> set[str]:
    if not data or not worksheet_windows or not worksheet_name_lookup:
        return set()

    max_offset = len(data)
    marker_names: set[str] = set()
    for window_name, window_start, window_end in worksheet_windows:
        if window_end <= window_start:
            continue

        start = max(0, window_start)
        end = min(max_offset, window_end)
        if end <= start:
            continue

        if worksheet_window_lengths is None:
            candidate_lengths = [end - start]
        else:
            candidate_lengths = [
                window_length
                for window_length in worksheet_window_lengths.get(window_name, ())
                if 0 < window_length <= max_payload_bytes
            ]
            if not candidate_lengths:
                continue

        for candidate_length in candidate_lengths:
            payload = data[start : min(max_offset, start + candidate_length)]
            if len(payload) > max_payload_bytes:
                continue

            decoded = payload.decode("utf-8", errors="ignore").replace("\x00", " ")
            for raw_token in _WORKSHEET_WINDOW_NAME_TOKEN_RX.findall(decoded):
                normalized = _normalize_worksheet_token(raw_token)
                if not normalized:
                    continue
                for name in worksheet_name_lookup.get(normalized, set()):
                    marker_names.add(name)

    return marker_names


def recover_worksheet_rows_from_opju(
    data: bytes,
    *,
    worksheet_names: Iterable[str] | None = None,
    path: Path | None = None,
    worksheet_objects: Iterable[OriginObject] | None = None,
    max_tables: int = 200,
    include_family_binary: bool = True,
    include_descriptor_tables: bool = True,
) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]], set[str]]:
    """Recover worksheet-like rows and dimensions from OPJU payloads.

    Returns row/dimension maps by worksheet name that can be merged directly into
    extractor tables, plus a set of parser-backed worksheet names.
    """
    if not data.startswith(MAGIC_OPJU):
        return {}, {}, set()

    parsed_records = _parse_opju_records(
        data,
        path=path,
        max_reports=8,
        max_input_items=10,
        include_family_binary=include_family_binary,
        max_tables=max_tables,
    )
    rows_by_name: dict[str, list[list[str]]] = {}
    dims_by_name: dict[str, tuple[int, int]] = {}

    worksheet_name_list: list[str] = list(worksheet_names or [])
    worksheet_name_set = set(worksheet_name_list)
    worksheet_name_lookup = _build_worksheet_name_candidate_lookup(worksheet_name_list)
    function_region_tokens = _iter_worksheet_tokens_from_origin_storage_regions(
        parsed_records,
        data,
    )
    preview_region_tokens = _iter_worksheet_tokens_from_origin_storage_regions(
        parsed_records,
        data,
        region_kinds=(OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,),
    )
    workbook_tokens: set[str] = {
        match.group("token")
        for report in parsed_records.reports
        for match in _WORKSHEET_HINT_WORKBOOK_PREFIX_RX.finditer(report.raw_text or "")
        if match.group("token")
    }
    workbook_tokens.update(token for token in function_region_tokens if "/" not in token)
    supported_names = _infer_parser_backed_worksheet_names(
        workbook_tokens,
        worksheet_name_list,
    )
    report_token_names = {
        name
        for report in parsed_records.reports
        for name in _resolve_worksheet_tokens_to_names(
            _iter_family_worksheet_tokens_from_text(report.raw_text or ""),
            worksheet_name_lookup=worksheet_name_lookup,
        )
    }
    preview_token_names = set[str]()
    for token in preview_region_tokens:
        matched_names = _resolve_worksheet_tokens_to_names(
            {token},
            worksheet_name_lookup=worksheet_name_lookup,
            explicit_supported_names=supported_names,
        )
        if len(matched_names) == 1:
            preview_token_names.update(matched_names)
    report_token_names.update(preview_token_names)
    report_token_names.update(
        _resolve_worksheet_tokens_to_names(
            function_region_tokens,
            worksheet_name_lookup=worksheet_name_lookup,
            explicit_supported_names=supported_names,
        )
    )
    is_locked_parser_fallback = (
        not workbook_tokens
        and not parsed_records.reports
        and not parsed_records.worksheets
        and len(parsed_records.regions) <= 1
    )
    if (
        not workbook_tokens
        and not parsed_records.reports
        and not parsed_records.worksheets
        and len(parsed_records.regions) <= 1
    ):
        supported_names = set(worksheet_name_list)

    worksheet_windows = (
        _discover_worksheet_object_windows(
            path=path,
            worksheet_names=worksheet_name_list,
            worksheet_objects=worksheet_objects,
        )
        if path is not None
        else []
    )
    worksheet_window_lengths = (
        _discover_worksheet_object_lengths(
            path=path,
            worksheet_names=worksheet_name_list,
            worksheet_objects=worksheet_objects,
        )
        if path is not None
        else {}
    )
    short_window_markers = _iter_short_window_name_markers(
        data,
        worksheet_windows,
        worksheet_name_lookup=worksheet_name_lookup,
        max_payload_bytes=_OPJU_EVIDENCELESS_WORKSHEET_WINDOW_MAX_BYTES,
        worksheet_window_lengths=worksheet_window_lengths,
    )
    # Short-window markers are heuristic name hints only. They may guide bounded
    # window matching below, but do not establish parser-backed worksheet support
    # or permit family-wide expansion.

    explicit_supported_names = set(supported_names)
    explicit_supported_names.update(report_token_names)
    exact_report_supported_names = set(report_token_names)

    can_use_boundary_windows = not bool(supported_names)

    # Keep recovery names in parser-backed sheet namespace so extractor outputs
    # align with parser-discovered object names.
    family_tables: list[tuple[str, OpjuColumnTable]] = []
    bound_family_names: set[str] = set()
    for table_record, table in zip(
        parsed_records.worksheet_records,
        parsed_records.worksheets,
        strict=False,
    ):
        table_rows = _coerce_table_rows(table)
        if not table_rows:
            continue
        rows_by_name[table_record.name] = table_rows
        dims_by_name[table_record.name] = (
            len(table_rows),
            max((len(row) for row in table_rows), default=0),
        )
        if table.name.startswith("origin_storage_family_"):
            family_tables.append((table.name, table))
            bound_family_names.add(table.name)

    if not family_tables:
        family_tables = [
            (table.name, table)
            for table in parse_opju_column_tables(
                data,
                include_decoded=True,
                include_family_binary=True,
                max_tables=max_tables,
                max_rows=256,
            )
            if table.name.startswith("origin_storage_family_")
        ]
        bound_family_names = {name for name, _ in family_tables}

    family_tables = [
        (name, table)
        for name, table in family_tables
        if not (
            any(cell == "<OriginStorage/>" for row in table.rows for cell in row)
            and any(
                other.name != table.name
                and other.label == table.label
                and abs(other.offset - table.offset) <= 1
                and not any(cell == "<OriginStorage/>" for row in other.rows for cell in row)
                for _, other in family_tables
            )
        )
    ]
    bound_family_names.intersection_update(name for name, _ in family_tables)
    overlap_windows = _filter_overlap_candidate_worksheet_windows(
        worksheet_windows,
        worksheet_names=worksheet_name_list,
    )
    assigned_names: set[str] = set()
    for _, table in family_tables:
        table_rows = _coerce_table_rows(table)
        if not table_rows:
            continue

        if table.name not in rows_by_name:
            rows_by_name[table.name] = table_rows
            dims_by_name[table.name] = (
                len(table_rows),
                max((len(row) for row in table_rows), default=0),
            )
        if table.name not in bound_family_names:
            continue

        table_tokens = _iter_family_worksheet_tokens_from_payload(
            data,
            start=table.offset,
            length=table.length,
        )
        target_names = _match_family_table_to_worksheet_names(
            table,
            data=data,
            worksheet_name_lookup=worksheet_name_lookup,
            explicit_supported_names=explicit_supported_names,
            family_worksheet_tokens=table_tokens,
            worksheet_windows=worksheet_windows,
        )
        if (
            len(target_names) == 1
            and table_tokens
            and set(table_tokens) == {"sheet1"}
            and "/" in target_names[0]
            and _worksheet_root_name(target_names[0]) not in exact_report_supported_names
        ):
            unresolved_root = _pick_unresolved_overlap_root_target(
                table,
                overlap_windows=overlap_windows,
                worksheet_names=worksheet_name_set,
                assigned_names=assigned_names,
                can_use_boundary_windows=True,
            )
            if unresolved_root:
                target_names = [unresolved_root]
        if (
            len(target_names) == 1
            and table_tokens
            and set(table_tokens) == {"sheet1"}
            and "/" in target_names[0]
            and _worksheet_root_name(target_names[0]) in exact_report_supported_names
        ):
            target_name_root = _worksheet_root_name(target_names[0])
            unresolved_root = _pick_unresolved_overlap_root_target(
                table,
                overlap_windows=overlap_windows,
                worksheet_names=worksheet_name_set,
                assigned_names=assigned_names,
                can_use_boundary_windows=True,
            )
            if (
                unresolved_root is not None
                and unresolved_root != target_name_root
                and unresolved_root not in exact_report_supported_names
            ):
                target_names = [unresolved_root]

        family_target_candidates = set(target_names)
        overlap_allow_zero_distance = not exact_report_supported_names or (len(exact_report_supported_names) <= 3)

        if not target_names and not table_tokens:
            overlap_only_targets = _pick_family_target_names_by_window_overlap(
                table,
                overlap_windows,
                candidate_targets=set(worksheet_name_list),
                allow_zero_distance=False,
            )
            if len(overlap_only_targets) == 1:
                target_names = overlap_only_targets

        family_target_has_mixed_sheets = (
            len({_worksheet_name_sheet_token(name) for name in target_names if _worksheet_name_sheet_token(name)}) > 1
        )
        if len(target_names) > 1 and not family_target_has_mixed_sheets:
            target_names = _pick_family_target_names_by_window_overlap(
                table,
                worksheet_windows,
                candidate_targets=set(target_names),
                allow_zero_distance=overlap_allow_zero_distance,
            )
        table_has_rich_payload = (
            max(
                (len(row) for row in table_rows),
                default=0,
            )
            > 1
            and len(table_rows) > 1
        )
        allow_fallback = (
            not exact_report_supported_names or len(exact_report_supported_names) <= 2 or table_has_rich_payload
        )
        fallback_targets: set[str] | None = set(explicit_supported_names) if explicit_supported_names else None

        if not target_names and (not table_tokens and allow_fallback):
            target_names = _pick_family_target_names_by_window_overlap(
                table,
                worksheet_windows=worksheet_windows,
                candidate_targets=fallback_targets,
                allow_zero_distance=can_use_boundary_windows,
            )
        if not target_names and table_tokens and allow_fallback:
            sheet_candidates = _sheet_token_candidates(
                table_tokens,
                worksheet_name_lookup=worksheet_name_lookup,
            )
            if sheet_candidates:
                if worksheet_windows:
                    target_names = _pick_family_target_names_by_window_overlap(
                        table,
                        worksheet_windows=worksheet_windows,
                        candidate_targets=sheet_candidates,
                        allow_zero_distance=True,
                    )
                if not target_names:
                    target_names = [name for name in sorted(sheet_candidates) if name in worksheet_name_set]
        if not target_names and table_tokens:
            unresolved_root = _pick_unresolved_overlap_root_target(
                table,
                overlap_windows=overlap_windows,
                worksheet_names=worksheet_name_set,
                assigned_names=assigned_names,
                can_use_boundary_windows=True,
            )
            if unresolved_root:
                target_names = [unresolved_root]
        if (
            not target_names
            and allow_fallback
            and worksheet_windows
            and not exact_report_supported_names
            and not explicit_supported_names
        ):
            target_names = _pick_family_target_names_by_window_overlap(
                table,
                worksheet_windows=worksheet_windows,
                candidate_targets=set(worksheet_name_list),
                allow_zero_distance=can_use_boundary_windows,
            )
        if not target_names and allow_fallback:
            target_pool = list(fallback_targets or worksheet_name_list)
            target_names = _pick_family_target_names(
                target_pool,
                supported_names,
                # Map one additional parser-backed worksheet hint on OPJU fixtures
                # that expose repeated worksheet-window family hints.
                max_targets=min(_OPJU_MAX_FAMILY_TARGETS, len(worksheet_name_list)),
            )
        if not target_names:
            continue

        if exact_report_supported_names:
            matching_targets = {name for name in target_names if name in exact_report_supported_names}
            if matching_targets:
                target_names = _expand_single_char_sheet_targets(
                    matching_targets,
                    explicit_supported_names=explicit_supported_names,
                )
            elif len(target_names) == 1:
                # Preserve a single, unambiguous non-explicit target when
                # explicit parser-backed hints are present but do not cover it.
                # This avoids broad fanout while still recovering concrete
                # evidence for narrow matches.
                supported_names.update(target_names)
        if len(target_names) == 1 and family_target_candidates:
            selected_target = next(iter(sorted(target_names)))
            selected_sheet_token = _worksheet_name_sheet_token(selected_target)
            if exact_report_supported_names:
                if selected_target in exact_report_supported_names and _is_single_alpha_sheet_token(
                    selected_sheet_token
                ):
                    target_names = _expand_single_char_sheet_targets_from_selection(
                        family_target_candidates,
                        selected_target=selected_target,
                    )
                elif (
                    selected_sheet_token
                    and len(selected_sheet_token) == 2
                    and selected_target in exact_report_supported_names
                ):
                    expansion_candidates = {
                        name
                        for name in family_target_candidates
                        if _worksheet_name_prefix(name) == _worksheet_name_prefix(selected_target)
                        and len(_worksheet_name_sheet_token(name)) == 2
                        and _worksheet_name_sheet_token(name).isalpha()
                    }
                    target_names = _expand_adjacent_alpha2_sheet_targets_from_selection(
                        expansion_candidates,
                        selected_target=selected_target,
                    )
                    target_names = target_names | _expand_adjacent_alpha1_sheet_targets_from_selection(
                        expansion_candidates,
                        selected_target=selected_target,
                    )
            else:
                if _is_single_alpha_sheet_token(selected_sheet_token):
                    target_names = _expand_adjacent_alpha1_sheet_targets_from_selection(
                        family_target_candidates,
                        selected_target=selected_target,
                    )
                elif selected_sheet_token and len(selected_sheet_token) == 2:
                    expansion_candidates = {
                        name
                        for name in worksheet_name_set
                        if _worksheet_name_prefix(name) == _worksheet_name_prefix(selected_target)
                        and len(_worksheet_name_sheet_token(name)) == 2
                        and _worksheet_name_sheet_token(name).isalpha()
                    }
                    target_names = _expand_adjacent_alpha2_sheet_targets_from_selection(
                        expansion_candidates,
                        selected_target=selected_target,
                    )
                    target_names = target_names | _expand_adjacent_alpha1_sheet_targets_from_selection(
                        expansion_candidates,
                        selected_target=selected_target,
                    )

        unbound_targets = [name for name in sorted(target_names) if name not in assigned_names]
        if (
            not unbound_targets
            and allow_fallback
            and worksheet_windows
            and target_names
            and not exact_report_supported_names
            and not explicit_supported_names.difference(short_window_markers)
        ):
            target_roots = {_worksheet_root_name(name) for name in target_names if _worksheet_root_name(name)}
            reuse_targets = {
                name
                for name in worksheet_name_set
                if name not in assigned_names and _worksheet_root_name(name) in target_roots
            }
            if reuse_targets:
                remapped_targets = _pick_family_target_names_by_window_overlap(
                    table,
                    worksheet_windows=worksheet_windows,
                    candidate_targets=reuse_targets,
                    allow_zero_distance=can_use_boundary_windows,
                )
                if len(remapped_targets) == 1:
                    target_names = remapped_targets
                    unbound_targets = remapped_targets
        if not unbound_targets:
            fallback_target = _pick_assigned_sheet_root_fallback(
                table,
                worksheet_windows=worksheet_windows,
                target_name=next(iter(sorted(target_names)), ""),
                explicit_supported_names=explicit_supported_names,
                assigned_names=assigned_names,
            )
            if fallback_target:
                unbound_targets = [fallback_target]
        if not unbound_targets:
            continue

        for target_name in unbound_targets:
            rows_by_name[target_name] = table_rows
            dims_by_name[target_name] = (
                len(table_rows),
                max((len(row) for row in table_rows), default=0),
            )
            if target_name not in supported_names:
                supported_names.add(target_name)
            assigned_names.add(target_name)

    if explicit_supported_names and path is not None and not is_locked_parser_fallback:
        window_lengths = worksheet_window_lengths
        explicit_candidates = set(report_token_names)
        if not explicit_candidates:
            workbook_prefixes = {
                _normalize_worksheet_token(token) for token in workbook_tokens if _normalize_worksheet_token(token)
            }
            explicit_candidates = {
                name
                for name in supported_names
                if name in worksheet_name_list and (name in report_token_names or name not in short_window_markers)
                if _normalize_worksheet_token(_worksheet_name_prefix(name)) in workbook_prefixes
            }
        explicit_candidates.update(
            name
            for name in supported_names
            for length in window_lengths.get(name, ())
            if name in worksheet_name_list
            and (name in report_token_names or name not in short_window_markers)
            and length <= _OPJU_EVIDENCELESS_WORKSHEET_WINDOW_MAX_BYTES
        )
        if (
            exact_report_supported_names
            and len(exact_report_supported_names) == 1
            and worksheet_windows
            and window_lengths
        ):
            explicit_has_bound_payload = any(
                bool(rows_by_name.get(name)) or dims_by_name.get(name) == (0, 0)
                for name in exact_report_supported_names
            )
            explicit_window_keys = {_worksheet_window_coalesce_key(name) for name in exact_report_supported_names}
            short_window_keys: dict[str, tuple[str, int, int]] = {}
            if explicit_has_bound_payload:
                for name, window_start, window_end in worksheet_windows:
                    lengths = window_lengths.get(name)
                    if not lengths:
                        continue
                    if not any(length <= _OPJU_EVIDENCELESS_WORKSHEET_WINDOW_MAX_BYTES for length in lengths):
                        continue
                    key = _worksheet_window_coalesce_key(name)
                    if key in explicit_window_keys:
                        continue
                    if key not in short_window_keys:
                        short_window_keys[key] = (name, window_start, window_end)
            if len(short_window_keys) <= 3:
                explicit_candidates.update(
                    name
                    for name, _, _ in short_window_keys.values()
                    if name in report_token_names or name not in short_window_markers
                )
        coalesced_candidate_count_ok = (
            len(explicit_supported_names) == 1 and len(worksheet_name_list) <= 3 and worksheet_name_list
        )
        all_explicit_rows_appear_non_data = all(
            _are_rows_placeholder_only(rows_by_name.get(name, [])) for name in explicit_supported_names
        )
        if coalesced_candidate_count_ok and all_explicit_rows_appear_non_data:
            explicit_candidates.update(worksheet_name_list)
        for name in sorted(explicit_candidates):
            if name not in window_lengths:
                continue
            for length in window_lengths[name]:
                if (
                    not coalesced_candidate_count_ok
                    and name not in report_token_names
                    and length > _OPJU_EVIDENCELESS_WORKSHEET_WINDOW_MAX_BYTES
                ):
                    continue
                existing_rows = rows_by_name.get(name)
                if name in assigned_names and existing_rows:
                    break
                if existing_rows and not _are_rows_placeholder_only(existing_rows):
                    break
                rows_by_name[name] = []
                dims_by_name[name] = (0, 0)
                supported_names.add(name)
                break

    if parsed_records.worksheets:
        # In worksheet-family parser mode, keep zero-row explicit worksheet
        # candidates only when they are grounded by report or token evidence.
        # This reduces placeholder over-extraction for noisy parser fixtures.
        weak_zero_rows = [
            name for name, dims in dims_by_name.items() if dims == (0, 0) and name not in report_token_names
        ]
        for name in weak_zero_rows:
            rows_by_name.pop(name, None)
            dims_by_name.pop(name, None)
            supported_names.discard(name)

    marker_window_mode = not parsed_records.reports and len(parsed_records.worksheets) <= 1
    if marker_window_mode and path is not None:
        marker_window_seen_keys: set[str] = set()
        marker_window_lengths = worksheet_window_lengths
        marker_window_seen_counts: dict[str, int] = {}
        for name, window_start, window_end in worksheet_windows:
            marker_key = _worksheet_window_coalesce_key(name)
            if marker_key in marker_window_seen_keys:
                continue
            lengths = marker_window_lengths.get(name)
            if not lengths:
                continue
            marker_window_seen_keys.add(marker_key)
            offset_idx = marker_window_seen_counts.get(name, 0)
            marker_window_seen_counts[name] = offset_idx + 1
            if offset_idx >= len(lengths):
                continue
            window_end = window_start + lengths[offset_idx]
            if not _worksheet_window_matches_name_marker(
                data,
                start=window_start,
                end=window_end,
                name=name,
            ):
                continue
            if name in rows_by_name:
                continue
            rows_by_name[name] = []
            dims_by_name[name] = (0, 0)
            supported_names.add(name)

    if include_descriptor_tables:
        for table in _descriptor_tables(data, max_tables=max_tables):
            rows = table.text_rows()
            rows_by_name[table.name] = rows
            dims_by_name[table.name] = (table.row_count, len(table.columns))
            supported_names.add(table.name)

    # Keep parser-backed worksheet mappings tied to family-table evidence, rather
    # than inventing worksheet coverage from heuristic object discovery.
    return rows_by_name, dims_by_name, supported_names
