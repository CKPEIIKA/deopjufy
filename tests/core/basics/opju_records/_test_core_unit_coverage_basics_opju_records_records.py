import deopjufier
import deopjufier.inventory
from tests.core.basics.opju_records._test_core_unit_coverage_basics_opju_records_common import *  # noqa: F403
from tests.core.basics.opju_records._test_core_unit_coverage_basics_opju_records_common import (
    _book_dir,
    _find_graph_block_for_object,
    _manifest_path,
)


def encode_blob_runs(values: tuple[float, ...], fmt: str = "<f") -> str:
    packed = b"".join(struct.pack(fmt, value) for value in values)
    return base64.b64encode(packed).decode("ascii")


def test_parse_opju_origin_storage_family_table_emits_numeric_columns_from_binary_payload() -> None:
    payload = (
        b'<OriginStorage xmlns="urn" Label="test">'
        b"<N>3</N>"
        b'<Alpha TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((1.0, 2.0, 3.0), "<f").encode("ascii")
        + b"</Alpha>"
        b'<Beta TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((10.0, 11.0, 12.0), "<f").encode("ascii")
        + b"</Beta>"
        b"</OriginStorage>"
    )
    data = b"CPYUA 4.3318 0\x00" + payload
    payload_start = len(data) - len(payload)
    candidate = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=payload_start,
        source_end=len(data),
        payload_start=0,
        payload_end=len(payload),
        payload=payload,
    )

    tables = parse_opju_origin_storage_family_tables(
        data,
        include_decoded=True,
        max_tables=4,
        max_rows=16,
        candidates=(candidate,),
        include_family_binary=True,
    )

    assert tables
    family = tables[0]
    assert family.name.startswith("origin_storage_family_")
    assert family.rows == [
        ["1", "1.0", "10.0"],
        ["2", "2.0", "11.0"],
        ["3", "3.0", "12.0"],
    ]


def test_parse_opju_origin_storage_family_table_accepts_raw_candidate() -> None:
    def encode_blob_runs(values: tuple[float, ...], fmt: str = "<f") -> str:
        packed = b"".join(struct.pack(fmt, value) for value in values)
        return base64.b64encode(packed).decode("ascii")

    payload = (
        b'<OriginStorage xmlns="urn" Label="test">'
        b"<n>2</n>"
        b'<Counts TypeID="65541" BlobArrElementaryType="5">'
        + encode_blob_runs((1.0, 2.0), "<d").encode("ascii")
        + b"</Counts>"
        b'<Percentiles TypeID="65541" BlobArrElementaryType="5">'
        + encode_blob_runs((10.0, 20.0), "<d").encode("ascii")
        + b"</Percentiles>"
        b"</OriginStorage>"
    )
    data = b"CPYUA 4.3318 0\x00" + payload
    payload_start = len(data) - len(payload)
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=payload_start,
        source_end=len(data),
        payload_start=0,
        payload_end=len(payload),
        payload=payload,
    )

    tables = parse_opju_origin_storage_family_tables(
        data,
        include_decoded=True,
        max_tables=4,
        max_rows=16,
        candidates=(candidate,),
        include_family_binary=True,
    )

    assert tables
    family = tables[0]
    assert family.name.startswith("origin_storage_family_")
    assert family.rows == [
        ["1", "1.0", "10.0"],
        ["2", "2.0", "20.0"],
    ]


