from deopjufier.inventory import OriginObject
from deopjufier.opju.recovery_helpers_tokens import _normalize_worksheet_token
from deopjufier.opju.recovery_main import _pick_unresolved_overlap_root_target
from tests.core.basics.opju_records._test_core_unit_coverage_basics_opju_records_common import *  # noqa: F403
from tests.core.basics.opju_records._test_core_unit_coverage_basics_opju_records_common import (
    _LOCKED_ZENODO_OPJU_RECOVERY_FIXTURES,
)
from tests.test_core_unit_coverage_utils import _resolve_repo_fixture


def test_normalize_worksheet_token_preserves_trailing_sheet_letters() -> None:
    assert _normalize_worksheet_token("book1_an") == "book1_an"
    assert _normalize_worksheet_token("book1_ar") == "book1_ar"
    assert _normalize_worksheet_token("book1_ax") == "book1_ax"


def test_pick_unresolved_overlap_root_target_prefers_root_when_present() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )

    assert (
        _pick_unresolved_overlap_root_target(
            table,
            overlap_windows=[("Book1_A", 12, 22)],
            worksheet_names={"Book1", "Book1_A"},
            assigned_names=set(),
            can_use_boundary_windows=True,
        )
        == "Book1"
    )


def test_pick_unresolved_overlap_root_target_prefers_concrete_match_when_root_missing() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )

    assert (
        _pick_unresolved_overlap_root_target(
            table,
            overlap_windows=[("N2N_D", 12, 22)],
            worksheet_names={"N2N_D"},
            assigned_names=set(),
            can_use_boundary_windows=True,
        )
        == "N2N_D"
    )


def test_pick_unresolved_overlap_root_target_preserves_versioned_name() -> None:
    table = OpjuColumnTable(
        name="origin_storage_family_01",
        label=None,
        offset=12,
        length=10,
        rows=[["1"], ["2"]],
    )

    assert (
        _pick_unresolved_overlap_root_target(
            table,
            overlap_windows=[("Book1A_A@2", 12, 22)],
            worksheet_names={"Book1A", "Book1A_A@2"},
            assigned_names=set(),
            can_use_boundary_windows=True,
        )
        == "Book1A_A@2"
    )


@pytest.mark.parametrize(
    ("fixture_label", "fixture_path", "expected_supported", "expected_family_count", "expected_named_rows"),
    _LOCKED_ZENODO_OPJU_RECOVERY_FIXTURES,
    ids=[entry[0] for entry in _LOCKED_ZENODO_OPJU_RECOVERY_FIXTURES],
)
def test_recover_worksheet_rows_from_opju_diagnostics_for_locked_zenodo_fixtures(
    fixture_label: str,
    fixture_path: Path,
    expected_supported: set[str],
    expected_family_count: int,
    expected_named_rows: set[str],
) -> None:
    if not fixture_path.exists():
        pytest.skip(f"Fixture missing: {fixture_path}")

    discovered_worksheet_names = sorted(
        {obj.name for obj in discover_origin_objects(fixture_path) if obj.object_kind == "worksheet"}
    )
    data = fixture_path.read_bytes()
    rows_by_name, dims_by_name, supported_names = recover_worksheet_rows_from_opju(
        data,
        worksheet_names=discovered_worksheet_names,
        path=fixture_path,
    )
    family_tables = [
        table
        for table in parse_opju_column_tables(
            data,
            max_tables=200,
            max_rows=256,
            include_decoded=True,
            include_family_binary=True,
        )
        if table.name.startswith("origin_storage_family_")
    ]
    family_names = {table.name for table in family_tables}
    named_row_keys = {name for name in rows_by_name if not name.startswith("origin_storage_family_")}

    assert fixture_label
    assert supported_names == expected_supported
    assert len(family_tables) == expected_family_count
    assert family_names.issubset(rows_by_name)
    assert family_names.issubset(dims_by_name)

    for table in family_tables:
        assert rows_by_name[table.name] == table.rows
        assert dims_by_name[table.name] == (
            len(table.rows),
            max((len(row) for row in table.rows), default=0),
        )

    if expected_family_count == 0:
        assert rows_by_name == {}
        assert dims_by_name == {}
    if expected_named_rows:
        assert expected_named_rows.issubset(named_row_keys)
        for name in sorted(expected_named_rows):
            assert dims_by_name[name] == (
                len(rows_by_name[name]),
                max((len(row) for row in rows_by_name[name]), default=0),
            )
    else:
        assert named_row_keys == set()


