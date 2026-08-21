from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from deopjufier.extract.tables import scan_numeric_tables_from_bytes
from deopjufier.strings import (
    _iter_ascii_strings_from_bytes,
    _iter_utf16_strings_from_bytes,
)

RAW_REGION_CLASS_EMBEDDED_IMAGE = "embedded_image"
RAW_REGION_CLASS_TEXT = "text_region"
RAW_REGION_CLASS_NUMERIC_TABLE = "numeric_table_candidate"
RAW_REGION_CLASS_UNKNOWN_HIGH_ENTROPY = "unknown_high_entropy"
RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY = "unknown_low_entropy"

TEXT_REGION_MIN_LENGTH = 4
_TEXT_CLASS_SCAN_MIN_BYTES = 16
_TEXT_ENTROPY_MAX = 6.5
_ENTROPY_HIGH_THRESHOLD = 7.0
_RAW_HEURISTIC_SAMPLE_MAX_BYTES = 256 * 1024
_REGION_CONFIDENCE = {
    RAW_REGION_CLASS_EMBEDDED_IMAGE: 0.95,
    RAW_REGION_CLASS_TEXT: 0.55,
    RAW_REGION_CLASS_NUMERIC_TABLE: 0.82,
    RAW_REGION_CLASS_UNKNOWN_HIGH_ENTROPY: 0.4,
    RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY: 0.4,
}


def _sample_region_bytes(raw: bytes, *, max_bytes: int = _RAW_HEURISTIC_SAMPLE_MAX_BYTES) -> bytes:
    """Bound heuristic scans on large unknown regions.

    Raw-region classification is intentionally heuristic. Sampling the head and
    tail keeps the signal deterministic while avoiding repeated full scans over
    multi-megabyte gaps in real fixture tests.
    """
    if max_bytes <= 0 or len(raw) <= max_bytes:
        return raw

    head = max_bytes // 2
    tail = max_bytes - head
    if head <= 0 or tail <= 0:
        return raw[:max_bytes]
    return raw[:head] + raw[-tail:]


@dataclass(frozen=True)
class RawRegionClassification:
    """Deterministic classification result for an unknown byte range."""

    offset: int
    length: int
    region_class: str
    confidence: float


def _entropy(raw: bytes) -> float:
    if not raw:
        return 0.0

    counts = Counter(raw)
    total = len(raw)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def _overlap(a_offset: int, a_length: int, b_offset: int, b_length: int) -> bool:
    a_end = a_offset + max(0, a_length)
    b_end = b_offset + max(0, b_length)
    return a_offset < b_end and b_offset < a_end


def _looks_like_text(raw: bytes, *, min_length: int = TEXT_REGION_MIN_LENGTH) -> bool:
    if len(raw) < _TEXT_CLASS_SCAN_MIN_BYTES:
        return False
    if _entropy(raw) > _TEXT_ENTROPY_MAX:
        return False

    def _has_visible(row: str) -> bool:
        return any(ch.isprintable() and not ch.isspace() for ch in row)

    ascii_rows = list(_iter_ascii_strings_from_bytes(raw, min_length=min_length))
    if any(_has_visible(row) for row in ascii_rows):
        return True

    utf16_rows = list(_iter_utf16_strings_from_bytes(raw, min_length=min_length))
    return any(_has_visible(row) for row in utf16_rows)


def _looks_like_numeric_candidate(raw: bytes, *, min_rows: int = 2, min_columns: int = 2) -> bool:
    if len(raw) < 16:
        return False
    rows = scan_numeric_tables_from_bytes(raw, min_rows=min_rows, min_columns=min_columns)
    return bool(rows)


def classify_raw_region(
    raw: bytes,
    *,
    min_rows: int = 2,
    min_columns: int = 2,
    min_length: int = TEXT_REGION_MIN_LENGTH,
    classify_numeric: bool = True,
) -> str:
    sampled = _sample_region_bytes(raw)

    if classify_numeric and _looks_like_numeric_candidate(sampled, min_rows=min_rows, min_columns=min_columns):
        return RAW_REGION_CLASS_NUMERIC_TABLE

    if _looks_like_text(sampled, min_length=min_length):
        return RAW_REGION_CLASS_TEXT

    if _entropy(sampled) >= _ENTROPY_HIGH_THRESHOLD:
        return RAW_REGION_CLASS_UNKNOWN_HIGH_ENTROPY

    return RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY


def classify_raw_regions(
    data: bytes,
    ranges: list[tuple[int, int]],
    *,
    image_blocks: list[tuple[int, int]] | None = None,
    min_rows: int = 2,
    min_columns: int = 2,
    text_min_length: int = TEXT_REGION_MIN_LENGTH,
    classify_numeric: bool = True,
) -> list[RawRegionClassification]:
    if not ranges:
        return []

    image_blocks = image_blocks or []
    output: list[RawRegionClassification] = []
    for offset, length in ranges:
        if length <= 0:
            continue
        end = offset + length
        if offset < 0 or end > len(data):
            end = min(max(end, 0), len(data))
            offset = min(max(offset, 0), max(end, 0))
            length = max(0, end - offset)
            if length <= 0:
                continue

        raw = data[offset : offset + length]

        region_class = classify_raw_region(
            raw,
            min_rows=min_rows,
            min_columns=min_columns,
            min_length=text_min_length,
            classify_numeric=classify_numeric,
        )
        for block_offset, block_length in image_blocks:
            if _overlap(offset, length, block_offset, block_length):
                region_class = RAW_REGION_CLASS_EMBEDDED_IMAGE
                break

        output.append(
            RawRegionClassification(
                offset=offset,
                length=length,
                region_class=region_class,
                confidence=_REGION_CONFIDENCE.get(region_class, 0.4),
            )
        )

    return output


def unsupported_region_classes(
    region_classes: list[str],
) -> set[str]:
    supported = {RAW_REGION_CLASS_EMBEDDED_IMAGE}
    return {cls for cls in region_classes if cls not in supported}
