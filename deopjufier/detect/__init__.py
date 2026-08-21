"""Very small file detector used by CLI paths."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ZIP_LOCAL_HEADER = b"PK\x03\x04"
SQLITE_MAGIC = b"SQLite format 3\x00"
TEXT_ISLAND_MIN_LENGTH = 64
XML_ISLAND_MIN_LENGTH = 64
CONTAINER_TEXT_MAX_LENGTH = 16 * 1024
CONTAINER_ZLIB_SCAN_BYTES = 32 * 1024
ZLIB_HEADER_LENGTH = 2

_XML_DECLARATION_PATTERN = re.compile(rb"<\?xml[^>]*\?>", re.IGNORECASE)
_XML_TAG_PATTERN = re.compile(rb"<([A-Za-z_][A-Za-z0-9_.:-]*)(?:\s[^>]*)?>", re.IGNORECASE)
_TEXT_ISLAND_PATTERN = re.compile(rb"[\t\n\r -~]{64,}")

ORIGIN_OPJU_MAGIC = b"CPYUA"
ORIGIN_OPJ_MAGIC = b"CPYA"
KNOWN_ORIGIN_TYPES = {"opj", "opju"}

MAGIC_SAMPLE = (
    # OriginLab OPJ family formats (header signatures).
    # CPYUA must be checked before CPYA because CPYUA starts with CPYA.
    (ORIGIN_OPJU_MAGIC, "opju", 0.99, "magic"),
    (ORIGIN_OPJ_MAGIC, "opj", 0.99, "magic"),
    (ZIP_LOCAL_HEADER, "zip_container", 0.8, "magic"),
    (SQLITE_MAGIC, "sqlite_db", 0.8, "magic"),
    (b"\x89PNG\r\n\x1a\n", "png", 0.8, "magic"),
    (b"\xff\xd8", "jpeg", 0.8, "magic"),
)


@dataclass(frozen=True)
class DetectedFile:
    path: Path
    detected_type: str
    confidence: float
    reason: str
    magic_type: str | None = None
    magic_offset: int | None = None


@dataclass(frozen=True)
class ContainerProbe:
    kind: str
    offset: int
    length: int
    confidence: float


def _classify_magic(magic: bytes) -> tuple[str, float, str] | None:
    for signature, kind, confidence, reason in MAGIC_SAMPLE:
        if magic.startswith(signature):
            return kind, confidence, reason
    return None


def _is_zip_likely(data: bytes, offset: int) -> bool:
    if offset + 30 > len(data):
        return False
    method = int.from_bytes(data[offset + 8 : offset + 10], "little")
    return method in {0, 8, 12, 14, 98}


def _zip_like_length(data: bytes, offset: int) -> int:
    if offset + 30 > len(data):
        return 0
    filename_len = int.from_bytes(data[offset + 26 : offset + 28], "little")
    extra_len = int.from_bytes(data[offset + 28 : offset + 30], "little")
    header_len = 30 + filename_len + extra_len
    data_start = offset + header_len
    if data_start > len(data):
        return 0
    compressed_len = int.from_bytes(data[offset + 18 : offset + 22], "little")
    if compressed_len == 0:
        return min(len(data), data_start) - offset
    if data_start + compressed_len > len(data):
        return min(len(data), data_start) - offset
    return min(len(data), data_start + compressed_len) - offset


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def _sqlite_like_length(data: bytes, offset: int) -> int:
    if offset + 100 > len(data):
        return 0
    page_size = int.from_bytes(data[offset + 16 : offset + 18], "big")
    if page_size == 1:
        page_size = 65536
    if page_size < 512:
        return 0
    if page_size > 65536:
        return 0
    if not _is_power_of_two(page_size):
        return 0
    write_version = data[offset + 18]
    read_version = data[offset + 19]
    if write_version not in {1, 2} or read_version not in {1, 2}:
        return 0
    return min(len(data) - offset, page_size)


def _is_valid_zlib_header(data: bytes, offset: int) -> bool:
    if offset + 2 > len(data):
        return False
    cmf = data[offset]
    flg = data[offset + 1]
    return (cmf & 0x0F) == 8 and ((cmf << 8 | flg) % 31) == 0


def _zlib_like_length(data: bytes, offset: int) -> int | None:
    if not _is_valid_zlib_header(data, offset):
        return None
    scan_end = min(len(data), offset + CONTAINER_ZLIB_SCAN_BYTES)
    chunk = data[offset:scan_end]
    try:
        decompressor = zlib.decompressobj()
        decompressor.decompress(chunk)
    except zlib.error:
        return None
    if decompressor.eof:
        return max(2, scan_end - offset - len(decompressor.unused_data))
    return max(2, scan_end - offset)


def _overlap(a_offset: int, a_length: int, b_offset: int, b_length: int) -> bool:
    return not (a_offset + a_length <= b_offset or b_offset + b_length <= a_offset)


def _contains_non_overlap(probe: ContainerProbe, existing: list[ContainerProbe]) -> bool:
    return all(not _overlap(probe.offset, probe.length, item.offset, item.length) for item in existing)


def _looks_like_text(region: bytes) -> bool:
    if len(region) < TEXT_ISLAND_MIN_LENGTH:
        return False
    alpha_num = sum(1 for b in region if (65 <= b <= 90) or (97 <= b <= 122) or (48 <= b <= 57))
    spaces = region.count(32) + region.count(9) + region.count(10) + region.count(13)
    return alpha_num >= len(region) * 0.28 and spaces >= 1


def _find_xml_islands(data: bytes) -> list[ContainerProbe]:
    probes: list[ContainerProbe] = []
    for match in _XML_DECLARATION_PATTERN.finditer(data):
        probes.append(
            ContainerProbe(
                kind="xml_island",
                offset=match.start(),
                length=match.end() - match.start(),
                confidence=0.98,
            )
        )

    for match in _XML_TAG_PATTERN.finditer(data):
        tag = match.group(1).decode("ascii", errors="ignore")
        if not tag:
            continue
        close_token = f"</{tag}>".encode("ascii")
        close = data.find(close_token, match.end())
        if close < 0:
            self_close = data.find(b"/>", match.end())
            if self_close >= 0 and self_close < match.end() + 128:
                end = self_close + 2
            else:
                continue
        else:
            close_end = data.find(b">", close + len(close_token))
            if close_end < 0:
                continue
            end = close_end + 1
        span = end - match.start()
        if span < XML_ISLAND_MIN_LENGTH or span > CONTAINER_TEXT_MAX_LENGTH:
            continue
        probes.append(
            ContainerProbe(
                kind="xml_island",
                offset=match.start(),
                length=span,
                confidence=0.92,
            )
        )

    probes.sort(key=lambda probe: (probe.offset, probe.length))
    accepted: list[ContainerProbe] = []
    for probe in sorted(probes, key=lambda probe: probe.length, reverse=True):
        if _contains_non_overlap(probe, accepted):
            accepted.append(probe)
    return sorted(accepted, key=lambda probe: probe.offset)


def _find_text_islands(data: bytes, *, xml_spans: list[ContainerProbe]) -> list[ContainerProbe]:
    candidates: list[ContainerProbe] = []
    for match in _TEXT_ISLAND_PATTERN.finditer(data):
        length = match.end() - match.start()
        span_len = min(length, CONTAINER_TEXT_MAX_LENGTH)
        segment = data[match.start() : match.start() + span_len]
        if not _looks_like_text(segment):
            continue
        if any(_overlap(match.start(), span_len, xml.offset, xml.length) for xml in xml_spans):
            continue
        candidates.append(
            ContainerProbe(
                kind="text_island",
                offset=match.start(),
                length=span_len,
                confidence=0.45,
            )
        )
    return candidates


def probe_container_regions(data: bytes) -> list[ContainerProbe]:
    """Return deterministic container-like region probes for reconnaissance."""
    if not data:
        return []

    probes: list[ContainerProbe] = []

    offset = 0
    while True:
        hit = data.find(ZIP_LOCAL_HEADER, offset)
        if hit < 0:
            break
        if _is_zip_likely(data, hit):
            length = _zip_like_length(data, hit)
            if length > 0:
                probes.append(
                    ContainerProbe(
                        kind="zip_like",
                        offset=hit,
                        length=length,
                        confidence=0.92,
                    )
                )
        offset = hit + len(ZIP_LOCAL_HEADER)

    offset = 0
    while True:
        hit = data.find(SQLITE_MAGIC, offset)
        if hit < 0:
            break
        length = _sqlite_like_length(data, hit)
        if length > 0:
            probes.append(
                ContainerProbe(
                    kind="sqlite_like",
                    offset=hit,
                    length=length,
                    confidence=0.96,
                )
            )
        offset = hit + len(SQLITE_MAGIC)

    offset = data.find(b"\x78")
    while offset >= 0:
        length = _zlib_like_length(data, offset)
        if length is not None:
            probes.append(
                ContainerProbe(
                    kind="zlib_like",
                    offset=offset,
                    length=length,
                    confidence=0.88,
                )
            )
        offset = data.find(b"\x78", offset + 1)

    xml_spans = _find_xml_islands(data)
    probes.extend(xml_spans)
    probes.extend(_find_text_islands(data, xml_spans=xml_spans))

    return sorted(
        probes,
        key=lambda probe: (probe.offset, probe.kind, probe.length),
    )


@lru_cache(maxsize=512)
def _detect_file_cached(path: str, size: int, mtime_ns: int) -> DetectedFile:
    """Detect file kind from extension and bounded magic bytes.

    Extension checks are accepted, but magic signatures override when they confirm
    a different file family.
    """
    path_obj = Path(path)
    suffix = path_obj.suffix.lower()

    with path_obj.open("rb") as fh:
        magic = fh.read(64)
    magic_hit = _classify_magic(magic)

    if suffix in {".opj", ".opju"}:
        detected_type = "opj" if suffix == ".opj" else "opju"

        if magic_hit is None:
            return DetectedFile(
                path=path_obj,
                detected_type=detected_type,
                confidence=0.95,
                reason="extension",
                magic_type=None,
                magic_offset=None,
            )

        if magic_hit[0] in KNOWN_ORIGIN_TYPES:
            if magic_hit[0] == detected_type:
                return DetectedFile(
                    path=path_obj,
                    detected_type=detected_type,
                    confidence=magic_hit[1],
                    reason="extension",
                    magic_type=magic_hit[0],
                    magic_offset=0,
                )

            return DetectedFile(
                path=path_obj,
                detected_type=magic_hit[0],
                confidence=magic_hit[1],
                reason="magic",
                magic_type=magic_hit[0],
                magic_offset=0,
            )

        return DetectedFile(
            path=path_obj,
            detected_type=detected_type,
            confidence=0.95,
            reason="extension",
            magic_type=magic_hit[0],
            magic_offset=0,
        )

    if magic_hit is None:
        return DetectedFile(
            path=path_obj,
            detected_type="unknown",
            confidence=0.05,
            reason="no-match",
        )

    kind, confidence, reason = magic_hit
    return DetectedFile(
        path=path_obj,
        detected_type=kind,
        confidence=confidence,
        reason=reason,
        magic_type=kind,
        magic_offset=0,
    )


def detect_file(path: Path) -> DetectedFile:
    stats = path.stat()
    return _detect_file_cached(str(path), stats.st_size, stats.st_mtime_ns)
