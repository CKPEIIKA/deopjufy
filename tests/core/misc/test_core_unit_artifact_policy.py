"""Unit tests for artifact warning policy helpers."""

from __future__ import annotations

from pathlib import Path

from deopjufier.commands.artifact_policy import (
    has_malformed_graph_preview,
    should_warn_for_missing_artifact,
)
from deopjufier.manifest import ManifestItem
from tests.test_core_unit_coverage_utils import _make_manifest


def _item(
    *,
    kind: str = "generic",
    name: str = "item",
    status: str = "ok",
    confidence: float = 0.8,
    discovery_type: str | None = None,
    heuristic: bool | None = None,
    source_object_path: str | None = None,
    error: str | None = None,
) -> ManifestItem:
    return ManifestItem(
        kind=kind,
        name=name,
        status=status,
        confidence=confidence,
        discovery_type=discovery_type,
        heuristic=heuristic,
        source_object_path=source_object_path,
        error=error,
    )


def test_should_warn_for_missing_artifact_suppresses_opj_default_flow(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opj"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    assert should_warn_for_missing_artifact(manifest, "worksheet", detected_type="opj")


def test_should_warn_for_missing_artifact_respects_parser_backed_collection_markers(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    manifest.add_item(
        _item(
            kind="worksheet",
            name="book_collection",
            status="unsupported",
            source_object_path="book_collection",
            discovery_type="parser_backed_hint",
            heuristic=False,
            error="no_worksheet_objects",
        )
    )

    assert not should_warn_for_missing_artifact(
        manifest,
        "worksheet",
        detected_type="opju",
    )


def test_should_warn_for_missing_artifact_gates_excel_by_parser_backing(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)

    assert not should_warn_for_missing_artifact(
        manifest,
        "excel",
        detected_type="opju",
        has_parser_backed_artifacts=False,
    )

    sample = tmp_path / "sample_with_evidence.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    manifest.add_item(
        _item(
            kind="excel",
            name="excel_sheet",
            status="partial",
            source_object_path="excel_sheet",
            discovery_type="parser_window",
            heuristic=False,
        )
    )
    assert should_warn_for_missing_artifact(
        manifest,
        "excel",
        detected_type="opju",
        has_parser_backed_artifacts=True,
    )


def test_should_warn_for_missing_artifact_gates_matrix_by_parser_backing(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)

    assert not should_warn_for_missing_artifact(
        manifest,
        "matrix",
        detected_type="opju",
        has_parser_backed_artifacts=False,
    )

    sample = tmp_path / "sample_with_evidence.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    manifest.add_item(
        _item(
            kind="matrix",
            name="matrix_sheet",
            status="partial",
            source_object_path="matrix_sheet",
            discovery_type="parser_window",
            heuristic=False,
        )
    )
    assert should_warn_for_missing_artifact(
        manifest,
        "matrix",
        detected_type="opju",
        has_parser_backed_artifacts=True,
    )


def test_should_warn_for_missing_artifact_suppresses_opj_function_without_parser_evidence(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "sample.opj"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)

    assert not should_warn_for_missing_artifact(
        manifest,
        "function",
        detected_type="opj",
        has_parser_backed_artifacts=False,
    )


def test_should_warn_for_missing_artifact_gates_function_by_parser_backing(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)

    assert not should_warn_for_missing_artifact(
        manifest,
        "function",
        detected_type="opju",
        has_parser_backed_artifacts=False,
    )

    sample = tmp_path / "sample_with_evidence.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    manifest.add_item(
        _item(
            kind="function",
            name="function_line",
            status="partial",
            source_object_path="function_line",
            discovery_type="parser_window",
            heuristic=False,
        )
    )
    assert should_warn_for_missing_artifact(
        manifest,
        "function",
        detected_type="opju",
        has_parser_backed_artifacts=True,
    )


def test_has_malformed_graph_preview_detects_partial_malformed_items(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    assert not has_malformed_graph_preview(manifest)

    sample = tmp_path / "sample_malformed.opju"
    sample.write_text("x", encoding="utf-8")
    manifest = _make_manifest(sample)
    manifest.add_item(
        _item(
            kind="malformed_graph_preview",
            name="Graph1",
            status="partial",
            source_object_path="Graph/Graph1",
            discovery_type="parser_window",
            heuristic=True,
            error="png_chunk_crc_mismatch",
        )
    )
    assert has_malformed_graph_preview(manifest)
