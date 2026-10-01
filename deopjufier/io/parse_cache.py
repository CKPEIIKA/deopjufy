"""Per-command memo of results derived from input files.

The CLI opens one scope for each command. Inside it, file reads and parse
results are memoized by file identity (resolved path, size, mtime) and call
parameters, so repeated discovery passes in one command share work. Outside a
scope nothing is memoized, and nothing outlives the command that produced it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TypeVar, cast

_T = TypeVar("_T")

_ACTIVE_STORE: ContextVar[dict[tuple[object, ...], object] | None] = ContextVar("deopjufy_parse_cache", default=None)


@contextmanager
def parse_cache_scope() -> Iterator[None]:
    """Memoize file-derived results until the block exits."""
    token = _ACTIVE_STORE.set({})
    try:
        yield
    finally:
        _ACTIVE_STORE.reset(token)


def file_key(path: Path | None, *parts: object) -> tuple[object, ...] | None:
    """Identify one file state plus call parameters, or None when the file is unavailable."""
    if path is None:
        return None
    try:
        stats = path.stat()
    except OSError:
        return None
    return (path.resolve(), stats.st_size, stats.st_mtime_ns, *parts)


def memoized(namespace: str, key: tuple[object, ...] | None, compute: Callable[[], _T]) -> _T:
    """Return the scoped result for ``key``, computing it once per command."""
    store = _ACTIVE_STORE.get()
    if store is None or key is None:
        return compute()
    scoped_key = (namespace, *key)
    if scoped_key not in store:
        store[scoped_key] = compute()
    return cast(_T, store[scoped_key])
