"""OriginStorage report parsing for OPJU containers."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass

from .analysis import OpjuAnalyzedCandidate, sanitize_origin_storage_text
from .common import MAGIC_OPJU
from .regions import (
    OpjuOriginStorageCandidate,
    find_matching_origin_storage_close,
    iter_origin_storage_candidates,
)

_ORIGIN_STORAGE_OPEN_TAG = b"<OriginStorage"
_ORIGIN_STORAGE_CLOSE_TAG = b"</OriginStorage>"
_ORIGIN_STORAGE_CLOSE_TAG_TEXT = _ORIGIN_STORAGE_CLOSE_TAG.decode("ascii")
_EXACT_LEAF_FIELD_RE = re.compile(
    rb"<(?P<tag>[A-Za-z_][A-Za-z0-9_:.-]*)(?:\s[^<>]*?)?>(?P<value>[^<>]*)</(?P=tag)\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_TAG_EVENT_RE = re.compile(
    rb"<\s*(?P<closing>/)?\s*(?P<tag>[A-Za-z_][A-Za-z0-9_:.-]*)(?:\s[^<>]*?)?(?P<self_closing>/)?\s*>",
    flags=re.DOTALL,
)
_EXACT_FIELD_WHITESPACE = b" \t\r\n"
_MAX_EXACT_FIELD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class OpjuOriginStorageField:
    """Strictly decoded leaf field with exact payload and source ranges."""

    tag: str
    value: str
    payload_start: int
    payload_end: int
    path: str | None = None
    source_start: int | None = None
    source_end: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "tag": self.tag,
            "value": self.value,
            "payload_range": {"start": self.payload_start, "end": self.payload_end},
            "encoding": "utf-8",
            "verification": "exact",
        }
        if self.source_start is not None and self.source_end is not None:
            payload["source_range"] = {"start": self.source_start, "end": self.source_end}
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class OpjuOriginStorageReport:
    index: int
    offset: int
    length: int
    label: str | None
    function: str | None
    user: str | None
    time: str | None
    data_filter: str | None
    rows: int | None
    columns: int | None
    input_data: list[str]
    descriptive_stats: dict[str, dict[str, str]]
    ranks: dict[str, dict[str, str]]
    test_statistics: dict[str, str]
    raw_text: str
    equation: str | None = None
    fields: tuple[OpjuOriginStorageField, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "label": self.label,
            "function": self.function,
            "equation": self.equation,
            "user": self.user,
            "time": self.time,
            "data_filter": self.data_filter,
            "rows": self.rows,
            "columns": self.columns,
            "input_data": self.input_data,
            "descriptive_stats": self.descriptive_stats,
            "ranks": self.ranks,
            "test_statistics": self.test_statistics,
            "raw_text": self.raw_text,
        }


def _strict_field_text(value: bytes) -> str | None:
    if not value or len(value) > _MAX_EXACT_FIELD_BYTES:
        return None
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(char not in "\n\r\t" and (ord(char) < 0x20 or ord(char) == 0x7F) for char in text):
        return None
    return text


def _close_tag(stack: list[str], tag: str) -> None:
    lowered = tag.lower()
    while stack:
        if stack.pop().lower() == lowered:
            return


def _tag_paths(payload: bytes) -> dict[int, str]:
    paths: dict[int, str] = {}
    stack: list[str] = []
    for match in _TAG_EVENT_RE.finditer(payload):
        tag = match.group("tag").decode("ascii")
        if match.group("closing"):
            _close_tag(stack, tag)
            continue
        paths[match.start()] = "/".join((*stack, tag))
        if not match.group("self_closing"):
            stack.append(tag)
    return paths


def _exact_leaf_fields(payload: bytes, *, source_start: int | None) -> tuple[OpjuOriginStorageField, ...]:
    fields: list[OpjuOriginStorageField] = []
    paths = _tag_paths(payload)
    for match in _EXACT_LEAF_FIELD_RE.finditer(payload):
        raw_value = match.group("value")
        value = raw_value.strip(_EXACT_FIELD_WHITESPACE)
        text = _strict_field_text(value)
        if text is None:
            continue
        left_trim = len(raw_value) - len(raw_value.lstrip(_EXACT_FIELD_WHITESPACE))
        payload_start = match.start("value") + left_trim
        payload_end = payload_start + len(value)
        fields.append(
            OpjuOriginStorageField(
                tag=match.group("tag").decode("ascii"),
                value=text,
                payload_start=payload_start,
                payload_end=payload_end,
                path=paths.get(match.start()),
                source_start=source_start + payload_start if source_start is not None else None,
                source_end=source_start + payload_end if source_start is not None else None,
            )
        )
    return tuple(fields)


def parse_origin_storage_leaf_fields(
    payload: bytes,
    *,
    source_start: int | None = None,
) -> tuple[OpjuOriginStorageField, ...]:
    """Return strictly decoded XML leaf fields with decoded/source offsets.

    ``source_start`` is appropriate only when ``payload`` is a contiguous raw
    file slice.  Decoded payload callers should leave it unset and retain the
    decoder's source map beside the returned decoded ranges.
    """
    return _exact_leaf_fields(payload, source_start=source_start)


@dataclass(frozen=True)
class _TolerantReportFields:
    label: str | None
    function: str | None
    equation: str | None
    user: str | None
    time: str | None
    data_filter: str | None
    input_data: list[str]


def _iter_candidate_blocks(
    data: bytes,
    *,
    include_decoded: bool,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
) -> Iterable[tuple[int, bytes]]:
    if not data.startswith(MAGIC_OPJU):
        return ()
    if candidates is None:
        candidates = tuple(iter_origin_storage_candidates(data, include_decoded=include_decoded))
    raw_starts_with_decoded_twin: set[int] = set()
    if include_decoded:
        raw_starts_with_decoded_twin = {
            candidate.source_start - 2 for candidate in candidates if candidate.source_kind == "decoded"
        }
    for candidate in candidates:
        if candidate.source_kind == "raw" and candidate.source_start in raw_starts_with_decoded_twin:
            continue
        yield (candidate.source_start, candidate.payload)


def _sanitize_origin_storage_text(raw: str) -> str:
    return sanitize_origin_storage_text(raw)


def _clean_origin_storage_text(raw: str) -> str:
    decoded = html.unescape(raw)
    decoded = decoded.replace('\\"', '"').replace("\\'", "'")
    decoded = decoded.replace("\r\n", "\n").replace("\r", "\n")
    while "<" in decoded and ">" in decoded:
        before, _sep, decoded_tail = decoded.partition("<")
        _middle, _sep, decoded = decoded_tail.partition(">")
        if before:
            decoded = before + decoded
            break
    return decoded.replace("\x00", "").replace("\u0001", "").strip()


def _extract_escaped_attr(open_tag: str, name: str) -> str | None:
    marker = f"{name}="
    if marker not in open_tag:
        return None
    pos = open_tag.find(marker)
    if pos < 0:
        return None
    start = pos + len(marker)
    if start >= len(open_tag):
        return None
    quote = open_tag[start]
    if quote not in {'"', "'"}:
        return None
    start += 1
    end = open_tag.find(quote, start)
    if end < 0:
        return None
    return _clean_origin_storage_text(open_tag[start:end])


def _extract_text(payload: str, pattern: re.Pattern[str]) -> str | None:
    """Compatibility shim used by call sites that still expect the regex API."""
    match = pattern.search(payload)
    if not match:
        return None
    if match.re.groups == 0:
        value = match.group(0)
    elif len(match.groups()) == 1:
        value = match.group(1)
    else:
        values = [group for group in match.groups() if group is not None]
        value = " ".join(values)
    if value is None:
        return None
    return _clean_origin_storage_text(value.strip())


def _root_attrib(root: ET.Element, key: str) -> str | None:
    target = key.lower()
    for attr_name, value in root.attrib.items():
        if attr_name.lower() == target:
            return value
    return None


def _extract_dimensions(payload: str) -> tuple[int | None, int | None]:
    def _to_int(value: str | None) -> int | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    rows = _to_int(_extract_escaped_attr(payload, "Rows"))
    columns = _to_int(_extract_escaped_attr(payload, "Columns"))
    if rows is None:
        start = payload.find("<Rows>")
        if start >= 0:
            end = payload.find("</Rows>", start + len("<Rows>"))
            if end > start:
                rows = _to_int(payload[start + len("<Rows>") : end])
    if columns is None:
        start = payload.find("<Columns>")
        if start >= 0:
            end = payload.find("</Columns>", start + len("<Columns>"))
            if end > start:
                columns = _to_int(payload[start + len("<Columns>") : end])
    return rows, columns


def _append_unique(values: list[str], entry: str, *, max_items: int) -> None:
    if entry and entry not in values and len(values) < max_items:
        values.append(entry)


def _element_label(element: ET.Element) -> str | None:
    for key, value in element.attrib.items():
        if key.lower() == "label":
            return value
    return None


def _first(element_path: Iterable[ET.Element]) -> ET.Element | None:
    for element in element_path:
        return element
    return None


def _extract_text_by_label(root: ET.Element, target: str) -> str | None:
    for element in root.iter():
        label = _element_label(element)
        if label == target:
            value = (element.text or "").strip()
            if value:
                return value
    return None


def _iter_idtr_pairs(root: ET.Element) -> Iterable[tuple[str | None, str | None]]:
    for idtr in root.iter():
        if not idtr.tag.lower().startswith("idtr"):
            continue
        data_name = None
        range_text = None
        for child in idtr:
            tag = child.tag.lower()
            if tag not in {"idtc1", "idtc2"}:
                continue
            escape = child.attrib.get("EscTransl")
            if not escape:
                continue
            if tag == "idtc1" and _element_label(child) == "Data":
                data_name = escape
            elif tag == "idtc2":
                range_text = escape
        yield data_name, range_text


def _clean_row_payload(payload: ET.Element) -> dict[str, str]:
    return {
        child.tag: _clean_origin_storage_text((child.text or "").strip())
        for child in payload.iter()
        if (child.text or "").strip()
    }


def _extract_row_fields(payload: str) -> dict[str, str]:
    try:
        wrapped = f"<Payload>{payload}</Payload>"
        root = ET.fromstring(wrapped)
    except ET.ParseError:
        return {}
    fields: dict[str, str] = {}
    for child in list(root):
        text = (child.text or "").strip()
        if text:
            fields[child.tag] = _clean_origin_storage_text(text)
    return fields


def _extract_description_stats(root: ET.Element) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    descriptive_stats: dict[str, dict[str, str]] = {}
    ranks: dict[str, dict[str, str]] = {}
    for row in root.iter():
        tag = row.tag.lower()
        if tag not in {"r1", "r2"}:
            continue
        label = _element_label(row)
        if not label:
            continue
        fields = _clean_row_payload(row)
        if not fields:
            continue
        key = label.strip()
        descriptive_stats[key] = fields
        if '"-"' in key:
            if tag == "r1":
                ranks.setdefault(key, fields)
            else:
                ranks[f"{key} (R2)" if key in ranks else key] = fields
    return descriptive_stats, ranks


def _extract_test_statistics(root: ET.Element) -> dict[str, str]:
    output: dict[str, str] = {}
    stats = _first(el for el in root.iter() if el.tag.lower() == "stats")
    if stats is not None:
        for child in list(stats):
            value = _clean_origin_storage_text((child.text or "").strip())
            if value:
                output[f"C{child.tag[1:]}" if child.tag.lower().startswith("c") else child.tag] = value
    footer = _first(el for el in root.iter() if el.tag.lower() == "footer")
    if footer is not None:
        footer_text = _clean_origin_storage_text((footer.text or "").strip())
        if footer_text:
            output["footer"] = footer_text
    return output


def _parse_xml_root(block_text: str) -> ET.Element | None:
    start = block_text.lower().find("<originstorage")
    if start < 0:
        return None
    block_text = block_text[start:]
    end = block_text.find(_ORIGIN_STORAGE_CLOSE_TAG_TEXT)
    if end >= 0:
        block_text = block_text[: end + len(_ORIGIN_STORAGE_CLOSE_TAG_TEXT)]
    try:
        return ET.fromstring(block_text)
    except ET.ParseError:
        return None


def _extract_tag_text(payload: str, tag: str) -> str | None:
    match = re.search(
        rf"<{re.escape(tag)}(?:\s[^>]*)?>(?P<value>.*?)</{re.escape(tag)}>",
        payload,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    value = _clean_origin_storage_text(match.group("value"))
    return value or None


def _extract_tag_attr(payload: str, tag: str, attr: str) -> str | None:
    match = re.search(
        rf"<{re.escape(tag)}\b(?P<attrs>[^>]*)>",
        payload,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    return _extract_escaped_attr(match.group("attrs"), attr)


def _extract_tolerant_input_data(payload: str, *, max_items: int) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"\bEscTransl=(?P<quote>['\"])(?P<value>.*?)(?P=quote)", payload, re.DOTALL):
        value = _clean_origin_storage_text(match.group("value"))
        if value.startswith("[") or "!" in value:
            _append_unique(values, value, max_items=max_items)
    return values


def _tolerant_report_fields(payload: str, *, max_input_items: int) -> _TolerantReportFields | None:
    function = _extract_tag_text(payload, "NLFitXFName") or _extract_tag_attr(payload, "Calculation", "AnalysisName")
    equation = _extract_tag_text(payload, "Equation")
    label = _extract_tag_attr(payload, "Calculation", "Label") or _extract_tag_attr(payload, "OriginStorage", "Label")
    input_data = _extract_tolerant_input_data(payload, max_items=max_input_items)
    if not any((function, equation, label, input_data)):
        return None
    return _TolerantReportFields(
        label=label,
        function=function,
        equation=equation,
        user=_extract_tag_text(payload, "UserName"),
        time=_extract_tag_text(payload, "Time"),
        data_filter=_extract_tag_text(payload, "DataFilter"),
        input_data=input_data,
    )


def _is_report_candidate(analysis: OpjuAnalyzedCandidate, *, include_analyses: bool) -> bool:
    if analysis.region_kind in {"origin_storage_report", "origin_storage_preview"}:
        return True
    return include_analyses and "<calculation" in analysis.normalized_text_lower


def parse_opju_origin_storage_reports(
    data: bytes,
    *,
    max_reports: int = 200,
    max_input_items: int = 10,
    include_decoded: bool = False,
    include_analyses: bool = False,
    candidates: tuple[OpjuOriginStorageCandidate, ...] | None = None,
    analyses: tuple[OpjuAnalyzedCandidate, ...] | None = None,
) -> list[OpjuOriginStorageReport]:
    if max_reports <= 0 or max_input_items <= 0 or not data.startswith(MAGIC_OPJU):
        return []

    reports: list[OpjuOriginStorageReport] = []
    report_index = 0
    seen: set[tuple[int, int]] = set()

    if analyses is not None:
        candidate_blocks = (
            (analysis.source_start, analysis.payload, analysis)
            for analysis in analyses
            if _is_report_candidate(analysis, include_analyses=include_analyses)
        )
    else:
        candidate_blocks = (
            (source_start, block, None)
            for source_start, block in _iter_candidate_blocks(
                data,
                include_decoded=include_decoded,
                candidates=candidates,
            )
        )

    for source_start, block, analysis in candidate_blocks:
        if report_index >= max_reports:
            break
        if analysis is not None and analysis.root is not None and analysis.starts_with_originstorage:
            root = analysis.root
            if root.tag.lower() != "originstorage":
                continue
            report_start = analysis.source_start
            report_end = analysis.source_end
            block_clean = analysis.sanitized_text or _sanitize_origin_storage_text(analysis.normalized_text)
        else:
            start = block.find(b"<originstorage")
            if start < 0:
                start = block.find(b"<OriginStorage")
                if start < 0:
                    continue
            end = find_matching_origin_storage_close(block, start)
            if start < 0:
                continue
            if end < 0:
                fallback = block.find(_ORIGIN_STORAGE_CLOSE_TAG, start + len(_ORIGIN_STORAGE_OPEN_TAG))
                if fallback < 0:
                    continue
                end = fallback + len(_ORIGIN_STORAGE_CLOSE_TAG)
            end = min(end, len(block))

            report_start = source_start + start
            report_end = source_start + end
            block_text = block[start:end]
            block_clean = _sanitize_origin_storage_text(block_text.decode("utf-8", errors="ignore"))
            root = _parse_xml_root(block_clean)

        if (report_start, report_end) in seen:
            continue
        seen.add((report_start, report_end))

        field_source_start = source_start if analysis is None or analysis.source_kind == "raw" else None
        exact_fields = parse_origin_storage_leaf_fields(block, source_start=field_source_start)
        report_rows, report_columns = _extract_dimensions(block_clean)
        if root is not None and root.tag.lower() == "originstorage":
            report_label = _root_attrib(root, "Label") or _extract_tag_attr(block_clean, "Calculation", "Label")
            function = _extract_text_by_label(root, "X-Function") or _extract_tag_text(block_clean, "NLFitXFName")
            equation = _extract_tag_text(block_clean, "Equation")
            user = _extract_text_by_label(root, "User Name") or _extract_tag_text(block_clean, "UserName")
            time = _extract_text_by_label(root, "Time") or _extract_tag_text(block_clean, "Time")
            data_filter = _extract_text_by_label(root, "Data Filter") or _extract_tag_text(block_clean, "DataFilter")
            input_data = []
            for data_name, range_text in _iter_idtr_pairs(root):
                if data_name and range_text:
                    _append_unique(input_data, f"{data_name}; {range_text}", max_items=max_input_items)
            descriptive_stats, ranks = _extract_description_stats(root)
            test_statistics = _extract_test_statistics(root)
        else:
            if not include_analyses:
                continue
            tolerant = _tolerant_report_fields(block_clean, max_input_items=max_input_items)
            if tolerant is None:
                if not exact_fields:
                    continue
                report_label = None
                function = None
                equation = None
                user = None
                time = None
                data_filter = None
                input_data = []
            else:
                report_label = tolerant.label
                function = tolerant.function
                equation = tolerant.equation
                user = tolerant.user
                time = tolerant.time
                data_filter = tolerant.data_filter
                input_data = tolerant.input_data
            descriptive_stats = {}
            ranks = {}
            test_statistics = {}
        raw_text = _clean_origin_storage_text(block_clean)

        report_length = max(1, report_end - report_start)
        reports.append(
            OpjuOriginStorageReport(
                index=report_index,
                offset=report_start,
                length=report_length,
                label=report_label,
                function=function,
                equation=equation,
                user=user,
                time=time,
                data_filter=data_filter,
                rows=report_rows,
                columns=report_columns,
                input_data=input_data,
                descriptive_stats=descriptive_stats,
                ranks=ranks,
                test_statistics=test_statistics,
                raw_text=raw_text,
                fields=exact_fields,
            )
        )
        report_index += 1

    return reports
