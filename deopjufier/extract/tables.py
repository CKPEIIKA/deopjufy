"""Heuristic numeric table scanner."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TextIO

from deopjufier.extract.path_helpers import manifest_relative_path as _manifest_path
from deopjufier.extract.path_helpers import unique_output_path as _unique_path
from deopjufier.extract.tabular_helpers import _pack_row_values
from deopjufier.io import iter_file_chunks
from deopjufier.manifest import Manifest, ManifestItem

_NUMERIC_WORD = str
_FIELD_SEP_TRANSLATE = str.maketrans("\t;,", "   ")
_NUMERIC_TABLE_CACHE: dict[tuple[Path, int, int, int, int], list[tuple[int, int, int, list[_NUMERIC_WORD]]]] = {}
_SCAN_NUMERIC_ENCODINGS = ("utf-8", "utf-16le", "utf-16be")


def _iter_numeric_lines(raw: bytes, encoding: str) -> list[tuple[str, int]]:
    if encoding == "utf-8":
        lines = raw.splitlines(keepends=True)
        offset = 0
        decoded: list[tuple[str, int]] = []
        for line in lines:
            text = line.decode(encoding, errors="ignore").rstrip("\r\n")
            decoded.append((text, offset))
            offset += len(line)
        return decoded

    text = raw.decode(encoding, errors="ignore")
    lines = text.splitlines(keepends=True)
    offset = 0
    decoded: list[tuple[str, int]] = []
    for line in lines:
        encoded = line.encode(encoding, errors="ignore")
        if not encoded:
            if line:
                offset += len(raw) - offset
            continue

        decoded.append((line.rstrip("\r\n"), offset))
        offset += len(encoded)
    return decoded


def _scan_numeric_rows_from_lines(
    lines_and_offsets: list[tuple[str, int]], *, min_rows: int, min_columns: int
) -> list[tuple[int, int, int, list[_NUMERIC_WORD]]]:
    rows: list[tuple[int, int, int, list[_NUMERIC_WORD]]] = []
    table_id = 0
    row_in_table = 0

    for text, offset in lines_and_offsets:
        values = _parse_numeric_line(text, min_columns=min_columns)
        if values is not None:
            if row_in_table == 0:
                table_id += 1
            row_in_table += 1
            rows.append((table_id, row_in_table, offset, values))
            continue

        if 0 < row_in_table < min_rows:
            while rows and rows[-1][0] == table_id:
                rows.pop()
        row_in_table = 0

    if 0 < row_in_table < min_rows and table_id > 0:
        while rows and rows[-1][0] == table_id:
            rows.pop()

    return rows


def _parse_numeric_line(line: str, min_columns: int) -> list[_NUMERIC_WORD] | None:
    cleaned = line.strip()
    if not cleaned:
        return None

    parts = cleaned.translate(_FIELD_SEP_TRANSLATE).split()
    if len(parts) < min_columns:
        return None

    for part in parts:
        try:
            float(part)
        except ValueError:
            return None

    return parts


def scan_numeric_tables_from_bytes(
    raw: bytes,
    *,
    min_rows: int = 5,
    min_columns: int = 2,
) -> list[tuple[int, int, int, list[str]]]:
    """Parse a byte payload and return guessed numeric rows.

    The payload is expected to contain UTF-8 compatible rows. Non-numeric lines are
    treated as separators between table segments.
    """
    utf8_lines = _iter_numeric_lines(raw, "utf-8")
    utf8_rows = _scan_numeric_rows_from_lines(utf8_lines, min_rows=min_rows, min_columns=min_columns)
    if utf8_rows:
        return utf8_rows

    best_rows: list[tuple[int, int, int, list[_NUMERIC_WORD]]] = []
    for encoding in _SCAN_NUMERIC_ENCODINGS[1:]:
        if len(raw) < 2:
            continue

        candidate = _scan_numeric_rows_from_lines(
            _iter_numeric_lines(raw, encoding),
            min_rows=min_rows,
            min_columns=min_columns,
        )
        if len(candidate) > len(best_rows):
            best_rows = candidate

    return best_rows


def scan_numeric_tables_from_file(
    path: Path,
    *,
    min_rows: int = 5,
    min_columns: int = 2,
    chunk_size: int = 1 << 20,
) -> list[tuple[int, int, int, list[str]]]:
    """Scan a file for numeric table rows with bounded memory usage.

    Parsing remains deterministic while processing the file in bounded chunks.
    """
    rows: list[tuple[int, int, int, list[_NUMERIC_WORD]]] = []
    table_id = 0
    row_in_table = 0
    offset = 0
    carry = b""

    for block in iter_file_chunks(path, chunk_size=chunk_size):
        chunk = carry + block
        lines = chunk.splitlines(keepends=True)
        if chunk and not chunk.endswith((b"\n", b"\r")):
            carry = lines[-1] if lines else b""
            lines = lines[:-1]
        else:
            carry = b""

        for line_bytes in lines:
            text = line_bytes.rstrip(b"\r\n").decode("utf-8", "ignore").strip()
            values = _parse_numeric_line(text, min_columns=min_columns)
            if values is not None:
                if row_in_table == 0:
                    table_id += 1
                row_in_table += 1
                rows.append((table_id, row_in_table, offset, values))
            else:
                if 0 < row_in_table < min_rows:
                    while rows and rows[-1][0] == table_id:
                        rows.pop()
                row_in_table = 0
            offset += len(line_bytes)

    if carry:
        text = carry.decode("utf-8", "ignore").strip()
        values = _parse_numeric_line(text, min_columns=min_columns)
        if values is not None:
            if row_in_table == 0:
                table_id += 1
            row_in_table += 1
            rows.append((table_id, row_in_table, offset, values))
        elif 0 < row_in_table < min_rows:
            while rows and rows[-1][0] == table_id:
                rows.pop()

    return rows


def scan_numeric_tables(
    path: Path,
    min_rows: int = 5,
    min_columns: int = 2,
) -> list[tuple[int, int, int, list[str]]]:
    """Return guessed table rows as tuples (table_id,row_index,offset,cells)."""
    file_stats = path.stat()
    cache_key = (
        path,
        file_stats.st_size,
        file_stats.st_mtime_ns,
        min_rows,
        min_columns,
    )
    cached = _NUMERIC_TABLE_CACHE.get(cache_key)
    if cached is not None:
        return [*cached]

    rows = scan_numeric_tables_from_file(path, min_rows=min_rows, min_columns=min_columns)

    _NUMERIC_TABLE_CACHE[cache_key] = rows
    return rows


def write_tables_csv(path: Path, out: TextIO, min_rows: int = 5, min_columns: int = 2, delimiter: str = ",") -> int:
    rows = scan_numeric_tables(path, min_rows=min_rows, min_columns=min_columns)
    if not rows:
        return 0

    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    writer.writerow(["table_id", "row_in_table", "offset", "columns", "values"])

    count = 0
    for table_id, row_in_table, offset, values in rows:
        writer.writerow([table_id, row_in_table, offset, len(values), _pack_row_values(values)])
        count += 1

    return count


def extract_tables(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    output_format: str = "csv",
    min_rows: int = 5,
    min_columns: int = 2,
    force: bool = False,
    table_rows: list[tuple[int, int, int, list[str]]] | None = None,
    manifest_root: Path | None = None,
) -> int:
    """Extract heuristic table rows to CSV/TSV/JSON and append manifest items."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = (
        table_rows
        if table_rows is not None
        else scan_numeric_tables(input_path, min_rows=min_rows, min_columns=min_columns)
    )

    if output_format == "csv":
        filename = "guessed_tables.csv"
    elif output_format == "tsv":
        filename = "guessed_tables.tsv"
    else:
        filename = "guessed_tables.json"
    target = out_dir / filename

    if target.exists() and not force:
        manifest.add_item(
            ManifestItem(
                kind="table_scan",
                name="numeric_tables",
                status="skipped",
                confidence=0.6,
                discovery_type="heuristic_scan",
                heuristic=True,
                path=_manifest_path(target, manifest_root or out_dir),
                source_object_path="numeric_tables",
                error="target_exists",
            )
        )
        return 0
    target = _unique_path(out_dir, filename, force=force)

    if output_format in {"csv", "tsv"}:
        delimiter = "," if output_format == "csv" else "\t"
        with target.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp, delimiter=delimiter, lineterminator="\n")
            writer.writerow(["table_id", "row_in_table", "offset", "columns", "values"])
            for table_id, row_in_table, offset, values in rows:
                writer.writerow([table_id, row_in_table, offset, len(values), _pack_row_values(values)])
    else:
        payload = [
            {
                "table_id": table_id,
                "row_in_table": row_in_table,
                "offset": offset,
                "columns": len(values),
                "values": values,
            }
            for table_id, row_in_table, offset, values in rows
        ]
        with target.open("w", encoding="utf-8", newline="\n") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)
            fp.write("\n")

    status = "extracted" if rows else "partial"
    manifest.add_item(
        ManifestItem(
            kind="table_scan",
            name="numeric_tables",
            status=status,
            confidence=0.8 if rows else 0.4,
            discovery_type="heuristic_scan",
            heuristic=True,
            path=_manifest_path(target, manifest_root or out_dir),
            source_object_path="numeric_tables",
        )
    )
    return len(rows)
