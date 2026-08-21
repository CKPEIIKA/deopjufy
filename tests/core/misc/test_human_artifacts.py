from __future__ import annotations

from pathlib import Path

from deopjufier.commands.simple_extract.human_artifacts import retain_human_artifacts
from deopjufier.manifest import ManifestItem
from tests.test_core_unit_coverage_utils import _make_manifest


def _write(root: Path, relative: str, payload: bytes) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def _item(
    kind: str,
    name: str,
    path: str,
    *,
    source_object_path: str | None = None,
    content_class: str | None = None,
    function_formula: str | None = None,
) -> ManifestItem:
    return ManifestItem(
        kind=kind,
        name=name,
        status="extracted",
        confidence=0.9,
        path=path,
        source_object_path=source_object_path or name,
        content_class=content_class,
        function_formula=function_formula,
        extraction_method="opju_descriptor_table" if kind in {"excel", "matrix", "worksheet"} else None,
        verification="exact" if kind in {"excel", "matrix", "worksheet"} else None,
    )


def test_human_projection_filters_machine_content_and_deduplicates(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA")
    output = tmp_path / "out"
    output.mkdir()
    manifest = _make_manifest(sample)

    _write(output, "books/data.csv", b"A,B\n1,2\n")
    _write(output, "books/data-copy.csv", b"A,B\n1,2\n")
    _write(output, "books/blank.csv", b"A,B\n,\n")
    _write(output, "books/references.csv", b"A\ncell://Book1!A\n")
    _write(output, "books/corrupt.csv", b"A\n!junk\n<broken>\n\\bad\n@bad\n!bad\n<bad\n\\bad2\n@bad2\n")
    _write(output, "matrices/origin_storage_family_01.csv", b"A,B\n1,2\n")
    _write(output, "functions/raw.txt", b"<OriginStorage><Calculation/></OriginStorage>")
    _write(output, "functions/formula.txt", b"x*x\n")
    _write(output, "notes/raw.txt", b"<OriginStorage><Notes/></OriginStorage>")
    _write(output, "notes/readme.txt", b"A useful project note.\n")
    _write(output, "images/raw.png", b"same-preview")
    _write(output, "graphs/Graph1.png", b"same-preview")
    _write(output, "attachments/workbook-link.json", b'{"embedded_payload":false}\n')

    manifest.items.extend(
        [
            _item("worksheet", "Data", "books/data.csv", content_class="data"),
            _item("worksheet", "DataCopy", "books/data-copy.csv", content_class="data"),
            _item("worksheet", "Blank", "books/blank.csv", content_class="empty"),
            _item(
                "worksheet",
                "References",
                "books/references.csv",
                content_class="internal_references",
            ),
            _item("worksheet", "Corrupt", "books/corrupt.csv", content_class="corrupt_text"),
            _item(
                "matrix",
                "origin_storage_family_01",
                "matrices/origin_storage_family_01.csv",
                content_class="data",
            ),
            _item("function", "Raw", "functions/raw.txt"),
            _item("function", "Formula", "functions/formula.txt", function_formula="x*x"),
            _item("note", "RawNote", "notes/raw.txt"),
            _item("note", "Readme", "notes/readme.txt"),
            _item("image", "embedded", "images/raw.png"),
            _item("graph_preview", "Graph1", "graphs/Graph1.png"),
            _item(
                "external_workbook_link",
                "LinkedWorkbook",
                "attachments/workbook-link.json",
            ),
        ]
    )

    retain_human_artifacts(manifest, output)

    retained = {(item.kind, item.name) for item in manifest.items}
    assert retained == {
        ("worksheet", "Data"),
        ("function", "Formula"),
        ("note", "Readme"),
        ("graph_preview", "Graph1"),
        ("external_workbook_link", "LinkedWorkbook"),
    }
    data_item = next(item for item in manifest.items if item.name == "Data")
    assert data_item.overlapping_objects == ["DataCopy"]
    graph_item = next(item for item in manifest.items if item.name == "Graph1")
    assert graph_item.overlapping_objects == ["embedded"]
    assert not (output / "books/data-copy.csv").exists()
    assert not (output / "images/raw.png").exists()


def test_human_projection_drops_ambiguous_opju_table_broadcast(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA")
    output = tmp_path / "out"
    output.mkdir()
    manifest = _make_manifest(sample)
    manifest.input.detected_type = "opju"

    for index in range(4):
        path = f"books/sheet-{index}.csv"
        _write(output, path, b"A,B\n1,2\n")
        manifest.add_item(_item("worksheet", f"Sheet{index}", path, content_class="data"))

    retain_human_artifacts(manifest, output)

    assert manifest.items == []
    assert not (output / "books").exists()


def test_human_projection_removes_manifest_owned_partial_artifacts(tmp_path: Path) -> None:
    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"CPYUA")
    output = tmp_path / "out"
    output.mkdir()
    manifest = _make_manifest(sample)
    _write(output, "functions/partial.raw.bin", b"partially decoded")
    manifest.add_item(
        ManifestItem(
            kind="function",
            name="PartialFunction",
            status="partial",
            confidence=0.5,
            path="functions/partial.raw.bin",
        )
    )

    retain_human_artifacts(manifest, output)

    assert manifest.items == []
    assert not (output / "functions").exists()
