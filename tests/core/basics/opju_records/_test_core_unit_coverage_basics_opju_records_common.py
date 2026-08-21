"""Split coverage for OPJU report, table, and structural record parsing."""

# ruff: noqa: F401

from __future__ import annotations

import base64
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import deopjufier.inventory
from deopjufier.blocks import ImageBlock
from deopjufier.extract.discovery_helpers import book_dir as _book_dir
from deopjufier.extract.discovery_helpers import (
    find_graph_block_for_object as _find_graph_block_for_object,
)
from deopjufier.extract.path_helpers import manifest_relative_path as _manifest_path
from deopjufier.inventory import (
    discover_origin_objects,
    parse_opju_column_tables,
    parse_opju_origin_storage_reports,
    parse_opju_records,
)
from deopjufier.opju import (
    OpjuColumnTable,
    OpjuOriginStorageReport,
    OpjuRecords,
    OpjuWorksheetRecord,
    recover_matrix_rows_from_opju,
)
from deopjufier.opju import analysis as opju_analysis
from deopjufier.opju import regions as opju_regions
from deopjufier.opju.numeric_runs import OpjuNumericBlobRun, iter_opju_binary_runs_from_file
from deopjufier.opju.recovery import recover_worksheet_rows_from_opju
from deopjufier.opju.recovery_helpers_tokens import (
    _build_worksheet_name_candidate_lookup,
    _expand_adjacent_alpha1_sheet_targets_from_selection,
    _infer_parser_backed_worksheet_names,
)
from deopjufier.opju.recovery_helpers_windows import (
    _iter_family_worksheet_tokens_from_payload,
    _match_family_table_to_worksheet_names,
)
from deopjufier.opju.regions import OpjuOriginStorageCandidate
from deopjufier.opju.tables import (
    _FAMILY_BINARY_FORMULA_MIN_ROWS,
    parse_opju_origin_storage_family_tables,
)
from tests.core.basics.opju_parse._test_core_unit_coverage_basics_opju_parse import (
    SYNTHETIC_BINARY_FIXTURE,
    SYNTHETIC_FIXTURE,
)
from tests.test_core_unit_coverage_utils import _resolve_repo_fixture

_LOCKED_ZENODO_OPJU_RECOVERY_FIXTURES = (
    (
        "figure_1b",
        _resolve_repo_fixture(Path(__file__), "refs/public/zenodo/zenodo-10721640-figure-1b.opju"),
        {"Sheet1"},
        2,
        {"Sheet1"},
    ),
    (
        "eucd2p2",
        _resolve_repo_fixture(Path(__file__), "refs/public/zenodo/zenodo-18450855-eucd2p2.opju"),
        {
            "Book1",
            "Book11",
            "Book11/Sheet1",
            "Book15",
            "Book15/Sheet1",
            "Book15_A",
            "Book15_B",
            "Book2",
            "Sheet1",
            "Sheet2",
        },
        43,
        {"Book1", "Book11", "Book11/Sheet1", "Book15", "Book15/Sheet1", "Book2", "Sheet2"},
    ),
    (
        "ahrrenius_ybscsz",
        _resolve_repo_fixture(Path(__file__), "refs/public/zenodo/zenodo-10364693-ahrrenius-ybscsz.opju"),
        {
            "Book1/FitLinear2",
            "Book1/FitLinear3",
            "Book1/FitLinear4",
            "Book1/FitLinear5",
            "Book1/FitLinear6",
            "Book1/FitLinear7",
            "Book3/FitLinear4",
            "Book3/FitLinear5",
            "Book3/FitLinear6",
            "Book4/FitLinear1",
            "Book4/FitLinear2",
            "Book4/FitLinear3",
            "Book1/Sheet1",
            "Book3/Sheet1",
            "Book4/Sheet1",
        },
        76,
        {
            "Book1/FitLinear2",
            "Book1/FitLinear3",
            "Book1/FitLinear4",
            "Book1/FitLinear5",
            "Book1/FitLinear6",
            "Book1/FitLinear7",
            "Book3/FitLinear4",
            "Book3/FitLinear5",
            "Book3/FitLinear6",
            "Book4/FitLinear1",
            "Book4/FitLinear2",
            "Book4/FitLinear3",
            "Book1/Sheet1",
            "Book3/Sheet1",
            "Book4/Sheet1",
        },
    ),
    (
        "small_science_paper",
        _resolve_repo_fixture(Path(__file__), "refs/public/zenodo/zenodo-19549171-small-science-paper.opju"),
        {
            "Book1_A@7",
            "Book1_AB@7",
            "Book1_AC@7",
            "Book1_AD@7",
            "Book1_AE@7",
            "Book1_AF@7",
            "Book1_AG@7",
            "Book1_AH@7",
            "Book1_AI@7",
            "Book1_AJ@7",
            "Book1_AK@7",
            "Book1_AL@7",
            "Book1_AM@7",
            "Book1_AN@7",
            "Book1_AO@7",
            "Book1_AP@7",
            "Book1_AQ@7",
            "Book1_AR@7",
            "Book1_AS@7",
            "Book1_AT@7",
            "Book1_AU@7",
            "Book1_AV@7",
            "Book1_E@7",
            "Book1_F@7",
            "Book1_P@10",
            "Book1_Y@7",
            "Book1_Z@7",
        },
        31,
        {
            "Book1_A@7",
            "Book1_AB@7",
            "Book1_AC@7",
            "Book1_AD@7",
            "Book1_AE@7",
            "Book1_AF@7",
            "Book1_AG@7",
            "Book1_AH@7",
            "Book1_AI@7",
            "Book1_AJ@7",
            "Book1_AK@7",
            "Book1_AL@7",
            "Book1_AM@7",
            "Book1_AN@7",
            "Book1_AO@7",
            "Book1_AP@7",
            "Book1_AQ@7",
            "Book1_AR@7",
            "Book1_AS@7",
            "Book1_AT@7",
            "Book1_AU@7",
            "Book1_AV@7",
            "Book1_E@7",
            "Book1_F@7",
            "Book1_P@10",
            "Book1_Y@7",
            "Book1_Z@7",
        },
    ),
)
