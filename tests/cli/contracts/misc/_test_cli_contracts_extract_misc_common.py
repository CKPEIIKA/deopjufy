"""Core CLI and helper contract tests for deopjufier."""

# ruff: noqa: F401

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from deopjufier.cli import main
from deopjufier.commands import support as command_support
from deopjufier.detect import detect_file
from deopjufier.errors import CorruptedInputError
from deopjufier.io import sanitize_name
from deopjufier.session import ExtractionSession
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))

_OPJ_OPJU_OVERCLAIM_PATTERNS = (
    r"complete\s+parser-confirmed",
    r"complete\s+`?\.opj`?\s+and\s+`?\.opju`?",
    r"current(?:ly)?\s+(?:has|provides|offers|is)\s+full",
    r"(?:opj|opju)\s+(?:has|provides|offers|is)\s+full\s+support",
    r"parser-backed.*worksheet/matrix.*in\s+(?:all|every)",
    r"parser-backed.*object\s*trees.*in\s+(?:all|every)",
    r"all\s+real\s+fixtures",
    r"all\s+`?\.opj`?/`?\.opju`?\s+inputs",
    r"all\s+fixtures",
    r"full\s+(?:graph|parser)\s+(?:reconstruction|support)",
)


def _assert_no_overclaim_support_language(text: str, source: str) -> None:
    for pattern in _OPJ_OPJU_OVERCLAIM_PATTERNS:
        assert re.search(pattern, text, flags=re.IGNORECASE) is None, (
            f"{source} still contains overclaim pattern: {pattern}"
        )


def _record_parser_backed_objects(seen: dict[str, bool], *, label: str) -> object:
    def _step(*_args: object, **kwargs: object) -> int:
        objects = kwargs.get("objects")
        if not isinstance(objects, list):
            objects = []
        seen[label] = seen.get(label, False) or any(
            getattr(obj, "parser_confirmed", False) for obj in objects if obj is not None
        )
        return 0

    return _step


__all__ = [name for name in globals() if not name.startswith("__")]
