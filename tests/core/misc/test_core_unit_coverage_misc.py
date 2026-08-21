"""Unit-level coverage tests for core modules and uncovered branches."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from deopjufier.blocks import (
    ImageBlock,
    find_image_blocks,
)
from deopjufier.cli import main
from deopjufier.commands.support import _limit_extract_objects
from deopjufier.discovery import _is_media_signature
from deopjufier.errors import (
    CorruptedInputError,
    DeopjufyError,
    UnsupportedFileError,
)
from deopjufier.extract import (
    extract_images,
    extract_raw_blocks,
    extract_strings,
    extract_tables,
    extract_text_regions,
)
from deopjufier.extract import tables as tables_module
from deopjufier.extract.discovery_helpers import book_dir as _book_dir
from deopjufier.extract.discovery_helpers import gap_ranges as _gap_ranges
from deopjufier.extract.metadata_helpers import infer_note_format as _infer_note_format
from deopjufier.extract.metadata_helpers import write_note_file as _write_note_file
from deopjufier.extract.path_helpers import unique_output_path as _unique_path
from deopjufier.extract.raw_regions import (
    RAW_REGION_CLASS_TEXT,
    RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY,
    RawRegionClassification,
)
from deopjufier.extract.tables import _parse_numeric_line
from deopjufier.extract.tabular_helpers import book_rows_for_range as _book_rows_for_range
from deopjufier.extract.tabular_helpers import write_book_csv as _write_book_csv
from deopjufier.extract.tabular_helpers import write_book_xlsx as _write_book_xlsx
from deopjufier.inventory import (
    OriginObject,
    discover_origin_objects,
)
from deopjufier.strings import _iter_ascii_strings, iter_strings
from tests.test_core_unit_coverage_utils import _make_manifest, _repo_root

REPO_ROOT = _repo_root(Path(__file__))


def test_parse_numeric_line_with_bad_text() -> None:
    assert _parse_numeric_line("1 2 bad", min_columns=2) is None
    assert _parse_numeric_line("x", min_columns=1) is None
    assert _parse_numeric_line("1 2 3", min_columns=3) == ["1", "2", "3"]


def test_scan_numeric_tables_from_bytes_prefers_utf8_when_present() -> None:
    data = b"1 2 3\n4 5 6\n"
    rows = tables_module.scan_numeric_tables_from_bytes(data, min_rows=1, min_columns=3)

    assert rows == [
        (1, 1, 0, ["1", "2", "3"]),
        (1, 2, 6, ["4", "5", "6"]),
    ]


def test_scan_numeric_tables_from_bytes_recovers_utf16_payloads() -> None:
    payload = "1 2 3\r\n4 5 6\r\n".encode("utf-16le")
    rows = tables_module.scan_numeric_tables_from_bytes(payload, min_rows=1, min_columns=3)

    assert rows == [
        (1, 1, 0, ["1", "2", "3"]),
        (1, 2, 14, ["4", "5", "6"]),
    ]


def test_limit_extract_objects_bounds_heuristics_but_keeps_parser_records() -> None:
    objects = [
        OriginObject(
            offset=index,
            name=f"Book{index}",
            length=1,
            object_kind="worksheet",
            source_object_path=f"Book/Book{index}",
        )
        for index in range(5)
    ]
    objects.append(
        OriginObject(
            offset=100,
            name="GraphA",
            length=1,
            object_kind="graph",
            source_object_path="Graph/GraphA",
            parser_confirmed=True,
        )
    )

    limited = _limit_extract_objects(objects, per_kind_limit=2)

    assert [obj.name for obj in limited if obj.object_kind == "worksheet"] == ["Book0", "Book1"]
    assert any(obj.name == "GraphA" and obj.parser_confirmed for obj in limited)


def test_discover_origin_objects_can_limit_large_file_heuristic_kinds(tmp_path: Path) -> None:
    sample = tmp_path / "kind_limit.opj"
    payload = b"CPYA\0Book1_A\0Book2_A\0Book3_A\0Graph1\0Graph2\0Graph3\0"
    sample.write_bytes(payload + b"0" * (131072 + 1))

    objects = discover_origin_objects(
        sample,
        max_repeats_per_name=None,
        heuristic_kind_limit=1,
    )

    worksheet_names = [obj.name for obj in objects if obj.object_kind == "worksheet"]
    graph_names = [obj.name for obj in objects if obj.object_kind == "graph"]

    assert worksheet_names == ["Book1_A"]
    assert graph_names == ["Graph1"]


def test_discover_origin_objects_limit_does_not_hide_late_kinds(tmp_path: Path) -> None:
    sample = tmp_path / "kind_limit_late_note.opj"
    payload = b"CPYA\0"
    payload += b" ".join([f"Book{i}_A".encode() for i in range(24)] + [f"noise{i}".encode() for i in range(24)])
    payload += b" Note1 "
    payload += b"Graph1"
    sample.write_bytes(payload)

    objects = discover_origin_objects(sample, heuristic_kind_limit=24)

    assert "Note1" in [obj.name for obj in objects if obj.object_kind == "note"]


def test_infer_note_format_prefers_html_and_markdown() -> None:
    assert _infer_note_format("<html><body>note</body></html>") == "html"
    assert _infer_note_format("# heading\nsome text") == "md"
    assert _infer_note_format("regular note body") == "txt"


def test_iter_strings_supports_utf16_and_raises_bad_encoding(tmp_path: Path) -> None:
    sample = tmp_path / "strings_utf16.bin"
    sample.write_bytes("hello world".encode("utf-16"))

    values = list(iter_strings(sample, encoding="utf16"))
    assert values
    with pytest.raises(ValueError, match="unsupported encoding"):
        list(iter_strings(sample, encoding="rot13"))


def test_iter_ascii_strings_carries_incomplete_sequence_across_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "carry.bin"
    sample.write_bytes(b"xxAB")
    # Keep this import local path stable for monkeypatching.
    from deopjufier import strings as strings_module

    monkeypatch.setattr(
        strings_module,
        "iter_file_chunks",
        lambda _path, chunk_size=8192: [b"AB", b"CDEF", b"G"],
    )
    values = list(_iter_ascii_strings(sample, min_length=4))
    assert values == ["ABCDEFG"]


def test_iter_strings_supports_latin1_and_utf8_paths(tmp_path: Path) -> None:
    sample = tmp_path / "strings_text.bin"
    sample.write_text("line1\nline2\n", encoding="utf-8")

    assert list(iter_strings(sample, encoding="latin1"))
    assert list(iter_strings(sample, encoding="utf-8"))


def test_iter_text_strings_from_path_handles_split_utf8_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "split_utf8.bin"
    text = "héllo\nworld\n"
    payload = text.encode("utf-8")
    sample.write_bytes(payload)

    from deopjufier import strings as strings_module

    # Force a UTF-8 split inside a multi-byte sequence.
    monkeypatch.setattr(
        strings_module,
        "iter_file_chunks",
        lambda _path, chunk_size=1 << 16: [payload[:2], payload[2:]],
    )
    assert list(iter_strings(sample, encoding="utf-8")) == ["héllo", "world"]


def test_iter_text_strings_from_path_uses_streaming_decoder_for_latin1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "stream_latin1.bin"
    sample.write_bytes(b"alpha\nbeta\n")

    from deopjufier import strings as strings_module

    monkeypatch.setattr(
        strings_module.Path,
        "read_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("read_text should not be used for streaming path mode")
        ),
    )
    assert list(iter_strings(sample, encoding="latin1")) == ["alpha", "beta"]


def test_scan_numeric_tables_from_file_carries_split_lines(tmp_path: Path) -> None:
    sample = tmp_path / "split.bin"
    sample.write_bytes(b"1 2\n3 4 5")

    rows = tables_module.scan_numeric_tables_from_file(sample, chunk_size=3, min_rows=1, min_columns=2)

    assert rows == [
        (1, 1, 0, ["1", "2"]),
        (1, 2, 4, ["3", "4", "5"]),
    ]


def test_scan_numeric_tables_from_file_does_not_read_full_file_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "large.bin"
    sample.write_bytes(b"10 20\n30 40\n")

    def _fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("scan_numeric_tables_from_file should not call Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", _fail_read_bytes)
    rows = tables_module.scan_numeric_tables_from_file(sample, chunk_size=4)

    assert rows


def test_iter_strings_uses_chunked_streaming_for_large_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"alpha beta\n" + b"x" * (8 * 1024 * 1024)
    sample = tmp_path / "large_strings.bin"
    sample.write_bytes(payload)

    def _fail_read_text(self: Path) -> str:
        raise AssertionError("iter_strings should not use Path.read_text for large input")

    monkeypatch.setattr(Path, "read_text", _fail_read_text)
    assert "alpha beta" in list(iter_strings(sample, encoding="ascii", min_length=5))


def test_scan_numeric_tables_from_file_scales_with_large_input_without_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "large_scan.bin"
    sample.write_bytes(b"10 20\n30 40\n" + (b"0 0\n" * (8 * 1024 * 1024 // 4)))

    def _fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("scan_numeric_tables_from_file should not use Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", _fail_read_bytes)
    rows = tables_module.scan_numeric_tables_from_file(sample, chunk_size=1 << 20, min_rows=1, min_columns=2)

    assert rows


def test_find_image_blocks_on_large_input_does_not_use_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"prefix" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"pad" * (8 * 1024 * 1024 // 3)
    sample = tmp_path / "large_window.bin"
    sample.write_bytes(data)

    def _fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("find_image_blocks should avoid Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", _fail_read_bytes)
    blocks = find_image_blocks(sample)

    assert any(block.kind == "png" for block in blocks)


def test_find_image_blocks_avoids_full_read_method(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "window.opju"
    sample.write_bytes(b"xx" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"yy")

    def _fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("find_image_blocks should avoid Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", _fail_read_bytes)
    blocks = find_image_blocks(sample)

    assert any(block.kind == "png" for block in blocks)


def test_find_image_blocks_scans_past_initial_window(tmp_path: Path) -> None:
    window = 8 * 1024 * 1024
    jpeg_payload = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + b"\x00\x00"
        + b"\xff\xd9"
    )
    sample = tmp_path / "far_window_scan.opju"
    sample.write_bytes(b"\x00" * (window + 17) + jpeg_payload)

    blocks = find_image_blocks(sample)
    expected_offset = window + 17
    assert any(
        block.kind == "jpeg" and block.offset == expected_offset and block.length == len(jpeg_payload)
        for block in blocks
    )


def test_find_image_blocks_png_jpeg_svg(tmp_path: Path) -> None:
    valid_jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + b"\x01\x02"
        + b"\xff\xd9"
    )

    sample = tmp_path / "imgs.opju"
    sample.write_bytes(
        b"\xff" * 5
        + b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
        + valid_jpeg
        + b"%PDF-1.7\n1 0 obj\n<< /Catalog >>\nendobj\n%%EOF\n"
        + b"<svg id='a'>x</svg>"
        + valid_jpeg
    )

    blocks = find_image_blocks(sample)
    blocks_by_kind = {block.kind for block in blocks}
    assert {"png", "jpeg", "svg", "pdf"} <= blocks_by_kind
    # if GIF appears, it is only from header heuristic.
    assert any(block.kind == "png" for block in blocks)
    assert any(block.kind == "jpeg" for block in blocks)
    assert any(block.kind == "svg" for block in blocks)
    assert any(block.kind == "pdf" for block in blocks)
    assert len(blocks) >= 3


def test_extract_raw_blocks_exports_expected_gaps(tmp_path: Path) -> None:
    data = b"START--" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"--END"
    sample = tmp_path / "rawgap.opju"
    sample.write_bytes(data)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "raw"
    written = extract_raw_blocks(sample, out_dir, manifest, min_size=4)
    assert written == 2
    assert len(manifest.items) == 2
    assert manifest.items[0].kind == "raw_dump"
    assert manifest.items[0].status == "extracted"
    assert manifest.items[1].status == "extracted"
    assert manifest.items[0].range_start == 0
    assert manifest.items[0].range_end is not None
    assert manifest.items[0].range_start is not None
    assert manifest.items[0].length is not None
    first_start = manifest.items[0].range_start
    first_length = manifest.items[0].length
    assert first_start is not None
    assert first_length is not None
    assert manifest.items[0].range_end == first_start + first_length
    assert manifest.items[1].range_start == 27
    assert manifest.items[1].range_end is not None
    assert manifest.items[1].range_start is not None
    assert manifest.items[1].length is not None
    second_start = manifest.items[1].range_start
    second_length = manifest.items[1].length
    assert second_start is not None
    assert second_length is not None
    assert manifest.items[1].range_end == second_start + second_length
    assert manifest.items[0].source_object_path is not None
    assert manifest.items[1].source_object_path is not None


def test_extract_raw_blocks_emits_raw_region_classification_and_warnings(tmp_path: Path) -> None:
    sample = tmp_path / "raw_warning.opju"
    sample.write_bytes(b"\x00" * 64)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "raw"
    written = extract_raw_blocks(sample, out_dir, manifest, min_size=32)

    assert written == 1
    assert manifest.items[0].kind == "raw_dump"
    assert manifest.items[0].object_kind == RAW_REGION_CLASS_UNKNOWN_LOW_ENTROPY
    assert any(item.startswith("Unsupported raw region class discovered") for item in manifest.warnings)


def test_extract_raw_blocks_excludes_text_regions_without_output(tmp_path: Path) -> None:
    sample = tmp_path / "raw_excluded_text.opju"
    sample.write_bytes(b"\x00" * 32)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "raw"
    written = extract_raw_blocks(
        sample,
        out_dir,
        manifest,
        min_size=4,
        gap_ranges=[(0, 32)],
        excluded_region_classes={RAW_REGION_CLASS_TEXT},
        gap_classifications=[
            RawRegionClassification(
                offset=0,
                length=32,
                region_class=RAW_REGION_CLASS_TEXT,
                confidence=0.8,
            )
        ],
    )

    assert written == 0
    assert len(manifest.items) == 1
    item = manifest.items[0]
    assert item.kind == "raw_dump"
    assert item.status == "skipped"
    assert item.error == "excluded_by_text_extraction"
    assert item.path is None


def test_extract_text_regions_exports_ascii_fragments(tmp_path: Path) -> None:
    sample = tmp_path / "text_regions.opju"
    sample.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82" + b"alpha beta\nline two\n" + b"\xff\xd8\xff\xd9"
    )

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "text_regions"
    written = extract_text_regions(
        sample,
        out_dir,
        manifest,
        min_size=1,
        min_length=4,
        force=True,
    )

    assert written == 1
    assert manifest.items
    item = manifest.items[0]
    assert item.kind == "text_region"
    assert item.status == "extracted"
    assert item.object_kind == RAW_REGION_CLASS_TEXT
    assert item.rows is not None
    assert item.rows >= 2
    outputs = list(out_dir.glob("text_off_*.txt"))
    assert len(outputs) == 1
    text_target = outputs[0]
    assert text_target.exists()
    text = text_target.read_text(encoding="utf-8")
    assert "alpha beta" in text
    assert "line two" in text


def test_extract_text_regions_skips_existing_region_output_without_force(tmp_path: Path) -> None:
    sample = tmp_path / "text_regions_existing.opju"
    sample.write_bytes(b"alpha beta\nline two\n\xff\xd8\xff\xd9")

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "text_regions"
    first_written = extract_text_regions(
        sample,
        out_dir,
        manifest,
        min_size=1,
        min_length=4,
        force=True,
    )
    assert first_written == 1
    text_item = manifest.items[0]
    assert text_item.path is not None
    text_path = Path(text_item.path)
    assert (out_dir / text_path).exists()

    manifest = _make_manifest(sample)
    second_written = extract_text_regions(
        sample,
        out_dir,
        manifest,
        min_size=1,
        min_length=4,
        force=False,
    )
    assert second_written == 0
    second_item = manifest.items[0]
    assert second_item.status == "skipped"
    assert second_item.error == "target_exists"
    assert second_item.path == text_path.as_posix()


def test_gap_ranges_with_overlapping_blocks_and_min_size() -> None:
    blocks = [
        ImageBlock(offset=10, length=10, kind="png", extension="png"),
        ImageBlock(offset=15, length=20, kind="jpeg", extension="jpg"),
        ImageBlock(offset=80, length=5, kind="svg", extension="svg"),
    ]

    ranges = _gap_ranges(120, blocks, min_size=5)

    assert ranges == [(0, 10), (35, 45), (85, 35)]


def test_gap_ranges_with_empty_blocks_and_invalid_min_size() -> None:
    assert _gap_ranges(120, [], min_size=0) == []
    assert _gap_ranges(120, [], min_size=-3) == []
    assert _gap_ranges(0, [], min_size=1) == []
    assert _gap_ranges(0, [ImageBlock(offset=0, length=10, kind="png", extension="png")], min_size=1) == []


def test_gap_ranges_accepts_precomputed_intervals_and_merges_overlap() -> None:
    ranges = _gap_ranges(200, [(10, 40), (30, 40), (150, 30)], min_size=5)
    assert ranges == [(0, 10), (70, 80), (180, 20)]


def test_gap_ranges_returns_entire_file_when_no_blocks() -> None:
    assert _gap_ranges(10, [], min_size=1) == [(0, 10)]
    assert _gap_ranges(3, [], min_size=4) == []


def test_is_media_signature_detects_known_magic_headers() -> None:
    assert _is_media_signature(0, b"CPYA\x00\x00") is True
    assert _is_media_signature(0, b"CPYUA\x00\x00") is True
    assert _is_media_signature(0, b"\x89PNG\r\n\x1a\n\x00\x00") is True
    assert _is_media_signature(0, b"\xff\xd8\xff\xd9") is True
    assert _is_media_signature(0, b"GIF87a") is True
    assert _is_media_signature(0, b"GIF89a") is True
    assert _is_media_signature(1, b" xCPYA\x00") is False
    assert _is_media_signature(0, b"random") is False


def test_book_rows_for_range_and_target_directory_helpers(tmp_path: Path) -> None:
    rows = [
        (1, 1, 10, ["a", "b", "c"]),
        (1, 2, 20, ["d", "e"]),
        (2, 1, 30, ["x"]),
    ]

    assert _book_rows_for_range(rows, 0, 15) == [(1, 1, 10, ["a", "b", "c"])]
    assert _book_rows_for_range(rows, 15, 25) == [(1, 2, 20, ["d", "e"])]
    assert _book_rows_for_range(rows, 5, 100) == rows

    target = _book_dir(tmp_path / "base", "Book\\My Sheet\\Name:1")
    assert str(target) == str(tmp_path / "base" / "Book" / "My_Sheet" / "Name_1")


def test_book_csv_and_note_writer_helpers(tmp_path: Path) -> None:
    csv_target = tmp_path / "table.csv"
    count = _write_book_csv(
        csv_target,
        [
            (1, 1, 10, ["1", "2"]),
            (1, 2, 20, ["3", "4", "5"]),
        ],
        delimiter=",",
    )
    assert count == 2
    text = csv_target.read_text(encoding="utf-8")
    assert "table_id,row_in_table,offset,columns,values" in text
    assert "1,1,10,2,1;2" in text
    assert "1,2,20,3,3;4;5" in text

    note_target = tmp_path / "note.txt"
    written = _write_note_file(note_target, "hello\0\0")
    assert written == 1
    assert note_target.read_text(encoding="utf-8") == "hello"


def test_book_xlsx_writer_requires_openpyxl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_import = __import__

    def _missing_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: tuple[str, ...] | list[str] | None = None,
        level: int = 0,
    ) -> object:
        if name == "openpyxl":
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _missing_import)
    with pytest.raises(ModuleNotFoundError, match="openpyxl"):
        _write_book_xlsx(tmp_path / "book.xlsx", [])


def test_unique_path_adds_suffix_without_forcing_existing_file(tmp_path: Path) -> None:
    base = tmp_path / "out"
    base.mkdir()
    first = _unique_path(base, "sample.txt")
    first.write_text("a", encoding="utf-8")

    second = _unique_path(base, "sample.txt")
    assert second == base / "sample__2.txt"
    second.write_text("b", encoding="utf-8")

    third = _unique_path(base, "sample.txt")
    assert third == base / "sample__3.txt"


def test_manifest_records_source_object_paths_for_all_extract_paths(tmp_path: Path) -> None:
    sample = tmp_path / "mixed.opju"
    sample.write_bytes(
        b"PREFIX"
        + b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
        + b"SUFFIX"
        + b"1 2 3\n4 5 6\n"
        + b"X" * 20
    )

    manifest = _make_manifest(sample)
    extract_images(sample, tmp_path / "images", manifest, force=True)
    extract_strings(sample, tmp_path / "strings", manifest, force=True, min_length=2)
    extract_tables(sample, tmp_path / "tables", manifest, force=True, min_rows=2, min_columns=2)
    extract_raw_blocks(sample, tmp_path / "raw", manifest, force=True, min_size=1)

    assert manifest.items
    assert all(item.source_object_path is not None for item in manifest.items)


def test_extract_raw_blocks_respects_parser_confirmed_object_ranges(tmp_path: Path) -> None:
    sample = tmp_path / "raw_with_object.opju"
    sample.write_bytes(b"A" * 120)

    manifest = _make_manifest(sample)
    out_dir = tmp_path / "raw"
    objects = [
        OriginObject(
            offset=20,
            name="Book1",
            length=50,
            object_kind="worksheet",
            source_object_path="Book/Book1",
            parser_confirmed=True,
        )
    ]
    count = extract_raw_blocks(
        sample,
        out_dir,
        manifest,
        min_size=1,
        objects=objects,
        force=True,
    )

    assert count == 2
    assert (out_dir / "raw_off_000000000000_len_000000000020.bin").read_bytes() == b"A" * 20
    assert (out_dir / "raw_off_000000000070_len_000000000050.bin").read_bytes() == b"A" * 50
    assert manifest.items[0].range_start == 0
    assert manifest.items[0].range_end == 20
    assert manifest.items[1].range_start == 70
    assert manifest.items[1].range_end == 120


def test_cli_main_uses_default_output_dir_for_extract(tmp_path: Path) -> None:
    sample = tmp_path / "missing.opju"
    sample.write_bytes(b"x")
    code = main(["extract", str(sample)])

    assert code == 0

    manifest_path = sample.with_suffix("") / "manifest.json"
    assert manifest_path.exists()


def test_cli_main_unknown_command_returns_usage() -> None:
    assert main(["bad-command"]) == 2


def test_cli_main_rejects_negative_dump_offset() -> None:
    path = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-opj-multi-family.opj"
    code = main(["dump-block", str(path), "--offset", "-1", "--length", "1"])
    assert code == 2


def test_cli_main_main_entrypoint_exists() -> None:
    from deopjufier.cli import cli_entrypoint

    # command parser rejects this path deterministically and keeps behavior consistent.
    with pytest.raises(SystemExit):
        cli_entrypoint()


def test_exceptions_hierarchy() -> None:
    assert issubclass(CorruptedInputError, DeopjufyError)
    assert issubclass(UnsupportedFileError, DeopjufyError)


def test_main_converts_broken_pipe_to_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deopjufier import app
    from deopjufier.commands import dispatch

    def _raise_broken_pipe(*_: object) -> int:
        raise BrokenPipeError()

    sample = tmp_path / "sample.opju"
    sample.write_bytes(b"\x00")

    monkeypatch.setattr(dispatch, "cmd_inspect", _raise_broken_pipe)
    assert app.main(["inspect", str(sample)]) == 0
