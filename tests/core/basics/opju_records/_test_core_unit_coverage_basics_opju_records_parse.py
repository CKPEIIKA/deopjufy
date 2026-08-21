from deopjufier.opju.tables import _FAMILY_BINARY_FORMULA_MIN_ROWS
from tests.core.basics.opju_records._test_core_unit_coverage_basics_opju_records_common import *  # noqa: F403


def test_parse_opju_origin_storage_reports_extracts_declared_shape() -> None:
    block = (
        b'<OriginStorage Rows="3" Columns="2" Label="Summary">'
        b"<Rows>3</Rows><Columns>2</Columns>"
        b'<Notes Label="Notes"><xf NodeID="1" Label="X-Function">Summary</xf>'
        b'<User NodeID="2" Label="User Name">reporter</User></Notes>'
        b"</OriginStorage>"
    )
    data = b"CPYUA 4.3318 113\0" + block + b"\x00"

    reports = parse_opju_origin_storage_reports(data, max_reports=1)

    assert len(reports) == 1
    report = reports[0]
    assert report.label == "Summary"
    assert report.rows == 3
    assert report.columns == 2


def test_parse_opju_origin_storage_reports_uses_decoded_candidate_for_origin_storage_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = b"CPYUA 4.3318 0\x00"
    decoded_start = len(base) + 8
    raw_start = decoded_start + 2
    decoded_payload = b'<OriginStorage Label="Decoded"><Notes>decode me</Notes></OriginStorage>'
    raw_payload = b'<OriginStorage Label="Raw"><Notes>raw noise</Notes></OriginStorage>'
    data = base + b"\x00" * (raw_start + len(raw_payload) - len(base))

    decoded_candidate = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=decoded_start,
        source_end=decoded_start + len(decoded_payload),
        payload_start=0,
        payload_end=len(decoded_payload),
        payload=decoded_payload,
    )
    raw_candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=raw_start,
        source_end=raw_start + len(raw_payload),
        payload_start=0,
        payload_end=len(raw_payload),
        payload=raw_payload,
    )

    monkeypatch.setattr(
        opju_regions,
        "_iter_origin_storage_raw_regions",
        lambda _payload: [(raw_start, raw_start + len(raw_payload))],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_lz4_candidates",
        lambda _payload, raw_offset: (decoded_candidate,) if raw_offset == raw_start else (raw_candidate,),
    )

    reports = parse_opju_origin_storage_reports(
        data,
        include_decoded=True,
        max_reports=2,
    )

    assert len(reports) == 1
    assert reports[0].label == "Decoded"


def test_parse_opju_column_tables_recovers_explicit_column_rows() -> None:
    data = (
        b"CPYUA 4.3318 113\n"
        b'<ColumnTable Name="Book3_B" Label="August">'
        b"18.3\n13.3\n16.5\n12.6\n9.5\n13.6\n8.1\n8.9\n10.0\n8.3\n7.9\n8.1\n13.4\n"
        b"</ColumnTable>"
        b'<ColumnTable Name="Book3_C" Label="November">'
        b"12.7\n11.1\n15.3\n12.7\n10.5\n15.6\n11.2\n14.2\n16.3\n15.5\n19.9\n20.4\n36.8\n"
        b"</ColumnTable>"
    )

    tables = parse_opju_column_tables(data)
    assert [table.name for table in tables] == ["Book3_B", "Book3_C"]
    assert tables[0].label == "August"
    assert tables[1].label == "November"
    assert tables[0].rows[0] == ["18.3"]
    assert tables[0].rows[-1] == ["13.4"]
    assert tables[1].rows[0] == ["12.7"]
    assert tables[1].rows[-1] == ["36.8"]


def test_iter_opju_family_signature_positions_scans_all_known_markers() -> None:
    marker_a = b"\x77\x11\x11\x11"
    marker_b = b"\x72\x11\x11\x11"
    marker_c = b"\x00\x00\x00\x00\x03\x00\x00\x00\x10\x00\x00\x00"
    data = b"pad" + marker_a + b"..." + marker_b + b"..." + marker_c
    positions = opju_regions._iter_opju_family_signature_positions(data)

    assert positions == [
        data.find(marker_a),
        data.find(marker_b),
        data.find(marker_c),
    ]


