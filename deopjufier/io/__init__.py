"""IO helpers for deterministic stream handling."""

from __future__ import annotations

import hashlib
import mmap
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


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
        try:
            with mmap.mmap(fh.fileno(), length=0, access=mmap.ACCESS_READ) as mapped:
                yield mapped
        except (OSError, ValueError):
            yield None


@lru_cache(maxsize=64)
def _read_cached_bytes(path: str, size: int, mtime_ns: int) -> bytes:
    return Path(path).read_bytes()


def read_cached_bytes(path: Path) -> bytes:
    """Read a file into memory once per stat signature."""
    stats = path.stat()
    return _read_cached_bytes(str(path), stats.st_size, stats.st_mtime_ns)


@lru_cache(maxsize=512)
def _sha256_file_cached(path: str, size: int, mtime_ns: int) -> str:
    h = hashlib.sha256()
    for chunk in iter_file_chunks(Path(path)):
        h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    """Compute sha256 for a file path with stat-keyed caching."""
    stats = path.stat()
    return _sha256_file_cached(str(path), stats.st_size, stats.st_mtime_ns)


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
        fh.seek(offset)
        return fh.read(length)
