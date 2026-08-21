from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from deopjufy_view.backend import DeopjufyBackend, DeopjufyCommandError
from deopjufy_view.model import (
    default_artifact_suffix,
    find_next_label,
    image_bytes,
    payload_bytes,
    payload_text,
    table_region_text,
    tabular_view,
)


def _fake_cli(path: Path) -> None:
    path.write_text(
        """\
import json
import pathlib
import sys

counter = pathlib.Path(sys.argv[1])
try:
    count = int(counter.read_text())
except (FileNotFoundError, ValueError):
    count = 0
counter.write_text(str(count + 1))
command = sys.argv[2]
file_path = sys.argv[3]
if command == "list":
    payload = {
        "schema_version": 1,
        "document": {"sha256": "a" * 64},
        "items": [{
            "id": "item:v1:one",
            "name": pathlib.Path(file_path).name,
            "retrieval_formats": ["json", "jsonl", "csv", "tsv"],
        }],
        "status": "ok",
    }
elif command == "extract":
    output = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
    output.mkdir()
    payload = {
        "input": {"path": file_path},
        "status": "ok",
        "profile": "map" if "--map" in sys.argv else "human",
        "format": sys.argv[sys.argv.index("--format") + 1],
        "items": [{"kind": "worksheet", "status": "extracted"}],
    }
    (output / "manifest.json").write_text(json.dumps(payload))
else:
    if "--output" in sys.argv:
        output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
        output.write_text("A,B\\n1,2\\n")
    payload = {
        "schema_version": 1,
        "document": {"sha256": "a" * 64},
        "item": {"id": sys.argv[4], "name": "Sheet1"},
        "status": "ok",
        "content": {
            "headers": ["A", "B"],
            "rows": [{"values": [1, None]}, {"values": [2, "x"]}],
        },
    }
print(json.dumps(payload))
""",
        encoding="utf-8",
    )


def test_backend_caches_catalog_and_loaded_object(tmp_path: Path) -> None:
    script = tmp_path / "fake_cli.py"
    counter = tmp_path / "count.txt"
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"sample")
    _fake_cli(script)
    backend = DeopjufyBackend((sys.executable, str(script), str(counter)))
    try:
        first_catalog = backend.catalog(sample)
        second_catalog = backend.catalog(sample)
        first_item = backend.get(sample, "item:v1:one")
        second_item = backend.get(sample, "item:v1:one")
    finally:
        backend.close()

    assert first_catalog is second_catalog
    assert first_item is second_item
    assert counter.read_text(encoding="utf-8") == "2"
    table = tabular_view(first_item)
    assert table is not None
    assert table.headers == ("A", "B")
    assert table.rows == (("1", ""), ("2", "x"))


def test_backend_batch_open_is_bounded_and_returns_each_document(tmp_path: Path) -> None:
    script = tmp_path / "fake_cli.py"
    counter = tmp_path / "count.txt"
    first = tmp_path / "first.opju"
    second = tmp_path / "second.opju"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    _fake_cli(script)
    backend = DeopjufyBackend((sys.executable, str(script), str(counter)), max_workers=2)
    try:
        futures = backend.submit_catalogs([first, second])
        names = {path.name: future.result()["items"][0]["name"] for path, future in futures.items()}
    finally:
        backend.close()

    assert names == {"first.opju": "first.opju", "second.opju": "second.opju"}


def test_backend_exports_through_get_contract(tmp_path: Path) -> None:
    script = tmp_path / "fake_cli.py"
    counter = tmp_path / "count.txt"
    sample = tmp_path / "sample.opju"
    output = tmp_path / "sheet.csv"
    sample.write_bytes(b"sample")
    _fake_cli(script)
    backend = DeopjufyBackend((sys.executable, str(script), str(counter)))
    try:
        payload = backend.export_item(sample, "item:v1:one", "csv", output)
        with pytest.raises(DeopjufyCommandError, match="not available"):
            backend.export_item(sample, "item:v1:one", "xlsx", tmp_path / "sheet.xlsx")
    finally:
        backend.close()

    assert payload["status"] == "ok"
    assert output.read_text(encoding="utf-8") == "A,B\n1,2\n"