def test_parse_opju_origin_storage_family_table_accepts_noisy_blob_array_data() -> None:
    def encode_blob_runs(
        values: tuple[float, ...],
        fmt: str = "<d",
    ) -> bytes:
        packed = b"".join(struct.pack(fmt, value) for value in values)
        return base64.b64encode(packed)

    raw_values = encode_blob_runs((1.0, 2.0), "<d")
    noisy_values = raw_values[:4] + b"\x7f" + raw_values[4:8] + b"\n" + raw_values[8:]

    payload = (
        b'<OriginStorage xmlns="urn" Label="test">'
        b"<N>2</N>"
        b'<FitX NodeID="1" Label="Fitted Curve" BlobArrElementaryType="5">' + noisy_values + b"</FitX>"
        b'<FitY NodeID="2" Label="X" BlobArrElementaryType="5">' + encode_blob_runs((10.0, 20.0)) + b"</FitY>"
        b"</OriginStorage>"
    )
    data = b"CPYUA 4.3318 0\x00" + payload
    payload_start = len(data) - len(payload)
    candidate = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=payload_start,
        source_end=len(data),
        payload_start=0,
        payload_end=len(payload),
        payload=payload,
    )

    tables = parse_opju_origin_storage_family_tables(
        data,
        include_decoded=True,
        max_tables=4,
        max_rows=16,
        candidates=(candidate,),
        include_family_binary=True,
    )

    assert tables
    family = tables[0]
    assert family.name.startswith("origin_storage_family_")
    assert family.rows == [
        ["1", "1.0", "10.0"],
        ["2", "2.0", "20.0"],
    ]


def test_parse_opju_origin_storage_family_table_parses_legacy_payload_at_offset_marker() -> None:
    padding = b"\x00" * 32
    payload = padding + b"\x77\x11\x11\x11" + b"\x6d\x11\x11\x11" + b"\x00" + b"R1" + b"\x00" + b"R2" + b"\x00" + b"R3"
    data = b"CPYUA 4.3318 0\x00" + payload
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=len(b"CPYUA 4.3318 0\x00"),
        source_end=len(data),
        payload_start=0,
        payload_end=len(payload),
        payload=payload,
    )

    tables = parse_opju_origin_storage_family_tables(
        data,
        include_decoded=True,
        max_tables=4,
        max_rows=16,
        candidates=(candidate,),
        include_family_binary=True,
    )

    assert len(tables) == 1
    assert tables[0].name.startswith("origin_storage_family_")
    assert tables[0].rows == [["R1"], ["R2"], ["R3"]]


def test_parse_opju_records_returns_typed_empty_for_non_opju_payload() -> None:
    records = parse_opju_records(b"not a CPYUA container")
    assert records.container is None
    assert records.regions == ()
    assert records.report_records == ()
    assert records.worksheet_records == ()
    assert records.reports == ()
    assert records.worksheets == ()


def test_parse_opju_records_parses_cpyua_header() -> None:
    records = parse_opju_records(SYNTHETIC_BINARY_FIXTURE.read_bytes())
    assert records.container is not None
    assert records.container.marker == "CPYUA"
    assert records.container.version == "4.3318"
    assert records.container.declared_length == 113
    assert records.worksheets
    assert records.worksheet_records[0].name == "Book3_B"


def test_parse_opju_records_classifies_origin_storage_regions_before_deeper_recovery() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b'<OriginStorage Label="r1"><Notes>one</Notes></OriginStorage>'
        b"<OriginStorage><Note>hint</Note></OriginStorage>"
        b"<OriginStorage><Function>f(x)=x</Function></OriginStorage>"
        b"<OriginStorage><Graph>plot</Graph></OriginStorage>"
        b"<OriginStorage><foo>unknown</foo></OriginStorage>"
        b"<OriginStorage>" + b"\x89PNG\r\n\x1a\n" + b"\x00" + b"</OriginStorage>"
    )
    records = parse_opju_records(data)

    assert [region.kind for region in records.regions] == [
        "opju_container",
        "origin_storage_report",
        "origin_storage_note",
        "origin_storage_function",
        "origin_storage_graph",
        "origin_storage_unknown_payload",
        "origin_storage_preview",
    ]
    assert any(
        region.kind == "origin_storage_report" and region.offset == data.find(b"<OriginStorage Label")
        for region in records.regions
    )
    assert any(region.kind == "origin_storage_note" for region in records.regions)
    assert any(region.kind == "origin_storage_function" for region in records.regions)
    assert any(region.kind == "origin_storage_graph" for region in records.regions)
    assert any(region.kind == "origin_storage_unknown_payload" for region in records.regions)
    assert any(region.kind == "origin_storage_preview" for region in records.regions)


