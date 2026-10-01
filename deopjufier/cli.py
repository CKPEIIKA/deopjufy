"""CLI adapter for the deopjufy application layer."""

from __future__ import annotations

import os
import sys

from deopjufier.commands import (
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
    NATIVE_BACKEND,
)
from deopjufier.commands import (
    main as app_main,
)


def main(argv: list[str] | None = None) -> int:
    return app_main(argv)


def cli_entrypoint() -> None:
    try:
        code = main()
        # Flush here so a reader that already closed the pipe (`| head`) is seen
        # now rather than as a flush error during interpreter shutdown.
        sys.stdout.flush()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        code = EXIT_SUCCESS
    raise SystemExit(code)


if __name__ == "__main__":
    cli_entrypoint()


__all__ = [
    "EXIT_CORRUPTED",
    "EXIT_GENERAL",
    "EXIT_MISSING_DEPENDENCY",
    "EXIT_PARTIAL",
    "EXIT_SUCCESS",
    "EXIT_UNSUPPORTED",
    "EXIT_USAGE",
    "NATIVE_BACKEND",
    "cli_entrypoint",
    "main",
]
