import deopjufier
import deopjufier.inventory
from tests.core.basics.opj_parse._test_core_unit_coverage_basics_opj_parse_common import *  # noqa: F403


def test_opj_stream_read_object_size_and_payload_roundtrip() -> None:
    stream = OpjStream(_u32(2) + b"\nab" + b"\n" + _u32(0) + b"\n")

    assert stream.read_object_size() == 2
    assert stream.read_object(2) == b"ab"
    assert stream.offset == 8
    assert stream.read_u32_le() == 0


def test_opj_stream_rejects_broken_object_size_delimiter() -> None:
    stream = OpjStream(_u32(1) + b"aX")
    with pytest.raises(OpjStreamError):
        stream.read_object_size()


def test_opj_stream_rejects_object_payload_truncation() -> None:
    stream = OpjStream(_u32(3) + b"ab")
    with pytest.raises(OpjStreamError):
        stream.read_object(3)


def test_walk_opj_file_recovers_dataset_elements_from_synthetic_file() -> None:
    payload = (
        b"CPYA 4.2673 552#\n"
        + _u32(4)
        + b"\n"
        + b"HEAD"
        + b"\n"
        + _u32(0)
        + b"\n"
        + _build_opj_walk_dataset("Book1_A")
        + _build_opj_walk_dataset("Book2_B")
        + _u32(0)
        + b"\n"
    )

    elements = walk_opj_file(payload)
    assert [element.kind for element in elements][:3] == [
        "global_header",
        "dataset",
        "dataset",
    ]
    names = [element.name for element in elements if element.kind == "dataset"]
    assert names == ["Book1_A", "Book2_B"]


def test_opj_dataset_preserves_mask_range_and_decodes_unsigned_integers() -> None:
    header = bytearray(0x73)
    header[0x16:0x18] = (0x6803).to_bytes(2, "little")
    header[0x19:0x1D] = (2).to_bytes(4, "little")
    header[0x21:0x25] = (1).to_bytes(4, "little")
    header[0x3D] = 2
    header[0x3F] = 8
    header[0x58 : 0x58 + len(b"Book1_A")] = b"Book1_A"
    mask = b"\x01\x80"
    payload = (
        b"CPYA 4.2673 552#\n"
        + _build_opj_global_header()
        + _u32(len(header))
        + b"\n"
        + bytes(header)
        + b"\n"
        + _u32(4)
        + b"\n"
        + struct.pack("<HH", 65535, 32768)
        + b"\n"
        + _u32(len(mask))
        + b"\n"
        + mask
        + b"\n"
        + _u32(0)
        + b"\n"
    )

    section = iter_opj_data_sections(payload)[0]
    assert section.values == [65535, 32768]
    assert section.mask == mask
    assert section.mask_offset is not None
    assert payload[section.mask_offset : section.mask_offset + len(mask)] == mask


def test_walk_opj_file_with_tolerant_mode_is_non_fatal_for_partial_payloads() -> None:
    payload = b"CPYA 4.2673 552#\n" + _u32(4) + b"\n" + b"HEAD" + b"\n" + _u32(5) + b"\n" + b"abc" + _u32(5)

    with pytest.raises(OpjStreamError):
        walk_opj_file(payload, tolerant=False)

    partial = walk_opj_file(payload, tolerant=True)
    assert isinstance(partial, list)


def test_parse_opj_note_sections_prefers_walker_output() -> None:
    data = (
        b"CPYA 4.2673 552#\n"
        + _u32(4)
        + b"\n"
        + b"HEAD"
        + b"\n"
        + _u32(0)
        + b"\n"
        + _u32(0)
        + b"\n"
        + b"\n"
        + _u32(0)
        + b"\n"
        + _build_opj_note_window("Results", "Results", "Parser-backed note one")
        + _build_opj_note_window("ResultsLog", "ResultsLog", "Parser-backed note two")
        + _u32(0)
        + b"\n"
    )

    sections = parse_opj_note_sections(data, max_sections=4, max_chars=1000)
    assert [section.name for section in sections] == ["Results", "ResultsLog"]
    assert sections[0].text == "Parser-backed note one"
    assert sections[1].text == "Parser-backed note two"