def test_parse_opju_records_classifies_preview_signatures() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><origin_storage_preview>%PDF-1.7\n1 0 obj\n%%EOF\n</OriginStorage>"
        b"<OriginStorage><svg xmlns='http://www.w3.org/2000/svg'>x</svg></OriginStorage>"
    )

    records = parse_opju_records(data)

    preview_regions = [region for region in records.regions if region.kind == "origin_storage_preview"]
    assert len(preview_regions) >= 2


def test_parse_opju_records_maps_report_source_to_preview_region() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><svg xmlns='http://www.w3.org/2000/svg'>1</svg></OriginStorage>"
        b'<OriginStorage Label="ReportOne"><Notes>ok</Notes></OriginStorage>'
    )

    records = parse_opju_records(data)

    preview_sources = [
        record.source_object_path for record in records.regions if record.kind == "origin_storage_preview"
    ]
    assert preview_sources

    report_sources = [record.source_object_path for record in records.report_records]
    assert any(source == preview_sources[0] for source in report_sources)

    preview_region_name = preview_sources[0]
    assert isinstance(preview_region_name, str)
    assert preview_region_name.removeprefix("previews/").startswith("origin_storage_preview_")


def test_parse_opju_records_classifies_xffunction_records_as_function() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><Operation><xfName>smooth</xfName><XFunctionName>smooth</XFunctionName></Operation></OriginStorage>"
    )

    records = parse_opju_records(data)

    assert records.regions[1].kind == "origin_storage_function"
    assert records.regions[1].name.startswith("origin_storage_function_")


def test_parse_opju_records_classifies_control_byte_split_function_tags() -> None:
    data = (
        b"CPYUA 4.3318 0\x00<OriginStorage><Operation><NLFitXFNa\x7fme>smooth</NLFitXFName></Operation></OriginStorage>"
    )

    records = parse_opju_records(data)

    assert len(records.regions) == 2
    assert records.regions[1].kind == "origin_storage_function"


def test_parse_opju_records_classifies_function_without_whole_word_match() -> None:
    data = (
        b"CPYUA 4.3318 0\x00<OriginStorage><Operation><functionlist>smooth</functionlist></Operation></OriginStorage>"
    )

    records = parse_opju_records(data)

    assert any(region.kind == "origin_storage_function" for region in records.regions)


def test_parse_opju_records_classifies_fitcurve_aliases_as_function() -> None:
    data = b"CPYUA 4.3318 0\x00<OriginStorage><Operation><__FITCURVE>smooth</__FITCURVE></Operation></OriginStorage>"

    records = parse_opju_records(data)
    assert any(region.kind == "origin_storage_function" for region in records.regions)


def test_parse_opju_records_classifies_expgraph_regions_as_function() -> None:
    data = b"CPYUA 4.3318 0\x00<OriginStorage><Operation><EXPGRAPH>1 2 3</EXPGRAPH></Operation></OriginStorage>"

    records = parse_opju_records(data)
    assert any(region.kind == "origin_storage_function" for region in records.regions)


