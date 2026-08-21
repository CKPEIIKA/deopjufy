"""Lock native image carving to independently observed binwalk evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from deopjufier.blocks import find_all_blocks
from tests.test_core_unit_coverage_utils import _repo_root

ROOT = _repo_root(Path(__file__))

BINWALK_PNG_EVIDENCE: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    (
        "refs/public/zenodo/zenodo-10721640-figure-1b.opju",
        ((19780, 13235),),
    ),
    (
        "refs/public/zenodo/zenodo-19549171-small-science-paper.opju",
        (
            (232723, 24731),
            (283397, 18624),
            (327385, 23248),
            (379477, 23484),
            (509777, 45220),
            (563735, 11920),
            (584357, 16832),
            (609910, 11885),
            (630500, 16553),
            (655724, 13160),
            (677756, 13368),
            (725927, 28291),
            (782739, 41103),
            (841495, 17792),
        ),
    ),
    (
        "refs/public/zenodo/zenodo-18450855-eucd2p2.opju",
        (
            (8564064, 14523),
            (8645775, 11456),
            (8704057, 13890),
            (8737137, 9053),
            (8767906, 12333),
            (8829673, 16643),
            (8848349, 24294),
            (8874681, 16134),
            (8895714, 15850),
            (8976859, 27975),
            (9129627, 20751),
            (9192921, 31370),
            (9226165, 10005),
            (9278485, 28558),
        ),
    ),
)


@pytest.mark.parametrize(("relative_path", "expected"), BINWALK_PNG_EVIDENCE)
def test_native_png_carving_matches_binwalk_offsets_and_lengths(
    relative_path: str,
    expected: tuple[tuple[int, int], ...],
) -> None:
    sample = ROOT / relative_path
    if not sample.exists():
        pytest.skip(f"fixture missing: {sample}")

    actual = tuple(
        (block.offset, block.length) for block in find_all_blocks(sample) if block.kind == "png" and block.valid
    )

    assert actual == expected
