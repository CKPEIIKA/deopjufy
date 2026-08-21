"""Acceptance tests for OPJ walk counts against committed ground-truth logs."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from deopjufier.opj import walk_opj_file
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))


def _log_path_for(path: Path) -> Path:
    mapping = {
        "refs/github/Ropj/inst/tree.opj": REPO_ROOT / "tests/groundtruth/github-Ropj-inst-tree.opj/opjfile.log",
        "refs/github/Ropj/inst/test.opj": REPO_ROOT / "tests/groundtruth/github-Ropj-inst-test.opj/opjfile.log",
        "refs/openopj/support/test.opj": REPO_ROOT / "tests/groundtruth/openopj-support-test.opj/opjfile.log",
    }

    relative = str(path.relative_to(REPO_ROOT))
    if relative in mapping:
        return mapping[relative]
    raise ValueError(f"no ground truth mapping for {path}")


_GROUND_TRUTH_COUNT_PATTERNS = {
    "dataset": re.compile(r"done\. Data sets:\s*(\d+)"),
    "window": re.compile(r"\.\.\.\s*done\.\s*Windows:\s*(\d+)"),
    "parameter": re.compile(r"\.\.\.\s*done\.\s*Parameters:\s*(\d+)"),
    "note": re.compile(r"done\. Note windows:\s*(\d+)"),
}
_GROUND_TRUTH_WINDOW_NAME_PATTERN = re.compile(r"^Window found: .*: (.+)$")


def _parse_groundtruth_counts(log_path: Path) -> dict[str, int]:
    text = log_path.read_bytes().decode("utf-8", errors="replace")
    counts: dict[str, int] = {}
    for kind, pattern in _GROUND_TRUTH_COUNT_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            counts[kind] = int(matches[-1])
    return counts


def _parse_groundtruth_window_names(log_path: Path) -> list[str]:
    names: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _GROUND_TRUTH_WINDOW_NAME_PATTERN.match(line)
        if match:
            names.append(match.group(1).strip())
    return names


@pytest.mark.parametrize(
    "fixture_rel",
    [
        "refs/github/Ropj/inst/tree.opj",
        "refs/github/Ropj/inst/test.opj",
        "refs/openopj/support/test.opj",
    ],
)
def test_walk_counts_match_opjfile_groundtruth(fixture_rel: str) -> None:
    fixture = REPO_ROOT / fixture_rel
    if not fixture.exists():
        pytest.skip(f"Fixture missing: {fixture}")

    log_path = _log_path_for(fixture)
    if not log_path.exists():
        pytest.skip(f"Ground-truth log missing: {log_path}")

    elements = walk_opj_file(fixture.read_bytes(), tolerant=True)
    observed = Counter(element.kind for element in elements)
    expected = _parse_groundtruth_counts(log_path)
    expected_windows = _parse_groundtruth_window_names(log_path)
    observed_windows = [element.name for element in elements if element.kind == "window"]

    for kind in ("dataset", "window", "parameter", "note"):
        if kind not in expected:
            continue
        assert observed[kind] == expected[kind]

    window_name_checked_fixtures = {
        "refs/github/Ropj/inst/test.opj",
        "refs/github/Ropj/inst/tree.opj",
        "refs/openopj/support/test.opj",
    }
    if fixture_rel in window_name_checked_fixtures and expected_windows:
        assert observed_windows == expected_windows