def test_analyze_origin_storage_candidates_scans_fallback_tags_once_per_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<OriginStorage><Operation><Note>one</Note><Note>two</Note></Operation></OriginStorage>"
    data = b"CPYUA 4.3318 0\x00" + payload
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=len(b"CPYUA 4.3318 0\x00"),
        source_end=len(data),
        payload_start=len(b"CPYUA 4.3318 0\x00"),
        payload_end=len(data),
        payload=payload,
    )

    calls = {"count": 0}
    original = opju_analysis._iter_tag_names

    def _counting_iter_tag_names(
        candidate_payload: bytes,
        root,
        *,
        normalized_text: str | None = None,
    ) -> tuple[str, ...]:
        calls["count"] += 1
        return original(
            candidate_payload,
            root,
            normalized_text=normalized_text,
        )

    monkeypatch.setattr(opju_analysis, "_iter_tag_names", _counting_iter_tag_names)

    analyzed = opju_analysis.analyze_origin_storage_candidates(
        data,
        include_decoded=False,
        candidates=(candidate,),
    )

    assert len(analyzed) == 1
    assert analyzed[0].region_kind == "origin_storage_note"
    assert analyzed[0].tag_names
    assert calls["count"] == 1


def test_analyze_origin_storage_candidates_scans_fallback_tag_names_once_when_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<OriginStorage><NoTe>one"
    data = b"CPYUA 4.3318 0\x00" + payload
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=len(b"CPYUA 4.3318 0\x00"),
        source_end=len(data),
        payload_start=len(b"CPYUA 4.3318 0\x00"),
        payload_end=len(data),
        payload=payload,
    )

    calls = {"count": 0}
    original = opju_analysis._iter_tag_names_from_text

    def _counting_iter_tag_names_from_text(text: str) -> tuple[str, ...]:
        calls["count"] += 1
        return tuple(original(text))

    monkeypatch.setattr(opju_analysis, "_iter_tag_names_from_text", _counting_iter_tag_names_from_text)

    analyzed = opju_analysis.analyze_origin_storage_candidates(
        data,
        include_decoded=False,
        candidates=(candidate,),
    )

    assert len(analyzed) == 1
    assert analyzed[0].region_kind == "origin_storage_note"
    assert calls["count"] == 1


def test_analyze_origin_storage_candidates_scans_fallback_tags_once_for_function_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<OriginStorage><Function>one"
    data = b"CPYUA 4.3318 0\x00" + payload
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=len(b"CPYUA 4.3318 0\x00"),
        source_end=len(data),
        payload_start=len(b"CPYUA 4.3318 0\x00"),
        payload_end=len(data),
        payload=payload,
    )

    calls = {"count": 0}
    original = opju_analysis._iter_tag_names_from_text

    def _counting_iter_tag_names_from_text(text: str) -> tuple[str, ...]:
        calls["count"] += 1
        return tuple(original(text))

    monkeypatch.setattr(opju_analysis, "_iter_tag_names_from_text", _counting_iter_tag_names_from_text)

    analyzed = opju_analysis.analyze_origin_storage_candidates(
        data,
        include_decoded=False,
        candidates=(candidate,),
    )

    assert len(analyzed) == 1
    assert analyzed[0].region_kind == "origin_storage_function"
    assert calls["count"] == 1


def test_analyze_origin_storage_candidates_skips_raw_path_scan_without_path_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<OriginStorage><Operation><Note>one</Note></Operation></OriginStorage>"
    data = b"CPYUA 4.3318 0\x00" + payload
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=len(b"CPYUA 4.3318 0\x00"),
        source_end=len(data),
        payload_start=len(b"CPYUA 4.3318 0\x00"),
        payload_end=len(data),
        payload=payload,
    )

    calls = {"count": 0}

    def _counting_raw_path(_text: str) -> tuple[str, ...]:
        calls["count"] += 1
        return ()

    monkeypatch.setattr(opju_analysis, "_raw_path_candidates", _counting_raw_path)

    analyzed = opju_analysis.analyze_origin_storage_candidates(
        data,
        include_decoded=False,
        candidates=(candidate,),
    )

    assert len(analyzed) == 1
    assert analyzed[0].region_kind == "origin_storage_note"
    assert calls["count"] == 0


