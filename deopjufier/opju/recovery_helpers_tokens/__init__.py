"""Parser-owned OPJU recovery helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING, cast

from deopjufier.opju.records import OpjuRecords, parse_opju_records
from deopjufier.opju.tables import OpjuColumnTable

_WORKSHEET_HINT_WORKBOOK_PREFIX_RX = re.compile(r"\[(?P<token>[A-Za-z_][A-Za-z0-9_]*)\]")
_WORKSHEET_PREFIX_MIN_LENGTH = 2
_WORKSHEET_TOKEN_RX = re.compile(r"\b(?:book|sheet)[a-z0-9_/-]+\b", re.IGNORECASE)
_WORKSHEET_CELL_REF_RX = re.compile(
    r"cell://\[(?P<workbook>[A-Za-z_][A-Za-z0-9_]*)\](?P<sheet>[A-Za-z0-9_@.-]+)",
    re.IGNORECASE,
)
_WORKSHEET_BRACKET_REF_RX = re.compile(
    (
        r"\[(?P<workbook>[A-Za-z_][A-Za-z0-9_]*)\]"
        r"(?:(?:&quot;"
        r"(?P<sheet_quoted>[^&]+)"
        r"&quot;|"
        r"&apos;"
        r"(?P<sheet_quoted3>[^&]+)"
        r"&apos;|"
        r"\"(?P<sheet_quoted2>[^\"]+)\"|"
        r"'(?P<sheet_quoted4>[^']+)'|"
        r"(?P<sheet_plain>[A-Za-z0-9_@.-]+)"
        r"))!?"
    ),
    re.IGNORECASE,
)
_WORKSHEET_TOKEN_MIN_LENGTH = 5
_OPJU_MAX_FAMILY_TARGETS = 8
_OPJU_EVIDENCELESS_WORKSHEET_WINDOW_MAX_BYTES = 16
_OPJU_SINGLE_CHAR_BATCH_MAX = 3
_OPJU_RECOVERY_RECORDS_CACHE: dict[
    tuple[Path, int, int, int, int, int, int, bool],
    OpjuRecords,
] = {}
_OPJU_RECOVERY_RECORDS_CACHE_LIMIT = 8


def _is_noisy_worksheet_window_name(name: str) -> bool:
    """Return true for worksheet-like names that should not drive overlap matching."""
    if "/" not in name:
        return False
    return name.lower().endswith("/theta")


if TYPE_CHECKING:
    from deopjufier.inventory import OriginObject


def _parse_opju_records(
    data: bytes,
    *,
    path: Path | None,
    max_reports: int,
    max_input_items: int,
    max_tables: int = 16,
    max_rows: int = 256,
    include_family_binary: bool = False,
) -> OpjuRecords:
    try:
        from deopjufier.opju import recovery as recovery_module
    except Exception:
        backend_parser: Callable[..., OpjuRecords] = parse_opju_records
    else:
        patched_parser = getattr(recovery_module, "parse_opju_records", None)
        backend_parser = patched_parser if callable(patched_parser) else parse_opju_records

    cache_key: tuple[Path, int, int, int, int, int, int, bool] | None = None
    if path is not None:
        try:
            path_stats = path.stat()
            cache_key = (
                path,
                path_stats.st_size,
                path_stats.st_mtime_ns,
                max_reports,
                max_input_items,
                max_tables,
                max_rows,
                include_family_binary,
            )
        except OSError:
            cache_key = None

    if cache_key is not None and cache_key in _OPJU_RECOVERY_RECORDS_CACHE:
        return _OPJU_RECOVERY_RECORDS_CACHE[cache_key]

    parse_kwargs: dict[str, object] = {
        "max_reports": max_reports,
        "max_input_items": max_input_items,
    }
    parse_signature = signature(backend_parser)
    parse_params = parse_signature.parameters

    if "path" in parse_params and path is not None:
        parse_kwargs["path"] = path
    if "max_tables" in parse_params:
        parse_kwargs["max_tables"] = max_tables
    if "max_rows" in parse_params:
        parse_kwargs["max_rows"] = max_rows
    if "include_decoded" in parse_params:
        parse_kwargs["include_decoded"] = True
    if "include_family_binary" in parse_params and include_family_binary:
        parse_kwargs["include_family_binary"] = include_family_binary

    parsed = cast(Callable[..., OpjuRecords], backend_parser)(data, **parse_kwargs)

    if cache_key is not None:
        _OPJU_RECOVERY_RECORDS_CACHE[cache_key] = parsed
        if len(_OPJU_RECOVERY_RECORDS_CACHE) > _OPJU_RECOVERY_RECORDS_CACHE_LIMIT:
            _OPJU_RECOVERY_RECORDS_CACHE.pop(next(iter(_OPJU_RECOVERY_RECORDS_CACHE)))

    return parsed


def _iter_workbook_token_variants(token: str) -> set[str]:
    token_body = token.strip("._- ").lower()
    if not token_body:
        return set()

    variants = {token_body}
    token_len = len(token_body)

    for length in range(3, min(token_len, 8) + 1):
        prefix = token_body[:length]
        if _is_workbook_style_prefix(prefix) and not prefix.endswith(("-", "_", "/")) and prefix not in variants:
            variants.add(prefix)

    # Handle compact forms like crossO2O2 -> O2O where a workbook-like token
    # is embedded without delimiter separators.
    for match in re.finditer(r"[a-z]\d[a-z]", token_body):
        variants.add(match.group(0))

    return variants


def _is_workbook_style_prefix(token: str) -> bool:
    if len(token) < 3:
        return False

    for index, char in enumerate(token):
        if char.isalpha():
            if index > 0 and token[index - 1].isdigit():
                return True
        elif char.isdigit():
            if index + 1 < len(token) and token[index + 1].isalpha():
                return True
            if index > 0 and token[index - 1].isalpha() and index < len(token) - 1:
                return True
        elif char not in {"_", "-", "/"}:
            return False

    return False


def _normalise_workbook_token_for_prefixes(token: str, worksheet_prefixes: set[str]) -> set[str]:
    """Normalize token hints to conservative worksheet-like prefixes."""
    if not token or not worksheet_prefixes:
        return set()

    def _matches_prefix(candidate: str, worksheet_prefix: str) -> bool:
        if worksheet_prefix == candidate:
            return True

        if any(candidate.startswith(f"{worksheet_prefix}{sep}") for sep in ("_", "/", "-", ".")):
            return True

        if candidate.startswith(worksheet_prefix):
            next_char = candidate[len(worksheet_prefix) : len(worksheet_prefix) + 1]
            if not next_char:
                return True
            return next_char in {"_", "/", "-", "."}
        return False

    candidate_tokens = _iter_workbook_token_variants(token)
    matched: set[str] = set()
    normalized_prefixes = {prefix: prefix.lower() for prefix in worksheet_prefixes if prefix}

    for candidate in candidate_tokens:
        if len(candidate) < _WORKSHEET_PREFIX_MIN_LENGTH:
            continue
        for worksheet_prefix, prefix_lower in normalized_prefixes.items():
            if _matches_prefix(candidate, prefix_lower):
                matched.add(worksheet_prefix)

    return matched


def _worksheet_name_prefix(name: str) -> str:
    """Return worksheet workbook-like prefix if present, otherwise empty string."""
    base_name = name
    if base_name.startswith("[") and base_name.endswith("]"):
        base_name = base_name[1:-1]

    if "__" in base_name:
        base_name = base_name.split("__", 1)[0]
    if "@" in base_name:
        base_name = base_name.split("@", 1)[0]

    parts = base_name.split("_", 1)
    return parts[0]


def _infer_parser_backed_worksheet_names(workbook_tokens: set[str], worksheet_names: Iterable[str]) -> set[str]:
    """Infer minimal parser-backed worksheet names from OriginStorage report tokens.

    Include every worksheet with a proven worksheet-prefix match, preserving
    deterministic output ordering.
    """
    worksheet_prefixes = {_worksheet_name_prefix(name) for name in worksheet_names}
    if not worksheet_prefixes:
        return set()

    normalized_prefixes: set[str] = set()
    for token in workbook_tokens:
        normalized_prefixes.update(_normalise_workbook_token_for_prefixes(token, worksheet_prefixes))

    matched_names: set[str] = set()
    for name in sorted(worksheet_names):
        prefix = _worksheet_name_prefix(name)
        if prefix in normalized_prefixes:
            matched_names.add(name)

    return matched_names


def _family_target_name_pool(
    worksheet_names: Iterable[str],
    parser_backed_names: Iterable[str],
) -> dict[str, list[str]]:
    names_by_prefix: dict[str, list[str]] = {}
    parser_names = set(parser_backed_names)
    for name in worksheet_names:
        if name not in parser_names:
            continue
        prefix = _worksheet_name_prefix(name)
        if not prefix:
            continue
        names_by_prefix.setdefault(prefix, [])
        if name not in names_by_prefix[prefix]:
            names_by_prefix[prefix].append(name)

    return names_by_prefix


def _pick_family_target_names(
    worksheet_names: Iterable[str],
    parser_backed_names: set[str],
    *,
    max_targets: int = 3,
) -> list[str]:
    if max_targets <= 0:
        return []

    names_by_prefix = _family_target_name_pool(worksheet_names, parser_backed_names)
    if not names_by_prefix:
        return []

    ordered_prefixes = sorted(
        ((prefix, sorted(names)) for prefix, names in names_by_prefix.items()),
        key=lambda item: (len(item[1]), item[0]),
        reverse=True,
    )
    prefix_names = ordered_prefixes[0][1]
    # Prefer explicit worksheet roots for initial deterministic family correlation.
    roots = [name for name in prefix_names if "@" not in name]
    candidates = roots if roots else prefix_names
    return candidates[:max_targets]


def _coerce_table_rows(table: OpjuColumnTable) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        if not row:
            continue
        rows.append(row)
    return rows


def _are_rows_placeholder_only(rows: list[list[str]]) -> bool:
    """Return True for parser-recovered rows that are metadata placeholders."""
    cleaned = [[str(value).strip() for value in row if str(value).strip()] for row in rows]
    cleaned = [row for row in cleaned if row]
    if not cleaned:
        return True

    if all(len(row) == 1 for row in cleaned):
        unique_values = {row[0] for row in cleaned}
        return len(unique_values) <= 1

    return False


def _normalize_worksheet_token(token: str) -> str:
    normalized = token.strip(" \"'\t\r\n\x00").strip("._-").lower()
    normalized = re.sub(r"\s+", "_", normalized)
    return normalized.strip("._-")


def _iter_worksheet_name_variants(name: str) -> set[str]:
    """Return conservative worksheet name variants used for parser-evidenced matching."""
    base_name = name
    if base_name.startswith("[") and base_name.endswith("]"):
        base_name = base_name[1:-1]

    variants: set[str] = {base_name}
    if "@" in base_name:
        variants.add(base_name.split("@", 1)[0])
    if "__" in base_name:
        variants.add(base_name.split("__", 1)[0])
    if "/" in base_name:
        head, tail = base_name.split("/", 1)
        variants.add(head)
        variants.add(tail)
        variants.add(tail.split("@", 1)[0])
        if "__" in tail:
            variants.add(tail.split("__", 1)[0])
            variants.add(tail.split("__", 1)[0].split("@", 1)[0])

    normalized_variants: set[str] = set()
    for variant in variants:
        normalized = _normalize_worksheet_token(variant)
        if normalized:
            normalized_variants.add(normalized)
    return normalized_variants


def _sheet_token_candidates(
    worksheet_tokens: set[str],
    worksheet_name_lookup: dict[str, set[str]],
) -> set[str]:
    """Resolve sheet-only tokens to conservative worksheet candidates."""
    sheet_candidates: set[str] = set()
    for token in worksheet_tokens:
        normalized = _normalize_worksheet_token(token)
        if not normalized or "/" in normalized or not normalized.startswith("sheet") or normalized == "sheet":
            continue
        if len(normalized) < len("sheet") + 1:
            continue
        for name in worksheet_name_lookup.get(normalized, set()):
            if not _is_noisy_worksheet_window_name(name):
                sheet_candidates.add(name)
    return sheet_candidates


def _worksheet_window_coalesce_key(name: str) -> str:
    """Return the OPJU worksheet coalescing key used by worksheet-object recovery."""
    base_name = name
    if "@" not in base_name:
        return base_name

    base_without_window = base_name.split("@", 1)[0]
    first_segment = base_without_window.split("_", 1)[0]
    if first_segment and not first_segment[-1].isdigit():
        return first_segment
    return base_without_window


def _worksheet_name_sheet_token(name: str) -> str:
    """Return a conservative worksheet sheet token for sibling-style matching."""
    base_name = name
    if not base_name:
        return ""

    if "/" in base_name:
        base_name = base_name.rsplit("/", 1)[-1]
    elif "_" in base_name:
        base_name = base_name.rsplit("_", 1)[-1]

    if "@" in base_name:
        base_name = base_name.split("@", 1)[0]
    if "__" in base_name:
        base_name = base_name.split("__", 1)[0]

    return _normalize_worksheet_token(base_name)


def _is_single_alpha_sheet_token(token: str) -> bool:
    return len(token) == 1 and token.isalpha()


def _expand_adjacent_alpha2_sheet_targets_from_selection(
    candidate_names: set[str],
    selected_target: str,
) -> set[str]:
    """Expand two-character alpha sheet tokens to nearby siblings.

    This is intentionally conservative: it only adds up to two adjacent siblings
    when the suffix token family is alpha/binary and no unrelated family is
    involved.
    """
    if not candidate_names or selected_target not in candidate_names:
        return {selected_target}

    selected_sheet = _worksheet_name_sheet_token(selected_target)
    if len(selected_sheet) != 2 or not selected_sheet.isalpha():
        return {selected_target}

    candidate_by_sheet: dict[str, set[str]] = {}
    for candidate in candidate_names:
        sheet = _worksheet_name_sheet_token(candidate)
        if len(sheet) != 2 or not sheet.isalpha():
            continue
        if not sheet.startswith(selected_sheet[0]):
            continue
        candidate_by_sheet.setdefault(sheet, set()).add(candidate)

    ordered_sheets = sorted(candidate_by_sheet)
    if selected_sheet not in candidate_by_sheet:
        return {selected_target}

    selected_index = ordered_sheets.index(selected_sheet)
    expanded = set(candidate_by_sheet[selected_sheet])

    for previous_index in range(selected_index - 1, -1, -1):
        previous_sheet = ordered_sheets[previous_index]
        expanded.update(candidate_by_sheet[previous_sheet])
        if len(expanded) >= _OPJU_SINGLE_CHAR_BATCH_MAX:
            break

    if selected_index == 0:
        # When selection is at the start of an alpha2 sequence (for example ``AA``),
        # also allow limited rightward expansion so contiguous families like
        # AA/AB/AC can be recovered together.
        for next_index in range(selected_index + 1, len(ordered_sheets)):
            next_sheet = ordered_sheets[next_index]
            expanded.update(candidate_by_sheet[next_sheet])
            if len(expanded) >= _OPJU_SINGLE_CHAR_BATCH_MAX:
                break

    if len(expanded) > _OPJU_SINGLE_CHAR_BATCH_MAX:
        return candidate_by_sheet[selected_sheet]

    return expanded


def _expand_adjacent_alpha1_sheet_targets_from_selection(
    candidate_names: set[str],
    selected_target: str,
) -> set[str]:
    """Expand one-character sheet tokens to an immediate predecessor sibling."""
    if not candidate_names or selected_target not in candidate_names:
        return {selected_target}

    selected_sheet = _worksheet_name_sheet_token(selected_target)
    if not selected_sheet or len(selected_sheet) != 1 or not selected_sheet.isalpha():
        return {selected_target}

    candidate_by_sheet: dict[str, set[str]] = {}
    for candidate in candidate_names:
        sheet = _worksheet_name_sheet_token(candidate)
        if len(sheet) != 1 or not sheet.isalpha():
            continue
        candidate_by_sheet.setdefault(sheet, set()).add(candidate)

    ordered_sheets = sorted(candidate_by_sheet)
    if selected_sheet not in candidate_by_sheet or selected_sheet not in ordered_sheets:
        return {selected_target}

    selected_index = ordered_sheets.index(selected_sheet)
    if selected_index <= 0:
        return {selected_target}

    previous_sheet = ordered_sheets[selected_index - 1]
    expanded = set(candidate_by_sheet[selected_sheet])
    expanded.update(candidate_by_sheet[previous_sheet])

    if len(expanded) > _OPJU_SINGLE_CHAR_BATCH_MAX:
        return candidate_by_sheet[selected_sheet]

    return expanded


def _worksheet_root_name(name: str) -> str:
    """Return a stable worksheet workbook root used for descendant matching."""
    base_name = name
    if "/" in base_name:
        base_name = base_name.split("/", 1)[0]
    if "__" in base_name:
        base_name = base_name.split("__", 1)[0]
    if "@" in base_name:
        base_name = base_name.split("@", 1)[0]
    return base_name


def _worksheet_window_matches_name_marker(
    data: bytes,
    *,
    start: int,
    end: int,
    name: str,
) -> bool:
    """Return True when a worksheet window payload is a textual name marker."""
    if not name:
        return False
    if start < 0 or end < start or end > len(data):
        return False

    raw = data[start:end]
    if not raw:
        return False

    marker = raw.decode("ascii", errors="ignore")
    marker = marker.strip("\x00\r\n\t ")
    return marker == name


def _build_worksheet_name_candidate_lookup(
    worksheet_names: Iterable[str],
) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    for raw_name in worksheet_names:
        if not raw_name:
            continue
        name = _normalize_worksheet_token(raw_name)
        if not name:
            continue
        if _is_noisy_worksheet_window_name(raw_name):
            continue
        for variant in _iter_worksheet_name_variants(name):
            if len(variant) < _WORKSHEET_TOKEN_MIN_LENGTH:
                continue
            lookup.setdefault(variant, set()).add(raw_name)
    return lookup


__all__ = [name for name in globals() if not name.startswith("__")]
