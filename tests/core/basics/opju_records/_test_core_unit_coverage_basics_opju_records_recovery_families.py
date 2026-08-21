"""OPJU family-table recovery regression tests."""

from __future__ import annotations

from deopjufier.inventory import OriginObject
from deopjufier.opju.recovery_helpers_tokens import _build_worksheet_name_candidate_lookup
from deopjufier.opju.recovery_helpers_windows import (
    _expand_adjacent_alpha1_sheet_targets_from_selection,
    _expand_adjacent_alpha2_sheet_targets_from_selection,
    _iter_family_worksheet_tokens_from_payload,
    _match_family_table_to_worksheet_names,
)
from tests.core.basics.opju_records._test_core_unit_coverage_basics_opju_records_common import *  # noqa: F403


def test_iter_family_worksheet_tokens_from_payload_captures_bare_sheet_tokens() -> None:
    data = b"CPYUA 4.3318 0\x00" + b"x" * 8 + b"Header\nSheet1\nMore\nbook11_A\n" + b"\x00" * 4

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=5,
        length=len(data) - 5,
    )

    assert tokens == {"sheet1", "book11_a"}


def test_iter_family_worksheet_tokens_from_payload_captures_cell_ref_target_names() -> None:
    payload = b"x\x00" * 16 + b"header\ncell://[Book1]FitLinear3!Parameters.Error.col_label4\x00"
    data = b"CPYUA 4.3318 0\x00" + payload

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=11,
        length=len(data) - 11,
    )

    assert "book1/fitlinear3" in tokens


def test_iter_family_worksheet_tokens_from_payload_captures_quoted_sheet_target_names() -> None:
    payload = b"x\x00" + b"[Book1]&quot;CV 1.2 V&quot;!AV[1]\x00" + b'[Book2]"Sheet-A"!B1\x00' + b"[Book3]Sheet1!B1\x00"
    data = b"CPYUA 4.3318 0\x00" + payload

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=11,
        length=len(data) - 11,
    )

    assert "book1/cv_1.2_v" in tokens
    assert "book2/sheet-a" in tokens
    assert "book3/sheet1" in tokens


def test_iter_family_worksheet_tokens_from_payload_captures_plain_sheet_target_names() -> None:
    payload = b"x\x00" + b"[Book15]Sheet1!A1\x00" + b"[Book15]Sheet-2!B3\x00" + b"[Book15A]plainname\x00"
    data = b"CPYUA 4.3318 0\x00" + payload

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=11,
        length=len(data) - 11,
    )

    assert "book15/sheet1" in tokens
    assert "book15/sheet-2" in tokens
    assert "book15a/plainname" in tokens


def test_iter_family_worksheet_tokens_from_payload_captures_workbook_token_from_plain_book_ref() -> None:
    payload = b"x\x00" + b"[Book1]20240610_001_SK107_2_100OE_abc\x00"
    data = b"CPYUA 4.3318 0\x00" + payload

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=11,
        length=len(data) - 11,
    )

    assert "book1" in tokens
    assert "book1/20240610_001_sk107_2_100oe_abc" in tokens


def test_iter_family_worksheet_tokens_from_payload_captures_apostrophe_sheet_target_names() -> None:
    payload = (
        b"x\x00"
        + b"[Book1]&apos;CV 1.2 V&apos;!AV[1]\x00"
        + b"[Book12]'Sheet-A'!B1\x00"
        + b"[Book13]'Plain Name'D2\x00"
    )
    data = b"CPYUA 4.3318 0\x00" + payload

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=11,
        length=len(data) - 11,
    )

    assert "book1/cv_1.2_v" in tokens
    assert "book12/sheet-a" in tokens
    assert "book13/plain_name" in tokens


def test_iter_family_worksheet_tokens_from_payload_captures_quoted_sheet_target_names_without_bang() -> None:
    payload = (
        b"x\x00" + b"[Book9]&quot;CV 1.2 V&quot;AV[1]\x00" + b'[Book12]"Sheet-A"C3\x00' + b"[Book11]Plain-NameD1\x00"
    )
    data = b"CPYUA 4.3318 0\x00" + payload

    tokens = _iter_family_worksheet_tokens_from_payload(
        data,
        start=11,
        length=len(data) - 11,
    )

    assert "book9/cv_1.2_v" in tokens
    assert "book12/sheet-a" in tokens
    assert "book11/plain-named1" in tokens


def test_build_worksheet_name_candidate_lookup_includes_normalized_worksheet_variants() -> None:
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book11/Sheet1",
            "Book1A_A@5",
            "Sheet7",
            "Book9_B",
        }
    )

    assert lookup["book11"] == {"Book11/Sheet1"}
    assert lookup["sheet1"] == {"Book11/Sheet1"}
    assert lookup["book11/sheet1"] == {"Book11/Sheet1"}
    assert lookup["book1a_a@5"] == {"Book1A_A@5"}
    assert lookup["sheet7"] == {"Sheet7"}