def test_analyze_origin_storage_candidates_scans_raw_paths_when_path_markers_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'<OriginStorage><Path>"C:/Book1.xlsx"</Path></OriginStorage>'
    data = b"CPYUA 4.3318 0\x00" + payload
    candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=len(b"CPYUA 4.3318 0\x00"),
        source_end=len(data),
        payload_start=len(b"CPYUA 4.3318 0\x00"),
        payload_end=len(data),
        payload=payload,
    )

    calls = {"count": 0}

    def _counting_raw_path(_text: str) -> tuple[str, ...]:
        calls["count"] += 1
        return ("C:/Book1.xlsx",)

    monkeypatch.setattr(opju_analysis, "_raw_path_candidates", _counting_raw_path)

    analyzed = opju_analysis.analyze_origin_storage_candidates(
        data,
        include_decoded=False,
        candidates=(candidate,),
    )

    assert len(analyzed) == 1
    assert analyzed[0].region_kind == "origin_storage_attachment"
    assert analyzed[0].attachment_name == "Book1.xlsx"
    assert calls["count"] == 1


def test_parse_opju_records_classifies_control_byte_split_note_tags() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><Operation><No\x7fte>one</No\x7fte></Operation><No\x7fte>two</No\x7fte></OriginStorage>"
    )

    records = parse_opju_records(data)

    assert any(region.kind == "origin_storage_note" for region in records.regions)


def test_parse_opju_records_balances_nested_origin_storage_blocks() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b"<OriginStorage><foo>"
        b"<OriginStorage><iy1>1</iy1><iy2>2</iy2></OriginStorage>"
        b"</foo></OriginStorage>"
    )

    records = parse_opju_records(data)

    assert [region.kind for region in records.regions] == [
        "opju_container",
        "origin_storage_function",
    ]
    function_region = records.regions[1]
    assert function_region.kind == "origin_storage_function"
    assert function_region.offset == len(b"CPYUA 4.3318 0\x00")
    assert function_region.length == len(
        b"<OriginStorage><foo><OriginStorage><iy1>1</iy1><iy2>2</iy2></OriginStorage></foo></OriginStorage>"
    )


def test_parse_opju_records_classifies_attachment_regions() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b'<OriginStorage Label="r1"><Notes>one</Notes></OriginStorage>'
        b"<OriginStorage>[H:\\Temp\\Book1.xlsx]</OriginStorage>"
    )

    records = parse_opju_records(data)
    assert any(region.kind == "origin_storage_attachment" and region.name == "Book1.xlsx" for region in records.regions)
    attachment = next(region for region in records.regions if region.kind == "origin_storage_attachment")
    assert attachment.source_object_path == "Excel/Book1.xlsx"
    assert attachment.confidence == 0.89


def test_parse_opju_records_stops_header_at_newline_before_binary_payload() -> None:
    signature = b"CPYUA 4.3445 200\n"
    binary_payload = b"\x27\x01\x6c\xc0\x11\x01\x06\x80\x01\x00"

    records = parse_opju_records(signature + binary_payload)

    assert records.container is not None
    assert records.container.header_length == len(signature)
    assert records.container.raw_header == signature
    assert records.container.version == "4.3445"
    assert records.container.declared_length == 200
    container_region = records.regions[0]
    assert container_region.kind == "opju_container"
    assert container_region.offset == 0
    assert container_region.length == len(signature)