def _make_formula_family_candidate(
    marker: bytes,
    *,
    table_rows: int = _FAMILY_BINARY_FORMULA_MIN_ROWS,
) -> OpjuOriginStorageCandidate:
    formulas = [f"=A{i}/{i + 1}" for i in range(1, table_rows + 1)]
    payload = marker + b"\x00" + b"\x00".join(formula.encode("ascii") for formula in formulas)
    start = len("CPYUA 4.3318 0\x00")
    return OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=start,
        source_end=start + len(payload),
        payload_start=0,
        payload_end=len(payload),
        payload=payload,
    )


def _make_legacy_family_candidate(
    marker: bytes,
    tokens: tuple[str, ...] = ("Sheet1", "Sheet1"),
    *,
    with_segments: bool = True,
) -> OpjuOriginStorageCandidate:
    payload = marker + b"\x00\x00\x01\x00\x00\x00\x00\x00\x02\x00"
    if with_segments:
        payload += b"m\x11\x11\x11"
    payload += b"\x00".join(token.encode("ascii") for token in tokens)

    start = len("CPYUA 4.3318 0\x00")
    return OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=start,
        source_end=start + len(payload),
        payload_start=0,
        payload_end=len(payload),
        payload=payload,
    )


def test_parse_opju_column_tables_parses_family_formula_markers_with_single_eq_tokens() -> None:
    marker = b"\x77\x11\x11\x11"
    candidate = _make_formula_family_candidate(marker)
    data = b"CPYUA 4.3318 0\x00" + candidate.payload

    def parse(*args: object, **kwargs: object) -> tuple[OpjuOriginStorageCandidate]:
        return (candidate,)

    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr(opju_regions, "iter_origin_storage_candidates", parse)
        tables = parse_opju_column_tables(
            data,
            include_decoded=True,
            include_family_binary=True,
            max_tables=1,
        )

    assert len(tables) == 1
    assert tables[0].label == "OriginStorageBinaryFamilyFormula"
    assert len(tables[0].rows) == _FAMILY_BINARY_FORMULA_MIN_ROWS
    assert tables[0].rows[0][0] == "=A1/2"


def test_parse_opju_column_tables_parses_legacy_family_marker_segments() -> None:
    marker = b"\x72\x11\x11\x11"
    candidate = _make_legacy_family_candidate(marker)
    data = b"CPYUA 4.3318 0\x00" + candidate.payload

    def parse(*args: object, **kwargs: object) -> tuple[OpjuOriginStorageCandidate]:
        return (candidate,)

    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr(opju_regions, "iter_origin_storage_candidates", parse)
        tables = parse_opju_column_tables(
            data,
            include_decoded=True,
            include_family_binary=True,
            max_tables=1,
        )

    assert len(tables) == 1
    assert tables[0].label == "OriginStorageBinaryFamilyLegacy"
    assert len(tables[0].rows) == 2
    assert tables[0].rows == [["Sheet1"], ["Sheet1"]]


def test_parse_opju_column_tables_parses_legacy_family_marker_without_segments() -> None:
    marker = b"\x77\x11\x11\x11"
    candidate = _make_legacy_family_candidate(
        marker,
        ("Hz", "Frequenz", "#0.125"),
        with_segments=False,
    )
    data = b"CPYUA 4.3318 0\x00" + candidate.payload

    def parse(*args: object, **kwargs: object) -> tuple[OpjuOriginStorageCandidate]:
        return (candidate,)

    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr(opju_regions, "iter_origin_storage_candidates", parse)
        tables = parse_opju_column_tables(
            data,
            include_decoded=True,
            include_family_binary=True,
            max_tables=1,
        )

    assert len(tables) == 1
    assert tables[0].label == "OriginStorageBinaryFamilyLegacy"
    assert [row[0] for row in tables[0].rows] == ["Hz", "Frequenz", "#0.125"]


def test_parse_opju_column_tables_parses_r_marker_family_formula_blocks() -> None:
    marker = b"\x72\x11\x11\x11"
    candidate = _make_formula_family_candidate(marker)
    data = b"CPYUA 4.3318 0\x00" + candidate.payload

    def parse(*args: object, **kwargs: object) -> tuple[OpjuOriginStorageCandidate]:
        return (candidate,)

    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr(opju_regions, "iter_origin_storage_candidates", parse)
        tables = parse_opju_column_tables(
            data,
            include_decoded=True,
            include_family_binary=True,
            max_tables=1,
        )

    assert len(tables) == 1
    assert tables[0].label == "OriginStorageBinaryFamilyFormula"
    assert len(tables[0].rows) == _FAMILY_BINARY_FORMULA_MIN_ROWS


