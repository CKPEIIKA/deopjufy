"""Smoke tests for OPJ/OPJU command entrypoints."""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from deopjufier.cli import main
from deopjufier.opj.records import _OPJ_DATASET_NAME_OFFSET
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))

SMOKE_PROJECTS = [
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj",
    REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj",
]
# Keep smoke coverage on representative smaller public fixtures only.
SMOKE_PROJECTS = [path for path in dict.fromkeys(SMOKE_PROJECTS) if path.exists()]


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _build_fake_opj_payload(names: list[str]) -> bytes:
    chunks: list[bytes] = []
    chunks.append(b"CPYA\n")
    chunks.append(_u32(4))
    chunks.append(b"HEAD")
    chunks.append(b"\n")
    chunks.append(_u32(0))
    chunks.append(b"\n")

    for name in names:
        header_payload = bytearray(_OPJ_DATASET_NAME_OFFSET + 25)
        name_bytes = name.encode("ascii", "ignore")
        if len(name_bytes) > 25:
            raise ValueError(f"name too long for fake OPJ payload: {name}")
        header_payload[_OPJ_DATASET_NAME_OFFSET : _OPJ_DATASET_NAME_OFFSET + len(name_bytes)] = name_bytes
        chunks.append(_u32(len(header_payload)))
        chunks.append(b"\n")
        chunks.append(bytes(header_payload))
        chunks.append(b"\n")
        chunks.append(_u32(0))
        chunks.append(b"\n")
        chunks.append(_u32(0))
        chunks.append(b"\n")

    chunks.append(_u32(0))
    chunks.append(b"\n")
    return b"".join(chunks)


SYNTHETIC_OPJ_CASES = [
    (  # token-only payload
        "objects_and_kinds",
        b"CPYA\0Book1_A\0Graph1\0PdMSheet1\0Note1\0Function1\0ExcelA\0__Meta\0",
        7,
        {
            "worksheet": 1,
            "graph": 1,
            "matrix": 1,
            "note": 1,
            "function": 1,
            "excel": 1,
            "meta": 1,
        },
        ("Book1_A", "Graph1", "PdMSheet1", "Note1", "Function1", "ExcelA", "__Meta"),
        (),
    ),
    (  # duplicate and bracket reference fallback
        "duplicates_and_brackets",
        b"CPYA\0Book1\0Book1\0[Book1]Sheet1\0[MBook1]MSheet1\0[O2O_A]X\0",
        2,
        {"worksheet": 4},
        ("Book1", "Book1/Sheet1", "MBook1/MSheet1", "O2O_A/X"),
        ("Book1",),
    ),
    (  # inline image signatures are also scanned
        "images_and_tokens",
        b"CPYA\0MatrixX\0GraphA\0\0\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xae\x42\x60\x82\xff\xd8\xff\xd9",
        1,
        {"matrix": 1, "graph": 1},
        ("MatrixX", "GraphA"),
        (),
    ),
    (  # header-driven OPJ payload decoding path
        "header_based_objects",
        _build_fake_opj_payload(
            [
                "Book1_A",
                "Graph1",
                "PdMSheet1",
                "Note1",
                "Function1",
                "ExcelA",
                "__Meta",
            ]
        ),
        7,
        {
            "worksheet": 1,
            "graph": 1,
            "matrix": 1,
            "note": 1,
            "function": 1,
            "excel": 1,
            "meta": 1,
        },
        ("Book1_A", "Graph1", "PdMSheet1", "Note1", "Function1", "ExcelA", "__Meta"),
        (),
    ),
    (  # repeated names exercise source path dedupe suffixes
        "header_duplicates",
        _build_fake_opj_payload(["Book1", "Book1", "Graph1", "Graph1", "Matrix1", "Matrix1"]),
        6,
        {"worksheet": 2, "graph": 2, "matrix": 2},
        ("Book1", "Graph1", "Matrix1"),
        ("Book1", "Graph1", "Matrix1"),
    ),
]


def _run_json_command(argv: list[str]) -> tuple[int, dict]:
    command_args = list(argv)
    if command_args and command_args[0] in {"inspect", "list"}:
        command_args.append("--json")
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(command_args)
    data = stdout.getvalue()
    return code, json.loads(data) if data else {}


