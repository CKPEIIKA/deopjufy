"""Tests for extract profile and raw-surface behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import main
from tests.test_core_unit_coverage_utils import _resolve_repo_fixture

_VALID_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    + b"\x90wS\xde"
    + b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x17"
    + b"8U\x00\x00\x00\x00IEND\xaeB`\x82"
)

_VALID_JPEG_1X1 = (
    b"\xff\xd8"
    + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    + b"\x00\x00"
    + b"\xff\xd9"
)


def test_extract_raw_dir_emits_manifest_items(tmp_path: Path) -> None:
    sample = tmp_path / "rawsample.opju"
    jpeg = _VALID_JPEG_1X1
    sample.write_bytes(b"R" * 1536 + jpeg + b"X" * 1536)

    outdir = tmp_path / "out"
    rawdir = tmp_path / "raw"
    manifest = outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
            "--raw-dir",
            str(rawdir),
        ]
    )

    assert code == 0
    assert manifest.exists()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert all(item.get("path") is None or not Path(item["path"]).is_absolute() for item in payload["items"])
    raw_items = [item for item in payload["items"] if item["kind"] == "raw_dump"]
    assert raw_items
    assert len(raw_items) == 2
    assert all(item.get("source_object_path") is not None for item in raw_items)
    assert payload["tool"]["backend"] == "native-parser"
    assert rawdir.exists()


def test_extract_default_profile_ignores_raw_dir_without_extended(tmp_path: Path) -> None:
    sample = tmp_path / "rawsample.opju"
    sample.write_bytes(b"R" * 512)

    outdir = tmp_path / "out"
    rawdir = tmp_path / "raw"
    manifest = outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--raw-dir",
            str(rawdir),
            "--raw-min-bytes",
            "32",
        ]
    )

    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert all(item.get("kind") != "raw_dump" for item in payload["items"])
    assert not rawdir.exists()


def test_extract_default_profile_matches_explicit_human_profile(tmp_path: Path) -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/test.opj")
    if not sample.exists():
        pytest.skip("Public OPJ fixture missing.")

    default_outdir = tmp_path / "default"
    human_outdir = tmp_path / "human"

    default_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(default_outdir),
            "--no-images",
            "--no-tables",
        ]
    )
    human_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(human_outdir),
            "--human",
            "--no-images",
            "--no-tables",
        ]
    )
    assert default_code in {0, 4}
    assert human_code in {0, 4}

    default_payload = json.loads((default_outdir / "manifest.json").read_text(encoding="utf-8"))
    human_payload = json.loads((human_outdir / "manifest.json").read_text(encoding="utf-8"))

    assert default_payload["status"] in {"ok", "partial"}
    assert human_payload["status"] in {"ok", "partial"}
    assert default_payload["status"] == human_payload["status"]

    def _item_key(item: dict[str, object]) -> tuple[object, ...]:
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

    assert sorted(_item_key(item) for item in default_payload["items"]) == sorted(
        _item_key(item) for item in human_payload["items"]
    )


@pytest.mark.parametrize(
    "human_flag",
    ["--human-only", "--human-artifacts-only"],
)
def test_extract_human_alias_profiles_match_explicit_human_profile(
    human_flag: str,
    tmp_path: Path,
) -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/test.opj")
    if not sample.exists():
        pytest.skip("Public OPJ fixture missing.")

    alias_outdir = tmp_path / f"alias_{human_flag.removeprefix('--').replace('-', '_')}"
    base_outdir = tmp_path / "base"

    alias_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(alias_outdir),
            human_flag,
            "--no-images",
            "--no-tables",
        ]
    )
    base_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(base_outdir),
            "--human",
            "--no-images",
            "--no-tables",
        ]
    )
    assert alias_code in {0, 4}
    assert base_code in {0, 4}

    base_payload = json.loads((base_outdir / "manifest.json").read_text(encoding="utf-8"))
    alias_payload = json.loads((alias_outdir / "manifest.json").read_text(encoding="utf-8"))

    assert base_payload["status"] in {"ok", "partial"}
    assert alias_payload["status"] in {"ok", "partial"}
    assert base_payload["status"] == alias_payload["status"]

    def _item_key(item: dict[str, object]) -> tuple[object, ...]:
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

    assert sorted(_item_key(item) for item in base_payload["items"]) == sorted(
        _item_key(item) for item in alias_payload["items"]
    )


def test_extract_default_profile_skips_machine_provenance_artifacts(tmp_path: Path) -> None:
    sample = _resolve_repo_fixture(Path(__file__), Path("refs/github/Ropj/inst/test.opj"))
    if not sample.exists():
        pytest.skip("Public OPJ fixture missing.")

    outdir = tmp_path / "out"
    manifest_path = outdir / "manifest.json"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-tables",
        ]
    )
    assert code in {0, 4}

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] in {"ok", "partial"}
    forbidden_kinds = {
        "origin_object_inventory",
        "origin_storage_report",
        "origin_storage_report_json",
        "origin_storage_report_summary",
        "raw_dump",
        "text_region",
    }
    assert all(item.get("kind") not in forbidden_kinds for item in payload["items"])
    assert not (outdir / "metadata").exists()
    assert not (outdir / "origin_storage_reports").exists()
    assert not (outdir / "raw").exists()
    assert not (outdir / "text").exists()


def test_extract_parser_only_is_human_profile_by_default(tmp_path: Path) -> None:
    sample_fixture = "refs/public/zenodo/zenodo-10721640-figure-1b.opju"
    sample = _resolve_repo_fixture(Path(__file__), sample_fixture)
    if not sample.exists():
        pytest.skip(f"{sample_fixture} fixture missing.")

    parser_only_outdir = tmp_path / "parser-only"
    human_outdir = tmp_path / "human"
    rawdir = tmp_path / "raw"
    textdir = tmp_path / "text"
    parser_manifest = parser_only_outdir / "manifest.json"
    human_manifest = human_outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(parser_only_outdir),
            "--parser-only",
            "--no-images",
            "--no-tables",
            "--raw-dir",
            str(rawdir),
            "--text-dir",
            str(textdir),
        ]
    )
    human_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(human_outdir),
            "--human",
            "--no-images",
            "--no-tables",
            "--raw-dir",
            str(rawdir / "human"),
            "--text-dir",
            str(textdir / "human"),
        ]
    )

    assert code in {0, 4}
    assert human_code in {0, 4}
    assert parser_manifest.exists()
    assert human_manifest.exists()

    parser_payload = json.loads(parser_manifest.read_text(encoding="utf-8"))
    human_payload = json.loads(human_manifest.read_text(encoding="utf-8"))

    parser_status = parser_payload.get("status")
    human_status = human_payload.get("status")
    assert parser_status in {"ok", "partial"}
    assert human_status in {"ok", "partial"}
    assert parser_status == human_status

    def _item_key(item: dict[str, object]) -> tuple[object, ...]:
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

    assert sorted(_item_key(item) for item in parser_payload["items"]) == sorted(
        _item_key(item) for item in human_payload["items"]
    )

    forbidden_kinds = {
        "origin_object_inventory",
        "origin_storage_report",
        "origin_storage_report_json",
        "origin_storage_report_summary",
        "raw_dump",
        "text_region",
    }
    assert all(item.get("kind") not in forbidden_kinds for item in parser_payload["items"])
    assert not rawdir.exists()
    assert not textdir.exists()
    assert not (parser_only_outdir / "metadata").exists()
    assert not (parser_only_outdir / "origin_storage_reports").exists()
    assert not (human_outdir / "metadata").exists()
    assert not (human_outdir / "origin_storage_reports").exists()


@pytest.mark.parametrize("machine_profile", ["--extended", "--map"])
def test_extract_parser_only_with_extended_keeps_raw_text_output(
    tmp_path: Path,
    machine_profile: str,
) -> None:
    sample = tmp_path / "parser-only-extended.opju"
    sample.write_bytes(
        b"Readable text for parser-only extended profile\n"
        + b"visible text for classification\n"
        + b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        + b"more trailing text\n"
    )

    outdir = tmp_path / "out"
    manifest = outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--parser-only",
            machine_profile,
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
            "--raw-min-bytes",
            "1",
            "--text-min-bytes",
            "1",
            "--text-min-length",
            "1",
        ]
    )

    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    rawdir = outdir / "raw"
    textdir = outdir / "text"
    raw_items = [item for item in payload["items"] if item.get("kind") == "raw_dump"]
    text_items = [item for item in payload["items"] if item.get("kind") == "text_region"]

    assert raw_items
    assert text_items
    assert rawdir.exists()
    assert textdir.exists()


@pytest.mark.parametrize("machine_profile", ["--extended", "--map"])
def test_parser_only_extended_keeps_machine_provenance_artifacts(
    tmp_path: Path,
    machine_profile: str,
) -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/test.opj")
    if not sample.exists():
        pytest.skip("Public OPJ fixture missing.")

    outdir = tmp_path / "parser-only-extended"
    manifest = outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--parser-only",
            machine_profile,
            "--no-images",
            "--no-tables",
            "--no-strings",
        ]
    )

    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    kinds = {item.get("kind") for item in payload["items"]}
    assert "origin_object_inventory" in kinds
    assert "origin_storage_report" in kinds
    assert (outdir / "metadata").exists()
    assert (outdir / "origin_storage_reports").exists()


@pytest.mark.parametrize("machine_profile", ["--extended", "--map"])
def test_extract_extended_profile_auto_defaults_raw_and_text_output_dirs(
    tmp_path: Path,
    machine_profile: str,
) -> None:
    sample = tmp_path / "extended-defaults.opju"
    sample.write_bytes(b"Readable text for extraction profile\n" * 128)

    outdir = tmp_path / "out"
    manifest = outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--no-images",
            "--no-tables",
            machine_profile,
        ]
    )

    assert code in {0, 4}
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    rawdir = outdir / "raw"
    textdir = outdir / "text"
    raw_items = [item for item in payload["items"] if item.get("kind") == "raw_dump"]
    text_items = [item for item in payload["items"] if item.get("kind") == "text_region"]

    assert raw_items
    assert text_items
    assert rawdir.exists()
    assert textdir.exists()


def test_extract_human_only_skips_raw_and_text_artifacts(tmp_path: Path) -> None:
    sample = tmp_path / "samples.opju"
    sample.write_bytes(b"Readable text for extract\nand visible strings from the file.\n")

    outdir = tmp_path / "out"
    rawdir = tmp_path / "raw"
    textdir = tmp_path / "text"
    manifest = outdir / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            "--human-only",
            "--no-objects",
            "--no-tables",
            "--raw-dir",
            str(rawdir),
            "--text-dir",
            str(textdir),
            "--strings-min-length",
            "1",
        ]
    )

    assert code == 0
    assert manifest.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert all(item.get("kind") not in {"raw_dump", "text_region"} for item in payload["items"])
    assert all(item.get("kind") != "strings" for item in payload["items"])
    assert not rawdir.exists()
    assert not textdir.exists()


@pytest.mark.parametrize(
    "human_flag",
    ["--human-only", "--human-artifacts-only", "--human"],
)
def test_extract_human_profile_skips_machine_provenance_artifacts(
    human_flag: str,
    tmp_path: Path,
) -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/github/Ropj/inst/test.opj")
    if not sample.exists():
        pytest.skip("Public OPJ fixture missing.")

    outdir = tmp_path / "out"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(outdir),
            human_flag,
            "--raw-dir",
            str(tmp_path / "raw"),
            "--text-dir",
            str(tmp_path / "text"),
        ]
    )
    assert code == 0

    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    assert all(
        item.get("kind")
        not in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
        }
        for item in manifest["items"]
    )
    assert not (outdir / "metadata").exists()
    assert not (outdir / "origin_storage_reports").exists()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "text").exists()


def test_extract_human_profile_keeps_only_non_empty_primary_artifacts(tmp_path: Path) -> None:
    sample = _resolve_repo_fixture(Path(__file__), "refs/openopj/support/test.opj")
    if not sample.exists():
        pytest.skip("OpenOPJ fixture missing.")

    outdir = tmp_path / "human"
    code = main(["extract", str(sample), "-o", str(outdir), "--human", "--no-images"])
    assert code in {0, 4}

    payload = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    allowed_kinds = {
        "attachment",
        "excel",
        "function",
        "graph",
        "graph_preview",
        "image",
        "matrix",
        "note",
        "parser_backed_graph_preview",
        "worksheet",
    }
    assert payload["items"]
    assert all(item.get("kind") in allowed_kinds for item in payload["items"])
    assert all(item.get("status") == "extracted" for item in payload["items"])
    assert all(item.get("path") and (outdir / str(item["path"])).stat().st_size > 0 for item in payload["items"])

    emitted_files = {path.relative_to(outdir).as_posix() for path in outdir.rglob("*") if path.is_file()}
    manifest_files = {str(item["path"]) for item in payload["items"]}
    assert emitted_files == manifest_files | {"manifest.json"}
    assert not any(path.endswith(".metadata.json") for path in emitted_files)
    assert "strings/strings.txt" not in emitted_files
    assert "tables/guessed_tables.csv" not in emitted_files


def test_map_profile_writes_exact_reconstructable_byte_partition(tmp_path: Path) -> None:
    sample = tmp_path / "byte-map.opju"
    source = b"CPYUA 4.3318 0\x00<OriginStorage><Unknown>payload</Unknown></OriginStorage>tail"
    sample.write_bytes(source)
    output = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--map",
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--force",
        ]
    )

    assert code == 0
    index_path = output / "byte-map/index.json"
    byte_map = json.loads(index_path.read_text(encoding="utf-8"))
    assert byte_map["byte_accounting"]["complete"] is True
    assert byte_map["byte_accounting"]["accounted_bytes"] == len(source)
    assert byte_map["byte_accounting"]["unaccounted_bytes"] == 0
    reconstructed = b"".join((index_path.parent / segment["path"]).read_bytes() for segment in byte_map["segments"])
    assert reconstructed == source
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    item = next(item for item in manifest["items"] if item["kind"] == "byte_map")
    assert item["status"] == "extracted"
    assert item["verification"] == "exact"