@pytest.mark.parametrize(
    ("payload", "expected_name"),
    [
        (b"<OriginStorage>[C:\\Data\\Quarterly_Report.pdf]</OriginStorage>", "Quarterly_Report.pdf"),
        (b"<OriginStorage>[/tmp/book1.xls]</OriginStorage>", "book1.xls"),
        (b"<OriginStorage>[D:\\Docs\\notes.docx]</OriginStorage>", "notes.docx"),
        (
            b'<OriginStorage><Path>"D:\\Temp\\Notes\\summary.pdf"</Path></OriginStorage>',
            "summary.pdf",
        ),
        (
            b'<OriginStorage><Path>"C:/Research/Archive/Figure 7.jpg"</Path></OriginStorage>',
            "Figure_7.jpg",
        ),
    ],
)
def test_parse_opju_records_classifies_attachment_regions_for_multiple_extensions(
    payload: bytes,
    expected_name: str,
) -> None:
    data = b"CPYUA 4.3318 0\x00" + payload
    records = parse_opju_records(data)

    regions = [region for region in records.regions if region.kind == "origin_storage_attachment"]
    assert regions
    attachment = next(region for region in regions if region.name == expected_name)
    assert attachment.source_object_path == f"Excel/{expected_name}"
    assert attachment.confidence == 0.89


def test_parse_opju_records_prefers_decoded_payload_when_twin_exists() -> None:
    base = b"CPYUA 4.3318 0\x00"
    decoded_start = len(base) + 8
    decoded_payload = b'<OriginStorage Label="Decoded"><Notes>short</Notes></OriginStorage>'
    decoded_end = decoded_start + len(decoded_payload)
    raw_payload = b'<OriginStorage Label="Raw"><Notes>' + b"x" * 64 + b"</Notes></OriginStorage>"
    raw_start = len(base) + 10
    raw_end = raw_start + len(raw_payload)

    data = base + b"\x00" * (raw_end - len(base))

    candidates = (
        OpjuOriginStorageCandidate(
            source_kind="decoded",
            source_start=decoded_start,
            source_end=decoded_end,
            payload_start=0,
            payload_end=len(decoded_payload),
            payload=decoded_payload,
        ),
        OpjuOriginStorageCandidate(
            source_kind="raw",
            source_start=raw_start,
            source_end=raw_end,
            payload_start=0,
            payload_end=len(raw_payload),
            payload=raw_payload,
        ),
    )

    def _fake_candidates(payload: bytes, *, include_decoded: bool = True):
        del payload
        return candidates

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            "deopjufier.opju.records.iter_origin_storage_candidates",
            _fake_candidates,
        )
        records = parse_opju_records(data, max_rows=1)
    finally:
        monkeypatch.undo()

    assert [region.kind for region in records.regions if region.kind != "opju_container"] == ["origin_storage_report"]
    assert records.regions[1].offset == decoded_start
    assert records.regions[1].length == len(decoded_payload)
    assert all(region.offset != raw_start for region in records.regions if region.kind != "opju_container")


def test_parse_opju_records_still_parses_raw_region_when_decoding_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = b"CPYUA 4.3318 0\x00"
    raw_payload = b'<OriginStorage Label="Raw"><Notes>raw only</Notes></OriginStorage>'
    raw_start = len(base) + 10
    raw_end = raw_start + len(raw_payload)

    data = base + b"\x00" * (raw_end - len(base))

    candidates = (
        OpjuOriginStorageCandidate(
            source_kind="raw",
            source_start=raw_start,
            source_end=raw_end,
            payload_start=0,
            payload_end=len(raw_payload),
            payload=raw_payload,
        ),
    )

    def _fake_candidates(payload: bytes, *, include_decoded: bool = True):
        del payload
        del include_decoded
        return candidates

    monkeypatch.setattr(
        "deopjufier.opju.records.iter_origin_storage_candidates",
        _fake_candidates,
    )
    records = parse_opju_records(data, include_decoded=False)

    assert records.regions[1].kind == "origin_storage_report"
    assert records.regions[1].offset == raw_start
    assert records.regions[1].length == len(raw_payload)


def test_parse_opju_records_classifies_attachment_with_control_byte_noise() -> None:
    data = (
        b'CPYUA 4.3318 0\x00<OriginStorage><Path>"C:\\Temp\\Quarterly\\Report\x7f_\x00Final.pdf"</Path></OriginStorage>'
    )
    records = parse_opju_records(data)

    attachment_items = [region for region in records.regions if region.kind == "origin_storage_attachment"]
    assert attachment_items
    attachment = attachment_items[0]
    assert attachment.name == "Report_Final.pdf"
    assert attachment.source_object_path == "Excel/Report_Final.pdf"
    assert attachment.confidence == 0.89


