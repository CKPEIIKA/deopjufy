"""Backward-compatible compatibility module for legacy imports."""

from __future__ import annotations

from ..regions import OpjuOriginStorageCandidate, iter_origin_storage_candidates

__all__ = ["OpjuOriginStorageCandidate", "iter_origin_storage_candidates"]
