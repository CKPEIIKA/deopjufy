"""Compatibility shim for split core coverage utility helpers."""

from tests.core.misc.test_core_unit_coverage_utils import (
    _make_manifest,
    _repo_root,
    _resolve_repo_fixture,
    _resolve_synthetic_fixture,
    _resolve_tests_fixture,
)

__all__ = [
    "_make_manifest",
    "_repo_root",
    "_resolve_repo_fixture",
    "_resolve_synthetic_fixture",
    "_resolve_tests_fixture",
]