def test_match_family_table_to_worksheet_names_prefers_cell_ref_tokens() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )
    data = b"CPYUA 4.3318 0\x00cell://[Book1]FitLinear3!Parameters\x00"
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book1/FitLinear3",
            "Book1/FitLinear4",
            "Book2/FitLinear3",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=data,
        worksheet_name_lookup=lookup,
        family_worksheet_tokens={"book1/fitlinear3"},
    )

    assert matched == ["Book1/FitLinear3"]


def test_match_family_table_to_worksheet_names_expands_single_character_sheet_batch() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book1_D@7",
            "Book1_E@7",
            "Book1_F@7",
            "Book1_G@7",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00book1_d book1_e book1_f\x00",
        worksheet_name_lookup=lookup,
        explicit_supported_names={"Book1_F@7"},
        family_worksheet_tokens={"book1_d", "book1_e", "book1_f"},
    )

    assert set(matched) == {"Book1_D@7", "Book1_E@7", "Book1_F@7"}


def test_match_family_table_to_worksheet_names_returns_overlap_batch_for_single_char_sheet_siblings() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book1_D@7",
            "Book1_E@7",
            "Book1_F@7",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00book1_d book1_e book1_f\x00",
        worksheet_name_lookup=lookup,
        worksheet_windows=[
            ("Book1_D@7", 0, 8),
            ("Book1_F@7", 12, 18),
        ],
        family_worksheet_tokens={"book1_d", "book1_e", "book1_f"},
    )

    assert set(matched) == {"Book1_D@7", "Book1_E@7", "Book1_F@7"}


def test_match_family_table_to_worksheet_names_prefers_exact_workbook_root_match() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book11",
            "Book11/Sheet1",
            "Book1/Sheet2",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00",
        worksheet_name_lookup=lookup,
        explicit_supported_names={"Book11"},
        family_worksheet_tokens={"book11"},
    )

    assert matched == ["Book11"]


def test_match_family_table_to_worksheet_names_prefers_supported_sheet_descendant_match() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book11/Sheet1",
            "Book15/Sheet1",
            "Sheet1",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00book11\x00sheet1\x00",
        worksheet_name_lookup=lookup,
        explicit_supported_names={"Book11"},
        family_worksheet_tokens={"book11", "sheet1"},
    )

    assert matched == ["Book11/Sheet1"]


def test_match_family_table_to_worksheet_names_retains_multiple_supported_sheet_descendants() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"]],
    )
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book11/Sheet1",
            "Book15/Sheet1",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00",
        worksheet_name_lookup=lookup,
        explicit_supported_names={"Book11/Sheet1", "Book15/Sheet1"},
        family_worksheet_tokens={"sheet1"},
    )

    assert set(matched) == {"Book11/Sheet1", "Book15/Sheet1"}


def test_match_family_table_to_worksheet_names_does_not_fanout_workbook_token_without_root_name() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )
    lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book1/FitLinear2",
            "Book1/FitLinear3",
        }
    )

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00",
        worksheet_name_lookup=lookup,
        explicit_supported_names={"Book1/FitLinear2"},
        family_worksheet_tokens={"book1"},
    )

    assert matched == []


def test_expand_adjacent_alpha1_sheet_targets_from_selection() -> None:
    assert _expand_adjacent_alpha1_sheet_targets_from_selection(
        {"Book1_B@7", "Book1_C@7", "Book1_D@7", "Book1_Z@7"},
        "Book1_C@7",
    ) == {"Book1_B@7", "Book1_C@7"}


def test_expand_adjacent_alpha1_sheet_targets_from_selection_ignores_non_alpha1_targets() -> None:
    assert _expand_adjacent_alpha1_sheet_targets_from_selection(
        {"Book1_CC@7", "Book1_D@7", "Book1_EE@7"},
        "Book1_CC@7",
    ) == {"Book1_CC@7"}


def test_expand_adjacent_alpha2_sheet_targets_from_selection_includes_previous_prefix_siblings() -> None:
    assert _expand_adjacent_alpha2_sheet_targets_from_selection(
        {"Book1_AB@7", "Book1_AC@7", "Book1_AD@7"},
        "Book1_AD@7",
    ) == {"Book1_AB@7", "Book1_AC@7", "Book1_AD@7"}


