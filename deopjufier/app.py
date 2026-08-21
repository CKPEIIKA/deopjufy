"""Application layer entrypoints for the deopjufy CLI."""

from __future__ import annotations

from deopjufier.commands import SUPPORTED_TYPES
from deopjufier.commands.dispatch import main as _run_cli
from deopjufier.commands.support import (
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
    NATIVE_BACKEND,
)
from deopjufier.session import ExtractionSession


def main(argv: list[str] | None = None) -> int:
    """Run the CLI program and return the exit code."""
    return _run_cli(argv)


__all__ = [
    "EXIT_CORRUPTED",
    "EXIT_GENERAL",
    "EXIT_MISSING_DEPENDENCY",
    "EXIT_PARTIAL",
    "EXIT_SUCCESS",
    "EXIT_UNSUPPORTED",
    "EXIT_USAGE",
    "NATIVE_BACKEND",
    "SUPPORTED_TYPES",
    "ExtractionSession",
    "main",
]