def test_parse_opju_column_tables_uses_decoded_candidate_for_origin_storage_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = b"CPYUA 4.3318 0\x00"
    decoded_start = len(base) + 8
    raw_start = decoded_start + 2
    decoded_payload = (
        b'<OriginStorage Label="Decoded"><ColumnTable Name="Parsed">1\n2\n3\n</ColumnTable></OriginStorage>'
    )
    raw_payload = b'<OriginStorage Label="Raw"><ColumnTable Name="Raw">9\n8\n7\n</ColumnTable></OriginStorage>'
    data = base + b"\x00" * (raw_start + len(raw_payload) - len(base))

    decoded_candidate = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=decoded_start,
        source_end=decoded_start + len(decoded_payload),
        payload_start=0,
        payload_end=len(decoded_payload),
        payload=decoded_payload,
    )
    raw_candidate = OpjuOriginStorageCandidate(
        source_kind="raw",
        source_start=raw_start,
        source_end=raw_start + len(raw_payload),
        payload_start=0,
        payload_end=len(raw_payload),
        payload=raw_payload,
    )

    monkeypatch.setattr(
        opju_regions,
        "_iter_origin_storage_raw_regions",
        lambda _payload: [(raw_start, raw_start + len(raw_payload))],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_lz4_candidates",
        lambda _payload, raw_offset: (decoded_candidate,) if raw_offset == raw_start else (raw_candidate,),
    )

    tables = parse_opju_column_tables(data, include_decoded=True, max_tables=2)

    assert [table.name for table in tables] == ["Parsed"]
    assert tables[0].rows == [["1"], ["2"], ["3"]]


def test_iter_opju_family_candidates_filters_to_xml_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = b"\x77\x11\x11\x11"
    base = b"CPYUA 4.3318 0\x00"
    marker_start = len(base) + 5
    size = 12
    compressed = b"\x01\x02\x03\x04" + b"\x00" * 20
    data = base + b"\x00" * (marker_start - len(base)) + marker + b"\x00" * 4 + size.to_bytes(4, "little") + compressed
    valid_xml = b'<OriginStorage Label="Report">ok</OriginStorage>'
    binary_payload = b"\x89PNG\r\n\x1a\nnot xml"

    call_order = {"value": 0}

    def _fake_lz4_decompress(src: bytes, declared_size: int):
        call_order["value"] += 1
        if declared_size != size or not src.startswith(b"\x01\x02\x03\x04"):
            raise ValueError("unexpected block")
        if call_order["value"] == 1:
            return binary_payload, 4
        return valid_xml, 4

    monkeypatch.setattr(opju_regions, "lz4_block_decompress", _fake_lz4_decompress)

    candidates = opju_regions._iter_opju_family_lz4_candidates(data, marker_start, marker)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_kind == "decoded"
    assert candidate.payload == valid_xml
    assert candidate.decompressed_size == size


def test_iter_origin_storage_candidates_includes_family_marker_decoded_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = b"\x77\x11\x11\x11"
    base = b"CPYUA 4.3318 0\x00"
    marker_start = len(base) + 5
    size = 12
    compressed = b"\x01\x02\x03\x04" + b"\x00" * 20
    data = base + b"\x00" * (marker_start - len(base)) + marker + b"\x00" * 4 + size.to_bytes(4, "little") + compressed
    valid_xml = b'<OriginStorage Label="Family"><Notes/></OriginStorage>'

    def _fake_lz4_decompress(src: bytes, declared_size: int):
        if declared_size != size or not src.startswith(b"\x01\x02\x03\x04"):
            raise ValueError("unexpected block")
        return valid_xml, 4

    monkeypatch.setattr(opju_regions, "lz4_block_decompress", _fake_lz4_decompress)

    candidates = opju_regions.iter_origin_storage_candidates(data)

    assert len(candidates) == 1
    assert candidates[0].source_kind == "decoded"
    assert candidates[0].payload == valid_xml


def test_iter_origin_storage_candidates_prefers_canonical_framing_before_inferred_alternatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = b"\x72\x11\x11\x11"
    base = b"CPYUA 4.3318 0\x00"
    marker_start = len(base) + 5
    data = base + b"\x00" * (marker_start - len(base)) + marker + b"\x00" * 16

    captured_hints: list[list[tuple[int, int]] | None] = []
    captured_rules: list[object] = []

    def _fake_lz4_candidates(
        payload: bytes,
        marker_offset: int,
        marker_value: bytes,
        framing_hints: list[tuple[int, int]] | None = None,
        *,
        require_origin_payload: bool = True,
        **kwargs: object,
    ) -> tuple[OpjuOriginStorageCandidate, ...]:
        del payload, marker_offset, marker_value, require_origin_payload
        captured_hints.append(framing_hints)
        captured_rules.append(kwargs.get("framing_rule"))
        return ()

    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_framing_for_markers",
        lambda *args, **kwargs: [
            (marker, -5, 4),
            (marker, 11, 14),
        ],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_lz4_candidates",
        _fake_lz4_candidates,
    )

    candidates = opju_regions.iter_origin_storage_candidates(data)

    assert candidates == []
    assert captured_hints == [[(-5, 4)], [(11, 14)]]
    assert captured_rules == ["canonical_family_marker", "inferred_family_marker"]


