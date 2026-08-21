from __future__ import annotations

from pathlib import Path

from deopjufier.inventory import discover_origin_objects
from deopjufier.opju import (
    OPJU_REGION_KIND_FOLDER_DIRECTORY,
    OPJU_REGION_KIND_PAGE_DIRECTORY,
    parse_opju_folder_directory,
    parse_opju_page_directory,
    parse_opju_records,
)
from deopjufier.session import ExtractionSession

_PNG_TERMINAL = b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _page_record(name: str, *, template: str = "LINE", with_frame: bool = True) -> bytes:
    frame = b"padding__FRAMESRCDATAINFOS" if with_frame else b""
    return (
        _PNG_TERMINAL
        + b"\x0a\x80\x75\x08\x00\x00"
        + name.encode("ascii")
        + b"\x90\x0c\x81\x04"
        + template.encode("ascii")
        + b"\x83\x0c"
        + b"SYSTEM"
        + frame
    )


def _folder_record(name: str) -> bytes:
    encoded = name.encode("ascii")
    return (
        (len(encoded) + 1).to_bytes(4, "little")
        + b"\x0a"
        + encoded
        + b"\x00\x0a\x02\x07\x01\x47\xc0\x11"
        + b"FolderLastUsed\x04\x01\x11\x00<OriginStorage/>\x00"
    )


def test_page_directory_requires_bounded_page_evidence() -> None:
    data = b"CPYUA 4.0 0\x00" + _page_record("GraphOne") + _page_record("ImagePage", with_frame=False)

    records = parse_opju_page_directory(data)

    assert [record.name for record in records] == ["GraphOne", "ImagePage"]
    assert [record.template_hint for record in records] == ["LINE", "LINE"]
    assert records[0].frame_offset is not None
    assert records[1].frame_offset is None
    assert all(record.preview_terminal_offset is not None for record in records)
    assert [record.source_object_path for record in records] == [
        "page_directory/GraphOne",
        "page_directory/ImagePage",
    ]
    assert all(record.structural_name == "opju_page_directory_name" for record in records)
    assert all(record.semantic_alias == "project_page_directory_entry" for record in records)
    assert all(record.semantic_confidence == "corpus_high" for record in records)


def test_page_directory_rejects_layer_placeholder_and_unbounded_name() -> None:
    layer = _page_record("_")
    unbounded = b"\x0a\x80\x75\x08\x00\x00FalsePage\x90LINE SYSTEM"

    assert parse_opju_page_directory(b"CPYUA 4.0 0\x00" + layer + unbounded) == ()


def test_folder_directory_recovers_names_without_claiming_hierarchy() -> None:
    data = b"CPYUA 4.0 0\x00" + _folder_record("ProjectRoot") + _folder_record("FolderA")

    records = parse_opju_folder_directory(data)

    assert [record.name for record in records] == ["ProjectRoot", "FolderA"]
    assert [record.source_object_path for record in records] == [
        "project_folders/ProjectRoot",
        "project_folders/FolderA",
    ]
    assert all(record.property_offset > record.offset for record in records)
    assert all(record.structural_name == "opju_folder_directory_name" for record in records)
    assert all(record.semantic_alias == "project_folder_directory_entry" for record in records)
    assert all(record.semantic_confidence == "corpus_high" for record in records)


def test_opju_records_and_inventory_surface_directory_entries(tmp_path: Path) -> None:
    data = b"CPYUA 4.0 0\x00" + _page_record("GraphOne") + _folder_record("FolderA")
    sample = tmp_path / "directory.opju"
    sample.write_bytes(data)

    records = parse_opju_records(data, path=sample)
    directory_regions = [
        (region.kind, region.name, region.source_object_path)
        for region in records.regions
        if region.kind in {OPJU_REGION_KIND_PAGE_DIRECTORY, OPJU_REGION_KIND_FOLDER_DIRECTORY}
    ]
    assert directory_regions == [
        (OPJU_REGION_KIND_PAGE_DIRECTORY, "GraphOne", "page_directory/GraphOne"),
        (OPJU_REGION_KIND_FOLDER_DIRECTORY, "FolderA", "project_folders/FolderA"),
    ]

    objects = discover_origin_objects(sample, collect_heuristics=False)
    assert [
        (item.name, item.object_kind, item.parser_confirmed)
        for item in objects
        if item.object_kind in {"project_page", "project_folder"}
    ] == [
        ("GraphOne", "project_page", True),
        ("FolderA", "project_folder", True),
    ]

    catalog = ExtractionSession.from_path(sample).list_items(include_images=False)
    directory_items = [item for item in catalog if item.get("object_kind") in {"project_page", "project_folder"}]
    assert [
        (item["structural_name"], item["semantic_alias"], item["semantic_confidence"]) for item in directory_items
    ] == [
        ("opju_page_directory_name", "project_page_directory_entry", "corpus_high"),
        ("opju_folder_directory_name", "project_folder_directory_entry", "corpus_high"),
    ]


def test_generic_page_identity_does_not_replace_graph_heuristic(tmp_path: Path) -> None:
    data = b"CPYUA 4.0 0\x00GraphOne\x00" + _page_record("GraphOne")
    sample = tmp_path / "directory.opju"
    sample.write_bytes(data)

    objects = discover_origin_objects(sample)

    assert [(item.object_kind, item.parser_confirmed) for item in objects if item.name == "GraphOne"] == [
        ("graph", False),
        ("project_page", True),
        ("graph", False),
    ]
