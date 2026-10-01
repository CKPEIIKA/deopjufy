"""IO helpers for deterministic stream handling."""

from __future__ import annotations

import hashlib
import mmap
import os
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from deopjufier.io.parse_cache import file_key, memoized


def iter_file_chunks(path: Path, chunk_size: int = 1 << 20) -> Iterable[bytes]:
    """Yield file chunks as bytes."""
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                return
            yield block


@contextmanager
def open_mmap(path: Path) -> Iterator[mmap.mmap | None]:
    """Yield a read-only file mapping when the file can be mapped."""
    if path.stat().st_size == 0:
        yield None
        return

    with path.open("rb") as fh:
        # Guard only the mapping call: errors raised by the caller's block must propagate.
        try:
            mapped = mmap.mmap(fh.fileno(), length=0, access=mmap.ACCESS_READ)
        except (OSError, ValueError):
            yield None
            return
        with mapped:
            yield mapped


def read_cached_bytes(path: Path) -> bytes:
    """Read a file into memory once per command scope (see ``parse_cache``)."""
    return memoized("file_bytes", file_key(path), path.read_bytes)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    for chunk in iter_file_chunks(path):
        h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 of a file once per command scope."""
    return memoized("file_sha256", file_key(path), lambda: _sha256_of_file(path))


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def sanitize_name(value: str) -> str:
    """Replace filesystem-unsafe path chars with `_`."""
    if not value:
        return "item"
    value = value.strip().replace("/", "_").replace("\\", "_")
    value = _sanitize_chars(value)
    value = value.rstrip(" .")

    if not value or value in {".", ".."}:
        return "item"

    stem = value
    suffix = ""
    dot_index = value.rfind(".")
    if dot_index > 0:
        stem = value[:dot_index]
        suffix = value[dot_index:]

    if not stem:
        return "item"

    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    value = f"{stem}{suffix}"
    if value.upper() in _WINDOWS_RESERVED_NAMES:
        value = f"_{value}"
    return value


def _sanitize_chars(value: str) -> str:
    """Collapse non-portable characters to underscores."""
    return _SANITIZE_RE.sub("_", value) or "item"


@dataclass(frozen=True)
class DumpRange:
    offset: int
    length: int


def dump_range(path: Path, offset: int, length: int) -> bytes:
    """Read a single binary slice from a file."""
    if offset < 0 or length < 0:
        raise ValueError("offset and length must be non-negative")

    with path.open("rb") as fh:
        # Never ask read() for more than the file holds; a huge length would allocate it.
        available = max(0, fh.seek(0, os.SEEK_END) - offset)
        fh.seek(offset)
        return fh.read(min(length, available))