def test_iter_origin_storage_candidates_stops_after_first_successful_framing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = b"\x72\x11\x11\x11"
    base = b"CPYUA 4.3318 0\x00"
    marker_start = len(base) + 5
    data = base + b"\x00" * (marker_start - len(base)) + marker + b"\x00" * 16
    calls: list[list[tuple[int, int]] | None] = []
    decoded = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=marker_start - 1,
        source_end=marker_start + 8,
        payload_start=0,
        payload_end=4,
        payload=b"data",
    )

    def _fake_lz4_candidates(
        payload: bytes,
        marker_offset: int,
        marker_value: bytes,
        framing_hints: list[tuple[int, int]] | None = None,
        **kwargs: object,
    ) -> tuple[OpjuOriginStorageCandidate, ...]:
        del payload, marker_offset, marker_value, kwargs
        calls.append(framing_hints)
        return (decoded,)

    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_framing_for_markers",
        lambda *args, **kwargs: [(marker, -5, 4), (marker, 11, 14)],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_lz4_candidates",
        _fake_lz4_candidates,
    )

    candidates = opju_regions.iter_origin_storage_candidates(
        data,
        include_family_binary=True,
    )

    assert candidates == [decoded]
    assert calls == [[(-5, 4)]]


def test_iter_origin_storage_candidates_skips_family_marker_candidates_when_decoded_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = b"CPYUA 4.3318 0\x00"
    origin_start = len(base) + 20
    origin_payload = b'<OriginStorage Label="Primary"><Notes>primary</Notes></OriginStorage>'
    family_marker = b"\x77\x11\x11\x11"
    family_start = len(base) + 4
    family_payload = b'<OriginStorage Label="Family"><Notes>ignored</Notes></OriginStorage>'
    padding = b"\x00" * (family_start - len(base))
    data = base + padding + family_marker + b"\x00" * 80

    origin_raw_end = origin_start + len(origin_payload)
    decoded_origin = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=origin_start + 2,
        source_end=origin_start + 2 + len(b'<OriginStorage Label="Primary"><Notes>primary</Notes></OriginStorage>'),
        payload_start=0,
        payload_end=len(origin_payload),
        payload=origin_payload,
    )
    family_candidate = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=family_start + 2,
        source_end=family_start + 2 + len(family_payload),
        payload_start=0,
        payload_end=len(family_payload),
        payload=family_payload,
    )

    monkeypatch.setattr(
        opju_regions,
        "_iter_origin_storage_raw_regions",
        lambda _payload: [(origin_start, origin_raw_end)],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_lz4_candidates",
        lambda _payload, raw_offset: (decoded_origin,) if raw_offset == origin_start else (),
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_lz4_candidates",
        lambda *args, **kwargs: (family_candidate,),
    )

    candidates = opju_regions.iter_origin_storage_candidates(data)

    assert all(candidate.source_start != family_candidate.source_start for candidate in candidates)
    assert any(candidate.source_start == decoded_origin.source_start for candidate in candidates)


def test_iter_origin_storage_candidates_includes_family_marker_candidates_when_forced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = b"CPYUA 4.3318 0\x00"
    origin_start = len(base) + 20
    origin_payload = b'<OriginStorage Label="Primary"><Notes>primary</Notes></OriginStorage>'
    family_marker = b"\x77\x11\x11\x11"
    family_marker_pos = len(base) + 4

    data = base + b"\x00" * (family_marker_pos - len(base)) + family_marker + b"\x00" * 80

    origin_raw_end = origin_start + len(origin_payload)
    decoded_origin = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=origin_start + 2,
        source_end=origin_start + 2 + len(b'<OriginStorage Label="Primary"><Notes>primary</Notes></OriginStorage>'),
        payload_start=0,
        payload_end=len(origin_payload),
        payload=origin_payload,
    )
    family_candidate = OpjuOriginStorageCandidate(
        source_kind="decoded",
        source_start=family_marker_pos + 2,
        source_end=family_marker_pos + 2 + len(b"binary"),
        payload_start=0,
        payload_end=6,
        payload=b"binary",
    )

    monkeypatch.setattr(
        opju_regions,
        "_iter_origin_storage_raw_regions",
        lambda _payload: [(origin_start, origin_raw_end)],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_lz4_candidates",
        lambda _payload, raw_offset: (decoded_origin,) if raw_offset == origin_start else (),
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_framing_for_markers",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        opju_regions,
        "_iter_opju_family_lz4_candidates",
        lambda *args, **kwargs: (family_candidate,),
    )

    candidates = opju_regions.iter_origin_storage_candidates(
        data,
        include_family_binary=True,
    )

    assert any(candidate.source_start == family_candidate.source_start for candidate in candidates)
    assert any(candidate.payload == family_candidate.payload for candidate in candidates)


