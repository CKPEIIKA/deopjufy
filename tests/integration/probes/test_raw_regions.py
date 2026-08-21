"""Tests for raw-region classification heuristics."""

from __future__ import annotations

from deopjufier.extract.raw_regions import (
    RAW_REGION_CLASS_EMBEDDED_IMAGE,
    RAW_REGION_CLASS_NUMERIC_TABLE,
    RAW_REGION_CLASS_TEXT,
    RAW_REGION_CLASS_UNKNOWN_HIGH_ENTROPY,
    RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY,
    classify_raw_regions,
    unsupported_region_classes,
)


def test_classify_raw_region_prefers_numeric_and_text_and_entropy() -> None:
    numeric = b"1 2 3 4 5 6\n7 8 9 10 11 12\n13 14 15 16 17 18\n"
    text = b"plain text payload with line breaks\nfor classification\n"
    entropy_data = bytes(range(256))

    numeric_region = classify_raw_regions(numeric, [(0, len(numeric))])[0]
    text_region = classify_raw_regions(text, [(0, len(text))])[0]
    entropy_region = classify_raw_regions(entropy_data, [(0, len(entropy_data))])[0]

    assert numeric_region.region_class == RAW_REGION_CLASS_NUMERIC_TABLE
    assert text_region.region_class == RAW_REGION_CLASS_TEXT
    assert entropy_region.region_class == RAW_REGION_CLASS_UNKNOWN_HIGH_ENTROPY


def test_classify_raw_region_can_skip_numeric_scanning() -> None:
    numeric = b"1 2 3 4 5 6\n7 8 9 10 11 12\n13 14 15 16 17 18\n"

    region = classify_raw_regions(
        numeric,
        [(0, len(numeric))],
        classify_numeric=False,
    )[0]

    assert region.region_class != RAW_REGION_CLASS_NUMERIC_TABLE


def test_classify_raw_region_marks_embedded_image_overlap() -> None:
    data = b"A" * 64 + b"\x89PNG\r\n\x1a\n" + b"dummy"
    image_blocks = [(64, 6)]

    regions = classify_raw_regions(data, [(58, 20)], image_blocks=image_blocks)
    assert regions
    assert regions[0].region_class == RAW_REGION_CLASS_EMBEDDED_IMAGE


def test_unsupported_region_classes_filters_known_class() -> None:
    assert unsupported_region_classes(
        [
            RAW_REGION_CLASS_EMBEDDED_IMAGE,
            RAW_REGION_CLASS_TEXT,
            RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY,
        ]
    ) == {RAW_REGION_CLASS_TEXT, RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY}
