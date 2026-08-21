"""Contains logic ported from liborigin
(https://sourceforge.net/projects/liborigin/), GPL-3.0.

Small cursor abstraction for OPJ object-stream parsing.
"""

from __future__ import annotations

from dataclasses import dataclass


class OpjStreamError(ValueError):
    """Raised when an OPJ object stream fails a bounds or delimiter check."""

    def __init__(self, message: str, *, offset: int | None = None) -> None:
        suffix = f" at offset {offset}" if offset is not None else ""
        super().__init__(f"{message}{suffix}")
        self.offset = offset


@dataclass
class OpjStream:
    """Bounds-checked cursor over OPJ object bytes."""

    data: bytes
    _offset: int = 0

    @property
    def offset(self) -> int:
        """Current stream offset."""
        return self._offset

    def seek(self, offset: int) -> None:
        """Move cursor to ``offset``."""
        if not 0 <= offset <= len(self.data):
            raise OpjStreamError("offset outside data", offset=offset)
        self._offset = offset

    @property
    def at_eof(self) -> bool:
        """Whether the cursor is at end of stream."""
        return self._offset >= len(self.data)

    def _ensure(self, count: int) -> None:
        if self._offset + count > len(self.data):
            raise OpjStreamError("insufficient bytes", offset=self._offset)

    def read_u32_le(self) -> int:
        """Read a little-endian ``u32`` from the stream."""
        self._ensure(4)
        value = int.from_bytes(self.data[self._offset : self._offset + 4], "little")
        self._offset += 4
        return value

    def read_byte(self) -> bytes:
        """Read one byte."""
        self._ensure(1)
        value = self.data[self._offset : self._offset + 1]
        self._offset += 1
        return value

    def read(self, size: int) -> bytes:
        """Read exactly ``size`` bytes."""
        if size <= 0:
            return b""
        self._ensure(size)
        start = self._offset
        self._offset += size
        return self.data[start : start + size]

    def read_object_size(self) -> int:
        """Parse one ``u32 size`` entry.

        This mirrors ``OriginAnyParser::readObjectSize``:
        4-byte little-endian size plus a mandatory ``\\n``.
        """
        value = self.read_u32_le()
        delimiter = self.read_byte()
        if delimiter != b"\n":
            raise OpjStreamError("bad object-size delimiter", offset=self._offset - 1)
        return value

    def read_object(self, size: int) -> bytes:
        """Parse one object payload and optional delimiter.

        This mirrors ``OriginAnyParser::readObjectAsString``:
        read ``size`` payload bytes, then one ``\\n`` if ``size > 0``.
        """
        payload = self.read(size)
        if size == 0:
            return payload
        delimiter = self.read_byte()
        if delimiter != b"\n":
            raise OpjStreamError("bad object payload delimiter", offset=self._offset - 1)
        return payload
