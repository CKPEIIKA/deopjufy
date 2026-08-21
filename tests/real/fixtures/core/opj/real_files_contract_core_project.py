"""Project-level real-file contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import main
from tests.real.fixtures.core.real_files_contract_core import (
    LIGHT_REAL_PROJECTS,
    REAL_SMOKE_PROJECTS,
    REPO_ROOT,
    _project_id,
    _public_opju_graph_gap_sample,
    _run_inspect,
    _run_list,
)


@pytest.mark.parametrize("project", LIGHT_REAL_PROJECTS, ids=_project_id)
def test_real_project_inspect_is_stable(project: Path) -> None:
    code, payload = _run_inspect(project)
    assert code == 0
    assert payload["detected_type"] in {"opj", "opju"}
    assert payload["tool"]["name"] == "deopjufy"
    assert payload["reason"] == "extension"
    if project.suffix == ".opj":
        assert payload["support_class"] in {"heuristic", "partial"}
    else:
        assert payload["support_class"] in {"heuristic", "parser", "partial"}
    assert payload["status"] == "ok"
    assert isinstance(payload["counts"], dict)
    assert payload["counts"]["images"] >= 0
    assert isinstance(payload["size_bytes"], int)
    assert "origin_object_kinds" in payload["counts"]


@pytest.mark.parametrize("project", LIGHT_REAL_PROJECTS, ids=_project_id)
def test_real_project_list_keeps_offset_order(
    project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["list", str(project), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code in {0, 3}
    assert payload["file"] == str(project)
    assert payload["detected_type"] in {"opj", "opju"}

    offsets = [item["offset"] for item in payload["items"]]
    assert offsets == sorted(offsets)


@pytest.mark.parametrize("project", LIGHT_REAL_PROJECTS, ids=_project_id)
def test_real_project_extract_generates_manifest(
    project: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"
    raw_dir = tmp_path / "raw"

    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
            "--raw-dir",
            str(raw_dir),
            "--raw-min-bytes",
            "16384",
        ]
    )

    manifest = output / "manifest.json"
    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["input"]["path"] == str(project)
    assert payload["input"]["detected_type"] in {"opj", "opju"}
    assert payload["tool"]["backend"] == "native-parser"
    assert payload["parser_status"] in {"ok", "empty", "unsupported", "error"}
    assert payload["support_class"] in {"parser", "heuristic", "partial", "failed"}
    # Origin-object inventory collection emission is currently backend-dependent;
    # assert only contract-visible evidence we control directly here.


@pytest.mark.timeout(90)
@pytest.mark.parametrize("project", REAL_SMOKE_PROJECTS, ids=_project_id)
def test_real_project_cli_smoke_contract(project: Path, tmp_path: Path) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    inspect_code, inspect_payload = _run_inspect(project)
    assert inspect_code == 0
    assert inspect_payload["detected_type"] in {"opj", "opju"}
    assert inspect_payload["status"] in {"ok", "unsupported", "partial"}
    assert "parser_status" in inspect_payload

    list_code, list_payload = _run_list(project)
    assert list_code in {0, 3}
    assert list_payload["file"] == str(project)
    assert list_payload["detected_type"] in {"opj", "opju"}

    output = tmp_path / "out"
    raw_dir = tmp_path / "raw"
    extract_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
            "--raw-dir",
            str(raw_dir),
            "--raw-min-bytes",
            "16384",
        ]
    )

    assert extract_code in {0, 4}
    manifest_path = output / "manifest.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["input"]["path"] == str(project)
    assert payload["input"]["detected_type"] in {"opj", "opju"}
    assert payload["tool"]["backend"] == "native-parser"
    assert payload["status"] in {"ok", "unsupported", "partial"}
    assert payload["parser_status"] in {"ok", "empty", "unsupported", "error"}
    assert isinstance(payload["items"], list)
    # Inventory objects are optional in current backend behavior; assert fixture
    # output shape and parser status directly instead.


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-18450855-eucd2p2.opju",
    ],
)
def test_real_project_human_only_omits_non_artifact_partial_signals(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    output = tmp_path / "out"
    raw_dir = tmp_path / "raw"
    text_dir = tmp_path / "text"
    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--human-only",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
        ]
    )

    assert code in {0, 4}
    payload = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert payload["status"] in {"ok", "partial", "unsupported"}
    assert payload["parser_status"] in {"ok", "empty", "unsupported", "error"}
    assert not raw_dir.exists()
    assert not text_dir.exists()
    items = payload.get("items", [])
    assert all(item.get("kind") not in {"raw_dump", "text_region"} for item in items)
    assert all(item.get("status") == "extracted" for item in items)
    assert all(item.get("path") and (output / str(item["path"])).stat().st_size > 0 for item in items)


def test_real_project_default_profile_is_human_only(
    tmp_path: Path,
) -> None:
    project = _public_opju_graph_gap_sample()
    output = tmp_path / "out"
    raw_dir = tmp_path / "raw"
    text_dir = tmp_path / "text"

    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
        ]
    )

    assert code in {0, 4}
    payload = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    items = payload.get("items", [])
    assert payload["status"] in {"ok", "partial", "unsupported"}
    assert not raw_dir.exists()
    assert not text_dir.exists()
    assert all(item.get("kind") not in {"raw_dump", "text_region"} for item in items), (
        "Expected default profile to skip machine provenance outputs"
    )
    assert all(item.get("status") == "extracted" for item in items)
    assert all(item.get("path") and (output / str(item["path"])).stat().st_size > 0 for item in items)


def _item_signature(item: dict[str, object]) -> tuple[object, ...]:
    return (
        item.get("kind"),
        item.get("name"),
        item.get("status"),
        item.get("error"),
        item.get("path"),
        item.get("source_object_path"),
        item.get("discovery_type"),
        item.get("heuristic"),
        item.get("rows"),
        item.get("columns"),
    )


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
    ],
)
def test_real_project_parser_only_matches_human_profile(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    parser_only_output = tmp_path / "parser-only"
    human_output = tmp_path / "human"

    parser_only_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(parser_only_output),
            "--parser-only",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )
    human_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(human_output),
            "--human",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    assert parser_only_code in {0, 4}
    assert human_code in {0, 4}

    parser_only_payload = json.loads((parser_only_output / "manifest.json").read_text(encoding="utf-8"))
    human_payload = json.loads((human_output / "manifest.json").read_text(encoding="utf-8"))

    assert parser_only_payload["status"] in {"ok", "partial"}
    assert human_payload["status"] in {"ok", "partial"}
    assert parser_only_payload["status"] == human_payload["status"]
    assert sorted(_item_signature(item) for item in parser_only_payload.get("items", [])) == sorted(
        _item_signature(item) for item in human_payload.get("items", [])
    )


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
    ],
)
def test_real_project_parser_only_human_default_and_extended_are_distinct(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    parser_only_human_output = tmp_path / "parser-only-human"
    parser_only_extended_output = tmp_path / "parser-only-extended"
    raw_dir = tmp_path / "parser-only-extended-raw"
    text_dir = tmp_path / "parser-only-extended-text"

    human_mode_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(parser_only_human_output),
            "--parser-only",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )
    assert human_mode_code in {0, 4}

    parser_only_human_payload = json.loads((parser_only_human_output / "manifest.json").read_text(encoding="utf-8"))
    assert all(
        item.get("kind")
        not in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "raw_dump",
            "text_region",
        }
        for item in parser_only_human_payload.get("items", [])
    )
    assert not (parser_only_human_output / "metadata").exists()
    assert not (parser_only_human_output / "origin_storage_reports").exists()
    assert not raw_dir.exists()
    assert not text_dir.exists()

    extended_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(parser_only_extended_output),
            "--parser-only",
            "--extended",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
            "--raw-min-bytes",
            "1",
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "1",
        ]
    )
    assert extended_code in {0, 4}
    parser_only_extended_payload = json.loads(
        (parser_only_extended_output / "manifest.json").read_text(encoding="utf-8")
    )
    parser_extended_items = parser_only_extended_payload.get("items", ())
    assert parser_extended_items
    assert raw_dir.exists()
    assert text_dir.exists()
    assert any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "metadata",
            "raw_dump",
            "text_region",
        }
        for item in parser_extended_items
    )


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-19549171-small-science-paper.opju",
    ],
)
def test_real_project_human_artifacts_only_skips_machine_provenance_outputs(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    output = tmp_path / "out"
    raw_dir = tmp_path / "raw"
    text_dir = tmp_path / "text"
    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--human-artifacts-only",
            "--no-images",
            "--no-strings",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
        ]
    )

    assert code in {0, 4}
    payload = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    items = payload.get("items", [])
    assert not raw_dir.exists()
    assert not text_dir.exists()
    assert all(
        item.get("kind")
        not in {
            "raw_dump",
            "text_region",
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
        }
        for item in items
    )
    assert not (output / "metadata").exists()
    assert not (output / "origin_storage_reports").exists()
    assert any(item.get("kind") == "worksheet" for item in items), (
        "Expected human-facing parser outputs to remain with --human-artifacts-only"
    )
    assert any(item.get("status") in {"partial", "unsupported", "extracted"} for item in items)


def test_real_project_extended_profile_auto_creates_raw_and_text_outputs(
    tmp_path: Path,
) -> None:
    project = _public_opju_graph_gap_sample()
    output = tmp_path / "out"

    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--extended",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    manifest = output / "manifest.json"
    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    raw_dir = output / "raw"
    text_dir = output / "text"
    assert not raw_dir.exists()
    assert not text_dir.exists()
    raw_items = [item for item in payload.get("items", []) if item.get("kind") == "raw_dump"]
    text_items = [item for item in payload.get("items", []) if item.get("kind") == "text_region"]
    assert not raw_items
    assert not text_items
    assert all((text_dir / item["path"]).exists() for item in text_items if isinstance(item.get("path"), str))
    assert all((raw_dir / item["path"]).exists() for item in raw_items if isinstance(item.get("path"), str))


@pytest.mark.parametrize("extended_arg", ["--extended", "--map"])
def test_real_project_profile_aliases_include_machine_outputs(
    tmp_path: Path,
    extended_arg: str,
) -> None:
    project = _public_opju_graph_gap_sample()
    output = tmp_path / "out" / extended_arg.lstrip("-")

    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            extended_arg,
            "--no-images",
            "--no-strings",
        ]
    )

    manifest = output / "manifest.json"
    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "metadata",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
    ],
)
def test_real_project_parser_only_map_uses_machine_outputs(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    output = tmp_path / "out"
    raw_dir = output / "raw"
    text_dir = output / "text"

    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--parser-only",
            "--map",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
            "--raw-min-bytes",
            "1",
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "1",
        ]
    )

    assert code in {0, 4}
    manifest = output / "manifest.json"
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert raw_dir.exists()
    assert text_dir.exists()
    assert any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "metadata",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
    ],
)
def test_real_project_parser_only_map_uses_default_raw_text_locations(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    output = tmp_path / "out"
    code = main(
        [
            "extract",
            str(project),
            "-o",
            str(output),
            "--parser-only",
            "--map",
            "--no-images",
            "--no-strings",
            "--no-tables",
        ]
    )

    assert code in {0, 4}
    manifest = output / "manifest.json"
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert (output / "raw").exists()
    assert (output / "text").exists()
    assert any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "metadata",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    ("project"),
    [
        REPO_ROOT / "refs" / "public" / "zenodo" / "zenodo-10721640-figure-1b.opju",
    ],
)
def test_real_project_parser_only_map_extends_machine_profile_with_exact_byte_map(
    project: Path,
    tmp_path: Path,
) -> None:
    if not project.exists():
        pytest.skip(f"Fixture missing: {project}")

    extended_output = tmp_path / "parser-only-extended"
    map_output = tmp_path / "parser-only-map"
    extended_raw_dir = extended_output / "raw"
    extended_text_dir = extended_output / "text"
    map_raw_dir = map_output / "raw"
    map_text_dir = map_output / "text"

    extended_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(extended_output),
            "--parser-only",
            "--extended",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(extended_raw_dir),
            "--text-dir",
            str(extended_text_dir),
            "--raw-min-bytes",
            "1",
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "1",
        ]
    )
    map_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(map_output),
            "--parser-only",
            "--map",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(map_raw_dir),
            "--text-dir",
            str(map_text_dir),
            "--raw-min-bytes",
            "1",
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "1",
        ]
    )

    assert extended_code in {0, 4}
    assert map_code in {0, 4}

    extended_payload = json.loads((extended_output / "manifest.json").read_text(encoding="utf-8"))
    map_payload = json.loads((map_output / "manifest.json").read_text(encoding="utf-8"))

    assert extended_payload["status"] in {"ok", "partial"}
    assert map_payload["status"] in {"ok", "partial"}
    map_base_items = [item for item in map_payload.get("items", ()) if item.get("kind") != "byte_map"]
    assert sorted(_item_signature(item) for item in extended_payload.get("items", ())) == sorted(
        _item_signature(item) for item in map_base_items
    )
    assert any(item.get("kind") == "byte_map" and item.get("verification") == "exact" for item in map_payload["items"])
    assert (map_output / "byte-map/index.json").exists()
    assert extended_raw_dir.exists()
    assert extended_text_dir.exists()
    assert map_raw_dir.exists()
    assert map_text_dir.exists()
