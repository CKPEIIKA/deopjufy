"""OPJ-specific real-file contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import main
from deopjufier.opj import (
    parse_opj_boundaries,
    parse_opj_tree_nodes,
    parse_opj_tree_references,
)
from tests.real.fixtures.core.real_files_contract_core import (
    REAL_PROJECTS,
    REPO_ROOT,
    _assert_unsupported_collection,
    _project_id,
)


@pytest.mark.parametrize("project", [path for path in REAL_PROJECTS if path.suffix == ".opj"], ids=_project_id)
def test_real_opj_worksheet_partial_items_include_explicit_error(project: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"

    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
            "--extended",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--raw-min-bytes",
            "16384",
        ]
    )

    manifest = output / "manifest.json"
    assert code in {0, 4}
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    worksheet_partials = [
        item for item in payload["items"] if item.get("kind") == "worksheet" and item.get("status") == "partial"
    ]
    assert all(item.get("error") for item in worksheet_partials)


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
        REPO_ROOT / "refs" / "openopj" / "support" / "test.opj",
    ],
)
def test_real_opj_extract_emits_non_empty_worksheet_rows(project: Path, tmp_path: Path) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    output = tmp_path / "out"
    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
        ]
    )

    manifest_path = output / "manifest.json"
    assert code in {0, 4}
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name")).endswith("_collection")
    ]
    assert worksheet_items, "Expected worksheet items from real OPJ fixture"

    extracted = [item for item in worksheet_items if item.get("status") == "extracted"]
    assert extracted, "Expected at least one extracted worksheet"
    for item in extracted:
        assert (item.get("rows") or 0) > 0
        assert (item.get("columns") or 0) > 0
        table_path = output / str(item["path"])
        assert table_path.exists()
        lines = table_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) > 1


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-3779638-fig4.opj",
    ],
)
def test_real_project_default_profile_ignores_raw_and_text_output_dirs(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    output = tmp_path / "real-default-profile" / project.name
    raw_dir = output / "explicit_raw"
    text_dir = output / "explicit_text"
    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
        ]
    )
    manifest_path = output / "manifest.json"
    assert code in {0, 4}
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not raw_dir.exists()
    assert not text_dir.exists()
    assert "Raw/text carving options are inactive in human profile" in " ".join(payload.get("warnings", ()))
    assert not any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    "project",
    [
        REPO_ROOT / "refs" / "openopj" / "support" / "test.opj",
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
    ],
)
def test_real_opj_extract_emits_non_empty_matrix_rows(project: Path, cached_extract) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    run = cached_extract(project, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    output = run.output_dir
    payload = run.payload

    matrix_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "matrix" and not str(item.get("name")).endswith("_collection")
    ]
    assert matrix_items, "Expected matrix items from real OPJ fixture"

    extracted = [item for item in matrix_items if item.get("status") == "extracted"]
    assert extracted, "Expected at least one extracted matrix"
    for item in extracted:
        assert (item.get("rows") or 0) > 0
        assert (item.get("columns") or 0) > 0
        matrix_path = output / str(item["path"])
        assert matrix_path.exists()
        lines = matrix_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) > 1
        assert item.get("heuristic") is False
        assert item.get("discovery_type") == "parser_window"


@pytest.mark.parametrize("project", REAL_PROJECTS, ids=_project_id)
def test_real_project_strings_runs(project: Path) -> None:
    code = main(["strings", str(project), "--min-length", "6"])
    assert code == 0


@pytest.mark.parametrize(
    "sample",
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
        REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "tree.opj",
    ],
)
def test_real_tree_opj_has_no_parser_backed_matrix_payload_without_evidence(sample: Path, cached_extract) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload
    matrix_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "matrix" and not str(item.get("name")).endswith("_collection")
    ]
    assert not matrix_items, "Expected no parser-backed matrix artifact for tree fixture"

    parser_backed_matrix_markers = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "matrix"
        and item.get("discovery_type") == "parser_window"
        and item.get("error") == "no_extracted_table_rows"
    ]
    assert not parser_backed_matrix_markers, (
        "Expected no parser_window matrix gap artifacts for tree fixture without section-backed "
        f"matrix evidence: {sample}"
    )


@pytest.mark.parametrize(
    "sample",
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
        REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "tree.opj",
    ],
)
def test_real_tree_opj_origin_storage_reports_are_expectedly_absent(sample: Path, cached_extract) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}

    report_items = [
        item
        for item in run.payload.get("items", [])
        if item.get("kind") == "origin_storage_report" and item.get("name") == "origin_storage_reports"
    ]
    assert not report_items, "Expected no origin storage report collection artifact for tree.opj"


def test_real_openopj_support_excel_attachment_is_honest(
    cached_extract,
) -> None:
    sample = REPO_ROOT / "refs" / "openopj" / "support" / "test.opj"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload
    output = run.output_dir

    excel_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") in {"excel", "attachment"} and not str(item.get("name")).endswith("_collection")
    ]
    assert excel_items, "Expected excel/attachment artifacts from real fixture"

    attachment_items = [
        item for item in excel_items if item.get("name") == "Excel" and item.get("kind") == "attachment"
    ]
    assert attachment_items, "Expected non-spreadsheet-like Excel fixture item as attachment"
    for item in attachment_items:
        assert item.get("status") == "extracted"
        assert item.get("error") is None
        output_path = output / str(item["path"])
        assert output_path.exists()

    spreadsheet_like_items = [item for item in excel_items if str(item.get("name")).endswith(".XLS")]
    assert spreadsheet_like_items, "Expected spreadsheet-like excel artifact from real fixture"
    for item in spreadsheet_like_items:
        assert item.get("kind") in {"excel", "attachment"}
        assert item.get("error") != "no_extracted_table_rows"


@pytest.mark.parametrize(
    "sample",
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
        REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "tree.opj",
    ],
)
def test_real_tree_opj_does_not_emit_matrix_like_worksheet_placeholders(sample: Path, tmp_path: Path) -> None:
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
            "--manifest",
            str(manifest_path),
            "--no-images",
            "--no-strings",
        ]
    )
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name")).endswith("_collection")
    ]

    for item in worksheet_items:
        worksheet_name = str(item.get("name"))
        leaf = worksheet_name.rsplit("/", 1)[-1].lower()
        is_matrix_like = leaf.startswith(("mbook", "msheet", "matrix", "pdm"))
        assert not is_matrix_like, f"matrix-like worksheet placeholder leaked: {worksheet_name}"


@pytest.mark.parametrize(
    "sample",
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
        REPO_ROOT / "refs" / "ropj" / "src" / "Ropj" / "inst" / "tree.opj",
    ],
)
def test_real_tree_opj_worksheet_partials_require_data_or_metadata(sample: Path, cached_extract) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name")).endswith("_collection")
    ]
    for item in worksheet_items:
        if item.get("status") == "partial":
            has_metadata = any(
                metadata_item.get("kind") == "worksheet_metadata"
                and metadata_item.get("name") == f"{item.get('name')}_metadata"
                for metadata_item in payload.get("items", [])
                if isinstance(metadata_item, dict)
            )
            assert item.get("rows", 0) > 0 or has_metadata, (
                f"zero-row worksheet partial without metadata is now considered unsupported for tree.opj: {item!r}"
            )

    _assert_unsupported_collection(
        payload=payload,
        kind="worksheet",
        name="book_collection",
        error="no_extracted_table_rows",
    )

    assert not any(
        item.get("kind") in {"matrix", "matrix_collection", "matrix_metadata"} for item in payload.get("items", [])
    ), f"Tree fixture matrix placeholders should be suppressed for {sample}"


def test_real_zenodo_3779638_fig4_opj_is_honest_baseline(cached_extract) -> None:
    sample = REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-3779638-fig4.opj"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    run = cached_extract(sample, "--no-images", "--no-strings")
    assert run.exit_code in {0, 4}
    payload = run.payload

    worksheet_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "worksheet" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert worksheet_items, "Expected worksheet artifacts for zenodo-3779638-fig4.opj"
    assert any(item.get("status") == "extracted" and item.get("rows", 0) > 0 for item in worksheet_items), (
        "Expected at least one emitted worksheet table row for fig4 baseline"
    )
    assert all(item.get("status") in {"extracted", "partial"} for item in worksheet_items)

    note_items = [
        item
        for item in payload.get("items", [])
        if item.get("kind") == "note" and not str(item.get("name", "")).endswith("_collection")
    ]
    assert note_items, "Expected note-like parser-backed outputs for zenodo-3779638-fig4.opj"
    assert all(item.get("status") == "extracted" for item in note_items)

    for kind_name, collection_name in (
        ("graph", "graph_collection"),
        ("matrix", "matrix_collection"),
    ):
        assert any(
            item.get("kind") == kind_name
            and item.get("name") == collection_name
            and item.get("status") == "unsupported"
            for item in payload.get("items", [])
        ), f"Expected unsupported {kind_name} collection for fig4 baseline"

    assert not any(item.get("kind") == "origin_storage_report" for item in payload.get("items", [])), (
        "Unexpected origin storage report for fig4 baseline"
    )

    for kind_name in {"graph_preview", "parser_backed_graph_preview"}:
        assert not any(
            item.get("kind") == kind_name and item.get("status") == "extracted" for item in payload.get("items", [])
        ), f"Expected no extracted {kind_name} output from fig4 baseline"

    for item in payload.get("items", []):
        if item.get("kind") == "graph" and item.get("name") == "graph_collection":
            assert item.get("error") == "no_graph_previews"
            break

    data = sample.read_bytes()
    boundaries = parse_opj_boundaries(data)
    assert not any(item.kind == "matrix" for item in boundaries), (
        "Found parser-classified matrix boundaries; matrix collection gap is no longer evidence-based"
    )
    matrix_like_nodes = [
        node
        for node in parse_opj_tree_nodes(data)
        if node.name.lower().startswith(("mbook", "msheet", "matrix", "pdm"))
    ]
    assert not matrix_like_nodes, f"Found matrix-like tree evidence: {[node.name for node in matrix_like_nodes]}"
    matrix_like_references = [
        reference
        for reference in parse_opj_tree_references(data)
        if reference.child_name.lower().startswith(("mbook", "msheet", "matrix", "pdm"))
    ]
    assert not matrix_like_references, (
        f"Expected no OPJ matrix-like tree references, got {[item.child_name for item in matrix_like_references]}"
    )
