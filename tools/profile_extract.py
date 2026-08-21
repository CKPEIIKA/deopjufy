from __future__ import annotations

import cProfile
import pstats
import shutil
import tempfile
from pathlib import Path

from deopjufier.cli import main


def run_profile(*args: str) -> int:
    outdir = Path(tempfile.mkdtemp(prefix="deopjufier-prof-"))
    profiler = cProfile.Profile()
    try:
        profiler.enable()
        code = main([*list(args), "-o", str(outdir)])
        profiler.disable()
        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative").print_stats(40)
        return code
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


if __name__ == "__main__":
    import sys

    raise SystemExit(run_profile(*sys.argv[1:]))