def test_recover_worksheet_rows_from_opju_eucd2p2_emits_rows() -> None:
    fixture_path = _resolve_repo_fixture(
        Path(__file__),
        "refs/public/zenodo/zenodo-18450855-eucd2p2.opju",
    )
    if not fixture_path.exists():
        pytest.skip("Fixture missing: zenodo-18450855-eucd2p2.opju")

    discovered_worksheet_names = {
        obj.name for obj in discover_origin_objects(fixture_path) if obj.object_kind == "worksheet"
    }
    rows_by_name, dims_by_name, supported_names = recover_worksheet_rows_from_opju(
        fixture_path.read_bytes(),
        worksheet_names=discovered_worksheet_names,
        path=fixture_path,
    )

    assert "Book1" in supported_names
    assert "Book11" in supported_names
    assert "Book1A" in supported_names
    assert "Book2" in supported_names
    assert len(rows_by_name.get("Book11", [])) > 0
    assert len(rows_by_name.get("Book1A", [])) > 0
    assert len(rows_by_name.get("Book2", [])) > 0
    assert rows_by_name["Book1"] == []
    assert dims_by_name["Book1"] == (0, 0)
    assert rows_by_name["Sheet2"] == []
    assert dims_by_name["Sheet2"] == (0, 0)

    for name in {
        "Book7",
        "Book7_A",
        "Book7_B",
        "Book9",
        "Book9_B",
        "Book9_O",
        "Book9_S",
    }:
        assert name in rows_by_name
        assert rows_by_name[name] == []
        assert dims_by_name[name] == (0, 0)
        assert name in supported_names

    assert "Sheet2" in supported_names

    for name in {"Book1", "Book11"}:
        if rows_by_name.get(name):
            assert dims_by_name[name] == (
                len(rows_by_name[name]),
                max((len(row) for row in rows_by_name[name]), default=0),
            )


def test_recover_worksheet_rows_from_opju_eucd2p2_uses_origin_storage_function_tokens() -> None:
    fixture_path = _resolve_repo_fixture(
        Path(__file__),
        "refs/public/zenodo/zenodo-18450855-eucd2p2.opju",
    )
    if not fixture_path.exists():
        pytest.skip("Fixture missing: zenodo-18450855-eucd2p2.opju")

    discovered_worksheet_names = {
        obj.name for obj in discover_origin_objects(fixture_path) if obj.object_kind == "worksheet"
    }
    rows_by_name, dims_by_name, supported_names = recover_worksheet_rows_from_opju(
        fixture_path.read_bytes(),
        worksheet_names=discovered_worksheet_names,
        path=fixture_path,
    )

    assert "Book15/Sheet1" in rows_by_name
    assert "Book15/Sheet1" in supported_names
    assert dims_by_name["Book15/Sheet1"] == (
        len(rows_by_name["Book15/Sheet1"]),
        max((len(row) for row in rows_by_name["Book15/Sheet1"]), default=0),
    )


def test_recover_worksheet_rows_from_opju_small_science_expands_adjacent_alpha1_sheet() -> None:
    fixture_path = _resolve_repo_fixture(
        Path(__file__),
        "refs/public/zenodo/zenodo-19549171-small-science-paper.opju",
    )
    if not fixture_path.exists():
        pytest.skip("Fixture missing: zenodo-19549171-small-science-paper.opju")

    discovered_worksheet_names = {
        obj.name for obj in discover_origin_objects(fixture_path) if obj.object_kind == "worksheet"
    }
    rows_by_name, dims_by_name, supported_names = recover_worksheet_rows_from_opju(
        fixture_path.read_bytes(),
        worksheet_names=discovered_worksheet_names,
        path=fixture_path,
    )

    assert "Book1_Y@7" in rows_by_name
    assert rows_by_name["Book1_Y@7"] == rows_by_name["Book1_Z@7"]
    assert dims_by_name["Book1_Y@7"] == (
        len(rows_by_name["Book1_Y@7"]),
        max((len(row) for row in rows_by_name["Book1_Y@7"]), default=0),
    )
    assert "Book1_Y@7" in supported_names


def test_recover_worksheet_rows_from_opju_falls_back_to_worksheet_names_without_report_tokens() -> None:
    rows_by_name, dims_by_name, parser_hints = recover_worksheet_rows_from_opju(
        b"CPYUA 4.3318 0\x00no reports",
        worksheet_names={"Book1_A", "Sheet1"},
    )

    assert rows_by_name == {}
    assert dims_by_name == {}
    assert parser_hints == {"Book1_A", "Sheet1"}


