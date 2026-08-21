"""Simple string extraction helpers."""

from __future__ import annotations

import codecs
import re
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path

from deopjufier.io import iter_file_chunks

_UTF16_LINE_SPLIT = re.compile(r"\s+")


@lru_cache(maxsize=16)
def _ascii_pattern(min_length: int) -> re.Pattern[bytes]:
    min_length = max(min_length, 1)
    return re.compile(rb"[ -~]" + f"{{{min_length},}}".encode())


def _iter_ascii_strings(path: Path, min_length: int = 4) -> Iterator[str]:
    printable = _ascii_pattern(min_length)
    overlap = max(min_length - 1, 1)
    carry = b""

    for block in iter_file_chunks(path):
        current = block if not carry else carry + block
        last_match_touches_end = False
        matched = False
        block_len = len(current)

        for match in printable.finditer(current):
            matched = True
            start, end = match.span()
            if end == block_len:
                carry = current[start:]
                last_match_touches_end = True
                break
            yield match.group().decode("ascii", "ignore")

        if not matched:
            carry = current[-overlap:]
        elif not last_match_touches_end:
            carry = b""

    if carry:
        for m in printable.finditer(carry):
            if len(m.group()) >= min_length:
                yield m.group().decode("ascii", "ignore")


def _iter_ascii_strings_from_bytes(raw: bytes, min_length: int = 4) -> Iterator[str]:
    printable = _ascii_pattern(min_length)
    for match in printable.finditer(raw):
        yield match.group().decode("ascii", "ignore")


def _iter_utf16_strings(path: Path, min_length: int = 4) -> Iterator[str]:
    carry_bytes = b""
    carry_line = ""
    for block in iter_file_chunks(path, chunk_size=1 << 16):
        payload = carry_bytes + block
        if len(payload) < 2:
            carry_bytes = payload
            continue

        if len(payload) & 1:
            carry_bytes = payload[-1:]
            payload = payload[:-1]
        else:
            carry_bytes = b""

        text = payload.decode("utf-16", errors="ignore")
        text = carry_line + text
        lines = text.splitlines()
        if text and not text.endswith(("\n", "\r")):
            carry_line = lines[-1] if lines else ""
            lines = lines[:-1]
        else:
            carry_line = ""

        for line in lines:
            value = line.strip()
            if _UTF16_LINE_SPLIT.sub(" ", value).strip() and len(value) >= min_length:
                yield _UTF16_LINE_SPLIT.sub(" ", value).strip()

    if carry_line.strip():
        value = carry_line.strip()
        value = _UTF16_LINE_SPLIT.sub(" ", value).strip()
        if value and len(value) >= min_length:
            yield value


def _iter_utf16_strings_from_bytes(raw: bytes, min_length: int = 4) -> Iterator[str]:
    if len(raw) < 2:
        return

    if len(raw) & 1:
        raw = raw[:-1]

    text = raw.decode("utf-16", errors="ignore")
    for line in text.splitlines():
        value = _UTF16_LINE_SPLIT.sub(" ", line).strip()
        if value and len(value) >= min_length:
            yield value


def _iter_text_strings_from_bytes(raw: bytes, encoding: str, min_length: int = 4) -> Iterator[str]:
    text = raw.decode(encoding, errors="ignore")
    for line in text.splitlines():
        if len(line) >= min_length:
            yield line.strip()


def _iter_text_strings_from_path(
    path: Path, encoding: str, min_length: int = 4, chunk_size: int = 1 << 16
) -> Iterator[str]:
    # Incremental decode keeps UTF-8 behavior deterministic across chunk boundaries
    # without reading the full input into memory.
    decoder = codecs.getincrementaldecoder(encoding)(errors="ignore")
    carry = ""
    for block in iter_file_chunks(path, chunk_size=chunk_size):
        text = decoder.decode(block)
        if not text and not carry:
            continue

        merged = carry + text
        lines = merged.splitlines()
        if merged and not merged.endswith(("\n", "\r")):
            carry = lines[-1] if lines else merged
            lines = lines[:-1]
        else:
            carry = ""

        for line in lines:
            if len(line) >= min_length:
                yield line.strip()

    tail = decoder.decode(b"", final=True)
    if carry:
        merged = carry + tail
    else:
        merged = tail
    if merged and len(merged) >= min_length:
        yield merged.strip()


def iter_strings(
    source: Path | bytes,
    encoding: str = "ascii",
    min_length: int = 4,
) -> Iterable[str]:
    """Yield visible strings from a binary file."""
    if isinstance(source, bytes):
        if encoding == "ascii":
            yield from _iter_ascii_strings_from_bytes(source, min_length=min_length)
            return
        if encoding in {"utf16", "utf-16", "utf-16le", "utf16le"}:
            yield from _iter_utf16_strings_from_bytes(source, min_length=min_length)
            return
        if encoding in {"latin1", "latin-1", "utf-8", "utf8"}:
            yield from _iter_text_strings_from_bytes(
                source,
                "latin-1" if encoding in {"latin1", "latin-1"} else "utf-8",
                min_length=min_length,
            )
            return
        raise ValueError(f"unsupported encoding: {encoding}")

    path = source
    if encoding == "ascii":
        yield from _iter_ascii_strings(path, min_length=min_length)
    elif encoding in {"utf16", "utf-16", "utf-16le", "utf16le"}:
        yield from _iter_utf16_strings(path, min_length=min_length)
    elif encoding in {"latin1", "latin-1", "utf-8", "utf8"}:
        normalized = "latin-1" if encoding in {"latin1", "latin-1"} else "utf-8"
        yield from _iter_text_strings_from_path(path, normalized, min_length=min_length)
    else:
        raise ValueError(f"unsupported encoding: {encoding}")
