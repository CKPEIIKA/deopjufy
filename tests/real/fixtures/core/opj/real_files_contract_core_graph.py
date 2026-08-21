"""Split out graph/project-tree real-file contracts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from deopjufier.blocks import GIF_SIGS, JPEG_SIG, PNG_SIG
from deopjufier.cli import main
from deopjufier.opj import parse_opj_tree_nodes
from deopjufier.opju import (
    OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,
    parse_opju_records,
)
from tests.real.fixtures.core.real_files_contract_core import (
    _assert_unsupported_collection,
    _project_id,
    _public_opju_graph_gap_sample,
    _public_opju_jpg_attachment_sample,
    _public_opju_report_sample,
    _public_opju_worksheet_gap_sample,
)
from tests.test_core_unit_coverage_utils import _repo_root, _resolve_repo_fixture

REPO_ROOT = _repo_root(Path(__file__))

REAL_GRAPH_FIXTURE_PATHS = [
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
    REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "openopj" / "support" / "test.opj",
]


_SVG_SIGNATURE_RE = re.compile(rb"<svg\b", re.IGNORECASE)


def _has_image_signature(payload: bytes) -> bool:
    if payload.startswith(PNG_SIG) or payload.startswith(JPEG_SIG):
        return True
    if any(payload.startswith(signature) for signature in GIF_SIGS):
        return True
    return _SVG_SIGNATURE_RE.search(payload) is not None


@pytest.mark.parametrize("sample", REAL_GRAPH_FIXTURE_PATHS, ids=_project_id)
def test_real_graph_preview_artifacts_have_stable_graph_alignment(
    sample: Path,
    cached_extract,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-tables", "--no-strings")
    payload = run.payload
    graph_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "graph" and not str(item.get("name")).endswith("_collection")
    ]
    assert graph_items, f"No graph objects found in {sample}"

    preview_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") in {"graph_preview", "parser_backed_graph_preview", "malformed_graph_preview"}
    ]
    assert preview_items, f"No graph-preview artifacts found in {sample}"

    preview_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in preview_items:
        source = item.get("source_object_path")
        if not source:
            continue
        preview_by_source.setdefault(source, []).append(item)

    for graph_item in graph_items:
        source = graph_item.get("source_object_path")
        assert source
        preview_candidates = preview_by_source.get(source, [])
        assert preview_candidates, f"Missing preview artifact for {source}"

        assert all(item.get("name") == graph_item.get("name") for item in preview_candidates)
        assert all(item.get("discovery_type") == graph_item.get("discovery_type") for item in preview_candidates)

        if graph_item.get("status") == "unsupported":
            assert any(
                item.get("status") == "unsupported" and item.get("error") == graph_item.get("error")
                for item in preview_candidates
            )
        elif graph_item.get("status") == "partial":
            assert any(item.get("status") in {"partial", "unsupported"} for item in preview_candidates)
            if graph_item.get("error") is not None:
                assert any(item.get("error") == graph_item.get("error") for item in preview_candidates)
        elif graph_item.get("status") == "extracted":
            assert any(item.get("status") == "extracted" for item in preview_candidates)
            for item in preview_candidates:
                if item.get("status") == "extracted":
                    assert item.get("path")
                    assert (run.output_dir / str(item["path"])).exists()


@pytest.mark.parametrize(
    "sample",
    [
        _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/tree.opj"),
        _resolve_repo_fixture(Path(__file__), "refs/ropj/src/Ropj/inst/tree.opj"),
    ],
)
def test_real_opj_extract_exports_project_tree_hierarchy(
    sample: Path,
    tmp_path: Path,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "out"
    manifest_path = output / "manifest.json"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )
    assert code in {0, 4}
    assert manifest_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    tree_items = [item for item in payload.get("items", []) if item.get("kind") == "project_tree"]
    assert tree_items, f"Expected project-tree manifest entries for {sample}"

    expected_node_paths = [node.path for node in parse_opj_tree_nodes(sample.read_bytes())]
    assert expected_node_paths, f"Expected parser-visible tree nodes for {sample}"

    observed = {item["path"] for item in tree_items if isinstance(item.get("path"), str)}
    for node_path in expected_node_paths:
        expected_path = str(Path("tree") / node_path / "node.json")
        assert expected_path in observed
        assert (output / expected_path).exists()


@pytest.mark.parametrize(
    ("sample", "error"),
    [
        (REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj", "no_graph_previews"),
        (REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj", "no_graph_previews"),
        (REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "test.opj", "no_graph_previews"),
        (REPO_ROOT / "refs" / "openopj" / "support" / "test.opj", "no_graph_previews"),
    ],
)
def test_real_graph_collection_unsupported_marker_stable(
    sample: Path,
    error: str,
    cached_extract,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")
    payload = cached_extract(sample, "--no-images").payload
    _assert_unsupported_collection(
        payload,
        kind="graph",
        name="graph_collection",
        error=error,
    )
    _assert_no_warning_for_unsupported_collection(
        payload,
        kind="graph",
        warning="No graph data emitted to graph exports.",
    )


@pytest.mark.parametrize(
    "sample",
    [
        (REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju"),
        (REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-s3.opju"),
        (REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-s6.opju"),
        (REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-s7.opju"),
    ],
)
def test_real_graph_collection_bounds_match_opju_preview_windows(
    sample: Path,
    cached_extract,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")
    payload = cached_extract(sample, "--no-images").payload
    graph_collection = next(
        (
            item
            for item in payload.get("items", [])
            if item.get("kind") == "graph"
            and item.get("name") == "graph_collection"
            and item.get("status") == "unsupported"
            and item.get("error") == "no_graph_previews"
        ),
        None,
    )
    assert graph_collection is not None, f"Expected graph collection artifact for {sample}"
    assert isinstance(graph_collection.get("range_start"), int)
    assert isinstance(graph_collection.get("range_end"), int)
    range_start = graph_collection["range_start"]
    range_end = graph_collection["range_end"]
    assert range_start <= range_end
    file_bytes = sample.read_bytes()
    assert 0 <= range_start <= range_end <= len(file_bytes)

    parsed_records = parse_opju_records(file_bytes, path=sample)
    preview_spans = [
        (record.offset, record.offset + record.length)
        for record in parsed_records.regions
        if record.kind == OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW and record.length > 0
    ]
    if preview_spans:
        assert graph_collection["range_start"] == min(start for start, _ in preview_spans)
        assert graph_collection["range_end"] == max(end for _, end in preview_spans)


def test_real_opj_graph_preview_missing_has_windowed_no_image_evidence(
    cached_extract,
) -> None:
    sample = REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    payload = cached_extract(sample).payload
    misses = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "graph_preview"
        and item.get("error") == "no_embedded_image_block"
        and item.get("status") == "unsupported"
        and isinstance(item.get("range_start"), int)
        and isinstance(item.get("range_end"), int)
    ]
    assert misses, "Expected unsupported graph preview miss with range evidence"

    file_bytes = sample.read_bytes()
    for item in misses:
        range_start = item["range_start"]
        range_end = item["range_end"]
        assert 0 <= range_start <= range_end <= len(file_bytes)
        preview_window = file_bytes[range_start:range_end]
        assert not _has_image_signature(preview_window)


def _run_extract_manifest(sample: Path, tmp_path: Path, *extra_args: str) -> dict[str, Any]:
    output = tmp_path / "out"
    args = [
        "extract",
        str(sample),
        "-o",
        str(output),
        "--no-strings",
        "--no-tables",
    ]
    args.extend(extra_args)
    code = main(args)
    assert code in {0, 4}
    manifest_path = output / "manifest.json"
    assert manifest_path.exists()
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _assert_no_warning_for_unsupported_collection(payload: dict[str, Any], kind: str, warning: str) -> None:
    items = payload.get("items", [])
    warnings = payload.get("warnings", [])
    assert isinstance(items, list)
    assert isinstance(warnings, list)
    has_unsupported_collection = any(
        isinstance(item, dict)
        and item.get("kind") == kind
        and isinstance(item.get("name"), str)
        and item["name"].endswith("_collection")
        and item.get("status") == "unsupported"
        for item in items
    )
    if has_unsupported_collection:
        assert not any(warning in warning_text for warning_text in warnings)


def test_real_extract_no_worksheet_warning_when_worksheet_collection_is_unsupported(cached_extract) -> None:
    payload = cached_extract(_public_opju_worksheet_gap_sample(), "--no-images").payload
    _assert_no_warning_for_unsupported_collection(
        payload,
        kind="worksheet",
        warning="No worksheet data emitted to book exports.",
    )


@pytest.mark.parametrize(
    ("sample", "kind", "warning"),
    [
        (
            _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/tree.opj"),
            "worksheet",
            "No worksheet data emitted to book exports.",
        ),
        (
            _resolve_repo_fixture(Path(__file__), "refs/ropj/src/Ropj/inst/tree.opj"),
            "worksheet",
            "No worksheet data emitted to book exports.",
        ),
    ],
)
def test_real_extract_no_warning_when_collection_is_unsupported(
    sample: Path,
    kind: str,
    warning: str,
    cached_extract,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")
    payload = cached_extract(sample, "--no-images").payload
    _assert_no_warning_for_unsupported_collection(payload, kind=kind, warning=warning)


def test_real_extract_zenodo_worksheet_hint_is_evidence(
    cached_extract,
) -> None:
    sample = _resolve_repo_fixture(
        Path(__file__),
        "refs/public/zenodo/zenodo-10364693-ahrrenius-ybscsz.opju",
    )
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    payload = cached_extract(sample, "--no-images").payload

    assert not any("No worksheet data emitted to book exports." in warning for warning in payload.get("warnings", []))
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert worksheet_items, "Expected parser-backed worksheet artifact for worksheet-gap sample"
    assert all(item.get("status") in {"partial", "extracted"} for item in worksheet_items)
    assert all(item.get("error") in {None, "no_extracted_table_rows"} for item in worksheet_items)


def test_real_extract_opju_without_excel_collection_records_has_no_excel_warning(cached_extract) -> None:
    sample = _public_opju_report_sample()
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    payload = cached_extract(sample, "--no-images").payload
    items = payload.get("items", [])
    assert isinstance(items, list)
    assert not any(
        isinstance(item, dict) and item.get("kind") == "excel" and str(item.get("name", "")).endswith("_collection")
        for item in items
    )
    assert "No excel data emitted to excel exports." not in payload.get("warnings", [])


@pytest.mark.parametrize(
    "sample_factory",
    [
        _public_opju_report_sample,
        _public_opju_worksheet_gap_sample,
        _public_opju_graph_gap_sample,
        _public_opju_jpg_attachment_sample,
    ],
    ids=[
        "zenodo-10721640-figure-1b",
        "zenodo-10364693-ahrrenius-ybscsz",
        "zenodo-18450855-eucd2p2",
        "zenodo-19549171-small-science-paper",
    ],
)
def test_real_opju_parser_only_reduces_worksheet_noise(sample_factory, cached_extract) -> None:
    sample = sample_factory()
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    default_payload = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        "--no-tables",
    ).payload
    parser_only_payload = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        "--no-tables",
        "--parser-only",
    ).payload

    default_worksheets = [item for item in default_payload.get("items", []) if item.get("kind") == "worksheet"]
    parser_only_worksheets = [item for item in parser_only_payload.get("items", []) if item.get("kind") == "worksheet"]

    assert default_worksheets
    assert parser_only_worksheets
    assert len(parser_only_worksheets) <= len(default_worksheets)
    assert all(
        str(item.get("name", "")).endswith("_collection")
        or item.get("discovery_type") in {"parser_window", "parser_backed_hint"}
        for item in parser_only_worksheets
    )
    assert all(item.get("heuristic") is not True for item in parser_only_worksheets)


def test_real_opju_graph_gap_parser_only_worksheet_gap_support_is_expected(
    cached_extract,
) -> None:
    sample = _public_opju_graph_gap_sample()
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    payload = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        "--no-tables",
        "--parser-only",
    ).payload

    assert payload["support_class"] in {"parser", "partial"}
    worksheet_items = [item for item in payload.get("items", []) if item.get("kind") == "worksheet"]
    assert worksheet_items
    assert all(
        str(item.get("name", "")).endswith("_collection")
        or item.get("discovery_type") in {"parser_window", "parser_backed_hint"}
        for item in worksheet_items
    )
    assert all(item.get("status") in {"partial", "extracted"} for item in worksheet_items)
    assert any(item.get("error") == "no_extracted_table_rows" for item in worksheet_items)
    assert all(item.get("heuristic") is not True for item in worksheet_items)


@pytest.mark.parametrize("sample", REAL_GRAPH_FIXTURE_PATHS, ids=_project_id)
def test_real_opj_parser_only_limits_object_noise(sample: Path, cached_extract) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    default_payload = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        "--no-tables",
    ).payload
    parser_only_payload = cached_extract(
        sample,
        "--no-images",
        "--no-strings",
        "--no-tables",
        "--parser-only",
    ).payload

    default_items = default_payload.get("items", [])
    parser_items = parser_only_payload.get("items", [])
    assert parser_items, f"Expected parser-only extraction to emit parser-backed items for {sample}"

    default_worksheet_names_heuristic = {
        item.get("name") for item in default_items if item.get("kind") == "worksheet" and item.get("heuristic")
    }
    parser_only_worksheet_names = {item.get("name") for item in parser_items if item.get("kind") == "worksheet"}

    assert parser_only_worksheet_names.isdisjoint(default_worksheet_names_heuristic)
    assert len(parser_items) <= len(default_items)
    assert all(item.get("heuristic") is not True for item in parser_items if item.get("kind") == "worksheet")


def test_public_opju_function_items_expose_formula_range_metadata(cached_extract) -> None:
    sample = _public_opju_graph_gap_sample()
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    payload = cached_extract(sample, "--no-images").payload
    function_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "function" and item.get("name") != "function_collection"
    ]
    assert function_items, "Expected parser-backed function artifacts for public fixture"
    assert all(item.get("error") is None for item in function_items)
    assert any(item.get("status") == "extracted" for item in function_items)


@pytest.mark.timeout(240)
def test_public_opju_function_metadata_sidecar_is_deterministic(tmp_path: Path) -> None:
    sample = _public_opju_graph_gap_sample()
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run_hashes: list[list[str]] = []
    for index in range(2):
        output = tmp_path / f"public-run-{index}"
        code = main(
            [
                "extract",
                str(sample),
                "-o",
                str(output),
                "--no-images",
                "--no-tables",
            ]
        )
        assert code in {0, 4}
        manifest_path = output / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata_paths = [
            output / str(item.get("path"))
            for item in payload.get("items", [])
            if item.get("kind") == "function_metadata" and isinstance(item.get("path"), str)
        ]
        if not metadata_paths:
            function_items = [
                item
                for item in payload.get("items", [])
                if item.get("kind") == "function" and item.get("error") is None
            ]
            assert function_items, "Expected at least one function artifact from public fixture"
            continue
        metadata_hashes = []
        for path in metadata_paths:
            assert path.exists()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            metadata_hashes.append(digest)
        run_hashes.append(sorted(metadata_hashes))
        assert payload["status"] in {"ok", "partial"}

    if run_hashes:
        assert len(run_hashes) == 2
        assert run_hashes[0] == run_hashes[1]


def test_real_project_dump_block_prefix() -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/test.opj")

    code = main(
        [
            "dump-block",
            str(sample),
            "--offset",
            "0",
            "--length",
            "16",
        ]
    )

    assert code == 0
