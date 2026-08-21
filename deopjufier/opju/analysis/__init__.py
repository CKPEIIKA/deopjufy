"""Shared analyzed OriginStorage candidate helpers for OPJU parsing."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass

from deopjufier.blocks import GIF_SIGS, JPEG_SIG, PDF_SIG, PNG_SIG
from deopjufier.io import sanitize_name
from deopjufier.opju.common import (
    MAGIC_OPJU,
    OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT,
    OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION,
    OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH,
    OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE,
    OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,
    OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT,
    OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD,
)
from deopjufier.opju.regions import OpjuOriginStorageCandidate, iter_origin_storage_candidates

_OPJU_ORIGIN_STORAGE_ATTACHMENT_EXTENSIONS = (
    "csv",
    "doc",
    "docx",
    "jpeg",
    "jpg",
    "odt",
    "ods",
    "pdf",
    "ppt",
    "pptx",
    "png",
    "rtf",
    "tsv",
    "xls",
    "xlsm",
    "xlsx",
)
_OPJU_ORIGIN_STORAGE_ATTACHMENT_EXTENSION_MARKERS = tuple(
    f".{ext}" for ext in _OPJU_ORIGIN_STORAGE_ATTACHMENT_EXTENSIONS
)
_OPJU_ORIGIN_STORAGE_SVG_SIGNATURE = b"<svg"
_ORIGIN_STORAGE_CLASSIFICATION_SNIPPET_BYTES = 16384
_OPJU_ORIGIN_STORAGE_FUNCTION_TAG_MARKERS = (
    "formula",
    "func",
    "function",
    "functionlist",
    "__xf",
    "__fitcurve",
    "expgraph",
    "xfname",
    "xfunctionname",
    "nlfitxfname",
    "mathtool",
    "operator",
    "operand",
    "iy1",
    "iy2",
    "oy",
)
_OPJU_ORIGIN_STORAGE_FUNCTION_TEXT_MARKERS = (
    "<iy1",
    "<iy2",
    "<oy",
    "<operand",
    "<operator",
    "<formula",
    "<functionlist",
    "__xf",
    "__fitcurve",
    "expgraph",
    "xfname",
    "xfunctionname",
    "nlfitxfname",
    "<mathtool",
)
_OPJU_ORIGIN_STORAGE_GRAPH_TAG_MARKERS = ("graph", "layer", "plot", "sheet")
_OPJU_ORIGIN_STORAGE_ORIGIN_STORAGE_CLOSE_TAG_TEXT = "</originstorage>"
_OPJU_MARKUP_CONTROL_BYTES = bytes(range(0x00, 0x20)) + b"\x7f"
_OPJU_PREVIEW_SIGNATURES = (PNG_SIG, JPEG_SIG, *GIF_SIGS, PDF_SIG)
_OPJU_MARKUP_TRANSLATION = bytes.maketrans(b"", b"")
_TAG_NAME_RE = re.compile(r"</?\s*([A-Za-z_][A-Za-z0-9_:.-]*)")
_TAG_NAME_NORMALIZE_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class OpjuAnalyzedCandidate:
    source_start: int
    source_end: int
    source_kind: str
    payload: bytes
    normalized_payload: bytes
    normalized_text: str
    normalized_text_lower: str
    starts_with_originstorage: bool
    sanitized_text: str | None
    root: ET.Element | None
    tag_names: tuple[str, ...]
    raw_path_candidates: tuple[str, ...]
    attachment_name: str | None
    has_label: bool
    region_kind: str


def normalize_markup_bytes(payload: bytes) -> bytes:
    """Drop control bytes that are common in raw Origin payload markup."""
    return payload.translate(_OPJU_MARKUP_TRANSLATION, _OPJU_MARKUP_CONTROL_BYTES)


def normalize_markup_text(payload: bytes) -> str:
    return normalize_markup_bytes(payload).decode("utf-8", errors="ignore")


def sanitize_origin_storage_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char for char in text if char.isprintable() or char in "\n\t" or char == "\x00")
    text = text.replace("\x00", "")
    text = text.replace('\\"', "&quot;").replace("\\'", "'")
    text = text.replace("<T ime", "<Time").replace("</T ime", "</Time")
    return text


def parse_origin_storage_root(payload: bytes, *, normalized_text: str | None = None) -> ET.Element | None:
    text = (normalized_text if normalized_text is not None else normalize_markup_text(payload)).replace("\ufeff", "")
    stripped = text.lstrip()
    if not stripped:
        return None
    if not stripped[:32].lower().startswith("<originstorage"):
        return None
    close_index = text.find(_OPJU_ORIGIN_STORAGE_ORIGIN_STORAGE_CLOSE_TAG_TEXT)
    if close_index >= 0:
        text = text[: close_index + len(_OPJU_ORIGIN_STORAGE_ORIGIN_STORAGE_CLOSE_TAG_TEXT)]
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def _iter_tag_names_from_text(payload_text: str) -> Iterable[str]:
    for match in _TAG_NAME_RE.finditer(payload_text):
        tag = match.group(1)
        normalized = "".join(_TAG_NAME_NORMALIZE_RE.findall(tag.lower()))
        if normalized:
            yield normalized


def _starts_with_originstorage(normalized_text: str) -> bool:
    stripped = normalized_text.lstrip()
    if not stripped:
        return False
    return stripped[:32].lower().startswith("<originstorage")


def _iter_tag_names(
    payload: bytes,
    root: ET.Element | None,
    *,
    normalized_text: str | None = None,
) -> tuple[str, ...]:
    if root is not None:
        tags: list[str] = []
        for element in root.iter():
            tag = element.tag
            if "}" in tag:
                tag = tag.split("}", 1)[1]
            normalized = "".join(char.lower() for char in tag if char.isalnum() or char == "_")
            if normalized:
                tags.append(normalized)
        return tuple(tags)
    text = normalized_text if normalized_text is not None else normalize_markup_text(payload)
    return tuple(_iter_tag_names_from_text(text))


def _has_origin_storage_label(
    root: ET.Element | None,
    normalized_text: str,
) -> bool:
    if root is not None:
        for key in root.attrib:
            if key.lower() == "label":
                return True

    open_tag_end = normalized_text.find(">")
    if open_tag_end < 0:
        return False
    open_tag = normalized_text[:open_tag_end]
    return "label=" in open_tag.lower()


def _iter_raw_path_candidates(payload_text: str) -> Iterable[str]:
    if "[" not in payload_text and '"' not in payload_text:
        return ()

    cursor = 0
    while True:
        start = payload_text.find("[", cursor)
        if start < 0:
            break
        end = payload_text.find("]", start + 1)
        if end < 0:
            break
        bracket = payload_text[start + 1 : end].strip()
        if bracket:
            yield bracket
        cursor = end + 1

    cursor = 0
    while True:
        start = payload_text.find('"', cursor)
        if start < 0:
            break
        end = payload_text.find('"', start + 1)
        if end < 0:
            break
        quoted = payload_text[start + 1 : end].strip()
        if quoted:
            yield quoted
        cursor = end + 1


def _raw_path_candidates(payload_text: str) -> tuple[str, ...]:
    return tuple(_iter_raw_path_candidates(payload_text))


def _iter_attachment_path_candidates(value: str) -> Iterable[str]:
    text = value.replace("\x00", "").replace("\u0000", "").replace("\x7f", "")
    text = text.strip().strip("[]")
    if not text:
        return

    yield text
    if "]" in text:
        for part in text.split("]"):
            stripped = part.strip("[] ")
            if stripped:
                yield stripped
    if '"' in text:
        for part in text.split('"'):
            stripped = part.strip(' "')
            if stripped:
                yield stripped


def _extract_attachment_name_from_text(value: str) -> str | None:
    for segment in _iter_attachment_path_candidates(value):
        if "\\" in segment:
            segment = segment.rsplit("\\", 1)[-1]
        if "/" in segment:
            segment = segment.rsplit("/", 1)[-1]
        segment = segment.strip()
        if not segment or "." not in segment:
            continue
        base, ext = segment.rsplit(".", 1)
        if not base or not ext:
            continue
        candidate = sanitize_name(segment)
        if not candidate:
            continue
        if not candidate.lower().endswith(f".{ext.lower()}"):
            continue
        if any(
            candidate.lower().endswith(ext_marker) for ext_marker in _OPJU_ORIGIN_STORAGE_ATTACHMENT_EXTENSION_MARKERS
        ):
            return candidate

        lower = segment.lower()
        if any(marker in lower for marker in _OPJU_ORIGIN_STORAGE_ATTACHMENT_EXTENSION_MARKERS):
            return candidate

    return None


def extract_origin_storage_attachment_name(
    payload: bytes,
    *,
    root: ET.Element | None = None,
    normalized_text: str | None = None,
    normalized_text_lower: str | None = None,
    raw_path_candidates: tuple[str, ...] | None = None,
) -> str | None:
    if not payload:
        return None
    normalized = normalized_text if normalized_text is not None else normalize_markup_text(payload)
    lower_payload = normalized_text_lower if normalized_text_lower is not None else normalized.lower()
    if not any(marker in lower_payload for marker in _OPJU_ORIGIN_STORAGE_ATTACHMENT_EXTENSION_MARKERS):
        return None

    parsed_root = root if root is not None else parse_origin_storage_root(payload)
    candidates: list[str] = []

    if parsed_root is not None:
        for element in parsed_root.iter():
            candidates.extend(v for v in element.attrib.values() if v)
            text = (element.text or "").strip()
            if text:
                candidates.append(text)
            tail = (element.tail or "").strip()
            if tail:
                candidates.append(tail)

    candidates.append(normalized)
    if raw_path_candidates is None:
        candidates.extend(_iter_raw_path_candidates(normalized))
    else:
        candidates.extend(raw_path_candidates)

    for candidate in candidates:
        filename = _extract_attachment_name_from_text(candidate)
        if filename is not None:
            return filename
    return None


def classify_origin_storage_region(
    payload: bytes,
    *,
    root: ET.Element | None = None,
    normalized_payload: bytes | None = None,
    normalized_text: str | None = None,
    normalized_text_lower: str | None = None,
    tag_names: tuple[str, ...] | None = None,
    attachment_name: str | None = None,
    has_label: bool | None = None,
) -> str:
    normalized_text_value = normalized_text if normalized_text is not None else normalize_markup_text(payload)
    normalized_text_lower_value = (
        normalized_text_lower if normalized_text_lower is not None else normalized_text_value.lower()
    )
    parsed_root = root if root is not None else parse_origin_storage_root(payload)
    attachment = (
        attachment_name
        if attachment_name is not None
        else extract_origin_storage_attachment_name(
            payload,
            root=parsed_root,
            normalized_text=normalized_text_value,
            normalized_text_lower=normalized_text_lower_value,
        )
    )
    if attachment is not None:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT

    normalized_payload_value = (
        normalized_payload
        if normalized_payload is not None
        else normalize_markup_bytes(payload[:_ORIGIN_STORAGE_CLASSIFICATION_SNIPPET_BYTES])
    )
    if any(sig in payload for sig in _OPJU_PREVIEW_SIGNATURES):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW
    if PDF_SIG in payload:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW
    if _OPJU_ORIGIN_STORAGE_SVG_SIGNATURE in normalized_payload_value:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW
    if any(marker in normalized_text_lower_value for marker in _OPJU_ORIGIN_STORAGE_FUNCTION_TEXT_MARKERS):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION

    label_present = (
        has_label if has_label is not None else _has_origin_storage_label(parsed_root, normalized_text_value)
    )
    if label_present:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT

    tags = (
        tag_names
        if tag_names is not None
        else _iter_tag_names(
            payload,
            parsed_root,
            normalized_text=normalized_text_value,
        )
    )
    if any(marker in tag for marker in _OPJU_ORIGIN_STORAGE_FUNCTION_TAG_MARKERS for tag in tags):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION
    if any(tag in _OPJU_ORIGIN_STORAGE_GRAPH_TAG_MARKERS for tag in tags):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH
    if any("note" in tag for tag in tags):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE
    return OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD


def _classify_origin_storage_region_details(
    payload: bytes,
    *,
    root: ET.Element | None,
    normalized_payload: bytes,
    normalized_text: str,
    normalized_text_lower: str,
    attachment_name: str | None,
    has_label: bool,
) -> tuple[str, tuple[str, ...]]:
    if attachment_name is not None:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT, ()
    if any(sig in payload for sig in _OPJU_PREVIEW_SIGNATURES):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW, ()
    if PDF_SIG in payload:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW, ()
    if _OPJU_ORIGIN_STORAGE_SVG_SIGNATURE in normalized_payload:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW, ()
    if any(marker in normalized_text_lower for marker in _OPJU_ORIGIN_STORAGE_FUNCTION_TEXT_MARKERS):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION, ()
    if has_label:
        return OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT, ()

    tag_names = _iter_tag_names(
        payload,
        root,
        normalized_text=normalized_text,
    )
    if any(marker in tag for marker in _OPJU_ORIGIN_STORAGE_FUNCTION_TAG_MARKERS for tag in tag_names):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION, tag_names
    if any(tag in _OPJU_ORIGIN_STORAGE_GRAPH_TAG_MARKERS for tag in tag_names):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH, tag_names
    if any("note" in tag for tag in tag_names):
        return OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE, tag_names
    return OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD, tag_names


def analyze_origin_storage_candidates(
    data: bytes,
    *,
    include_decoded: bool,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
) -> tuple[OpjuAnalyzedCandidate, ...]:
    if not data.startswith(MAGIC_OPJU):
        return ()
    if candidates is None:
        candidates = tuple(iter_origin_storage_candidates(data, include_decoded=include_decoded))

    analyzed: list[OpjuAnalyzedCandidate] = []
    for candidate in candidates:
        normalized_bytes = normalize_markup_bytes(candidate.payload)
        normalized_payload = normalized_bytes[:_ORIGIN_STORAGE_CLASSIFICATION_SNIPPET_BYTES]
        normalized_text = normalized_bytes.decode("utf-8", errors="ignore")
        normalized_text_lower = normalized_text.lower()
        starts_with_originstorage = _starts_with_originstorage(normalized_text)
        root = parse_origin_storage_root(candidate.payload, normalized_text=normalized_text)
        raw_path_candidates = ()
        if "[" in normalized_text or '"' in normalized_text:
            raw_path_candidates = _raw_path_candidates(normalized_text)
        attachment_name = extract_origin_storage_attachment_name(
            candidate.payload,
            root=root,
            normalized_text=normalized_text,
            normalized_text_lower=normalized_text_lower,
            raw_path_candidates=raw_path_candidates,
        )
        has_label = _has_origin_storage_label(root, normalized_text)
        region_kind, tag_names = _classify_origin_storage_region_details(
            candidate.payload,
            root=root,
            normalized_payload=normalized_payload,
            normalized_text=normalized_text,
            normalized_text_lower=normalized_text_lower,
            attachment_name=attachment_name,
            has_label=has_label,
        )
        sanitized_text = (
            sanitize_origin_storage_text(normalized_text)
            if region_kind == OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT
            else None
        )
        analyzed.append(
            OpjuAnalyzedCandidate(
                source_start=candidate.source_start,
                source_end=candidate.source_end,
                source_kind=candidate.source_kind,
                payload=candidate.payload,
                normalized_payload=normalized_payload,
                normalized_text=normalized_text,
                normalized_text_lower=normalized_text_lower,
                starts_with_originstorage=starts_with_originstorage,
                sanitized_text=sanitized_text,
                root=root,
                tag_names=tag_names,
                raw_path_candidates=raw_path_candidates,
                attachment_name=attachment_name,
                has_label=has_label,
                region_kind=region_kind,
            )
        )
    return tuple(analyzed)


__all__ = [
    "OpjuAnalyzedCandidate",
    "analyze_origin_storage_candidates",
    "classify_origin_storage_region",
    "extract_origin_storage_attachment_name",
    "normalize_markup_bytes",
    "normalize_markup_text",
    "parse_origin_storage_root",
    "sanitize_origin_storage_text",
]
