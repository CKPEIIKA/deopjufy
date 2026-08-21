"""Worksheet coalescing and parser-evidence ranking."""

from __future__ import annotations

from collections.abc import Mapping

from deopjufier.extract.object_tables_helpers._names import (
    _OPJU_PARSER_NAME_HINT_LIMIT,
    _collect_opju_worksheet_family_roots,
    _looks_like_worksheet_object_name,
    _opju_coalesce_worksheet_name_key,
    _parser_backed_name_lookup,
    _resolve_parser_record_name,
    _worksheet_name_without_window_suffixes,
)
from deopjufier.inventory import OriginObject
from deopjufier.opj import OpjWorksheetMetadata


def _coalesce_parser_backed_worksheet_objects(
    objects: list[OriginObject],
    recovered_rows_by_name: dict[str, list[list[str]]],
    recovered_metadata_by_name: Mapping[str, OpjWorksheetMetadata],
    parser_window_name_lookup: set[str],
    parser_backed_worksheet_name_hints: set[str] | None,
    is_opju: bool = False,
) -> list[OriginObject]:
    active_parser_backed_worksheet_name_hints = (
        parser_backed_worksheet_name_hints
        if parser_backed_worksheet_name_hints is not None
        and len(parser_backed_worksheet_name_hints) <= _OPJU_PARSER_NAME_HINT_LIMIT
        else None
    )

    parser_names = _parser_backed_name_lookup(objects, parser_window_name_lookup)
    parser_names.update(recovered_rows_by_name.keys())
    parser_names.update(recovered_metadata_by_name.keys())
    if active_parser_backed_worksheet_name_hints is not None:
        parser_names.update(active_parser_backed_worksheet_name_hints)

    coalesce_family_roots = _collect_opju_worksheet_family_roots(parser_names) if is_opju else set()
    parser_rows_lookup = {name: None for name in recovered_rows_by_name}
    parser_metadata_lookup = {name: None for name in recovered_metadata_by_name}
    parser_lookup = {name: None for name in parser_names}
    worksheet_window_groups: dict[str, set[str]] = {}
    for obj in objects:
        if not _looks_like_worksheet_object_name(obj.name):
            continue
        if "@" not in obj.name:
            continue
        worksheet_window_groups.setdefault(obj.name.split("@", 1)[0], set()).add(obj.name)

    def _select_window_representative(names: list[OriginObject]) -> OriginObject:
        best = names[0]

        def _window_preference(name: str) -> int:
            if "@" not in name:
                return -(10**9)
            suffix = name.rsplit("@", 1)[1]
            if not suffix.isdigit():
                return -(10**9)
            return -int(suffix)

        def _rows_for_name(name: str) -> list[list[str]] | None:
            exact_rows = recovered_rows_by_name.get(name)
            if exact_rows is not None:
                return exact_rows

            canonical_rows_name = _resolve_parser_record_name(
                name,
                parser_rows_lookup,
                prefer_root=True,
            )
            if canonical_rows_name is None:
                return None
            return recovered_rows_by_name.get(canonical_rows_name)

        def _metadata_for_name(name: str) -> OpjWorksheetMetadata | None:
            exact_metadata = recovered_metadata_by_name.get(name)
            if exact_metadata is not None:
                return exact_metadata

            canonical_metadata_name = _resolve_parser_record_name(
                name,
                parser_metadata_lookup,
                prefer_root=True,
            )
            if canonical_metadata_name is None:
                return None
            return recovered_metadata_by_name.get(canonical_metadata_name)

        def _has_parser_hint(name: str) -> bool:
            if active_parser_backed_worksheet_name_hints is None:
                return False
            if name in active_parser_backed_worksheet_name_hints:
                return True
            return (
                _resolve_parser_record_name(
                    name,
                    {n: None for n in active_parser_backed_worksheet_name_hints},
                    prefer_root=True,
                )
                is not None
            )

        def _rank(candidate: OriginObject) -> tuple[int, int, int, int, int, int, int]:
            rows = _rows_for_name(candidate.name)
            if rows is not None:
                rows_weight = 3 if rows else 2
            else:
                rows_weight = 0

            metadata = _metadata_for_name(candidate.name)
            metadata_weight = 2 if metadata is not None else 0

            resolved_hint_name = _resolve_parser_record_name(
                candidate.name,
                parser_lookup,
                prefer_root=True,
            )
            lookup_weight = 1 if resolved_hint_name is not None else 0
            parser_confirmed_weight = 1 if getattr(candidate, "parser_confirmed", False) else 0

            return (
                max(rows_weight, metadata_weight, lookup_weight),
                rows_weight,
                metadata_weight,
                1 if _has_parser_hint(candidate.name) else 0,
                parser_confirmed_weight,
                len(rows or []),
                _window_preference(candidate.name),
            )

        best_rank = _rank(best)
        for candidate in names[1:]:
            candidate_rank = _rank(candidate)
            if candidate_rank > best_rank or (candidate_rank == best_rank and candidate.name < best.name):
                best = candidate
                best_rank = candidate_rank

        return best

    def _worksheet_family_root(name: str) -> str | None:
        base_name = name.split("@", 1)[0]
        base_name = _worksheet_name_without_window_suffixes(base_name)
        if base_name in coalesce_family_roots:
            return base_name
        if "_" not in base_name:
            return None
        first_segment = base_name.split("_", 1)[0]
        if first_segment in coalesce_family_roots and not first_segment[-1].isdigit():
            return first_segment
        return None

    window_representatives: dict[str, str] = {}
    family_representatives: dict[str, str] = {}
    if is_opju:
        objects_by_name: dict[str, list[OriginObject]] = {}
        for obj in sorted(objects, key=lambda item: (item.offset, item.source_object_path, item.name)):
            objects_by_name.setdefault(obj.name, []).append(obj)

        for base_name, names in worksheet_window_groups.items():
            group: list[OriginObject] = []
            for name in names:
                group.extend(objects_by_name.get(name, []))

            if not group:
                continue

            group.sort(key=lambda item: (item.offset, item.source_object_path, item.name))
            window_representatives[base_name] = _select_window_representative(group).name

        for root in sorted(coalesce_family_roots):
            family_members: list[OriginObject] = [
                obj
                for obj in sorted(objects, key=lambda item: (item.offset, item.source_object_path, item.name))
                if _worksheet_family_root(obj.name) == root and "@" in obj.name
            ]
            if not family_members:
                continue
            family_representatives[root] = _select_window_representative(family_members).name

    if is_opju and window_representatives:
        filtered_objects: list[OriginObject] = []
        seen_filtered: set[tuple[str, int, str, int]] = set()
        for obj in sorted(objects, key=lambda item: (item.offset, item.source_object_path, item.name)):
            if "@" in obj.name:
                name_base = obj.name.split("@", 1)[0]
                if name_base in window_representatives and obj.name != window_representatives[name_base]:
                    continue

            key = (obj.name, obj.offset, obj.source_object_path, obj.length)
            if key in seen_filtered:
                continue
            seen_filtered.add(key)
            filtered_objects.append(obj)
        objects = filtered_objects

    def _name_evidence_weight(name: str) -> int:
        rows_name = _resolve_parser_record_name(name, parser_rows_lookup, prefer_root=True)
        if rows_name is not None:
            rows = recovered_rows_by_name[rows_name]
            return 3 if rows else 2

        if _resolve_parser_record_name(name, parser_metadata_lookup, prefer_root=True):
            return 2
        if name in parser_lookup:
            return 1
        return 0

    dedupe_worksheet_name_only = (
        parser_backed_worksheet_name_hints is not None
        and len(parser_backed_worksheet_name_hints) > _OPJU_PARSER_NAME_HINT_LIMIT
    )
    CoalesceSelectKey = tuple[str] | tuple[str, str] | tuple[str, str, int]
    selected: dict[CoalesceSelectKey, OriginObject] = {}
    for obj in sorted(objects, key=lambda item: item.offset):
        if not _looks_like_worksheet_object_name(obj.name):
            continue
        if is_opju:
            if "@" in obj.name:
                name_base = obj.name.split("@", 1)[0]
                family_root = _worksheet_family_root(obj.name)
                if family_root is not None and family_root in family_representatives:
                    canonical_name = family_representatives[family_root]
                else:
                    canonical_name = window_representatives.get(name_base, obj.name)
            else:
                family_root = _worksheet_family_root(obj.name)
                if family_root is not None and family_root in family_representatives:
                    canonical_name = family_representatives[family_root]
                else:
                    canonical_name = _opju_coalesce_worksheet_name_key(
                        obj.name,
                        family_roots=coalesce_family_roots,
                    )
        else:
            canonical_name = _resolve_parser_record_name(
                obj.name,
                parser_lookup,
            )

        if (
            is_opju
            and canonical_name is not None
            and "/" in canonical_name
            and canonical_name not in parser_lookup
            and not any(ch.isdigit() for ch in canonical_name.split("/", 1)[1])
            and not recovered_rows_by_name.get(canonical_name)
        ):
            continue

        if canonical_name is None:
            canonical_name = obj.name
        if is_opju and dedupe_worksheet_name_only:
            key: CoalesceSelectKey = (canonical_name,)
        else:
            key = (
                (
                    canonical_name,
                    obj.source_object_path,
                )
                if is_opju
                else (canonical_name, "", 0)
            )
        existing = selected.get(key)
        existing_weight = _name_evidence_weight(existing.name) if existing else -1
        candidate_weight = _name_evidence_weight(obj.name)
        if (
            existing is None
            or candidate_weight > existing_weight
            or (candidate_weight == existing_weight and not existing.parser_confirmed and obj.parser_confirmed)
        ):
            selected[key] = obj
    return list(selected.values())


__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