def test_walk_opj_file_prefers_clean_note_labels_for_naming() -> None:
    payload = (
        b"CPYA 4.2673 552#\n"
        + _build_opj_global_header()
        + _u32(0)
        + b"\n"
        + _u32(0)
        + b"\n"
        + b"\x00\n"
        + _u32(0)
        + b"\n"
        + _build_opj_note_window_with_raw_bytes(
            b"\x16\x00\x00\x00\x16\x00\x00\x00\x01\x00\x00Z\x00\x00\x00\x00T",
            b"\x01Results\x00",
            "Parser-backed label-only note",
        )
        + _u32(0)
        + b"\n"
    )

    elements = walk_opj_file(payload)
    notes = [element for element in elements if element.kind == "note"]
    assert [note.name for note in notes] == ["Results"]
    assert notes[0].metadata["label"] == "Results"


def test_iter_opj_data_sections_uses_strict_walk_before_tolerant_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b"CPYA 4.2673 552#\n"
        + _u32(4)
        + b"\n"
        + b"HEAD"
        + b"\n"
        + _u32(0)
        + b"\n"
        + _build_opj_walk_dataset("Book1_A")
        + _u32(0)
        + b"\n"
    )

    from deopjufier.opj import walker as opj_walker

    calls: list[bool] = []
    original_walk = opj_walker.walk_opj_file

    def strict_first_walk(data: bytes, *, tolerant: bool = True) -> list[opj_walker.OpjWalkElement]:
        calls.append(tolerant)
        return original_walk(data, tolerant=tolerant)

    monkeypatch.setattr(opj_walker, "walk_opj_file", strict_first_walk)
    sections = iter_opj_data_sections(payload)
    assert len(sections) >= 1
    assert calls == [False]
    assert [section.name for section in sections][:1] == ["Book1_A"]


def test_iter_opj_data_sections_preserves_strict_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
    signature = b"CPYA 4.2673 552#\n"
    dataset1 = _build_opj_walk_dataset("Book1_A")
    dataset2 = _build_opj_walk_dataset("Book1_B")
    payload = signature + _build_opj_global_header() + dataset1 + dataset2

    dataset1_start = len(signature) + len(_build_opj_global_header())
    dataset2_start = dataset1_start + len(dataset1)

    def _element(start: int, name: str) -> OpjWalkElement:
        header_size = 0x73
        header_offset = start + 5
        data_offset = start + 5 + header_size + 1 + 4 + 1
        return OpjWalkElement(
            kind="dataset",
            start_offset=start,
            end_offset=start + 5 + header_size + 1 + 4 + 1,
            name=name,
            metadata={
                "header_size": header_size,
                "data_size": 0,
                "header_offset": header_offset,
                "data_offset": data_offset,
            },
        )

    first = _element(dataset1_start, "Book1_A")
    second = _element(dataset2_start, "Book1_B")

    from deopjufier.opj import walker as opj_walker

    calls: list[bool] = []

    def _strict_walk() -> Iterable[OpjWalkElement]:
        yield first
        raise OpjStreamError("stream corrupted", offset=dataset1_start)

    def walk_with_failure(_data: bytes, *, tolerant: bool = False) -> Iterable[OpjWalkElement]:
        calls.append(tolerant)
        if tolerant:
            return [second]

        return _strict_walk()

    monkeypatch.setattr(opj_walker, "walk_opj_file", walk_with_failure)
    sections = iter_opj_data_sections(payload)

    assert calls == [False, True]
    assert [section.name for section in sections] == ["Book1_A", "Book1_B"]


