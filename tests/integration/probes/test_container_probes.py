"""Synthetic byte probes for container-like regions."""

from __future__ import annotations

import zlib

from deopjufier.detect import (
    SQLITE_MAGIC,
    ZIP_LOCAL_HEADER,
    ContainerProbe,
    probe_container_regions,
)


def _zip_local_header() -> bytes:
    header = bytearray(30)
    header[0:4] = ZIP_LOCAL_HEADER
    header[4:6] = (20).to_bytes(2, "little")
    header[8:10] = (8).to_bytes(2, "little")
    header[18:22] = (3).to_bytes(4, "little")
    header[22:26] = (3).to_bytes(4, "little")
    header[26:28] = (0).to_bytes(2, "little")
    header[28:30] = (0).to_bytes(2, "little")
    return bytes(header)


def _sqlite_header() -> bytes:
    header = bytearray(100)
    header[: len(SQLITE_MAGIC)] = SQLITE_MAGIC
    header[16] = 0x10
    header[17] = 0x00
    header[18] = 1
    header[19] = 1
    return bytes(header)


def test_probe_container_regions_detects_zip_like_signature() -> None:
    data = b"lead" + _zip_local_header() + b"abc"
    probes = probe_container_regions(data)

    assert any(probe == ContainerProbe(kind="zip_like", offset=4, length=33, confidence=0.92) for probe in probes)


def test_probe_container_regions_detects_sqlite_magic() -> None:
    data = b"pad" + _sqlite_header()
    probes = probe_container_regions(data)

    assert any(
        probe
        == ContainerProbe(
            kind="sqlite_like",
            offset=3,
            length=100,
            confidence=0.96,
        )
        for probe in probes
    )


def test_probe_container_regions_detects_zlib_stream() -> None:
    compressed = zlib.compress(b"hello " * 120)
    data = b"noise" + compressed
    probes = probe_container_regions(data)

    assert any(probe.kind == "zlib_like" and probe.offset == 5 for probe in probes)


def test_probe_container_regions_detects_xml_and_text_islands() -> None:
    data = (
        b"pad"
        + b"<?xml version='1.0'?>\n"
        + b"<root><child>alpha beta gamma</child></root>\n"
        + b"\x00"
        + (b"plain text block with spaces and digits 12345 " * 4)
        + b"\n"
    )
    probes = probe_container_regions(data)

    assert any(probe.kind == "xml_island" and probe.offset == 3 for probe in probes)
    assert any(probe.kind == "text_island" for probe in probes)


def test_container_region_probing_is_deterministic() -> None:
    compressed = zlib.compress(b"abc" * 32)
    mixed = (
        b"\x00"
        + ZIP_LOCAL_HEADER
        + _zip_local_header()[4:]
        + b"abc"
        + b"\x00" * 32
        + _sqlite_header()
        + b"\x00" * 20
        + compressed
        + b"<a>text text text</a>"
        + b"note text text text\n"
    )
    assert probe_container_regions(mixed) == probe_container_regions(mixed)
