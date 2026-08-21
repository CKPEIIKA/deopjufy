"""Helpers for post-recovery tabular filtering."""

import re

_PARSER_CELL_TOKEN_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_PARSER_SIMPLE_TOKEN_RX = re.compile(r"^[A-Za-z0-9._-]+$")
_PARSER_SPACED_TOKEN_RX = re.compile(r"^[A-Za-z0-9._-]+(?: [A-Za-z0-9._-]+)+$")
_PARSER_SINGLE_COLUMN_MEANINGFUL_RATIO = 0.25


def _is_single_column_delimited_numeric_payload(token: str) -> bool:
    """Return True when token is a compact numeric sequence with separators."""
    value = token.strip()
    if ";" not in value:
        return False
    parts = [part.strip() for part in value.split(";") if part.strip()]
    if len(parts) < 2:
        return False
    return all(_PARSER_CELL_TOKEN_RE.fullmatch(part) for part in parts)


def _is_single_column_token_meaningful(token: str) -> bool:
    """Return True when a single-column parser token is plausible payload."""
    value = token.strip()
    if not value:
        return False
    if _is_single_column_delimited_numeric_payload(value):
        return True
    if value.startswith("cell://"):
        return True
    if _PARSER_CELL_TOKEN_RE.fullmatch(value):
        return True
    if len(value) <= 2:
        return False
    lowered = value.lower()
    if value.endswith("*") or lowered.startswith("sheet"):
        return False

    # High-noise glyph runs are not stable worksheet payload.
    if len(value) <= 3:
        return False
    if not (_PARSER_SIMPLE_TOKEN_RX.fullmatch(value) or _PARSER_SPACED_TOKEN_RX.fullmatch(value)):
        return False
    if lowered.startswith("page"):
        return False
    return True


def _is_parser_recovered_row_meaningful(rows: list[list[str]]) -> bool:
    """Return True when parser-recovered rows look like extractable tabular data."""
    if not rows:
        return False

    single_column_values: set[str] = set()
    for row in rows:
        cleaned_row = [str(value).strip() for value in row if str(value).strip()]
        if not cleaned_row:
            continue
        if len(cleaned_row) > 1:
            # Multi-column structure is explicit evidence of data-bearing
            # content, so avoid repeatedly walking large OPJ payloads.
            return True
        single_column_values.add(cleaned_row[0])

    if not single_column_values:
        return False

    # Single-column payloads that are exact duplicates are usually worksheet
    # metadata placeholders (for example ["Sheet1", "Sheet1"]).
    if len(single_column_values) == 1:
        value = next(iter(single_column_values))
        # One-cell payloads are often unreliable; keep only structured markers
        # or clearly numeric vectors.
        if _is_single_column_delimited_numeric_payload(value):
            return True
        if value.startswith("cell://"):
            return True
        if _PARSER_CELL_TOKEN_RE.fullmatch(value):
            return True
        return False

    lowered = [value.lower() for value in single_column_values]
    if any(value in {"plot", "intercept", "slope", "slope_2", "intercept_2"} for value in lowered):
        return False
    meaningful_values = [value for value in single_column_values if _is_single_column_token_meaningful(value)]
    if not meaningful_values:
        return False
    if len(meaningful_values) / len(single_column_values) < _PARSER_SINGLE_COLUMN_MEANINGFUL_RATIO:
        return False
    return True


def _filter_meaningful_recovered_rows(
    rows_by_name: dict[str, list[list[str]]],
    dims_by_name: dict[str, tuple[int, int]],
    parser_backed_worksheet_names: set[str] | None = None,
) -> tuple[dict[str, list[list[str]]], dict[str, tuple[int, int]]]:
    """Normalize parser-recovered rows, dropping row payloads that are placeholder-only."""
    parser_backed_worksheet_names = parser_backed_worksheet_names or set()

    filtered_rows: dict[str, list[list[str]]] = {}
    filtered_dims: dict[str, tuple[int, int]] = {}
    for name, rows in rows_by_name.items():
        if name in parser_backed_worksheet_names:
            # Preserve parser bindings, but only treat payload as recovered
            # table data when it passes the conservative content check. Other
            # bindings remain visible as explicit zero-row partial windows.
            if _is_parser_recovered_row_meaningful(rows):
                filtered_rows[name] = rows
                if name in dims_by_name:
                    filtered_dims[name] = dims_by_name[name]
                else:
                    filtered_dims[name] = (
                        len(rows),
                        max((len(row) for row in rows), default=0),
                    )
            else:
                filtered_rows[name] = []
                filtered_dims[name] = (
                    0,
                    0,
                )
            continue

        if _is_parser_recovered_row_meaningful(rows):
            filtered_rows[name] = rows
            if name in dims_by_name:
                filtered_dims[name] = dims_by_name[name]
            else:
                filtered_dims[name] = (
                    len(rows),
                    max((len(row) for row in rows), default=0),
                )
            continue

        # Preserve non-meaningful entries as matched names so parser evidence
        # remain visible while still allowing narrow parser-backed zero-row
        # evidence to be emitted as extracted where applicable.
        filtered_rows[name] = []
        filtered_dims[name] = (0, 0)

    return filtered_rows, filtered_dims


__all__ = [name for name in globals() if not name.startswith("__")]