def test_expand_adjacent_alpha2_sheet_targets_from_selection_includes_next_prefix_siblings_at_sequence_start() -> None:
    assert _expand_adjacent_alpha2_sheet_targets_from_selection(
        {"Book1_AA@7", "Book1_AB@7", "Book1_AC@7"},
        "Book1_AA@7",
    ) == {"Book1_AA@7", "Book1_AB@7", "Book1_AC@7"}


def test_match_family_table_to_worksheet_names_prefers_alpha2_evidence_over_single_char_overlap() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=1000,
        length=900,
        rows=[["1"], ["2"], ["3"]],
    )
    worksheet_name_lookup = _build_worksheet_name_candidate_lookup(
        {
            "Book1_AA@7",
            "Book1_AB@7",
            "Book1_AC@7",
            "Book1_G@7",
            "Book1_H@7",
            "Book1_I@7",
            "Book1_J@7",
            "Book1_Z@7",
        }
    )
    table_tokens = {
        "book1_aa",
        "book1_g",
        "book1_h",
        "book1_i",
        "book1_j",
        "book1_z",
    }
    worksheet_windows = [
        ("Book1_AA@7", 1200, 1400),
        ("Book1_G@7", 1300, 1391),
        ("Book1_H@7", 1400, 1491),
        ("Book1_I@7", 1500, 1591),
        ("Book1_J@7", 1700, 1791),
        ("Book1_Z@7", 500, 2000),
    ]

    matched = _match_family_table_to_worksheet_names(
        table,
        data=b"CPYUA 4.3318 0\x00",
        worksheet_name_lookup=worksheet_name_lookup,
        family_worksheet_tokens=table_tokens,
        worksheet_windows=worksheet_windows,
    )

    assert matched == ["Book1_AA@7"]


def test_recover_worksheet_rows_from_opju_expands_two_char_sheet_matches_to_previous_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "fixture.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00book1_ad\x00")

    def _fake_parse(
        payload: bytes,
        *,
        path: Path | None = None,
        max_reports: int = 8,
        max_input_items: int = 10,
        include_family_binary: bool = False,
        max_tables: int = 16,
        max_rows: int = 256,
    ) -> OpjuRecords:
        del payload, path, max_input_items, max_tables, max_rows
        table_rows = [["1"], ["2"], ["3"]]
        return OpjuRecords(
            container=None,
            regions=(),
            report_records=(),
            worksheet_records=(
                OpjuWorksheetRecord(
                    name="origin_storage_family_01",
                    label=None,
                    offset=12,
                    length=8,
                    row_count=3,
                ),
            ),
            worksheets=(
                OpjuColumnTable(
                    name="origin_storage_family_01",
                    label=None,
                    offset=12,
                    length=8,
                    rows=table_rows,
                ),
            ),
            reports=(),
        )

    monkeypatch.setattr("deopjufier.opju.recovery.parse_opju_records", _fake_parse)

    worksheet_objects = cast(
        tuple[OriginObject, ...],
        (
            SimpleNamespace(
                name="Book1_AB@7",
                object_kind="worksheet",
                offset=4,
                length=8,
                parser_confirmed=False,
            ),
            SimpleNamespace(
                name="Book1_AC@7",
                object_kind="worksheet",
                offset=24,
                length=8,
                parser_confirmed=False,
            ),
            SimpleNamespace(
                name="Book1_AD@7",
                object_kind="worksheet",
                offset=12,
                length=8,
                parser_confirmed=False,
            ),
        ),
    )

    rows_by_name, dims_by_name, supported_names = recover_worksheet_rows_from_opju(
        sample.read_bytes(),
        worksheet_names={"Book1_AB@7", "Book1_AC@7", "Book1_AD@7"},
        worksheet_objects=worksheet_objects,
        path=sample,
    )

    assert rows_by_name["Book1_AD@7"] == [["1"], ["2"], ["3"]]
    assert rows_by_name["Book1_AC@7"] == [["1"], ["2"], ["3"]]
    assert rows_by_name["Book1_AB@7"] == [["1"], ["2"], ["3"]]
    assert dims_by_name["Book1_AD@7"] == (3, 1)
    assert supported_names == {"Book1_AB@7", "Book1_AC@7", "Book1_AD@7"}