def test_backend_exports_whole_project_through_extract_contract(tmp_path: Path) -> None:
    script = tmp_path / "fake_cli.py"
    counter = tmp_path / "count.txt"
    sample = tmp_path / "sample.opju"
    output = tmp_path / "sample_extracted"
    sample.write_bytes(b"sample")
    _fake_cli(script)
    backend = DeopjufyBackend((sys.executable, str(script), str(counter)))
    try:
        payload = backend.export_all(sample, output, output_format="csv", complete=True)
        with pytest.raises(DeopjufyCommandError, match="already exists"):
            backend.export_all(sample, output)
    finally:
        backend.close()

    assert payload["status"] == "ok"
    assert payload["profile"] == "map"
    assert payload["format"] == "csv"
    assert payload["items"] == [{"kind": "worksheet", "status": "extracted"}]
    assert (output / "manifest.json").is_file()


def test_backend_rejects_unversioned_output(tmp_path: Path) -> None:
    script = tmp_path / "bad_cli.py"
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"sample")
    script.write_text("print('{}')\n", encoding="utf-8")
    backend = DeopjufyBackend((sys.executable, str(script)))
    try:
        with pytest.raises(DeopjufyCommandError, match="schema version"):
            backend.catalog(sample)
    finally:
        backend.close()


def test_payload_text_uses_text_content_or_stable_json() -> None:
    assert payload_text({"content": "hello"}) == "hello"
    assert payload_text({"schema_version": 1}).strip() == json.dumps(
        {"schema_version": 1},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    assert (
        image_bytes({"artifacts": [{"kind": "image", "content_encoding": "base64", "content": "aW1hZ2U="}]}) == b"image"
    )
    assert (
        image_bytes({"artifacts": [{"kind": "raw_dump", "content_encoding": "base64", "content": "aW1hZ2U="}]}) is None
    )


def test_tabular_view_uses_column_roles_and_metadata_rows() -> None:
    payload = {
        "content": {
            "headers": ["A", "B"],
            "rows": [{"values": ["1000", "1.58e-9"]}, {"values": ["3000", "1.08e-8"]}],
        },
        "artifacts": [
            {
                "kind": "worksheet_metadata",
                "content": {
                    "columns": [
                        {"designation": "X", "long_name": "T", "units": "K"},
                        {"designation": "Y", "long_name": "rate", "formula": "=A*2"},
                    ]
                },
            }
        ],
    }

    table = tabular_view(payload)

    assert table is not None
    assert table.headers == ("A(X)", "B(Y)")
    assert table.metadata_rows == (
        ("Long", ("T", "rate")),
        ("Units", ("K", "")),
        ("Formula", ("", "=A*2")),
    )
    assert table.grid_row_count == 5
    assert table.row_label(0) == "Long"
    assert table.row_label(3) == "1"
    assert table.value(3, 1) == "1.58e-9"
    assert table.column_is_numeric(0)
    assert table.column_is_numeric(1)


def test_table_selection_search_and_payload_export_helpers() -> None:
    table = tabular_view({"content": {"headers": ["A", "B"], "rows": [{"values": ["x,y", "2"]}]}})
    assert table is not None
    assert table_region_text(table, 0, 0, 0, 1, delimiter=",") == '"x,y",2\n'
    labels = ("Book1/Sheet1 worksheet", "Graph1 graph", "Notes note")
    assert find_next_label(labels, "graph") == 1
    assert find_next_label(labels, "book", start=1) == 0
    assert find_next_label(labels, "missing") is None
    assert payload_bytes({"content_encoding": "text", "content": "hello"}) == b"hello"
    assert payload_bytes({"content_encoding": "base64", "content": "aW1hZ2U="}) == b"image"
    json_bytes = payload_bytes({"content_encoding": "json", "content": {"b": 2, "a": 1}})
    assert json_bytes is not None and json.loads(json_bytes) == {"a": 1, "b": 2}
    assert default_artifact_suffix({"artifacts": [{"path": "images/plot.png", "content": "..."}]}) == ".png"