@pytest.mark.skipif(not SMOKE_PROJECTS, reason="Reference OPJ fixtures are not available.")
@pytest.mark.parametrize(
    "project",
    SMOKE_PROJECTS,
    ids=lambda path: str(path.relative_to(REPO_ROOT)),
)
def test_smoke_reference_projects_run_core_commands(project: Path, tmp_path: Path) -> None:
    inspect_code, inspect_payload = _run_json_command(["inspect", str(project)])
    assert inspect_code == 0
    assert inspect_payload["status"] == "ok"
    assert inspect_payload["detected_type"] in {"opj", "opju"}

    list_code, list_payload = _run_json_command(["list", str(project)])
    assert list_code in {0, 3}
    assert list_payload["status"] in {"ok", "unsupported"}
    assert isinstance(list_payload["items"], list)
    if list_payload["items"]:
        offsets = [item["offset"] for item in list_payload["items"]]
        assert offsets == sorted(offsets)

    strings_code = main(["strings", str(project), "--min-length", "6"])
    assert strings_code == 0

    images_dir = tmp_path / "smoke-images"
    images_code = main(["images", str(project), "-o", str(images_dir)])
    assert images_code in {0, 3}

    table_code = main(
        [
            "table-scan",
            str(project),
            "--format",
            "json",
            "--min-rows",
            "4",
            "--min-columns",
            "3",
        ]
    )
    if table_code == 0:
        # ensure output is parseable if rows are found
        _, table_payload = _run_json_command(
            [
                "table-scan",
                str(project),
                "--format",
                "json",
                "--min-rows",
                "4",
                "--min-columns",
                "3",
            ]
        )
        assert isinstance(table_payload, list)
    else:
        assert table_code == 3

    extract_dir = tmp_path / "smoke-out"
    extract_code = main(
        [
            "extract",
            str(project),
            "-o",
            str(extract_dir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--no-objects",
        ]
    )
    assert extract_code in {0, 4}
    manifest_payload = json.loads((extract_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["tool"]["backend"] == "native-parser"
    assert all(
        not Path(item["path"]).is_absolute() for item in manifest_payload["items"] if item.get("path") is not None
    )
    worksheet_items = [item for item in manifest_payload["items"] if item.get("kind") == "worksheet"]
    for item in worksheet_items:
        book_path = Path(item["path"])
        resolved_path = book_path if book_path.is_absolute() else extract_dir / book_path
        assert "books" in book_path.parts
        if not book_path.suffix:
            assert item.get("name", "").endswith("_collection")
            continue
        assert book_path.suffix in {".csv", ".tsv", ".xlsx"}
        assert resolved_path.exists()

    dump_code = main(["dump-block", str(project), "--offset", "0", "--length", "0"])
    assert dump_code == 0


@pytest.mark.skipif(not SMOKE_PROJECTS, reason="Reference OPJ fixtures are not available.")
@pytest.mark.parametrize(
    "project",
    SMOKE_PROJECTS,
    ids=lambda path: str(path.relative_to(REPO_ROOT)),
)
def test_smoke_walk_command_runs_on_reference_projects(project: Path) -> None:
    inspect_code, inspect_payload = _run_json_command(["inspect", str(project)])
    if inspect_code != 0 or inspect_payload.get("detected_type") != "opj":
        pytest.skip("walk command is opj-specific")

    walk_code, walk_payload = _run_json_command(["walk", str(project), "--json"])
    assert walk_code == 0
    assert isinstance(walk_payload, list)
    assert walk_payload
    assert walk_payload[0]["kind"] == "global_header"
    assert all(isinstance(item["start_offset"], int) for item in walk_payload)


@pytest.mark.parametrize(
    "case_name, payload, min_objects, expected_kind_counts, required_names, collision_paths",
    SYNTHETIC_OPJ_CASES,
)
def test_smoke_synthetic_opj_variants(
    case_name: str,
    payload: bytes,
    min_objects: int,
    expected_kind_counts: dict[str, int],
    required_names: tuple[str, ...],
    collision_paths: tuple[str, ...],
    tmp_path: Path,
) -> None:
    sample = tmp_path / f"{case_name}.opj"
    sample.write_bytes(payload)

    inspect_code, inspect_payload = _run_json_command(["inspect", str(sample)])
    assert inspect_code == 0
    assert inspect_payload["counts"]["origin_objects"] >= min_objects
    assert inspect_payload["counts"]["origin_objects"] >= 0
    for kind, minimum in expected_kind_counts.items():
        assert inspect_payload["counts"]["origin_object_kinds"].get(kind, 0) >= minimum

    list_code, list_payload = _run_json_command(["list", str(sample)])
    assert list_code in {0, 3}
    assert "items" in list_payload
    assert {item["kind"] for item in list_payload["items"] if item["kind"] == "origin_object"}

    extract_dir = tmp_path / f"{case_name}-out"
    extract_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(extract_dir),
            "--no-images",
            "--no-strings",
            "--no-tables",
            "--extended",
        ]
    )
    assert extract_code in {0, 4}

    manifest = json.loads((extract_dir / "manifest.json").read_text(encoding="utf-8"))
    assert any(item["kind"] == "origin_object_inventory" for item in manifest["items"])
    assert (extract_dir / "metadata" / "origin_objects.json").exists()
    inventory = json.loads((extract_dir / "metadata" / "origin_objects.json").read_text(encoding="utf-8"))
    assert len(inventory) >= min_objects
    assert {item["name"] for item in inventory} >= set(required_names)

    if expected_kind_counts.get("matrix", 0) > 0:
        matrix_items = [item for item in manifest["items"] if item.get("kind") == "matrix"]
        assert len(matrix_items) >= expected_kind_counts["matrix"]
        for item in matrix_items:
            assert item.get("path")
            path = Path(item["path"])
            resolved = extract_dir / path
            assert "matrices" in path.parts
            if item.get("status") == "extracted":
                assert resolved.exists()
    if expected_kind_counts.get("graph", 0) > 0:
        graph_items = [item for item in manifest["items"] if item.get("kind") == "graph"]
        extracted_graph_items = [item for item in graph_items if item.get("status") == "extracted"]
        if extracted_graph_items:
            assert len(extracted_graph_items) >= expected_kind_counts["graph"]
            for item in extracted_graph_items:
                assert item.get("path")
                path = Path(item["path"])
                resolved = extract_dir / path
                assert resolved.exists()
                assert "graphs" in path.parts
        else:
            unsupported_graph_collection = [
                item
                for item in graph_items
                if item.get("name") == "graph_collection"
                and item.get("status") == "unsupported"
                and item.get("error") == "no_graph_previews"
            ]
            assert unsupported_graph_collection
    if expected_kind_counts.get("note", 0) > 0:
        note_items = [item for item in manifest["items"] if item.get("kind") == "note"]
        assert len(note_items) >= expected_kind_counts["note"]
        for item in note_items:
            assert item.get("path")
            path = Path(item["path"])
            resolved = extract_dir / path
            assert "notes" in path.parts
            assert resolved.exists()
    if expected_kind_counts.get("excel", 0) > 0:
        excel_items = [item for item in manifest["items"] if item.get("kind") == "excel"]
        assert len(excel_items) >= expected_kind_counts["excel"]
        for item in excel_items:
            assert item.get("path")
            path = Path(item["path"])
            if item.get("status") == "extracted":
                resolved = extract_dir / path
                assert resolved.exists()
            assert "excel" in path.parts
    if expected_kind_counts.get("function", 0) > 0:
        function_items = [item for item in manifest["items"] if item.get("kind") == "function"]
        assert len(function_items) >= expected_kind_counts["function"]
        for item in function_items:
            assert item.get("path")
            path = Path(item["path"])
            if item.get("status") == "extracted":
                resolved = extract_dir / path
                assert resolved.exists()
            assert "functions" in path.parts

    for name in collision_paths:
        matching_paths = [item["source_object_path"] for item in inventory if item.get("name") == name]
        assert len(matching_paths) >= 2
        assert any("__2" in path for path in matching_paths)
