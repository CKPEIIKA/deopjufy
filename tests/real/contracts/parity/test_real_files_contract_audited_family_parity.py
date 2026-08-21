"""Targeted parity checks for audited OPJ/OPJU family-level behavior."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.real.contracts.parity._audited_family_parity_data import (
    _AUDITED_FIXTURE_COUNTS,
    _OPJ_FIXTURES,
    _PUBLIC_OPJU_FIGURE_FIXTURES,
    REPO_ROOT,
    _assert_metadata_targets,
    _assert_windowed_non_collection_failures,
    _has_image_signature,
)


# Image-enabled extraction of the largest public fixture exceeds the default on slower runners.
@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("fixture_rel", "expected_graph_previews", "expected_parser_backed_graph_previews"),
    [
        ("refs/github/Ropj/inst/test.opj", 4, 0),
        ("refs/github/Ropj/inst/tree.opj", 1, 0),
        ("refs/openopj/support/test.opj", 2, 0),
        ("refs/ropj/src/Ropj/inst/test.opj", 4, 0),
        ("refs/ropj/src/Ropj/inst/tree.opj", 1, 0),
        ("refs/public/zenodo/zenodo-10364693-ahrrenius-ybscsz.opju", 26, 1),
        ("refs/public/zenodo/zenodo-10721640-figure-1b.opju", 0, 1),
        ("refs/public/zenodo/zenodo-18450855-eucd2p2.opju", 10, 1),
        ("refs/public/zenodo/zenodo-19549171-small-science-paper.opju", 9, 0),
    ],
)
def test_real_audited_graph_preview_counts_with_images(
    fixture_rel: str,
    expected_graph_previews: int,
    expected_parser_backed_graph_previews: int,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    record = _AUDITED_FIXTURE_COUNTS.get(fixture_rel)
    if record is None:
        pytest.skip(f"No audited family count entry for: {fixture_rel}")
    expected_matrix = int(record["families"].get("matrix", 0))

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    matrix_count = sum(
        1 for item in payload.get("items", []) if isinstance(item, dict) and item.get("kind") == "matrix"
    )
    assert matrix_count == expected_matrix, (
        f"Expected {expected_matrix} matrix items in image-enabled extract for {fixture_rel}, got {matrix_count}"
    )

    graph_preview_counts = Counter(item.get("kind") for item in payload.get("items", []) if isinstance(item, dict))
    assert graph_preview_counts["graph_preview"] == expected_graph_previews, (
        f"Expected {expected_graph_previews} graph_preview items for {fixture_rel}"
    )
    assert graph_preview_counts["parser_backed_graph_preview"] == expected_parser_backed_graph_previews, (
        f"Expected {expected_parser_backed_graph_previews} parser_backed_graph_preview items for {fixture_rel}"
    )

    parser_backed_previews = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "parser_backed_graph_preview"
    ]
    for item in parser_backed_previews:
        assert item.get("heuristic") is False
        assert item.get("discovery_type") == "parser_window"
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str)
        assert source_object_path.startswith("previews/")
        assert "origin_storage_preview_000" in source_object_path

        assert item.get("path") is not None
        path = run.output_dir / str(item["path"])
        status = item.get("status")
        assert status in {"extracted", "partial", "unsupported", "skipped", "failed"}
        preview_path = path.relative_to(run.output_dir).as_posix()
        expected_prefix = Path("graphs") / source_object_path
        assert preview_path.startswith(expected_prefix.as_posix() + "/")
        assert Path(preview_path).name.startswith("graph")
        if status == "extracted":
            assert path.exists()
            assert path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg"}
            preview_payload = path.read_bytes()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
                assert _has_image_signature(preview_payload)
            elif path.suffix.lower() == ".svg":
                assert preview_payload.startswith(b"<") or _has_image_signature(preview_payload)


@pytest.mark.parametrize(
    "fixture_rel",
    sorted(set(_AUDITED_FIXTURE_COUNTS) | set(_PUBLIC_OPJU_FIGURE_FIXTURES)),
)
def test_real_audited_origin_storage_report_paths_are_deterministic(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload
    output = run.output_dir

    report_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "origin_storage_report"
    ]
    report_json_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "origin_storage_report_json"
    ]
    summary_items = [
        item
        for item in payload.get("items", ())
        if isinstance(item, dict) and item.get("kind") == "origin_storage_report_summary"
    ]
    if not (report_items or report_json_items or summary_items):
        return

    for item in report_items:
        name = item.get("name")
        path_value = item.get("path")
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str) and source_object_path

        assert isinstance(name, str)
        if name in {"origin_storage_reports", "origin_storage_reports.json"}:
            if path_value is None:
                assert item.get("status") in {"unsupported", "partial", "skipped", "failed"}
                continue
            assert isinstance(path_value, str)
            assert path_value in {
                "origin_storage_reports",
                "origin_storage_reports/origin_storage_reports.json",
            }
            assert source_object_path == "origin_storage_reports"
            report_path = output / str(path_value)
            assert report_path.is_relative_to(output)
            rel_report_path = report_path.relative_to(output).as_posix()
            assert rel_report_path in {
                "origin_storage_reports",
                "origin_storage_reports/origin_storage_reports.json",
            }
            if item.get("status") == "extracted":
                assert report_path.exists()
            continue

        if path_value is None:
            assert item.get("status") in {"unsupported", "partial", "skipped", "failed"}
            continue
        assert isinstance(path_value, str)
        report_path = output / str(path_value)
        assert report_path.is_relative_to(output)
        rel_report_path = report_path.relative_to(output).as_posix()
        assert rel_report_path.startswith("origin_storage_reports/")
        assert source_object_path.startswith("origin_storage_reports/")
        assert rel_report_path.endswith(".txt")
        assert report_path.name.endswith(".txt")
        if item.get("status") == "extracted":
            assert report_path.exists()

    for item in report_json_items:
        source_object_path = item.get("source_object_path")
        path_value = item.get("path")
        assert isinstance(source_object_path, str) and source_object_path
        assert source_object_path.startswith("origin_storage_reports/")
        assert path_value is not None
        assert isinstance(path_value, str)
        report_path = output / str(path_value)
        assert report_path.is_relative_to(output)
        rel_report_path = report_path.relative_to(output).as_posix()
        assert rel_report_path.startswith("origin_storage_reports/")
        assert rel_report_path.endswith(".json")
        if item.get("status") == "extracted":
            assert report_path.exists()

    for item in summary_items:
        path_value = item.get("path")
        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str)
        assert source_object_path == "origin_storage_reports"
        assert path_value is not None
        assert isinstance(path_value, str)
        summary_path = output / str(path_value)
        assert summary_path.is_relative_to(output)
        assert (
            summary_path.relative_to(output).as_posix() == "origin_storage_reports/origin_storage_reports_summary.txt"
        )
        if item.get("status") == "extracted":
            assert summary_path.exists()


@pytest.mark.parametrize("fixture_rel", _OPJ_FIXTURES)
def test_real_audited_opj_items_keep_ownership_and_metadata_links(
    fixture_rel: str,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    non_collection_items = [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict) and not str(item.get("name", "")).endswith("_collection")
    ]
    assert non_collection_items, f"Expected non-collection artifacts for {fixture_rel}"

    for item in non_collection_items:
        kind = item.get("kind")
        if kind in {
            "origin_object_inventory",
            "strings",
            "raw_gap",
            "raw_dump",
            "project_tree",
        }:
            continue
        source_path = item.get("source_object_path")
        assert isinstance(source_path, str) and source_path, (
            f"Expected source_object_path for {kind} {item.get('name')} in {fixture_rel}"
        )

    _assert_windowed_non_collection_failures(payload, sample=sample)
    _assert_metadata_targets(payload, metadata_kind="graph_metadata", target_kind="graph")
    _assert_metadata_targets(
        payload,
        metadata_kind="worksheet_metadata",
        target_kind="worksheet",
    )
    _assert_metadata_targets(payload, metadata_kind="matrix_metadata", target_kind="matrix")
    _assert_metadata_targets(payload, metadata_kind="note_metadata", target_kind="note")

    metadata_dir_by_kind = {
        "graph_metadata": Path("graphs"),
        "worksheet_metadata": Path("books"),
        "matrix_metadata": Path("matrices"),
        "note_metadata": Path("notes"),
    }
    for item in payload.get("items", ()):  # iterate metadata items only
        if not isinstance(item, dict):
            continue
        metadata_kind = item.get("kind")
        if metadata_kind not in metadata_dir_by_kind:
            continue

        source_object_path = item.get("source_object_path")
        assert isinstance(source_object_path, str) and source_object_path
        assert item.get("path") is not None
        path = run.output_dir / str(item["path"])
        assert path.is_relative_to(run.output_dir)
        rel_path = path.relative_to(run.output_dir)
        root_dir = metadata_dir_by_kind[metadata_kind]
        assert rel_path.as_posix().startswith(f"{root_dir.as_posix()}/{source_object_path}/")
        assert rel_path.as_posix().endswith(".metadata.json")
        if item.get("status") == "extracted":
            assert path.exists()

    preview_sources = {
        item.get("source_object_path")
        for item in payload.get("items", [])
        if isinstance(item, dict)
        and item.get("kind") in {"graph_preview", "parser_backed_graph_preview"}
        and item.get("source_object_path") is not None
    }
    graph_sources = {
        item.get("source_object_path")
        for item in payload.get("items", [])
        if isinstance(item, dict)
        and item.get("kind") == "graph"
        and not str(item.get("name", "")).endswith("_collection")
        and item.get("source_object_path") is not None
    }
    assert preview_sources.issubset(graph_sources), (
        f"Expected all graph preview sources to match concrete graph sources in {fixture_rel}"
    )

    for item in payload.get("items", ()):
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "graph":
            continue
        source_object_path = item.get("source_object_path")
        if not isinstance(source_object_path, str) or not source_object_path:
            continue

        path_value = item.get("path")
        if path_value is None:
            continue
        path = run.output_dir / str(path_value)
        assert path.is_relative_to(run.output_dir)
        rel_path = path.relative_to(run.output_dir).as_posix()
        assert rel_path.startswith(f"graphs/{source_object_path}/") or rel_path == "graphs"

        if str(item.get("name", "")).endswith("_collection"):
            continue
        assert Path(rel_path).name == "graph.metadata.json"
        assert path.exists()


@pytest.mark.parametrize(
    ("fixture_rel", "expected_raw_dump_count"),
    [
        ("refs/public/zenodo/zenodo-10364693-ahrrenius-ybscsz.opju", 12),
        ("refs/public/zenodo/zenodo-18450855-eucd2p2.opju", 3),
        ("refs/public/zenodo/zenodo-19549171-small-science-paper.opju", 1),
    ],
)
def test_real_audited_raw_region_provenance_is_windowed(
    fixture_rel: str,
    expected_raw_dump_count: int,
    cached_extract,
) -> None:
    sample = REPO_ROOT / fixture_rel
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        with_raw_dir=True,
        raw_min_bytes=1024,
    )
    assert run.exit_code in {0, 4}
    assert run.raw_dir is not None

    payload = run.payload
    raw_items = [item for item in payload.get("items", []) if isinstance(item, dict) and item.get("kind") == "raw_dump"]
    assert len(raw_items) == expected_raw_dump_count, (
        f"Expected {expected_raw_dump_count} raw_dump artifacts for {fixture_rel}, got {len(raw_items)}"
    )

    file_bytes = sample.read_bytes()
    file_size = len(file_bytes)
    discovered_discovery_types = set()

    for item in raw_items:
        discovery_type = item.get("discovery_type")
        discovered_discovery_types.add(discovery_type)
        assert discovery_type in {"raw_region", "unknown_gap", "carved"}
        assert item.get("heuristic") is True
        status = item.get("status")
        assert status in {"extracted", "skipped"}
        if status == "extracted":
            assert item.get("path") is not None
            dumped_path = run.raw_dir / str(item["path"])
            assert dumped_path.exists()
        else:
            assert item.get("path") is None

        start = item.get("range_start")
        end = item.get("range_end")
        length = item.get("length")
        offset = item.get("offset")
        assert isinstance(start, int)
        assert isinstance(end, int)
        assert isinstance(length, int)
        assert isinstance(offset, int)
        assert start == offset
        assert end >= start
        assert end - start == length
        assert 0 <= start <= end <= file_size

        name = item.get("name")
        source_path = item.get("source_object_path")
        assert isinstance(name, str)
        assert isinstance(source_path, str)
        assert source_path == name
        assert source_path

        overlapping = item.get("overlapping_objects")
        assert isinstance(overlapping, list)
        assert all(isinstance(value, str) for value in overlapping)

    assert discovered_discovery_types