def test_recover_worksheet_rows_from_opju_binds_single_unambiguous_non_explicit_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"CPYUA 4.3318 0\x00"

    def _fake_parse(
        payload: bytes,
        *,
        path: Path | None = None,
        max_reports: int = 8,
        max_input_items: int = 10,
        max_tables: int = 16,
        max_rows: int = 256,
        include_decoded: bool = False,
        include_family_binary: bool = False,
    ) -> OpjuRecords:
        _ = (
            path,
            max_reports,
            max_input_items,
            max_tables,
            max_rows,
            include_decoded,
            include_family_binary,
        )
        return OpjuRecords(
            container=None,
            regions=(),
            report_records=(),
            worksheet_records=(
                OpjuWorksheetRecord(
                    name="origin_storage_family_01",
                    label=None,
                    offset=12,
                    length=10,
                    row_count=2,
                ),
            ),
            reports=(
                OpjuOriginStorageReport(
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
                    raw_text="[HintSheet] summary",
                ),
            ),
            worksheets=(
                OpjuColumnTable(
                    name="origin_storage_family_01",
                    label=None,
                    offset=12,
                    length=10,
                    rows=[["1"], ["2"]],
                ),
            ),
        )

    def _fake_family_tokens(payload: bytes, start: int, length: int) -> set[str]:
        _ = payload, start, length
        return {"book_exact"}

    monkeypatch.setattr(
        "deopjufier.opju.recovery.parse_opju_records",
        _fake_parse,
    )
    monkeypatch.setattr(
        "deopjufier.opju.recovery._iter_family_worksheet_tokens_from_payload",
        _fake_family_tokens,
    )

    rows_by_name, dims_by_name, parser_hints = recover_worksheet_rows_from_opju(
        data,
        worksheet_names={"HintSheet_A", "Book_Exact"},
    )

    assert rows_by_name["Book_Exact"] == [["1"], ["2"]]
    assert dims_by_name["Book_Exact"] == (2, 1)
    assert "Book_Exact" in rows_by_name
    assert parser_hints == {"HintSheet_A", "Book_Exact"}


def test_recover_worksheet_rows_from_opju_reuses_workbook_prefix_targets_with_repeated_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "fixture.opju"
    sample.write_bytes(b"CPYUA 4.3318 0\x00" + (b"\x00" * 200))
    worksheet_rows = [["1", "2"], ["3", "4"]]

    def _fake_parse(
        payload: bytes,
        *,
        path: Path | None = None,
        max_reports: int = 8,
        max_input_items: int = 10,
        max_tables: int = 16,
        max_rows: int = 256,
        include_decoded: bool = False,
        include_family_binary: bool = False,
    ) -> OpjuRecords:
        _ = (
            payload,
            path,
            max_reports,
            max_input_items,
            max_tables,
            max_rows,
            include_decoded,
            include_family_binary,
        )
        worksheet_records = (
            OpjuWorksheetRecord(
                name="origin_storage_family_01",
                label=None,
                offset=20,
                length=20,
                row_count=2,
            ),
            OpjuWorksheetRecord(
                name="origin_storage_family_02",
                label=None,
                offset=80,
                length=20,
                row_count=2,
            ),
        )
        worksheets = (
            OpjuColumnTable(
                name="origin_storage_family_01",
                label=None,
                offset=20,
                length=20,
                rows=worksheet_rows,
            ),
            OpjuColumnTable(
                name="origin_storage_family_02",
                label=None,
                offset=80,
                length=20,
                rows=worksheet_rows,
            ),
        )
        return OpjuRecords(
            container=None,
            regions=(),
            report_records=(),
            worksheet_records=worksheet_records,
            reports=(),
            worksheets=worksheets,
        )

    def _fake_match(
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        # Repeated worksheet mapping on the same root should repurpose the
        # unassigned name by window overlap.
        return ["Book1/FitLinear2"]

    monkeypatch.setattr(
        "deopjufier.opju.recovery_main._parse_opju_records",
        _fake_parse,
    )
    monkeypatch.setattr(
        "deopjufier.opju.recovery_main._match_family_table_to_worksheet_names",
        _fake_match,
    )

    rows_by_name, dims_by_name, supported_names = recover_worksheet_rows_from_opju(
        sample.read_bytes(),
        worksheet_names={"Book1/FitLinear2", "Book1/FitLinear3"},
        path=sample,
        worksheet_objects=cast(
            tuple[OriginObject, ...],
            (
                SimpleNamespace(
                    name="Book1/FitLinear2",
                    offset=20,
                    length=20,
                    object_kind="worksheet",
                ),
                SimpleNamespace(
                    name="Book1/FitLinear3",
                    offset=80,
                    length=20,
                    object_kind="worksheet",
                ),
            ),
        ),
    )

    assert rows_by_name["Book1/FitLinear2"] == worksheet_rows
    assert rows_by_name["Book1/FitLinear3"] == worksheet_rows
    assert dims_by_name["Book1/FitLinear2"] == (
        len(worksheet_rows),
        max((len(row) for row in worksheet_rows), default=0),
    )
    assert dims_by_name["Book1/FitLinear3"] == (
        len(worksheet_rows),
        max((len(row) for row in worksheet_rows), default=0),
    )
    assert supported_names == {
        "Book1/FitLinear2",
        "Book1/FitLinear3",
    }
