"""Parser-backed OPJU page and project-folder directory entries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from deopjufier.io import sanitize_name

_FRAME_MARKER = b"__FRAMESRCDATAINFOS"
_FOLDER_PROPERTY = b"FolderLastUsed"
_FOLDER_PAYLOAD = b"<OriginStorage/>"
_PNG_IEND = b"IEND\xaeB`\x82"
_SYSTEM_MARKER = b"SYSTEM"
_TEXT_RUN = re.compile(rb"[A-Za-z][A-Za-z0-9 _-]{2,31}")
_RESERVED_PAGE_NAMES = frozenset({"IEND", "SYSTEM", "TREE", "_"})
_PAGE_NAME_MAX_BYTES = 96
_PAGE_PREVIEW_MAX_DISTANCE = 24
_PAGE_SYSTEM_MAX_DISTANCE = 512
_PAGE_FRAME_MAX_DISTANCE = 8192


@dataclass(frozen=True)
class OpjuPageDirectoryRecord:
    """A syntactically bounded project-page directory name field."""

    name: str
    template_hint: str
    offset: int
    length: int
    frame_offset: int | None
    preview_terminal_offset: int | None
    source_object_path: str
    parser_rule: str = "opju_page_directory_name"
    confidence: float = 0.96
    structural_name: str = "opju_page_directory_name"
    semantic_alias: str = "project_page_directory_entry"
    semantic_confidence: str = "corpus_high"


@dataclass(frozen=True)
class OpjuFolderDirectoryRecord:
    """A project-folder name tied to its bounded folder property record."""

    name: str
    offset: int
    length: int
    property_offset: int
    source_object_path: str
    parser_rule: str = "opju_folder_directory_name"
    confidence: float = 0.98
    structural_name: str = "opju_folder_directory_name"
    semantic_alias: str = "project_folder_directory_entry"
    semantic_confidence: str = "corpus_high"


def _ascii_run_end(data: bytes, start: int) -> int:
    end = start
    limit = min(len(data), start + _PAGE_NAME_MAX_BYTES)
    while end < limit and 0x20 <= data[end] < 0x7F:
        end += 1
    return end


def _name_prefix_is_tagged(data: bytes, start: int) -> bool:
    prefix = data[max(0, start - 10) : start - 2]
    return b"\x0a" in prefix and any(byte >= 0x80 for byte in prefix)


def _template_hint(data: bytes, start: int, end: int) -> str | None:
    for match in _TEXT_RUN.finditer(data, start, end):
        value = match.group().decode("ascii")
        if value not in _RESERVED_PAGE_NAMES:
            return value
    return None


def _page_evidence(data: bytes, name_start: int, system_offset: int) -> tuple[int | None, int | None]:
    preview_offset = data.rfind(_PNG_IEND, max(0, name_start - _PAGE_PREVIEW_MAX_DISTANCE), name_start)
    frame_offset = data.find(
        _FRAME_MARKER,
        system_offset,
        min(len(data), system_offset + _PAGE_FRAME_MAX_DISTANCE),
    )
    return (frame_offset if frame_offset >= 0 else None, preview_offset if preview_offset >= 0 else None)


def _page_candidate(data: bytes, name_start: int) -> tuple[str, str, int | None, int | None] | None:
    if not _name_prefix_is_tagged(data, name_start):
        return None
    name_end = _ascii_run_end(data, name_start)
    if name_end == name_start or name_end >= len(data):
        return None
    if data[name_end] != 0 and data[name_end] < 0x80:
        return None
    name = data[name_start:name_end].decode("ascii")
    if name in _RESERVED_PAGE_NAMES or len(name) < 4:
        return None
    system_offset = data.find(
        _SYSTEM_MARKER,
        name_end,
        min(len(data), name_end + _PAGE_SYSTEM_MAX_DISTANCE),
    )
    if system_offset < 0:
        return None
    template_hint = _template_hint(data, name_end, system_offset)
    if template_hint is None:
        return None
    frame_offset, preview_offset = _page_evidence(data, name_start, system_offset)
    if frame_offset is None and preview_offset is None:
        return None
    return name, template_hint, frame_offset, preview_offset


def _unique_path(prefix: str, name: str, seen: dict[str, int]) -> str:
    leaf = sanitize_name(name)
    count = seen.get(leaf, 0) + 1
    seen[leaf] = count
    suffix = "" if count == 1 else f"__{count}"
    return f"{prefix}/{leaf}{suffix}"


def parse_opju_page_directory(data: bytes) -> tuple[OpjuPageDirectoryRecord, ...]:
    """Recover conservative page identities without asserting full page ownership."""
    records: list[OpjuPageDirectoryRecord] = []
    seen_paths: dict[str, int] = {}
    cursor = 0
    while (delimiter := data.find(b"\x00\x00", cursor)) >= 0:
        name_start = delimiter + 2
        parsed = _page_candidate(data, name_start)
        if parsed is not None:
            name, template_hint, frame_offset, preview_offset = parsed
            records.append(
                OpjuPageDirectoryRecord(
                    name=name,
                    template_hint=template_hint,
                    offset=name_start,
                    length=len(name.encode("ascii")),
                    frame_offset=frame_offset,
                    preview_terminal_offset=preview_offset,
                    source_object_path=_unique_path("page_directory", name, seen_paths),
                )
            )
        cursor = delimiter + 1
    return tuple(records)


def _folder_name_before_property(data: bytes, property_offset: int) -> tuple[str, int] | None:
    candidates: list[tuple[str, int]] = []
    for field_offset in range(max(0, property_offset - 96), property_offset):
        if field_offset + 5 > len(data) or data[field_offset + 4] != 0x0A:
            continue
        declared_length = int.from_bytes(data[field_offset : field_offset + 4], "little")
        if not 2 <= declared_length <= 64:
            continue
        name_start = field_offset + 5
        name_end = name_start + declared_length - 1
        if name_end >= property_offset or data[name_end] != 0:
            continue
        raw_name = data[name_start:name_end]
        if raw_name and all(0x20 <= byte < 0x7F for byte in raw_name):
            candidates.append((raw_name.decode("ascii"), name_start))
    return candidates[-1] if candidates else None


def parse_opju_folder_directory(data: bytes) -> tuple[OpjuFolderDirectoryRecord, ...]:
    """Recover folder-entry names while leaving hierarchy IDs uninterpreted."""
    records: list[OpjuFolderDirectoryRecord] = []
    seen_paths: dict[str, int] = {}
    cursor = 0
    while (property_offset := data.find(_FOLDER_PROPERTY, cursor)) >= 0:
        payload_end = min(len(data), property_offset + 96)
        parsed = _folder_name_before_property(data, property_offset)
        if parsed is not None and _FOLDER_PAYLOAD in data[property_offset:payload_end]:
            name, name_start = parsed
            records.append(
                OpjuFolderDirectoryRecord(
                    name=name,
                    offset=name_start,
                    length=len(name.encode("ascii")),
                    property_offset=property_offset,
                    source_object_path=_unique_path("project_folders", name, seen_paths),
                )
            )
        cursor = property_offset + len(_FOLDER_PROPERTY)
    return tuple(records)


__all__ = [
    "OpjuFolderDirectoryRecord",
    "OpjuPageDirectoryRecord",
    "parse_opju_folder_directory",
    "parse_opju_page_directory",
]
