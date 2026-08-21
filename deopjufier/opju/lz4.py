"""OPJU LZ4 block decompression helpers.

This module intentionally keeps a tiny stdlib-only implementation so parser logic
can operate on decoded Origin containers without external runtime
dependencies.
"""

from __future__ import annotations


def lz4_block_decompress(src: bytes, expected_size: int) -> tuple[bytes, int]:
    """Decode one raw LZ4 block.

    Args:
        src: Source bytes beginning at the LZ4 block offset.
        expected_size: Uncompressed size declared by OPJU region header.

    Returns:
        A tuple of decoded bytes and the number of bytes consumed from ``src``.

    Raises:
        ValueError: If the stream cannot decode to ``expected_size`` bytes.
    """
    if expected_size < 0:
        raise ValueError("bad LZ4 expected size")

    out: bytearray = bytearray()
    cursor = 0

    while cursor < len(src) and len(out) < expected_size:
        token = src[cursor]
        cursor += 1

        literal_count = token >> 4
        if literal_count == 15:
            while cursor < len(src):
                extension = src[cursor]
                cursor += 1
                literal_count += extension
                if extension != 255:
                    break

        out.extend(src[cursor : cursor + literal_count])
        cursor += literal_count
        if len(out) >= expected_size or cursor >= len(src):
            break

        if cursor + 1 >= len(src):
            raise ValueError("bad LZ4 offset")
        offset = src[cursor] | (src[cursor + 1] << 8)
        cursor += 2
        if offset <= 0 or offset > len(out):
            raise ValueError("bad LZ4 back-reference")

        match_length = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while cursor < len(src):
                extension = src[cursor]
                cursor += 1
                match_length += extension
                if extension != 255:
                    break

        for _ in range(match_length):
            if len(out) >= expected_size:
                break
            out.append(out[-offset])

    if len(out) != expected_size:
        raise ValueError("LZ4 block shorter than declared size")
    return bytes(out), cursor