def test_iter_opj_data_sections_propagates_unexpected_walker_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    header = bytearray(123)
    encoded = b"Book1_A"
    header[0x58 : 0x58 + len(encoded)] = encoded
    header[0x16:0x18] = (1).to_bytes(2, "little")
    header[0x19:0x1D] = (1).to_bytes(4, "little")
    header[0x1D:0x21] = (0).to_bytes(4, "little")
    header[0x21:0x25] = (0).to_bytes(4, "little")
    header[0x3D] = 8
    header[0x3F] = 0
    header[0x71:0x73] = (0).to_bytes(2, "little")

    payload = (
        b"CPYA 4.2673 552#\n"
        + _u32(123)
        + b"\n"
        + bytes(header)
        + b"\n"
        + _u32(8)
        + b"\n"
        + struct.pack("<d", 42.0)
        + b"\n"
        + _u32(0)
        + b"\n"
    )

    def fail_walk(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("legacy walk disabled for regression")

    monkeypatch.setattr("deopjufier.opj.walker.walk_opj_file", fail_walk)

    with pytest.raises(RuntimeError, match="legacy walk disabled for regression"):
        iter_opj_data_sections(payload)


def test_parse_opj_boundaries_propagates_unexpected_walker_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Payload that old fallback scan logic would inspect as a candidate window blob.
    data = b"CPYA 4.2673 552#\n" + (4).to_bytes(4, "little") + b"\n" + b"GraphLabel\n"

    def fail_walk(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("legacy walk disabled for regression")

    monkeypatch.setattr("deopjufier.opj.walker.walk_opj_file", fail_walk)

    with pytest.raises(RuntimeError, match="legacy walk disabled for regression"):
        parse_opj_boundaries(data)


def test_discover_origin_objects_large_opju_with_column_table_uses_parser_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    threshold = _OPJ_DISCOVERY_STREAM_THRESHOLD_BYTES
    payload = SYNTHETIC_FIXTURE.read_bytes()
    sample = tmp_path / "large.opju"
    sample.write_bytes(payload + b"\x00" * (threshold - len(payload) + 32))

    calls = {"read_cached": 0}
    original = deopjufier.inventory.read_cached_bytes

    def counting_read_cached_bytes(path: Path) -> bytes:
        calls["read_cached"] += 1
        return original(path)

    monkeypatch.setattr("deopjufier.inventory.read_cached_bytes", counting_read_cached_bytes)

    objects = discover_origin_objects(sample)
    worksheet = next(
        (obj for obj in objects if obj.object_kind == "worksheet" and obj.name == "Book3_B"),
        None,
    )
    assert worksheet is not None
    assert isinstance(worksheet, ParserBackedDiscoveryRecord)
    assert worksheet.parser_confirmed
    assert worksheet.parser_rule == "parse_opju_column_tables"
    assert calls["read_cached"] == 1


def test_discover_origin_objects_large_opj_uses_parser_boundaries_for_streaming_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    threshold = _OPJ_PARSER_BOUNDARY_MAX_BYTES + 1
    sample = tmp_path / "very_large_boundary.opj"
    sample.write_bytes(b"CPYA\0" + b"\x00" * (threshold - 1) + b"Graph1")

    calls = {"count": 0}

    def fail_parse_boundaries(*_args, **_kwargs) -> list[OpjObjectBoundary]:
        calls["count"] += 1
        return []

    monkeypatch.setattr("deopjufier.inventory.parse_opj_boundaries", fail_parse_boundaries)

    objects = discover_origin_objects(sample)
    assert calls["count"] == 1
    assert any(obj.name == "Graph1" for obj in objects)


def test_classify_object_kind_covers_reference_object_types() -> None:
    assert _classify_object_kind("Book1") == "worksheet"
    assert _classify_object_kind("PdMSheet1") == "matrix"
    assert _classify_object_kind("Graph1") == "graph"
    assert _classify_object_kind("N2N_A") == "worksheet"
    assert _classify_object_kind("Function1") == "function"
    assert _classify_object_kind("ExcelA") == "excel"
    assert _classify_object_kind("__Meta") == "meta"


def test_iter_object_windows_prefers_parser_confirmed_boundaries() -> None:
    objects = [
        OriginObject(
            offset=10,
            name="Book1_A",
            length=90,
            object_kind="worksheet",
            source_object_path="Book/Book1_A",
            parser_confirmed=True,
        ),
        OriginObject(
            offset=200,
            name="Graph1",
            length=20,
            object_kind="graph",
            source_object_path="Graph/Graph1",
            parser_confirmed=False,
        ),
    ]
    windows = iter_object_windows(objects, file_size=500)
    assert [start for _, start, _ in windows] == [10, 200]
    assert windows[0][2] == 100
    assert windows[1][2] == 500


def test_iter_object_windows_does_not_clip_parser_window_by_nested_heuristic() -> None:
    objects = [
        ParserBackedDiscoveryRecord(
            offset=10,
            name="origin_storage_preview_000",
            length=80,
            object_kind="opju_preview",
            source_object_path="previews/origin_storage_preview_000",
            parser_rule="parse_opju_origin_storage_records",
            parser_confidence=0.9,
        ),
        OriginObject(
            offset=20,
            name="svg",
            length=3,
            object_kind="meta",
            source_object_path="previews/origin_storage_preview_000/svg",
        ),
    ]
    windows = iter_object_windows(objects, file_size=200)

    assert [obj.source_object_path for obj, _, _ in windows] == [
        "previews/origin_storage_preview_000",
        "previews/origin_storage_preview_000/svg",
    ]
    assert windows[0][2] == 90
    assert windows[1][2] == 200


def test_origin_object_collision_paths_are_stabilized(tmp_path: Path) -> None:
    sample = tmp_path / "collisions.opju"
    sample.write_bytes(b"Book1\0Book1\0Book1\0")

    objects = discover_origin_objects(sample)
    paths = [obj.source_object_path for obj in objects if obj.name == "Book1"]
    assert len(paths) >= 1
    assert paths[0].endswith("object/Book1") or paths[0].endswith("Book/Book1")
    if len(paths) > 1:
        assert paths[1] != paths[0]


def test_discover_origin_objects_falls_back_to_origin_project_for_headered_opj(tmp_path: Path) -> None:
    sample = tmp_path / "header-only.opj"
    sample.write_bytes(b"CPYA\0")

    objects = discover_origin_objects(sample)
    assert len(objects) == 1
    assert objects[0].name == "origin_project"
    assert objects[0].source_object_path == "project/origin_project"


def test_discover_origin_objects_falls_back_to_heuristics_when_parser_boundaries_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sample = tmp_path / "boundary_fallback.opj"
    sample.write_bytes(b"CPYA\0" + b"prefix " + b"Book1_A" + b" " + b"Graph1")

    monkeypatch.setattr("deopjufier.inventory.parse_opj_boundaries", lambda *_args, **_kwargs: [])
    objects = discover_origin_objects(sample)
    names = [obj.name for obj in objects]

    assert "Book1_A" in names
    assert "Graph1" in names


def test_discover_origin_objects_keeps_parser_backed_source_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sample = tmp_path / "parsed_path.opj"
    sample.write_bytes(b"CPYA 4.2673 552#\n")

    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        lambda *_args, **_kwargs: [
            OpjObjectBoundary(
                kind="graph",
                name="Graph1",
                source_object_path="Tree/Graph1",
                start_offset=0,
                end_offset=16,
                length=16,
                confidence=0.88,
                parser_rule="opj_data_section",
            )
        ],
    )

    objects = discover_origin_objects(sample)
    assert any(obj.source_object_path == "Tree/Graph1" for obj in objects)


def test_derive_source_path_and_unique_pathing() -> None:
    assert _derive_source_path("Book1_A") == "Book/Book1_A"
    assert _derive_source_path("__Meta") == "meta/__Meta"
    assert _derive_source_path("Graph1") == "Graph/Graph1"
    assert _derive_source_path("Folder\\SubFolder\\Book1_A") == "Folder/SubFolder/Book1_A"

    objects = [
        OriginObject(offset=0, name="Book1", length=1, source_object_path="Book/Book1"),
        OriginObject(offset=1, name="Book1", length=1, source_object_path="Book/Book1"),
        OriginObject(offset=2, name="Graph1", length=1, source_object_path="Graph/Graph1"),
    ]
    stabilized = _ensure_unique_paths(objects)
    assert stabilized[0].source_object_path == "Book/Book1"
    assert stabilized[1].source_object_path == "Book/Book1__2"

    nested = [
        OriginObject(offset=0, name="Sheet1", length=1, source_object_path="Book4/Sheet1"),
        OriginObject(offset=1, name="Sheet1", length=1, source_object_path="Book4/Sheet1"),
        OriginObject(offset=2, name="Sheet1", length=1, source_object_path="Graph/Sheet1"),
    ]
    stabilized = _ensure_unique_paths(nested)
    assert stabilized[0].source_object_path == "Book4/Sheet1"
    assert stabilized[1].source_object_path == "Book4/Sheet1__2"
    assert stabilized[2].source_object_path == "Graph/Sheet1"