def test_iter_opju_family_lz4_candidates_uses_framing_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = b"\x77\x11\x11\x11"
    marker_start = 20
    header_delta = -6
    stream_offset = 4
    declared_size = 12
    block_start = marker_start + header_delta + stream_offset
    data = b"\x00" * marker_start + marker + b"\x00" * 20
    data = bytearray(data)
    data[marker_start + header_delta : marker_start + header_delta + 4] = declared_size.to_bytes(4, "little")
    data = bytes(data)
    expected_payload = b"<OriginStorage><Notes>hint</Notes></OriginStorage>"

    def _fake_lz4(src: bytes, size: int):
        assert size == declared_size
        assert src.startswith(data[block_start : block_start + 1])
        return expected_payload, 6

    monkeypatch.setattr(opju_regions, "lz4_block_decompress", _fake_lz4)

    candidates = opju_regions._iter_opju_family_lz4_candidates(
        data,
        marker_start,
        marker,
        header_delta_hint=header_delta,
        stream_offset_hint=stream_offset,
        require_origin_payload=True,
    )

    assert len(candidates) == 1
    assert candidates[0].source_start == block_start
    assert candidates[0].payload == expected_payload
    assert candidates[0].decompressed_size == declared_size
    assert candidates[0].compression == "lz4-block"
    assert candidates[0].family_marker == marker
    assert candidates[0].marker_offset == marker_start
    assert candidates[0].header_offset == marker_start + header_delta
    assert candidates[0].stream_offset == stream_offset
    assert candidates[0].framing_rule == "family_marker_scan"


def test_parse_opju_column_tables_decodes_binary_payloads() -> None:
    data = SYNTHETIC_BINARY_FIXTURE.read_bytes()

    tables = parse_opju_column_tables(data)
    assert [table.name for table in tables] == ["Book3_B", "Book3_C"]
    assert tables[0].label == "August"
    assert tables[1].label == "November"
    assert tables[0].rows == [
        ["18.3"],
        ["13.3"],
        ["16.5"],
        ["12.6"],
        ["9.5"],
        ["13.6"],
        ["8.1"],
        ["8.9"],
        ["10.0"],
        ["8.3"],
        ["7.9"],
        ["8.1"],
        ["13.4"],
    ]
    assert tables[1].rows == [
        ["12.7"],
        ["11.1"],
        ["15.3"],
        ["12.7"],
        ["10.5"],
        ["15.6"],
        ["11.2"],
        ["14.2"],
        ["16.3"],
        ["15.5"],
        ["19.9"],
        ["20.4"],
        ["36.8"],
    ]


def test_parse_opju_column_tables_limits_binary_rows_to_max_rows() -> None:
    payload = (
        (10).to_bytes(4, "little")
        + (4).to_bytes(4, "little")
        + struct.pack("<ffffffffff", *[float(i) for i in range(1, 11)])
    )
    data = b"CPYUA 4.3318 10\x00" + (b'<ColumnTable Name="Book3_B" Label="August">' + payload + b"</ColumnTable>")

    tables = parse_opju_column_tables(data, max_rows=4)
    assert len(tables) == 1
    assert tables[0].rows == [["1.0"], ["2.0"], ["3.0"], ["4.0"]]


def test_parse_opju_column_tables_rejects_partial_binary_payload_rows() -> None:
    payload = (10).to_bytes(4, "little") + (8).to_bytes(4, "little") + b"\x00" * 24
    data = b"CPYUA 4.3318 10\x00" + (b'<ColumnTable Name="Book3_B" Label="August">' + payload + b"</ColumnTable>")

    tables = parse_opju_column_tables(data)
    assert tables == []
