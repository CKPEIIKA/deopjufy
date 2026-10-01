"""Human and JSON output rendering helpers for CLI commands."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import cast


def _json_flag_argument_parser(command_parser) -> None:
    command_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON output")


def _pad(value: object, width: int, align: str = "left") -> str:
    text = "" if value is None else str(value)
    if align == "right":
        return text.rjust(width)
    return text.ljust(width)


def _trimmed(value: object, width: int | None = None) -> str:
    text = " ".join(str(value).split())
    if width is None or len(text) <= width:
        return text
    if width <= 1:
        return "…"
    return text[: width - 1] + "…"


def _print_key_values(pairs: list[tuple[str, object]], *, indent: int = 0) -> None:
    if not pairs:
        return
    key_width = max(len(key) for key, _ in pairs)
    pad = " " * indent
    for key, value in pairs:
        print(f"{pad}{key:<{key_width}}  {value}", file=sys.stdout)


def _print_table_rows(
    headers: list[str],
    rows: list[tuple[object, ...]],
    *,
    max_widths: dict[int, int] | None = None,
) -> None:
    if not headers:
        return
    normalized: list[list[str]] = [[str(header) for header in headers]] + [
        [_trimmed(value) for value in row] for row in rows
    ]
    caps = max_widths or {}
    # Widths fit the content; max_widths only caps a column, it never pads one.
    column_widths = [
        min(max(len(row[col]) for row in normalized), caps.get(col) or sys.maxsize) for col in range(len(headers))
    ]

    delimiter = "  "
    header_line = delimiter.join(
        _pad(header, width, "left") for header, width in zip(headers, column_widths, strict=False)
    ).rstrip()
    print(header_line)
    print("-" * len(header_line))
    for row in normalized[1:]:
        cells = [_trimmed(cell, width) for cell, width in zip(row, column_widths, strict=False)]
        print(
            delimiter.join(
                _pad(cell, width, "right" if header.lower() in {"offset", "length"} else "left")
                for cell, width, header in zip(cells, column_widths, headers, strict=False)
            ).rstrip()
        )


_HINT_VALUE_WIDTH = 72
# Format hints already summarized in the header lines.
_HEADER_HINT_KEYS = frozenset(
    {"magic_offset", "magic_type", "opj_build", "opj_file_version", "opj_magic", "opj_origin_version"}
)


def _count_phrase(counts: object) -> str:
    """Render ``{kind: count}`` as ``kind count, ...`` ordered by count, then name."""
    if not isinstance(counts, dict) or not counts:
        return "none"
    ordered = sorted(cast(dict[str, int], counts).items(), key=lambda pair: (-int(pair[1]), str(pair[0])))
    return ", ".join(f"{kind} {count:,}" for kind, count in ordered)


def _hint_text(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        entries = cast(list[object], value)
        names = [str(cast(dict[str, object], entry).get("name")) for entry in entries if isinstance(entry, dict)]
        if names and len(names) == len(entries) and "None" not in names:
            return f"{len(names)}: {', '.join(names)}"
        return f"{len(entries)} entries"
    text = " ".join(str(value).split())
    return text if len(text) <= _HINT_VALUE_WIDTH else text[: _HINT_VALUE_WIDTH - 3] + "..."


def _origin_line(hints: Mapping[str, object]) -> str | None:
    parts = []
    if hints.get("opj_origin_version") is not None:
        parts.append(f"version {hints['opj_origin_version']}")
    if hints.get("opj_build") is not None:
        parts.append(f"build {hints['opj_build']}")
    if hints.get("opj_file_version") is not None:
        parts.append(f"file format {hints['opj_file_version']}")
    return ", ".join(parts) or None


def _type_line(payload: Mapping[str, object], hints: Mapping[str, object]) -> str:
    detected = str(payload.get("detected_type", "unknown"))
    magic = hints.get("opj_magic") or (hints.get("magic_type") if hints.get("magic_verified") else None)
    evidence = f"{magic} magic" if magic else str(payload.get("reason", "no signature"))
    confidence = payload.get("confidence")
    if isinstance(confidence, (int, float)):
        evidence += f", confidence {confidence:.2f}"
    return f"{detected} ({evidence})"


def _support_line(payload: Mapping[str, object]) -> str:
    return (
        f"{payload.get('support_class', 'unknown')} "
        f"(parser {payload.get('parser_status', 'unknown')}, command {payload.get('status', 'unknown')})"
    )


def _print_warnings(warnings: object) -> None:
    if isinstance(warnings, list) and warnings:
        print("\nWarnings")
        for warning in warnings:
            print(f"  - {warning}")


def _print_inspect_summary(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    hints_raw = payload.get("format_hints", {})
    hints = cast(dict[str, object], hints_raw) if isinstance(hints_raw, dict) else {}
    size = payload.get("size_bytes")
    header: list[tuple[str, object]] = [
        ("Path", payload.get("path", "")),
        ("Type", _type_line(payload, hints)),
    ]
    origin = _origin_line(hints)
    if origin:
        header.append(("Origin", origin))
    header += [
        ("Size", f"{size:,} bytes" if isinstance(size, int) else "unknown"),
        ("SHA-256", payload.get("sha256") or "unknown"),
        ("Support", _support_line(payload)),
    ]
    if payload.get("coverage_scope"):
        header.append(("Coverage", f"{payload['coverage_scope']}, {payload.get('verification', 'unverified')}"))
    _print_key_values(header)

    counts_raw = payload.get("counts", {})
    counts = cast(dict[str, object], counts_raw) if isinstance(counts_raw, dict) else {}
    if counts:
        evidence = cast(dict[str, object], counts.get("parser_evidence_counts") or {})
        heuristic = cast(dict[str, object], evidence.get("heuristic") or {})
        objects = counts.get("origin_objects", 0)
        object_line = f"{objects:,}" if isinstance(objects, int) else str(objects)
        if heuristic:
            object_line += f": {heuristic.get('false', 0):,} parser-backed, {heuristic.get('true', 0):,} heuristic"
        images = counts.get("images", 0)
        print("\nContents")
        _print_key_values(
            [
                ("Items", f"{counts.get('items', 0):,} listed"),
                ("Objects", object_line),
                ("Kinds", _count_phrase(counts.get("origin_object_kinds"))),
                ("Images", f"{images:,} ({_count_phrase(counts.get('embedded_signatures'))})" if images else "none"),
            ],
            indent=2,
        )

    details: list[tuple[str, object]] = [
        (key, _hint_text(value)) for key, value in sorted(hints.items()) if key not in _HEADER_HINT_KEYS
    ]
    if details:
        print("\nFormat details")
        _print_key_values(details, indent=2)

    _print_warnings(payload.get("warnings", []))


def _print_list_summary(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    items = cast(list[dict[str, object]], payload.get("items", []))
    heuristic = sum(1 for item in items if item.get("heuristic"))
    signatures_raw = payload.get("embedded_signatures", {})
    signatures = cast(dict[str, object], signatures_raw) if isinstance(signatures_raw, dict) else {}
    image_total = signatures.get("total_blocks") or 0
    _print_key_values(
        [
            ("Path", payload.get("file", "")),
            ("Type", payload.get("detected_type", "unknown")),
            ("Support", _support_line(payload)),
            ("Items", f"{len(items):,}: {len(items) - heuristic:,} parser-backed, {heuristic:,} heuristic"),
            (
                "Images",
                f"{image_total:,} ({_count_phrase(signatures.get('counts_by_kind'))})" if image_total else "none",
            ),
        ]
    )

    if not items:
        print("\nNo discoverable items.")
        _print_warnings(payload.get("warnings"))
        return

    print("\nCatalog")
    rows: list[tuple[object, ...]] = [
        (
            item.get("offset", ""),
            item.get("length", ""),
            item.get("kind", ""),
            "heuristic" if item.get("heuristic") else "parser",
            item.get("name", ""),
            item.get("source_object_path", ""),
        )
        for item in items
    ]
    _print_table_rows(
        ["Offset", "Length", "Kind", "Evidence", "Name", "Object"],
        rows,
        max_widths={4: 40, 5: 40},
    )

    _print_warnings(payload.get("warnings"))


_COMPARE_ROWS_SHOWN = 20


def _signature_row(mismatch: Mapping[str, object]) -> tuple[object, ...]:
    signature = mismatch.get("signature")
    fields = cast(dict[str, object], signature) if isinstance(signature, dict) else {}
    delta = mismatch.get("delta", 0)
    side = "left" if isinstance(delta, int) and delta > 0 else "right"
    extra = abs(delta) if isinstance(delta, int) else delta
    return (
        side,
        f"+{extra}",
        fields.get("status") or "-",
        fields.get("kind") or "-",
        fields.get("name") or "-",
        fields.get("path") or "-",
    )


def _file_row(mismatch: Mapping[str, object]) -> tuple[object, ...]:
    identity = mismatch.get("identity")
    fields = cast(dict[str, object], identity) if isinstance(identity, dict) else {}
    return (mismatch.get("status", "unknown"), fields.get("kind") or "-", fields.get("path") or "-")


def _print_limited_table(title: str, headers: list[str], rows: list[tuple[object, ...]]) -> None:
    shown = rows[:_COMPARE_ROWS_SHOWN]
    print(f"\n{title} ({len(rows):,})")
    _print_table_rows(headers, shown, max_widths={4: 32, 5: 48} if len(headers) > 4 else {2: 60})
    if len(rows) > len(shown):
        print(f"... {len(rows) - len(shown):,} more; use --json for the complete list")


def _print_compare_summary(payload: dict[str, object]) -> None:
    if not payload:
        print("Result  no comparison")
        return
    summary = cast(dict[str, object], payload.get("summary", {}))
    mismatches = cast(dict[str, object], payload.get("mismatches", {}))
    left = cast(dict[str, object], payload.get("left", {}))
    right = cast(dict[str, object], payload.get("right", {}))
    signature_rows = [
        _signature_row(cast(dict[str, object], entry))
        for entry in cast(list[object], mismatches.get("manifest_signatures") or [])
        if isinstance(entry, dict)
    ]
    file_rows = [
        _file_row(cast(dict[str, object], entry))
        for entry in cast(list[object], mismatches.get("files") or [])
        if isinstance(entry, dict)
    ]
    if payload.get("match"):
        result = "match"
    else:
        result = (
            f"different: {summary.get('signature_mismatches', 0):,} item signature(s), "
            f"{summary.get('file_mismatches', 0):,} file mismatch(es)"
        )
    _print_key_values(
        [
            ("Left", f"{left.get('path', '')}  ({left.get('status', 'unknown')}, {left.get('item_count', 0):,} items)"),
            (
                "Right",
                f"{right.get('path', '')}  ({right.get('status', 'unknown')}, {right.get('item_count', 0):,} items)",
            ),
            ("Result", result),
        ]
    )
    if signature_rows:
        _print_limited_table(
            "Items present on one side only",
            ["Side", "Extra", "Status", "Kind", "Name", "Path"],
            signature_rows,
        )
    if file_rows:
        _print_limited_table("File mismatches", ["Status", "Kind", "Path"], file_rows)
