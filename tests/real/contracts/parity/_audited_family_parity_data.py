"""Targeted parity checks for audited OPJ/OPJU family-level behavior."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from deopjufier.blocks import GIF_SIGS, JPEG_SIG, PNG_SIG
from tests.real.fixtures.core.real_files_contract_core import REPO_ROOT

_FIXTURE_MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "audited_fixture_family_matrix.json"
_AUDITED_FIXTURE_COUNTS = json.loads(_FIXTURE_MATRIX_PATH.read_text(encoding="utf-8"))
_OPJ_FIXTURES = [
    "refs/github/Ropj/inst/test.opj",
    "refs/github/Ropj/inst/tree.opj",
    "refs/ropj/src/Ropj/inst/test.opj",
    "refs/ropj/src/Ropj/inst/tree.opj",
    "refs/openopj/support/test.opj",
    "refs/public/zenodo/zenodo-3779638-fig4.opj",
]
_PUBLIC_OPJU_FIGURE_FIXTURES = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": {},
    "refs/public/zenodo/zenodo-3779638-fig3.opju": {},
    "refs/public/zenodo/zenodo-4708192-fig3.opju": {},
    "refs/public/zenodo/zenodo-4708192-fig5.opju": {},
    "refs/public/zenodo/zenodo-4708192-fig6a-d.opju": {
        "Book1/FitLinear1": 6,
        "Book1/FitLinear2": 6,
        "Book1/FitLinear3": 6,
        "Book1/FitLinear4": 6,
        "Book1/FitLinear5": 6,
        "Book1/Sheet3": 2,
        "Book1/Sheet4": 2,
    },
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": {},
    "refs/public/zenodo/zenodo-4708192-fig7d.opju": {
        "Book1_A": 6,
        "Book1_G": 15,
    },
    "refs/public/zenodo/zenodo-4708192-fig7e-7f.opju": {
        "Book2_A": 7,
        "Book2_C": 15,
        "Book3_E": 15,
        "Book4": 9,
        "Book4/FitLinear1": 6,
        "Book4/FitLinear17": 9,
    },
}

_LOW_RECOVERY_OPJU_FIGURES = (
    "refs/public/zenodo/zenodo-3779638-fig2.opju",
    "refs/public/zenodo/zenodo-3779638-fig3.opju",
    "refs/public/zenodo/zenodo-4708192-fig5.opju",
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju",
)
_LOW_RECOVERY_OPJU_PREVIEW_COUNTS: dict[str, tuple[int, int, int]] = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": (1, 0, 1),
    "refs/public/zenodo/zenodo-3779638-fig3.opju": (4, 3, 1),
    "refs/public/zenodo/zenodo-4708192-fig5.opju": (5, 4, 1),
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": (3, 2, 1),
}
_LOW_RECOVERY_OPJU_NO_EMBEDDED_IMAGE_PREVIEWS: dict[str, set[str]] = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": set(),
    "refs/public/zenodo/zenodo-3779638-fig3.opju": {"Graph1"},
    "refs/public/zenodo/zenodo-4708192-fig5.opju": {"Graph1", "Graph2", "Graph3", "Graph4"},
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": {"Graph1", "Graph3"},
}
_LOW_RECOVERY_OPJU_NO_NOTE_OBJECTS: dict[str, bool] = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": True,
    "refs/public/zenodo/zenodo-3779638-fig3.opju": True,
    "refs/public/zenodo/zenodo-4708192-fig5.opju": True,
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": True,
}
_PUBLIC_OPJU_FIGURE_MIN_FUNCTION_COUNTS: dict[str, int] = {
    "refs/public/zenodo/zenodo-10364693-ahrrenius-ybscsz.opju": 3,
    "refs/public/zenodo/zenodo-10721640-figure-s7.opju": 1,
    "refs/public/zenodo/zenodo-18450855-eucd2p2.opju": 2,
    "refs/public/zenodo/zenodo-3779638-fig2.opju": 1,
    "refs/public/zenodo/zenodo-3779638-fig3.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig3.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig5.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig6a-d.opju": 6,
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig7d.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig7e-7f.opju": 1,
}
_LOW_RECOVERY_OPJU_TABLE_SCAN_COUNTS: dict[str, int] = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": 1,
    "refs/public/zenodo/zenodo-3779638-fig3.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig5.opju": 1,
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": 1,
}
_LOW_RECOVERY_OPJU_WORKSHEET_NAMES: dict[str, tuple[str, ...]] = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": (
        "Book1",
        "Book1/Sheet1",
        "Book1_A",
        "Book1_B",
        "Book1_C",
        "Book1_D",
        "Book1_E",
        "Book1_F1",
        "Book1_J",
        "Book1_K",
        "Book1_L",
        "Book1_M",
        "Book1_N",
        "Book1_O",
        "Book1_P",
        "Book1_Q",
        "Book2",
        "Book2_A",
        "Book2_B",
        "Sheet1",
    ),
    "refs/public/zenodo/zenodo-3779638-fig3.opju": (
        "Book3",
        "Book3_A",
        "Book3_B",
        "Book3_C",
        "Book3_D",
        "Book3_E",
        "Book3_F",
        "Book3_G",
        "Book3_H",
        "Book3_I",
        "Book3_J",
        "Book3_K1",
        "Book3_L",
        "Book3_M1",
        "Book3_N",
        "Book3_O",
        "Book3_P",
        "Book3_Q",
        "Book3_R",
        "Book3_S",
        "Book3_T",
        "Book3_U",
        "Book3_V",
        "Book3_W",
        "Book3_X",
        "Book3_Y1",
        "Book3_Z1",
        "Sheet1",
    ),
    "refs/public/zenodo/zenodo-4708192-fig5.opju": (
        "Book1",
        "Book1_A",
        "Book1_A@2",
        "Book1_B",
        "Book1_B@2",
        "Book1_C",
        "Book1_C@2",
        "Book1_D",
        "Book1_D@2",
        "Sheet1",
        "Sheet2",
        "Sheet3",
        "Sheet4",
    ),
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": (
        "Book1",
        "Book1_A",
        "Book1_A@2",
        "Book1_B",
        "Book1_B@2",
        "Book1_C",
        "Book1_C@2",
        "Sheet1",
        "Sheet2",
    ),
}

_PUBLIC_OPJU_FIGURE_VALUE_GOLDENS: dict[str, dict[str, dict[int, list[str]]]] = {
    "refs/public/zenodo/zenodo-4708192-fig6a-d.opju": {
        "Book1/FitLinear1": {
            1: [
                "cell://[Book1]FitLinear1!Notes.Equation.row_label",
            ],
            2: [
                "cell://[Book1]FitLinear1!Notes.Weight.row_label",
            ],
            3: [
                "cell://[Book1]FitLinear1!RegStats.SSR.row_label",
            ],
            4: [
                "cell://[Book1]FitLinear1!RegStats.Correlation.row_label",
            ],
            5: [
                "cell://[Book1]FitLinear1!RegStats.RSqCOD.row_label",
            ],
            6: [
                "cell://[Book1]FitLinear1!RegStats.AdjRSq.row_label",
            ],
        },
        "Book1/FitLinear2": {
            2: [
                "cell://[Book1]FitLinear2!Notes.Weight.row_label",
            ],
            3: [
                "cell://[Book1]FitLinear2!RegStats.SSR.row_label",
            ],
            4: [
                "cell://[Book1]FitLinear2!RegStats.Correlation.row_label",
            ],
            5: [
                "cell://[Book1]FitLinear2!RegStats.RSqCOD.row_label",
            ],
            6: [
                "cell://[Book1]FitLinear2!RegStats.AdjRSq.row_label",
            ],
        },
        "Book1/FitLinear3": {
            4: [
                "cell://[Book1]FitLinear3!RegStats.Correlation.row_label",
            ],
            5: [
                "cell://[Book1]FitLinear3!RegStats.RSqCOD.row_label",
            ],
            6: [
                "cell://[Book1]FitLinear3!RegStats.AdjRSq.row_label",
            ],
        },
        "Book1/FitLinear4": {
            4: [
                "cell://[Book1]FitLinear4!RegStats.Correlation.row_label",
            ],
            5: [
                "cell://[Book1]FitLinear4!RegStats.RSqCOD.row_label",
            ],
            6: [
                "cell://[Book1]FitLinear4!RegStats.AdjRSq.row_label",
            ],
        },
        "Book1/FitLinear5": {
            4: [
                "cell://[Book1]FitLinear5!RegStats.Correlation.row_label",
            ],
            5: [
                "cell://[Book1]FitLinear5!RegStats.RSqCOD.row_label",
            ],
            6: [
                "cell://[Book1]FitLinear5!RegStats.AdjRSq.row_label",
            ],
        },
        "Book1/Sheet3": {
            1: [
                "1",
                "-0.03208982188295166",
                "-0.03208982188295166",
                "-0.03208982188295166",
                "-0.03208982188295166",
                "-0.05359387263568026",
                "-0.03208982188295166",
            ],
            2: [
                "2",
                "-0.015816539440203572",
                "-0.015816539440203572",
                "-0.015816539440203572",
                "-0.031156997455470736",
                "0.053593872635680204",
                "-0.03208982188295166",
            ],
        },
        "Book1/Sheet4": {
            1: [
                "1",
                "35.64",
                "0.006139828700217759",
                "0.006139828700217759",
                "0.23786017129978224",
                "0.006139828700217759",
                "-0.020643574904908757",
                "14.705882352941178",
                "-0.020492668048080115",
                "7.352941176470589",
            ],
            2: [
                "2",
                "17.11",
                "-0.020643574904908757",
                "-0.020643574904908757",
                "0.30764357490490873",
                "-0.020643574904908757",
                "0.003367203240549732",
                "38.23529411764706",
                "0.020492668048080243",
                "92.64705882352942",
            ],
        },
    },
    "refs/public/zenodo/zenodo-4708192-fig7e-7f.opju": {
        "Book2_A": {
            1: ["10"],
            2: ["20"],
            3: ["30"],
        },
        "Book2_C": {
            3: ["Roncador"],
            4: ["Roncador"],
        },
        "Book3_E": {
            3: ["Roncador"],
            4: ["Roncador"],
        },
        "Book4": {
            1: ["cell://[Book4]FitLinear1!Notes.Equation"],
            2: ["cell://[Book4]FitLinear1!Parameters.Intercept.row_label"],
            3: ["cell://[Book4]FitLinear1!Notes.Weight"],
            9: ["cell://[Book4]FitLinear1!RegStats.C1.AdjRSq"],
        },
        "Book4/FitLinear1": {
            2: ["cell://[Book4]FitLinear1!Notes.Weight.row_label"],
            3: ["cell://[Book4]FitLinear1!RegStats.SSR.row_label"],
        },
        "Book4/FitLinear17": {
            3: ["cell://[Book4]FitLinear17!Notes.Weight"],
            1: ["cell://[Book4]FitLinear17!Notes.Equation"],
            2: ["cell://[Book4]FitLinear17!Parameters.Intercept.row_label"],
            4: ["cell://[Book4]FitLinear17!Parameters.Intercept.Value+Error"],
            5: ["cell://[Book4]FitLinear17!Parameters.Slope.Value+Error"],
            6: ["cell://[Book4]FitLinear17!RegStats.C1.SSR"],
            8: ["cell://[Book4]FitLinear17!RegStats.C1.RSqCOD"],
            9: ["cell://[Book4]FitLinear17!RegStats.C1.AdjRSq"],
        },
    },
    "refs/public/zenodo/zenodo-4708192-fig7d.opju": {
        "Book1_A": {
            1: ["20"],
            2: ["30"],
            3: ["60"],
            4: ["120"],
            5: ["240"],
            6: ["360"],
        },
        "Book1_G": {
            3: ["Roncador"],
            4: ["Roncador"],
            8: ["Iran"],
            9: ["Iran"],
        },
    },
}

_PUBLIC_OPJU_FIGURE_PREVIEW_NAMES: dict[str, list[str]] = {
    "refs/public/zenodo/zenodo-3779638-fig2.opju": [
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-3779638-fig3.opju": [
        "Graph1",
        "Layer",
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-4708192-fig3.opju": [
        "Graph1",
        "Graph2",
        "Graph3",
        "Graph4",
        "Graph7",
        "Layer",
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-4708192-fig5.opju": [
        "Graph1",
        "Graph2",
        "Graph3",
        "Graph4",
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-4708192-fig6a-d.opju": [
        "Graph1",
        "Graph1.Label_Row1.Label_Col1",
        "Graph10001.Label_Row1.Label_Col1",
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-4708192-fig6e-f.opju": [
        "Graph1",
        "Graph3",
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-4708192-fig7d.opju": [
        "origin_storage_preview_000",
    ],
    "refs/public/zenodo/zenodo-4708192-fig7e-7f.opju": [
        "Graph1",
        "Graph2",
        "Graph4",
        "Graph5",
        "Graph6",
        "Graph7",
        "Layer",
        "origin_storage_preview_000",
    ],
}


def _extract_table_row_values(path: Path, *, row_in_table: int) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header == ["table_id", "row_in_table", "offset", "columns", "values"]:
            for row in reader:
                if len(row) < 5 or int(row[1]) != row_in_table:
                    continue
                return [cell for cell in row[4].split(";") if cell]
        else:
            for index, row in enumerate(reader, start=1):
                if index == row_in_table:
                    return row
    raise AssertionError(f"Missing row_in_table={row_in_table} in {path}")


def _has_image_signature(payload: bytes) -> bool:
    return any(payload.startswith(signature) for signature in (PNG_SIG, JPEG_SIG, *GIF_SIGS))


def _assert_worksheet_rows_match_expectation(
    sample: Path,
    items: dict[str, dict[str, Any]],
    *,
    expected_rows: dict[str, int],
) -> None:
    expected_names = set(expected_rows)
    assert expected_names <= items.keys(), (
        f"Missing expected worksheet names for {sample}: {sorted(expected_names.difference(items.keys()))}"
    )
    for name, expected_row_count in expected_rows.items():
        item = items[name]
        assert item.get("status") == "extracted"
        assert item.get("error") is None
        assert item.get("rows") == expected_row_count
        assert item.get("columns", 0) > 0


def _assert_windowed_non_collection_failures(payload: dict[str, Any], *, sample: Path) -> None:
    file_size = len(sample.read_bytes())
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        name = item.get("name")
        if not isinstance(name, str):
            continue
        if str(name).endswith("_collection"):
            continue
        if item.get("status") not in {"partial", "unsupported"}:
            continue
        if kind in {"raw_gap", "raw_dump", "text_region", "table_scan", "strings"}:
            continue
        if kind in {"origin_object_inventory", "project_tree"}:
            continue

        start = item.get("range_start")
        end = item.get("range_end")
        assert isinstance(start, int), f"Expected range_start for {kind} {name}"
        assert isinstance(end, int), f"Expected range_end for {kind} {name}"
        assert 0 <= start <= end <= file_size


def _assert_metadata_targets(payload: dict[str, Any], metadata_kind: str, target_kind: str) -> None:
    metadata_items = [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict)
        and item.get("kind") == metadata_kind
        and not str(item.get("name", "")).endswith("_collection")
    ]
    if not metadata_items:
        return

    source_paths = {
        item.get("source_object_path")
        for item in payload.get("items", [])
        if isinstance(item, dict)
        and item.get("kind") == target_kind
        and not str(item.get("name", "")).endswith("_collection")
        and item.get("source_object_path") is not None
    }
    for item in metadata_items:
        source = item.get("source_object_path")
        assert isinstance(source, str) and source, f"Expected source_object_path on {metadata_kind} {item.get('name')}"
        assert source in source_paths, f"Expected {metadata_kind} {item.get('name')} to map to a {target_kind} artifact"