def test_recover_worksheet_rows_from_opju_prefers_report_references_for_zero_row_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = tmp_path / "fixture.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00")

    report = OpjuOriginStorageReport(
        index=0,
        offset=0,
        length=0,
        label=None,
        function=None,
        user=None,
        time=None,
        data_filter=None,
        rows=None,
        columns=None,
        input_data=[],
        descriptive_stats={},
        ranks={},
        test_statistics={},
        raw_text=('note: [Book1]FitLinearCurve7 was used. cell://[Book1]FitLinearCurve7!(A"B",B"C") [BookX]HintOnly'),
    )

    def _fake_parse(
        payload: bytes,
        *,
        path: Path | None = None,
        max_reports: int = 8,
        max_input_items: int = 10,
        include_family_binary: bool = False,
        max_tables: int = 16,
        max_rows: int = 256,
    ) -> OpjuRecords:
        del payload, path, max_input_items, max_tables, max_rows
        return OpjuRecords(
            container=None,
            regions=(),
            report_records=(),
            worksheet_records=(),
            reports=(report,),
            worksheets=(),
        )

    monkeypatch.setattr("deopjufier.opju.recovery.parse_opju_records", _fake_parse)

    rows_by_name, dims_by_name, parser_hints = recover_worksheet_rows_from_opju(
        sample.read_bytes(),
        worksheet_names={"Book1/FitLinearCurve7", "BookX/Unknown"},
        path=sample,
        worksheet_objects=cast(
            Any,
            (
                SimpleNamespace(
                    name="Book1/FitLinearCurve7",
                    object_kind="worksheet",
                    length=24,
                    offset=10,
                    parser_confirmed=False,
                ),
                SimpleNamespace(
                    name="BookX/Unknown",
                    object_kind="worksheet",
                    length=24,
                    offset=40,
                    parser_confirmed=False,
                ),
            ),
        ),
    )

    assert parser_hints == {"Book1/FitLinearCurve7", "BookX/Unknown"}
    assert rows_by_name["Book1/FitLinearCurve7"] == []
    assert dims_by_name["Book1/FitLinearCurve7"] == (0, 0)


def test_parse_opju_origin_storage_family_table_variant_with_non_strict_tags() -> None:
    def encode_blob_runs(values: tuple[float, ...], fmt: str = "<f") -> str:
        packed = b"".join(struct.pack(fmt, value) for value in values)
        return base64.b64encode(packed).decode("ascii")

    payload = (
        b'<OriginStorage xmlns="urn" Label="test">'
        b"<Results><N>3</N>"
        b'<Alpha TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((1.0, 2.0, 3.0), "<f").encode("ascii")
        + b"</Alpha>"
        b'<Beta TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((10.0, 11.0, 12.0), "<f").encode("ascii")
        + b"</Beta>"
        b"</Results></OriginStorage>"
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
    )

    assert tables
    family = tables[0]
    assert family.name.startswith("origin_storage_family_")
    assert family.rows == [
        ["1", "1.0", "10.0"],
        ["2", "2.0", "11.0"],
        ["3", "3.0", "12.0"],
    ]


def test_parse_opju_origin_storage_family_table_variant_with_lowercase_tags() -> None:
    def encode_blob_runs(values: tuple[float, ...], fmt: str = "<f") -> str:
        packed = b"".join(struct.pack(fmt, value) for value in values)
        return base64.b64encode(packed).decode("ascii")

    payload = (
        b'<OriginStorage xmlns="urn" Label="test">'
        b"<results><n>3</n>"
        b'<counts TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((1.0, 2.0, 3.0), "<f").encode("ascii")
        + b"</counts>"
        b'<percentiles TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((10.0, 11.0, 12.0), "<f").encode("ascii")
        + b"</percentiles>"
        b'<custompercentiles TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((20.0, 21.0, 22.0), "<f").encode("ascii")
        + b"</custompercentiles>"
        + b"</results></OriginStorage>"
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
    )

    assert tables
    family = tables[0]
    assert family.name.startswith("origin_storage_family_")
    assert family.rows == [
        ["1", "1.0", "10.0", "20.0"],
        ["2", "2.0", "11.0", "21.0"],
        ["3", "3.0", "12.0", "22.0"],
    ]


def test_parse_opju_origin_storage_family_table_variant_with_no_results_tag() -> None:
    def encode_blob_runs(values: tuple[float, ...], fmt: str = "<f") -> str:
        packed = b"".join(struct.pack(fmt, value) for value in values)
        return base64.b64encode(packed).decode("ascii")

    payload = (
        b'<OriginStorage xmlns="urn" Label="test">'
        b"<N>3</N>"
        b'<Alpha TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((1.0, 2.0, 3.0), "<f").encode("ascii")
        + b"</Alpha>"
        b'<Beta TypeID="65541" BlobArrElementaryType="4">'
        + encode_blob_runs((10.0, 11.0, 12.0), "<f").encode("ascii")
        + b"</Beta>"
        + b"</OriginStorage>"
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
    )

    assert tables
    family = tables[0]
    assert family.name.startswith("origin_storage_family_")
    assert family.rows == [
        ["1", "1.0", "10.0"],
        ["2", "2.0", "11.0"],
        ["3", "3.0", "12.0"],
    ]
