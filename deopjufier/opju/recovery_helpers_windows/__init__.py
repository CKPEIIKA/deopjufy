"""Window and matching helpers for OPJU recovery."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from deopjufier.opju.common import OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION
from deopjufier.opju.recovery_helpers_tokens import *

if TYPE_CHECKING:
    from deopjufier.inventory import OriginObject
    from deopjufier.opju.records import OpjuRecords


def _iter_worksheet_tokens_from_origin_storage_regions(
    parsed_records: OpjuRecords,
    data: bytes,
    *,
    region_kinds: Iterable[str] | None = None,
) -> set[str]:
    """Extract worksheet matcher tokens from selected OriginStorage regions."""
    if not data or not parsed_records.regions:
        return set()

    target_kinds = set(region_kinds or {OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION})
    if not target_kinds:
        return set()

    max_offset = len(data)
    tokens: set[str] = set()
    for region in parsed_records.regions:
        if region.kind not in target_kinds:
            continue
        start = region.offset
        if start < 0:
            continue
        end = region.offset + region.length
        if end <= start or start >= max_offset:
            continue
        payload = data[start : min(end, max_offset)]
        if not payload:
            continue
        tokens.update(
            _iter_family_worksheet_tokens_from_payload(
                payload,
                start=0,
                length=len(payload),
            )
        )

    return tokens


def _is_overlap_binding_candidate_name(name: str) -> bool:
    normalized = _normalize_worksheet_token(name)
    if not normalized:
        return False
    if _is_noisy_worksheet_window_name(normalized):
        return False
    if _looks_like_worksheet_token(normalized):
        return True

    overlap_candidate_root = normalized
    for separator in ("/", "@", "__", "_"):
        overlap_candidate_root = overlap_candidate_root.split(separator, 1)[0]

    if overlap_candidate_root.isalpha():
        return False
    if any(ch in overlap_candidate_root for ch in " .-+"):
        return False

    first_digit_index = -1
    for index, character in enumerate(overlap_candidate_root):
        if character.isdigit():
            first_digit_index = index
            break

    if first_digit_index < 0:
        return False

    root_suffix = overlap_candidate_root[first_digit_index + 1 :]
    if not root_suffix:
        return normalized.startswith("book") and len(normalized) > 4 and normalized[4].isdigit()
    if not root_suffix[0].isalpha():
        return False

    if not any(ch.isalpha() for ch in root_suffix):
        return False

    return True

    # Workbook roots such as `book1` or `book11_a` do not satisfy token
    # tokenized worksheet hints in their raw form, but they are still valid
    # strict-overlap candidates when a family table has explicit window overlap.
    return normalized.startswith("book") and len(normalized) > 4 and normalized[4].isdigit()


def _filter_overlap_candidate_worksheet_windows(
    worksheet_windows: Iterable[tuple[str, int, int]],
    *,
    worksheet_names: Iterable[str] | None = None,
) -> list[tuple[str, int, int]]:
    name_set = {name for name in worksheet_names} if worksheet_names else None
    return [
        (name, start, end)
        for name, start, end in worksheet_windows
        if (name_set is None or name in name_set) and _is_overlap_binding_candidate_name(name)
    ]


def _resolve_sheet_descendant_candidates(
    token: str,
    direct_matches: set[str],
    *,
    explicit_supported_names: set[str] | None = None,
) -> set[str]:
    """Narrow sheet-only tokens to explicit workbook-descendant worksheet names."""
    if not direct_matches:
        return set()
    normalized_token = _normalize_worksheet_token(token)
    if not normalized_token.startswith("sheet"):
        return set()

    if not explicit_supported_names:
        return set()

    supported_roots = {
        _normalize_worksheet_token(_worksheet_root_name(name)) for name in explicit_supported_names if name
    }
    if not supported_roots:
        return set()

    sheet_descendants: set[str] = set()
    for name in direct_matches:
        if "/" not in name:
            continue
        _, sheet_name = name.split("/", 1)
        if not sheet_name:
            continue
        if _normalize_worksheet_token(sheet_name) != normalized_token:
            continue
        if _normalize_worksheet_token(_worksheet_root_name(name)) in supported_roots:
            sheet_descendants.add(name)

    return sheet_descendants


def _resolve_workbook_root_candidates(
    token: str,
    direct_matches: set[str],
    *,
    explicit_supported_names: set[str] | None = None,
) -> set[str]:
    """Resolve workbook-only tokens to an exact workbook root name only.

    Keep this conservative: only exact root names are returned, and only when
    there is no broad multi-name ambiguity.
    """
    if not direct_matches:
        return set()

    normalized_token = _normalize_worksheet_token(token)
    if not normalized_token:
        return set()

    root_matches = {name for name in direct_matches if _normalize_worksheet_token(name) == normalized_token}
    if not root_matches:
        return set()

    if explicit_supported_names is None or len(explicit_supported_names) == 0:
        return root_matches

    explicit_roots = {name for name in root_matches if name in explicit_supported_names}

    if explicit_roots:
        return explicit_roots

    if len(root_matches) == 1:
        return root_matches

    return set()


def _discover_worksheet_object_windows(
    *,
    path: Path,
    worksheet_names: Iterable[str],
    worksheet_objects: Iterable[OriginObject] | None = None,
) -> list[tuple[str, int, int]]:
    from deopjufier.inventory import discover_origin_objects, iter_object_windows

    target_names = {name for name in worksheet_names}
    if not target_names:
        return []

    def _object_offset(item: OriginObject) -> int:
        return getattr(item, "offset", 0)

    provided_objects = sorted(worksheet_objects, key=_object_offset) if worksheet_objects is not None else None

    if provided_objects is None:
        try:
            provided_objects = discover_origin_objects(
                path,
                allowed_kinds=frozenset({"worksheet"}),
                total_limit=None,
            )
        except Exception:
            return []

        provided_objects = [obj for obj in provided_objects if getattr(obj, "object_kind", None) == "worksheet"]

    objects = [
        obj
        for obj in (provided_objects or ())
        if getattr(obj, "object_kind", None) == "worksheet" and not _is_noisy_worksheet_window_name(obj.name)
    ]
    if not objects:
        return []

    windows = iter_object_windows(
        sorted(objects, key=_object_offset),
        path.stat().st_size,
        scope_by_source_prefix=True,
    )
    return [
        (obj.name, start, end)
        for obj, start, end in windows
        if obj.object_kind == "worksheet" and obj.name in target_names and end > start
    ]


def _discover_worksheet_object_lengths(
    *,
    path: Path,
    worksheet_names: Iterable[str],
    worksheet_objects: Iterable[OriginObject] | None = None,
) -> dict[str, list[int]]:
    from deopjufier.inventory import discover_origin_objects

    target_names = {name for name in worksheet_names}
    if not target_names:
        return {}

    provided_objects = (
        sorted(worksheet_objects, key=lambda item: getattr(item, "offset", 0))
        if worksheet_objects is not None
        else None
    )
    if provided_objects is None:
        try:
            provided_objects = discover_origin_objects(
                path,
                allowed_kinds=frozenset({"worksheet"}),
                total_limit=None,
            )
        except Exception:
            return {}
        provided_objects = [obj for obj in provided_objects if getattr(obj, "object_kind", None) == "worksheet"]

    objects = [
        obj
        for obj in (provided_objects or ())
        if getattr(obj, "object_kind", None) == "worksheet" and not _is_noisy_worksheet_window_name(obj.name)
    ]
    if not objects:
        return {}

    lengths_by_name: dict[str, list[int]] = {}
    for obj in objects:
        if obj.name not in target_names:
            continue
        length = getattr(obj, "length", None)
        if not isinstance(length, int) or length < 0:
            continue
        lengths_by_name.setdefault(obj.name, []).append(length)
    return lengths_by_name


def _pick_family_target_names_by_window_overlap(
    table: OpjuColumnTable,
    worksheet_windows: Iterable[tuple[str, int, int]],
    *,
    candidate_targets: set[str] | None = None,
    allow_zero_distance: bool = False,
) -> list[str]:
    if table.length <= 0:
        return []

    candidate_set = set(candidate_targets or [])

    table_start = table.offset
    table_end = table.offset + table.length
    best_overlap = -1
    best_distance = 10**20
    best_start = 10**20
    best_span = 10**20
    best_names: set[str] = set()

    for name, window_start, window_end in worksheet_windows:
        if candidate_set and name not in candidate_set:
            continue
        if window_end <= window_start:
            continue
        window_span = window_end - window_start
        if window_span <= 0:
            continue
        overlap = min(table_end, window_end) - max(table_start, window_start)
        overlap = overlap if overlap > 0 else 0
        if overlap <= 0:
            if not allow_zero_distance:
                continue
            if best_overlap > 0:
                continue
            if window_end <= table_start:
                distance = table_start - window_end
            else:
                distance = window_start - table_end

            if best_overlap < 0 or distance < best_distance:
                best_overlap = 0
                best_distance = distance
                best_span = window_span
                best_start = window_start
                best_names = {name}
            elif distance == best_distance and (
                window_span < best_span or (window_span == best_span and window_start < best_start)
            ):
                best_span = window_span
                best_start = window_start
                best_overlap = 0
                best_names = {name}
            elif distance == best_distance and window_start == best_start:
                best_names.add(name)
            continue

        if overlap > best_overlap:
            best_overlap = overlap
            best_span = window_span
            best_start = window_start
            best_names = {name}
        elif overlap == best_overlap and (
            window_span < best_span or (window_span == best_span and window_start < best_start)
        ):
            best_span = window_span
            best_names = {name}
            best_start = window_start
        elif overlap == best_overlap and window_start == best_start:
            best_names.add(name)

    if not best_names:
        return []

    return sorted(best_names)


def _pick_family_target_names_by_window_overlap_with_tolerance(
    table: OpjuColumnTable,
    worksheet_windows: Iterable[tuple[str, int, int]],
    *,
    candidate_targets: set[str] | None = None,
    allow_zero_distance: bool = False,
    overlap_tolerance: int = 1,
) -> list[str]:
    """Like _pick_family_target_names_by_window_overlap with a small overlap tolerance.

    This is intentionally conservative and only expands beyond the best overlap
    when the alternative candidates are close, so it is suitable only for
    narrow heuristic recovery paths where one-off token evidence is trusted.
    """
    if table.length <= 0 or overlap_tolerance <= 0:
        return _pick_family_target_names_by_window_overlap(
            table,
            worksheet_windows,
            candidate_targets=candidate_targets,
            allow_zero_distance=allow_zero_distance,
        )

    candidate_set = set(candidate_targets or [])
    table_start = table.offset
    table_end = table.offset + table.length

    best_overlap = -1
    overlap_by_name: dict[str, int] = {}
    for name, window_start, window_end in worksheet_windows:
        if candidate_set and name not in candidate_set:
            continue
        if window_end <= window_start:
            continue
        overlap = min(table_end, window_end) - max(table_start, window_start)
        if overlap <= 0:
            if not allow_zero_distance:
                continue
            # For tolerance-based recovery, only tolerate nearby candidates when
            # they already overlap. Zero-distance expansion is handled by
            # strict helper paths.
            continue

        prior = overlap_by_name.get(name)
        if prior is None or overlap > prior:
            overlap_by_name[name] = overlap
        if overlap > best_overlap:
            best_overlap = overlap

    if not overlap_by_name:
        return []

    minimum_overlap = best_overlap - overlap_tolerance
    if minimum_overlap < 0:
        minimum_overlap = 0

    selected = {name for name, overlap in overlap_by_name.items() if overlap >= minimum_overlap}
    return sorted(selected)


def _looks_like_worksheet_token(token: str) -> bool:
    if not token or len(token) < _WORKSHEET_TOKEN_MIN_LENGTH:
        return False
    lowered = token.lower()
    if not (lowered.startswith("book") or lowered.startswith("sheet")):
        return False

    if lowered.startswith("sheet"):
        tail = lowered[5:]
        if not tail:
            return False

        first = tail[0]
        if (
            not first.isdigit()
            and first not in "_/-"
            and not (first.isalpha() and len(tail) > 1 and (tail[1].isdigit() or tail[1] in "_/-"))
        ):
            return False
        if not any(ch.isdigit() or ch in "_/-" for ch in tail):
            return False
        return True

    # Preserve existing conservatism for workbook-like tokens: require an explicit
    # worksheet/book separator marker to avoid broad Book* fanout.
    tail = lowered[4:]
    if not tail:
        return False
    if not any(ch in "_/-" for ch in tail):
        return False

    return True


def _iter_family_worksheet_tokens_from_payload(
    data: bytes,
    *,
    start: int,
    length: int,
) -> set[str]:
    payload = data[start : start + max(0, length)]
    if not payload:
        return set()

    text = payload.decode("utf-8", errors="ignore")
    raw_tokens: set[str] = set()
    for match in _WORKSHEET_TOKEN_RX.finditer(text):
        token = _normalize_worksheet_token(match.group(0))
        if _looks_like_worksheet_token(token):
            raw_tokens.add(token)

    for match in _WORKSHEET_CELL_REF_RX.finditer(text):
        workbook = _normalize_worksheet_token(match.group("workbook"))
        sheet = _normalize_worksheet_token(match.group("sheet"))
        if not workbook or not sheet:
            continue
        raw_tokens.add(f"{workbook}/{sheet}")

    for match in _WORKSHEET_BRACKET_REF_RX.finditer(text):
        workbook = _normalize_worksheet_token(match.group("workbook"))
        if workbook:
            raw_tokens.add(workbook)
        sheet = (
            match.group("sheet_quoted")
            or match.group("sheet_quoted2")
            or match.group("sheet_quoted3")
            or match.group("sheet_quoted4")
            or match.group("sheet_plain")
            or ""
        )
        sheet = _normalize_worksheet_token(sheet)
        if not workbook or not sheet:
            continue
        raw_tokens.add(f"{workbook}/{sheet}")

    return raw_tokens


def _iter_family_worksheet_tokens_from_text(text: str) -> set[str]:
    if not text:
        return set()

    payload = text.encode("utf-8", errors="ignore")
    return _iter_family_worksheet_tokens_from_payload(
        payload,
        start=0,
        length=len(payload),
    )


def _strip_worksheet_suffix(name: str) -> str:
    """Return a stable worksheet family stem by removing explicit window suffixes."""
    stem = name
    if "@" in stem:
        stem = stem.split("@", 1)[0]
    if "__" in stem:
        stem = stem.split("__", 1)[0]
    return stem


def _window_order_key(name: str) -> tuple[bool, int, str]:
    """Deterministic ordering for ambiguous worksheet-name resolution."""
    suffix = name
    if "@" in suffix:
        suffix = suffix.rsplit("@", 1)[-1]
        if suffix.isdigit():
            return (True, int(suffix), name)
    return (True, 10**9, name)


def _pick_preferred_name_for_family_token(names: set[str]) -> str | None:
    """Pick a deterministic family-token match from ambiguous worksheet names."""
    if not names:
        return None
    stems = {_strip_worksheet_suffix(name) for name in names}
    if len(stems) != 1:
        return None

    return min(names, key=_window_order_key)


def _resolve_worksheet_tokens_to_names(
    tokens: Iterable[str],
    *,
    worksheet_name_lookup: dict[str, set[str]],
    explicit_supported_names: set[str] | None = None,
) -> list[str]:
    matched_names: set[str] = set()
    token_match_sets: list[set[str]] = []

    for token in tokens:
        direct = worksheet_name_lookup.get(token, set())
        normalized_token = _normalize_worksheet_token(token)
        token_sheet = _worksheet_name_sheet_token(normalized_token)
        token_is_workbook_root = len(token_sheet) > 2
        if direct and not token.startswith("sheet") and token_is_workbook_root:
            direct = (
                _resolve_workbook_root_candidates(
                    token,
                    direct,
                    explicit_supported_names=explicit_supported_names,
                )
                or direct
            )
        sheet_descendants = _resolve_sheet_descendant_candidates(
            token,
            direct,
            explicit_supported_names=explicit_supported_names,
        )
        if sheet_descendants:
            direct = sheet_descendants
        elif token.startswith("sheet") and explicit_supported_names:
            explicit_sheet_matches = {name for name in direct if name in explicit_supported_names}
            if explicit_sheet_matches:
                direct = explicit_sheet_matches
        token_match_sets.append(set(direct))
        if token.startswith("sheet") and explicit_supported_names:
            explicit_sheet_matches = {name for name in direct if name in explicit_supported_names}
            if len(explicit_sheet_matches) > 1:
                matched_names.update(explicit_sheet_matches)
                continue
        if len(direct) == 1:
            matched_names.update(direct)
            continue

        preferred = _pick_preferred_name_for_family_token(set(direct))
        if preferred is not None:
            matched_names.add(preferred)
            continue

        if not direct or (not any(ch in token for ch in ("_", "/")) and not token.startswith("sheet")):
            continue

        qualifier_matches = {
            name for name in direct if token in {variant for variant in _iter_worksheet_name_variants(name)}
        }
        if len(qualifier_matches) == 1:
            matched_names.update(qualifier_matches)

    if token_match_sets:
        intersection: set[str] | None = None
        for entries in token_match_sets:
            intersection = set(entries) if intersection is None else intersection & entries
            if not intersection:
                break
        if intersection and len(intersection) == 1:
            return sorted(intersection)

    return sorted(matched_names)


def _expand_single_char_sheet_targets(
    candidate_names: set[str],
    explicit_supported_names: set[str] | None = None,
) -> set[str]:
    if not candidate_names:
        return set()

    if not explicit_supported_names:
        return candidate_names

    explicit_targets = {name for name in candidate_names if name in explicit_supported_names}
    if len(explicit_targets) != 1:
        return candidate_names

    seed_name = next(iter(explicit_targets))
    seed_prefix = _worksheet_name_prefix(seed_name)
    seed_sheet = _worksheet_name_sheet_token(seed_name)
    if not seed_prefix or not _is_single_alpha_sheet_token(seed_sheet):
        return candidate_names

    expanded = {
        name
        for name in candidate_names
        if _worksheet_name_prefix(name) == seed_prefix
        and _is_single_alpha_sheet_token(_worksheet_name_sheet_token(name))
    }
    if len(expanded) > _OPJU_SINGLE_CHAR_BATCH_MAX:
        return candidate_names

    return expanded


def _expand_single_char_sheet_targets_from_selection(
    candidate_names: set[str],
    selected_target: str,
) -> set[str]:
    """Expand a one-character sheet batch around a single overlap-selected target."""
    if not candidate_names:
        return set()

    if selected_target not in candidate_names:
        return {selected_target}

    seed_sheet = _worksheet_name_sheet_token(selected_target)
    if not _is_single_alpha_sheet_token(seed_sheet):
        return {selected_target}

    seed_prefix = _worksheet_name_prefix(selected_target)
    if not seed_prefix:
        return {selected_target}

    expanded = {
        name
        for name in candidate_names
        if _worksheet_name_prefix(name) == seed_prefix
        and _is_single_alpha_sheet_token(_worksheet_name_sheet_token(name))
    }

    if not expanded or selected_target not in expanded:
        return {selected_target}

    if len(expanded) > _OPJU_SINGLE_CHAR_BATCH_MAX:
        return {selected_target}

    return expanded


def _match_family_table_to_worksheet_names(
    table: OpjuColumnTable,
    *,
    data: bytes,
    worksheet_name_lookup: dict[str, set[str]],
    family_worksheet_tokens: set[str] | None = None,
    explicit_supported_names: set[str] | None = None,
    worksheet_windows: Iterable[tuple[str, int, int]] | None = None,
    allow_zero_distance: bool = False,
) -> list[str]:
    if not worksheet_name_lookup:
        return []

    tokens = (
        family_worksheet_tokens
        if family_worksheet_tokens is not None
        else _iter_family_worksheet_tokens_from_payload(
            data,
            start=table.offset,
            length=table.length,
        )
    )
    target_names = _resolve_worksheet_tokens_to_names(
        tokens,
        worksheet_name_lookup=worksheet_name_lookup,
        explicit_supported_names=explicit_supported_names,
    )

    if target_names and worksheet_windows is not None and len(target_names) > 1:
        overlap_selected = _pick_family_target_names_by_window_overlap(
            table,
            worksheet_windows,
            candidate_targets=set(target_names),
            allow_zero_distance=allow_zero_distance,
        )
        if overlap_selected:
            if len(target_names) > 1:
                selected_prefix = _worksheet_name_prefix(overlap_selected[0])
                selected_sheet = _worksheet_name_sheet_token(overlap_selected[0])
                same_prefix = {name for name in target_names if _worksheet_name_prefix(name) == selected_prefix}
                alpha2_candidates = {
                    name
                    for name in same_prefix
                    if _worksheet_name_sheet_token(name).isalpha() and len(_worksheet_name_sheet_token(name)) == 2
                }
                same_sheet_len1 = all(
                    _worksheet_name_sheet_token(name).isalpha() and len(_worksheet_name_sheet_token(name)) == 1
                    for name in same_prefix
                )
                same_sheet_len2 = all(
                    _worksheet_name_sheet_token(name).isalpha() and len(_worksheet_name_sheet_token(name)) == 2
                    for name in same_prefix
                )
                selected_sheet_len2 = (
                    selected_sheet is not None and len(selected_sheet) == 2 and selected_sheet.isalpha()
                )
                mixed_sheet_lengths = {len(_worksheet_name_sheet_token(name)) for name in same_prefix}
                if selected_sheet_len2 and len(mixed_sheet_lengths) > 1 and len(overlap_selected) == 1:
                    overlap_with_margin = _pick_family_target_names_by_window_overlap_with_tolerance(
                        table,
                        worksheet_windows,
                        candidate_targets=same_prefix,
                        allow_zero_distance=allow_zero_distance,
                    )
                    if len(overlap_with_margin) == 1 and overlap_with_margin[0] == overlap_selected[0]:
                        selected_start = table.offset
                        selected_end = table.offset + table.length
                        selected_window_starts: list[int] = []
                        for name, window_start, window_end in worksheet_windows:
                            if name != overlap_selected[0]:
                                continue
                            overlap = min(selected_end, window_end) - max(selected_start, window_start)
                            if overlap > 0:
                                selected_window_starts.append(window_start)
                        if selected_window_starts:
                            selected_window_start = selected_window_starts[0]
                            one_char_candidates = {
                                name for name in same_prefix if len(_worksheet_name_sheet_token(name)) == 1
                            }
                            nearest_one_char: list[tuple[int, str]] = []
                            for name in one_char_candidates:
                                candidate_starts: list[int] = []
                                for window_name, window_start, window_end in worksheet_windows:
                                    if window_name != name:
                                        continue
                                    overlap = min(selected_end, window_end) - max(selected_start, window_start)
                                    if overlap <= 0:
                                        continue
                                    candidate_starts.append(window_start)
                                if not candidate_starts:
                                    continue
                                distance = min(
                                    abs(candidate_start - selected_window_start) for candidate_start in candidate_starts
                                )
                                nearest_one_char.append((distance, name))
                            nearest_one_char.sort()
                            keep_one_char = {name for _, name in nearest_one_char[:2]}
                            return sorted(set(overlap_with_margin) | keep_one_char)

                    if len(overlap_with_margin) > 1:
                        return overlap_with_margin

                if same_prefix and selected_sheet and len(overlap_selected) == 1:
                    if same_sheet_len1 and len(same_prefix) <= _OPJU_SINGLE_CHAR_BATCH_MAX:
                        return sorted(same_prefix)
                    if same_sheet_len2:
                        expanded = _expand_adjacent_alpha2_sheet_targets_from_selection(
                            same_prefix,
                            selected_target=overlap_selected[0],
                        )
                        if len(expanded) > 1:
                            return sorted(expanded)
                if selected_sheet and len(selected_sheet) == 1 and alpha2_candidates:
                    selected_window_ranges: list[tuple[int, int]] = [
                        (window_start, window_end)
                        for name, window_start, window_end in worksheet_windows
                        if name == overlap_selected[0] and window_end > window_start
                    ]
                    alpha2_windows = [
                        (name, window_start, window_end)
                        for name, window_start, window_end in worksheet_windows
                        if name in alpha2_candidates and window_end > window_start
                    ]
                    selected_encloses_alpha2 = any(
                        window_start <= alpha2_start and alpha2_end <= window_end
                        for window_start, window_end in selected_window_ranges
                        for _, alpha2_start, alpha2_end in alpha2_windows
                    )
                    if not selected_encloses_alpha2:
                        one_char_candidates = {
                            name for name in same_prefix if len(_worksheet_name_sheet_token(name)) == 1
                        }
                        expanded_one_char = _expand_adjacent_alpha1_sheet_targets_from_selection(
                            one_char_candidates,
                            selected_target=overlap_selected[0],
                        )
                        if len(expanded_one_char) > 1:
                            return sorted(expanded_one_char)

                    alpha2_overlap = _pick_family_target_names_by_window_overlap(
                        table,
                        worksheet_windows,
                        candidate_targets=alpha2_candidates,
                        allow_zero_distance=allow_zero_distance,
                    )
                    if alpha2_overlap:
                        return alpha2_overlap

            return overlap_selected

        worksheet_sheet_tokens = {_worksheet_name_sheet_token(name) for name in target_names if "/" in name}
        all_sheet_descendants = all("/" in name and _worksheet_name_sheet_token(name) for name in target_names)
        same_sheet_token = len(worksheet_sheet_tokens) == 1
        if all_sheet_descendants and same_sheet_token:
            zero_distance_selected = _pick_family_target_names_by_window_overlap(
                table,
                worksheet_windows,
                candidate_targets=set(target_names),
                allow_zero_distance=True,
            )
            if zero_distance_selected:
                return zero_distance_selected

    if worksheet_windows is not None:
        sheet_candidates = _sheet_token_candidates(
            tokens,
            worksheet_name_lookup=worksheet_name_lookup,
        )
        if sheet_candidates:
            overlap_selected = _pick_family_target_names_by_window_overlap(
                table,
                worksheet_windows,
                candidate_targets=sheet_candidates,
                allow_zero_distance=allow_zero_distance,
            )
            if overlap_selected:
                return overlap_selected

    if target_names and len(target_names) > 1:
        # Preserve determinism: broad multi-name candidates are only retained when
        # at least one window-based overlap signal exists.
        # Without overlap, fallback to parser-backed reporting only.
        return []

    return target_names


def _is_proven_matrix_family_table(table_name: str, rows: list[list[str]]) -> bool:
    if not table_name.startswith("origin_storage_family_"):
        return False
    if not rows or len(rows) < 2:
        return False
    max_width = max((len(row) for row in rows), default=0)
    if max_width < 2:
        return False
    if any(len(row) == 0 for row in rows):
        return False
    return True


__all__ = [name for name in globals() if not name.startswith("__")]
