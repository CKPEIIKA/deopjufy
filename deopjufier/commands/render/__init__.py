"""Human and JSON output rendering helpers for CLI commands."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import cast

from deopjufier.compare import compare_results_as_text


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
    column_count = len(headers)

    if max_widths is None:
        column_widths = [0] * column_count
    else:
        column_widths = [max_widths.get(index, 0) for index in range(column_count)]

    for col in range(column_count):
        candidate_width = max(len(row[col]) for row in normalized)
        if max_widths is not None and max_widths.get(col, 0) > 0:
            candidate_width = min(candidate_width, max_widths[col])
        if column_widths[col] > 0:
            candidate_width = max(candidate_width, column_widths[col])
        column_widths[col] = candidate_width

    delimiter = "  "
    header_line = delimiter.join(
        _pad(header, width, "left") for header, width in zip(headers, column_widths, strict=False)
    )
    print(header_line)
    print("-" * len(header_line))
    for row in normalized[1:]:
        cells = [_trimmed(cell, width) for cell, width in zip(row, column_widths, strict=False)]
        print(
            delimiter.join(
                _pad(cell, width, "right" if header in {"offset", "length"} else "left")
                for cell, width, header in zip(cells, column_widths, headers, strict=False)
            )
        )


def _print_inspect_summary(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    _print_key_values(
        [
            ("Path", payload.get("path", "")),
            ("Detected Type", payload.get("detected_type", "")),
            ("Detected Confidence", payload.get("confidence", "")),
            ("Support Class", payload.get("support_class", "")),
            ("Parser Status", payload.get("parser_status", "")),
            ("Command Status", payload.get("status", "")),
            ("Reason", payload.get("reason", "")),
            ("Size bytes", payload.get("size_bytes", "")),
            ("SHA256", payload.get("sha256", "")),
        ],
        indent=0,
    )

    counts_raw = payload.get("counts", {})
    counts = cast(dict[str, object], counts_raw) if isinstance(counts_raw, dict) else {}
    if counts:
        print("\nCounts")
        for key, value in sorted(counts.items()):
            if isinstance(value, dict):
                print(f"{key}:")
                for nested_key, nested_value in sorted(value.items()):
                    if isinstance(nested_value, dict):
                        nested_items = ", ".join(
                            f"{nested_item}:{nested_count}"
                            for nested_item, nested_count in sorted(nested_value.items(), key=lambda item: item[0])
                        )
                        print(f"  {nested_key}: {{{nested_items}}}")
                    else:
                        print(f"  {nested_key}: {nested_value}")
            else:
                print(f"{key}: {value}")

    format_hints = payload.get("format_hints", {})
    if isinstance(format_hints, dict) and format_hints:
        format_hints_map = cast(dict[str, object], format_hints)
        print("\nFormat Hints")
        _print_key_values(
            [(key, value) for key, value in sorted(format_hints_map.items())],
            indent=2,
        )

    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        print("\nWarnings")
        for warning in warnings:
            print(f"- {warning}")


def _print_list_summary(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    items = cast(list[dict[str, object]], payload.get("items", []))
    _print_key_values(
        [
            ("File", payload.get("file", "")),
            ("Detected Type", payload.get("detected_type", "")),
            ("Support Class", payload.get("support_class", "")),
            ("Parser Status", payload.get("parser_status", "")),
            ("Command Status", payload.get("status", "")),
            ("Item Count", len(items)),
        ]
    )

    signatures = payload.get("embedded_signatures", {})
    if isinstance(signatures, dict):
        signatures_map = cast(dict[str, object], signatures)
        total_blocks = signatures_map.get("total_blocks")
        counts_by_kind = signatures_map.get("counts_by_kind")
        if total_blocks is not None:
            print(f"Embedded signatures: {total_blocks}")
        if isinstance(counts_by_kind, dict):
            for kind, count in sorted(counts_by_kind.items()):
                print(f"  {kind}: {count}")

    if not items:
        print("\nNo discoverable items.")
        warnings = payload.get("warnings")
        if isinstance(warnings, list) and warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")
        return

    print("\nItems")
    rows: list[tuple[object, ...]] = []
    for item in items:
        rows.append(
            (
                item.get("offset", ""),
                item.get("kind", ""),
                item.get("name", ""),
                item.get("length", ""),
                item.get("status", ""),
                item.get("path", ""),
                item.get("source_object_path", ""),
            )
        )
    _print_table_rows(
        ["Offset", "Kind", "Name", "Length", "Status", "Path", "Object"],
        rows,
        max_widths={2: 48, 5: 36, 6: 36},
    )

    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        print("\nWarnings")
        for warning in warnings:
            print(f"- {warning}")


def _print_compare_summary(payload: dict[str, object]) -> None:
    if not payload:
        print("Match: false")
        return
    summary = cast(dict[str, object], payload.get("summary", {}))
    mismatches = cast(dict[str, object], payload.get("mismatches", {}))

    print(compare_results_as_text(payload))

    if summary:
        _print_key_values(
            [
                ("Left items", summary.get("left_items", 0)),
                ("Right items", summary.get("right_items", 0)),
                ("Left-only items", summary.get("left_only_items", 0)),
                ("Right-only items", summary.get("right_only_items", 0)),
                ("Manifest signature mismatches", summary.get("signature_mismatches", 0)),
                ("File mismatches", summary.get("file_mismatches", 0)),
            ],
            indent=0,
        )

    manifest_mismatches = mismatches.get("manifest_signatures")
    if isinstance(manifest_mismatches, list) and manifest_mismatches:
        print("\nManifest signature mismatches")
        for mismatch in manifest_mismatches:
            if isinstance(mismatch, dict):
                mismatch_map = cast(dict[str, object], mismatch)
                signature = mismatch_map.get("signature")
                left_count = mismatch_map.get("left_count", "n/a")
                right_count = mismatch_map.get("right_count", "n/a")
                delta = mismatch_map.get("delta", "n/a")
            else:
                signature = None
                left_count = "n/a"
                right_count = "n/a"
                delta = "n/a"
            print(f"- signature={signature} left={left_count} right={right_count} delta={delta}")

    file_mismatches = mismatches.get("files")
    if isinstance(file_mismatches, list) and file_mismatches:
        shown = file_mismatches[:10]
        print(f"\nFile mismatches ({len(file_mismatches)} total, showing {len(shown)})")
        for mismatch in shown:
            if isinstance(mismatch, dict):
                mismatch_map = cast(dict[str, object], mismatch)
                status = mismatch_map.get("status", "unknown")
                identity = mismatch_map.get("identity", {})
                if isinstance(identity, dict):
                    print(f"- status={status} identity={identity}")
                else:
                    print(f"- status={status}")
