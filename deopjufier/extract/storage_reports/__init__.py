"""OriginStorage report extraction helpers."""

from __future__ import annotations

import json
from pathlib import Path

from deopjufier.extract.path_helpers import (
    manifest_relative_path as _manifest_path,
)
from deopjufier.inventory import parse_opju_records
from deopjufier.manifest import Manifest, ManifestItem
from deopjufier.opju.analysis import analyze_origin_storage_candidates
from deopjufier.opju.regions import iter_origin_storage_candidates
from deopjufier.opju.reports import OpjuOriginStorageReport, parse_opju_origin_storage_reports


def extract_origin_storage_reports(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    emit_per_record_items: bool = True,
    emit_no_records_item: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
) -> int:
    """Extract parsed `OriginStorage` report metadata and cleaned report text."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report_root = out_dir / "origin_storage_reports"
    report_root.mkdir(parents=True, exist_ok=True)
    data = file_data if file_data is not None else input_path.read_bytes()

    # Keep parser usage in one layer so callers can monkeypatch inventory-level
    # parser calls in tests and avoid duplicate signature/record scans.
    records = parse_opju_records(data, path=input_path)
    reports = list(records.reports)
    report_names_by_index = {report_record.index: report_record.name for report_record in records.report_records}
    report_rows_by_index = {report_record.index: report_record.rows for report_record in records.report_records}
    report_columns_by_index = {report_record.index: report_record.columns for report_record in records.report_records}
    report_source_by_index = {
        report_record.index: report_record.source_object_path for report_record in records.report_records
    }
    if not reports:
        is_opj = input_path.suffix.lower() == ".opj"
        if is_opj and not emit_no_records_item:
            return 0
        total_len = len(data)
        if is_opj:
            manifest.add_item(
                ManifestItem(
                    kind="origin_storage_report",
                    name="origin_storage_reports",
                    status="partial",
                    confidence=0.35,
                    discovery_type="parser_backed_hint",
                    heuristic=True,
                    path=_manifest_path(report_root, manifest_root or out_dir),
                    source_object_path="origin_storage_reports",
                    range_start=0,
                    range_end=total_len,
                    error="no_origin_storage_reports",
                )
            )
            return 0
        manifest.add_item(
            ManifestItem(
                kind="origin_storage_report",
                name="origin_storage_reports",
                status="partial",
                confidence=0.35,
                discovery_type="parser_backed_hint",
                heuristic=True,
                path=_manifest_path(report_root, manifest_root or out_dir),
                source_object_path="origin_storage_reports",
                range_start=0,
                range_end=total_len,
                error="no_origin_storage_reports",
            )
        )
        return 0

    payload = [
        {
            "index": report.index,
            "name": report_names_by_index.get(
                report.index,
                f"origin_storage_report_{report.index:03d}",
            ),
            "label": report.label,
            "function": report.function,
            "equation": report.equation,
            "user": report.user,
            "time": report.time,
            "data_filter": report.data_filter,
            "source_object_path": report_source_by_index.get(
                report.index,
                "origin_storage_reports/"
                f"{report_names_by_index.get(report.index, f'origin_storage_report_{report.index:03d}')}",
            ),
            "input_data": report.input_data,
            "rows": report.rows,
            "columns": report.columns,
            "descriptive_stats": report.descriptive_stats,
            "ranks": report.ranks,
            "test_statistics": report.test_statistics,
        }
        for report in reports
    ]
    manifest_json = report_root / "origin_storage_reports.json"
    summary_target = report_root / "origin_storage_reports_summary.txt"
    manifest_json_exists = manifest_json.exists()

    if emit_per_record_items:
        if manifest_json_exists and not force:
            manifest.add_item(
                ManifestItem(
                    kind="origin_storage_report",
                    name="origin_storage_reports",
                    status="skipped",
                    confidence=0.6,
                    discovery_type="parser_backed_hint",
                    heuristic=False,
                    path=_manifest_path(manifest_json, manifest_root or out_dir),
                    source_object_path="origin_storage_reports",
                    error="target_exists",
                )
            )
        else:
            with manifest_json.open("w", encoding="utf-8", newline="\n") as fp:
                json.dump(payload, fp, indent=2, sort_keys=True)
                fp.write("\n")
    else:
        manifest_json_exists = True
        for _report in reports:
            manifest.add_item(
                ManifestItem(
                    kind="origin_storage_report",
                    name="origin_storage_reports",
                    status="unsupported",
                    confidence=0.35,
                    discovery_type="parser_backed_hint",
                    heuristic=False,
                    path=_manifest_path(manifest_json, manifest_root or out_dir),
                    source_object_path="origin_storage_reports",
                    rows=len(payload),
                    error=None,
                )
            )
            break
        if manifest_json.exists():
            manifest_json_exists = True

    summary_status = "partial"
    summary_confidence = 0.4
    summary_error_payload = None
    summary_lines_for_write = ""
    summary_line_count = 0
    if emit_per_record_items:
        summary_lines: list[str] = []
        for report in reports:
            heading = report.label or f"OriginStorage {report.index}"
            summary_lines.append(heading)
            if report.function:
                summary_lines.append(f"function: {report.function}")
            if report.equation:
                summary_lines.append(f"equation: {report.equation}")
            if report.user:
                summary_lines.append(f"user: {report.user}")
            if report.time:
                summary_lines.append(f"time: {report.time}")
            if report.input_data:
                summary_lines.append("input:")
                summary_lines.extend(f"  {item}" for item in report.input_data)
            for key, value in report.test_statistics.items():
                summary_lines.append(f"{key}: {value}")
            summary_lines.append("")

        summary_text = "\n".join(summary_lines).strip()
        if summary_text:
            summary_lines_for_write = summary_text.replace("\r", "\n")
            summary_line_count = summary_text.count("\n") + 1
            if summary_target.exists() and not force:
                summary_status = "skipped"
                summary_confidence = 0.6
                summary_error_payload = "target_exists"
            else:
                summary_target.write_text(
                    summary_lines_for_write,
                    encoding="utf-8",
                    newline="\n",
                )
                summary_status = "extracted"
                summary_confidence = 0.7
                summary_error_payload = None

    if summary_status == "skipped":
        summary_confidence = 0.6
        summary_error_payload = "target_exists"

    extracted_report_count = 0
    if emit_per_record_items:
        for report in reports:
            report_name = report_names_by_index.get(
                report.index,
                f"origin_storage_report_{report.index:03d}",
            )
            report_source = report_source_by_index.get(
                report.index,
                f"origin_storage_reports/{report_name}",
            )
            manifest_text = report_root / f"{report_name}.txt"
            manifest_json_path = report_root / f"{report_name}.json"
            if manifest_text.exists() and not force:
                text_status = "skipped"
                text_error = "target_exists"
            else:
                manifest_text.write_text(
                    report.raw_text,
                    encoding="utf-8",
                    newline="\n",
                )
                text_status = "extracted"
                text_error = None
                extracted_report_count += 1

            if manifest_json_path.exists() and not force:
                json_status = "skipped"
                json_error = "target_exists"
            else:
                with manifest_json_path.open("w", encoding="utf-8", newline="\n") as fp:
                    json.dump(report.to_dict(), fp, indent=2, sort_keys=True)
                    fp.write("\n")
                json_status = "extracted"
                json_error = None

            manifest.add_item(
                ManifestItem(
                    kind="origin_storage_report",
                    name=report_name,
                    status=text_status,
                    confidence=0.85 if text_status == "extracted" else 0.6,
                    discovery_type="parser_backed_hint",
                    heuristic=False,
                    path=_manifest_path(manifest_text, manifest_root or out_dir),
                    source_object_path=report_source,
                    object_kind="metadata",
                    offset=report.offset,
                    length=report.length,
                    rows=report_rows_by_index.get(report.index),
                    columns=report_columns_by_index.get(report.index),
                    error=text_error,
                )
            )
            manifest.add_item(
                ManifestItem(
                    kind="origin_storage_report_json",
                    name=report_name,
                    status=json_status,
                    confidence=0.9 if json_status == "extracted" else 0.6,
                    discovery_type="parser_backed_hint",
                    heuristic=False,
                    path=_manifest_path(manifest_json_path, manifest_root or out_dir),
                    source_object_path=report_source,
                    object_kind="metadata",
                    offset=report.offset,
                    length=report.length,
                    rows=report_rows_by_index.get(report.index),
                    columns=report_columns_by_index.get(report.index),
                    error=json_error,
                )
            )

    if emit_per_record_items:
        manifest.add_item(
            ManifestItem(
                kind="origin_storage_report_summary",
                name="origin_storage_report_summary",
                status=summary_status,
                confidence=summary_confidence,
                discovery_type="parser_backed_hint",
                heuristic=False,
                path=_manifest_path(summary_target, manifest_root or out_dir),
                source_object_path="origin_storage_reports",
                object_kind="metadata",
                rows=summary_line_count,
                error=summary_error_payload,
            )
        )

    if emit_per_record_items:
        manifest.add_item(
            ManifestItem(
                kind="origin_storage_report",
                name="origin_storage_reports.json",
                status="skipped" if manifest_json_exists and not force else "extracted",
                confidence=0.6 if manifest_json_exists and not force else 0.8,
                discovery_type="parser_backed_hint",
                heuristic=False,
                path=_manifest_path(manifest_json, manifest_root or out_dir),
                source_object_path="origin_storage_reports",
                object_kind="metadata",
                rows=len(payload),
                error="target_exists" if manifest_json_exists and not force else None,
            )
        )
    return extracted_report_count


def _is_human_analysis_report(report: object) -> bool:
    return bool(
        getattr(report, "function", None)
        or _analysis_equations(report)
        or getattr(report, "input_data", None)
        or getattr(report, "test_statistics", None)
    )


def _analysis_equations(report: object) -> list[str]:
    equations: list[str] = []
    semantic_equation = getattr(report, "equation", None)
    if semantic_equation:
        equations.append(str(semantic_equation))
    for field in getattr(report, "fields", ()):
        if field.tag.lower() == "equation" and field.value not in equations:
            equations.append(field.value)
    return equations


def _analysis_summary_lines(report: object, index: int) -> list[str]:
    label = getattr(report, "label", None) or f"Analysis {index + 1}"
    lines = [str(label)]
    for key in ("function", "time", "data_filter"):
        value = getattr(report, key, None)
        if value:
            lines.append(f"{key}: {value}")
    lines.extend(f"equation: {equation}" for equation in _analysis_equations(report))
    input_data = getattr(report, "input_data", ())
    if input_data:
        lines.append("input:")
        lines.extend(f"  {value}" for value in input_data)
    return lines


def _analysis_record_payload(report: OpjuOriginStorageReport, index: int) -> dict[str, object]:
    payload: dict[str, object] = {
        "index": index,
        "source_object_path": f"analyses/origin_storage_analysis_{index:03d}",
        "completeness": "partial",
        "fields": [field.to_dict() for field in report.fields],
    }
    if _has_exact_source_attribution(report):
        payload["source_range"] = {"start": report.offset, "end": report.offset + report.length}
    return payload


def _has_exact_source_attribution(report: OpjuOriginStorageReport) -> bool:
    return bool(report.fields) and all(
        field.source_start is not None and field.source_end is not None for field in report.fields
    )


def _analysis_source_ranges(reports: list[OpjuOriginStorageReport]) -> list[dict[str, int]]:
    return [
        {"start": report.offset, "end": report.offset + report.length}
        for report in reports
        if report.length > 0 and _has_exact_source_attribution(report)
    ]


def extract_origin_storage_analysis_summary(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
) -> int:
    """Write structured OPJU analysis fields and a concise human summary."""
    data = file_data if file_data is not None else input_path.read_bytes()
    candidates = tuple(iter_origin_storage_candidates(data, include_decoded=True))
    analyses = analyze_origin_storage_candidates(data, include_decoded=True, candidates=candidates)
    parsed_reports = parse_opju_origin_storage_reports(
        data,
        include_decoded=True,
        include_analyses=True,
        candidates=candidates,
        analyses=analyses,
    )
    record_reports = [report for report in parsed_reports if report.fields]
    reports = [report for report in parsed_reports if _is_human_analysis_report(report)]
    if not record_reports and not reports:
        return 0

    target_dir = out_dir / "analyses"
    target_dir.mkdir(parents=True, exist_ok=True)
    if record_reports:
        records_target = target_dir / "origin_storage_analysis_records.json"
        records_payload = [_analysis_record_payload(report, index) for index, report in enumerate(record_reports)]
        if records_target.exists() and not force:
            records_status = "skipped"
            records_error = "target_exists"
        else:
            with records_target.open("w", encoding="utf-8", newline="\n") as fp:
                json.dump(records_payload, fp, indent=2, sort_keys=True)
                fp.write("\n")
            records_status = "extracted"
            records_error = None

        exact_attribution = all(_has_exact_source_attribution(report) for report in record_reports)
        manifest.add_item(
            ManifestItem(
                kind="analysis_records",
                name="origin_storage_analysis_records",
                status=records_status,
                confidence=0.98 if exact_attribution else 0.85,
                discovery_type="opju_origin_storage_leaf_fields",
                heuristic=False,
                path=_manifest_path(records_target, manifest_root or out_dir),
                source_object_path="analyses",
                object_kind="analysis",
                rows=len(record_reports),
                columns=max(len(report.fields) for report in record_reports),
                source_ranges=_analysis_source_ranges(record_reports),
                extraction_method="opju_origin_storage_leaf_fields",
                completeness="partial",
                verification="exact" if exact_attribution else "unverified",
                error=records_error,
            )
        )

    if not reports:
        return len(record_reports)
    lines: list[str] = []
    for index, report in enumerate(reports):
        lines.extend(_analysis_summary_lines(report, index))
        lines.append("")
    text = "\n".join(lines).strip() + "\n"

    target = target_dir / "origin_storage_analyses.txt"
    if target.exists() and not force:
        status = "skipped"
        error = "target_exists"
        confidence = 0.7
    else:
        target.write_text(text, encoding="utf-8", newline="\n")
        status = "extracted"
        error = None
        confidence = 0.9

    manifest.add_item(
        ManifestItem(
            kind="analysis_summary",
            name="origin_storage_analyses",
            status=status,
            confidence=confidence,
            discovery_type="parse_opju_origin_storage_reports",
            heuristic=False,
            path=_manifest_path(target, manifest_root or out_dir),
            source_object_path="analyses",
            object_kind="analysis",
            rows=len(reports),
            completeness="partial",
            verification="unverified",
            error=error,
        )
    )
    return len(record_reports)
