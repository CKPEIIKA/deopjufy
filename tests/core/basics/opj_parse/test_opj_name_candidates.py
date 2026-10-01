"""OPJ lookup candidates must come in a fixed, most-specific-first order."""

from __future__ import annotations

import subprocess
import sys

from deopjufier.opj.boundaries import _iter_opj_name_candidates


def test_candidates_are_ordered_most_specific_first() -> None:
    assert _iter_opj_name_candidates("PdMSheet1_A@3") == ["pdmsheet1_a", "pdmsheet1", "msheet1_a", "sheet1_a"]
    assert _iter_opj_name_candidates("cross_theta0jN2N2@2") == ["cross_theta0jn2n2", "cross"]


def test_candidate_order_does_not_depend_on_hash_seed() -> None:
    script = (
        "from deopjufier.opj.boundaries import _iter_opj_name_candidates;"
        "print(_iter_opj_name_candidates('PdMSheet1_A@3'), _iter_opj_name_candidates('cross_theta0jN2N2@2'))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": str(seed), "PATH": ""},
        ).stdout
        for seed in range(6)
    }

    assert len(outputs) == 1