def test_parse_opju_records_uses_deterministic_parser_backed_naming() -> None:
    data = (
        b"CPYUA 4.3318 0\x00"
        b'<OriginStorage Label="Report / One"><Notes>one</Notes></OriginStorage>'
        b'<OriginStorage Label="Report / One"><Notes>two</Notes></OriginStorage>'
        b'<ColumnTable Name="Book A">1\n</ColumnTable>'
        b'<ColumnTable Name="Book A">2\n</ColumnTable>'
    )

    first = parse_opju_records(data)
    second = parse_opju_records(data)

    assert [report.name for report in first.report_records] == [
        "Report___One",
        "Report___One__2",
    ]
    assert [table.name for table in first.worksheet_records] == ["Book_A", "Book_A__2"]

    assert [(r.name, r.source_object_path) for r in first.report_records] == [
        ("Report___One", "origin_storage_reports/Report___One"),
        ("Report___One__2", "origin_storage_reports/Report___One__2"),
    ]
    assert [(record.name, record.source_object_path) for record in first.worksheet_records] == [
        ("Book_A", "worksheets/Book_A"),
        ("Book_A__2", "worksheets/Book_A__2"),
    ]

    assert [report.name for report in second.report_records] == [
        "Report___One",
        "Report___One__2",
    ]
    assert [table.name for table in second.worksheet_records] == ["Book_A", "Book_A__2"]


def test_parse_opju_records_cache_reuse_for_reports_and_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = SYNTHETIC_BINARY_FIXTURE.read_bytes()
    sample = tmp_path / "fixture.opju"
    sample.write_bytes(data)

    calls = {"count": 0}
    original = deopjufier.inventory.opju_parser.parse_opju_records

    def _counting_parse_opju_records(
        payload: bytes,
        *,
        max_reports: int = 8,
        max_input_items: int = 10,
        max_tables: int = 16,
        max_rows: int = 256,
    ) -> OpjuRecords:
        calls["count"] += 1
        return original(
            payload,
            max_reports=max_reports,
            max_input_items=max_input_items,
            max_tables=max_tables,
            max_rows=max_rows,
        )

    monkeypatch.setattr(
        "deopjufier.inventory.opju_parser.parse_opju_records",
        _counting_parse_opju_records,
    )

    first_reports = parse_opju_origin_storage_reports(data, path=sample)
    first_tables = parse_opju_column_tables(data, path=sample)
    second_reports = parse_opju_origin_storage_reports(data, path=sample)

    assert calls["count"] == 1
    assert first_tables == parse_opju_column_tables(data, path=sample)
    assert second_reports == first_reports


def test_parse_opju_records_forwards_include_family_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, bool] = {}
    data = b"CPYUA 4.3318 0\x00"

    def _fake_parse(
        payload: bytes,
        *,
        max_reports: int = 8,
        max_input_items: int = 10,
        max_tables: int = 16,
        max_rows: int = 256,
        include_decoded: bool = True,
        include_family_binary: bool = False,
    ) -> OpjuRecords:
        seen["value"] = include_family_binary
        return OpjuRecords(
            container=None,
            regions=(),
            report_records=(),
            worksheet_records=(),
            reports=(),
            worksheets=(),
        )

    monkeypatch.setattr(
        "deopjufier.inventory.opju_parser.parse_opju_records",
        _fake_parse,
    )

    parsed = parse_opju_records(data, include_family_binary=True)

    assert parsed == OpjuRecords(
        container=None,
        regions=(),
        report_records=(),
        worksheet_records=(),
        reports=(),
        worksheets=(),
    )
    assert seen["value"] is True


