"""Custom errors used by deopjufy command flows."""

from __future__ import annotations


class DeopjufyError(Exception):
    """Base error for expected CLI failures."""


class UnsupportedFileError(DeopjufyError):
    """Raised when file type is not supported for the requested operation."""


class CorruptedInputError(DeopjufyError):
    """Raised when input appears truncated or unreadable."""


class PartialExtractionError(DeopjufyError):
    """Raised when only partial extraction was possible."""