def test_recover_worksheet_rows_from_opju_passes_path_to_parser_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "fixture.opju"
    data = b"CPYUA 4.3318 0\x00"
    sample.write_bytes(data)
    seen_paths: list[Path | None] = []

    def _fake_parse(
        payload: bytes,
        *,
        path: Path | None = None,
        max_reports: int = 8,
        max_input_items: int = 10,
    ) -> OpjuRecords:
        seen_paths.append(path)
        return OpjuRecords(
            container=None,
            regions=(),
            report_records=(),
            worksheet_records=(
                OpjuWorksheetRecord(
                    name="Book1_A",
                    label=None,
                    offset=12,
                    length=8,
                    row_count=2,
                ),
            ),
            reports=(),
            worksheets=(
                OpjuColumnTable(
                    name="Book1_A",
                    label=None,
                    offset=12,
                    length=8,
                    rows=[["1.0"], ["2.0"]],
                ),
            ),
        )

    monkeypatch.setattr("deopjufier.opju.recovery.parse_opju_records", _fake_parse)

    rows_by_name, dims_by_name, parser_hints = recover_worksheet_rows_from_opju(
        data,
        worksheet_names={"Book1_A"},
        path=sample,
    )

    assert seen_paths == [sample]
    assert rows_by_name == {"Book1_A": [["1.0"], ["2.0"]]}
    assert dims_by_name == {"Book1_A": (2, 1)}
    assert parser_hints == set()


def test_discover_origin_objects_uses_structural_opju_region_kinds() -> None:
    objects = discover_origin_objects(SYNTHETIC_FIXTURE)
    kinds = {obj.object_kind for obj in objects}
    assert "opju_report" in kinds
    assert "worksheet" in kinds


def test_manifest_path_is_relative_when_under_base(tmp_path: Path) -> None:
    base = tmp_path / "out"
    manifest_path = base / "a.txt"
    assert _manifest_path(manifest_path, base) == "a.txt"

    outside = base.parent / "other" / "a.txt"
    assert _manifest_path(outside, base) == "a.txt"
    assert _manifest_path(base / "a.txt", None) == "a.txt"


def test_manifest_path_never_returns_absolute_when_outside_base(tmp_path: Path) -> None:
    base = tmp_path / "out"
    outside = tmp_path / "outside" / "a.txt"
    assert not Path(_manifest_path(outside, base)).is_absolute()


def test_book_dir_normalizes_windows_separators_and_reserved_names() -> None:
    base = Path("output")
    assert _book_dir(base, "Folder\\Sub\\CON") == base / "Folder" / "Sub" / "_CON"
    assert _book_dir(base, "Folder/Sub/CON") == _book_dir(base, "Folder\\Sub\\CON")
    assert _book_dir(base, "Folder/Sub/COM1.txt") == base / "Folder" / "Sub" / "_COM1.txt"
    assert _book_dir(base, "Folder/Sub/.") == base / "Folder" / "Sub" / "item"


def test_find_graph_block_for_object_rejects_bad_bounds() -> None:
    blocks = [ImageBlock(offset=10, length=4, kind="png", extension="png")]
    assert _find_graph_block_for_object(blocks, -1, 20) is None
    assert _find_graph_block_for_object(blocks, 20, 10) is None
    assert _find_graph_block_for_object(blocks, 12, 20) == blocks[0]
    assert _find_graph_block_for_object(blocks, 1, 9) is None


def test_find_graph_block_for_object_prefers_valid_candidate_over_invalid() -> None:
    valid_block = ImageBlock(offset=22, length=16, kind="png", extension="png", valid=True)
    invalid_block = ImageBlock(offset=10, length=54, kind="bmp", extension="bmp", valid=False, error="bmp_invalid")

    selected = _find_graph_block_for_object(
        [invalid_block, valid_block],
        12,
        40,
        allow_invalid=True,
    )

    assert selected == valid_block
