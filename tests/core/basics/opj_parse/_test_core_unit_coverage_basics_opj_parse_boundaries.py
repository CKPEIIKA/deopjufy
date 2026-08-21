from deopjufier.opj import (
    parse_opj_matrix_metadata,
    parse_opj_note_metadata,
    parse_opj_project_nodes,
)
from tests.core.basics.opj_parse._test_core_unit_coverage_basics_opj_parse_common import *  # noqa: F403


def test_parse_opj_parameters_parses_expected_records() -> None:
    data = (
        b"CPYA 4.2673 552#\n"
        + b"ERR\n"
        + struct.pack("<d", 1.25)
        + b"\n"
        + b"SYRNG_C_DATA1\n"
        + struct.pack("<d", 0.1246)
        + b"\n"
        + b"\x00\n"
    )

    parameters = parse_opj_parameters(data)
    assert len(parameters) == 2
    assert parameters[0].name == "ERR"
    assert parameters[0].value == pytest.approx(1.25)
    assert parameters[1].name == "SYRNG_C_DATA1"
    assert parameters[1].value == pytest.approx(0.1246)


def test_parse_opj_boundaries_infers_tree_paths_from_references(monkeypatch: pytest.MonkeyPatch) -> None:
    section = OpjDataSection(
        offset=10,
        length=20,
        name="Sheet1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args, **_kwargs: [section],
    )
    monkeypatch.setattr("deopjufier.opj.parse_opj_note_sections", lambda *_args, **_kwargs: [])

    data = b"CPYA 4.2673 552#\nprefix [Book4]Sheet1 suffix"
    boundaries = parse_opj_boundaries(data)
    assert [entry.source_object_path for entry in boundaries] == ["Book4/Sheet1"]


def test_parse_opj_boundaries_infers_matrix_reference_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=20,
        length=10,
        name="MBook1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    data = b"CPYA 4.2673 552#\n... [MBook1]MSheet1 ... [MBook1]MSheet2"
    monkeypatch.setattr(
        "deopjufier.opj.boundaries._iter_opj_data_sections",
        lambda *_args, **_kwargs: [section],
    )

    boundaries = parse_opj_boundaries(data)

    matrix_refs = [
        boundary for boundary in boundaries if boundary.kind == "matrix" and boundary.name.startswith("MSheet")
    ]
    assert len(matrix_refs) >= 1
    assert matrix_refs[0].source_object_path == "MBook1/MSheet1"
    assert matrix_refs[0].parser_rule == "opj_tree_reference"


def test_parse_opj_tree_nodes_extracts_folder_records() -> None:
    fixture = REPO_ROOT / "refs/github/Ropj/inst/tree.opj"
    if not fixture.exists():
        pytest.skip("tree fixture missing from checkout")

    ownership_links = parse_opj_tree_ownership_links(fixture.read_bytes())
    assert OpjTreeOwnership("NoInfo", "User_Tree", 0.92) in ownership_links

    nodes = parse_opj_tree_nodes(fixture.read_bytes())
    assert nodes
    paths = [node.path for node in nodes]
    assert "tree/User_Tree" in paths
    assert any(node.name == "NoInfo" for node in nodes)
    root = next(node for node in nodes if node.path == "tree/User_Tree")
    assert root.node_id == 268435456
    assert root.parent_node_id is None
    assert root.start_offset < root.end_offset


def test_parse_binary_opj_project_tree_preserves_nested_paths_and_object_ids() -> None:
    fixture = REPO_ROOT / "refs/github/Ropj/inst/tree.opj"
    if not fixture.exists():
        pytest.skip("tree fixture missing from checkout")

    nodes = parse_opj_project_nodes(fixture.read_bytes())
    folders = [node for node in nodes if node.kind == "folder"]
    leaves = [node for node in nodes if node.kind != "folder"]

    assert [node.name for node in folders] == [
        "tree",
        "1 bla bla bla text with spaces",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]
    graph = next(node for node in leaves if node.name == "Graph1")
    assert graph.object_id == 0
    assert graph.path == "tree/1 bla bla bla text with spaces/Graph1"
    deepest_note = next(node for node in leaves if node.name == "7")
    assert deepest_note.kind == "note"
    assert deepest_note.path == "tree/1 bla bla bla text with spaces/2/3/4/5/6/7"


def test_parse_opj_note_metadata_keeps_results_log_and_exact_text_ranges() -> None:
    fixture = REPO_ROOT / "refs/openopj/support/test.opj"
    if not fixture.exists():
        pytest.skip("OpenOPJ fixture missing from checkout")

    data = fixture.read_bytes()
    notes = parse_opj_note_metadata(data)
    assert len(notes) == 2
    assert any(note.results_log for note in notes)
    for note in notes:
        assert note.start_offset < note.end_offset
        assert 0 <= note.text_offset <= note.text_offset + note.text_size <= len(data)


def test_parse_real_opj_column_headers_recovers_designations_formats_and_formulas() -> None:
    fixture = REPO_ROOT / "refs/github/Ropj/inst/test.opj"
    if not fixture.exists():
        pytest.skip("Ropj fixture missing from checkout")

    metadata = parse_opj_worksheet_metadata(fixture.read_bytes(), worksheet_names={"Book2"})["Book2"]
    assert [column.name for column in metadata.columns] == ["A", "B", "C"]
    assert [column.designation for column in metadata.columns] == ["X", "Y", "Y"]
    assert [column.value_type for column in metadata.columns] == ["text_numeric"] * 3
    assert [column.formula for column in metadata.columns] == ["i", "sin(i)*cos(i)", None]
    assert metadata.columns[2].comment == "long name\r\nunits\r\ncomments"


def test_parse_real_opj_matrix_layer_recovers_true_shape_and_view() -> None:
    fixture = REPO_ROOT / "refs/openopj/support/test.opj"
    if not fixture.exists():
        pytest.skip("OpenOPJ fixture missing from checkout")

    metadata = parse_opj_matrix_metadata(fixture.read_bytes(), matrix_names={"TestM"})["TestM"]
    assert metadata.shape == (32, 32)
    assert metadata.active_sheet == 0
    assert metadata.header_view == "column_row"
    assert len(metadata.sheets) == 1
    assert metadata.sheets[0].shape == (32, 32)
    assert metadata.sheets[0].view == "data"


def test_parse_opj_tree_matrix_ownership_evidence_is_parser_stable() -> None:
    if not TREE_MATRIX_EVIDENCE_FIXTURE.exists():
        pytest.skip("Fixture missing: tests/fixtures/opj-tree-matrix-ownership-evidence.json")

    evidence = json.loads(TREE_MATRIX_EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    fixture = REPO_ROOT / evidence["fixture"]
    if not fixture.exists():
        pytest.skip(f"Fixture missing: {fixture}")

    sample_data = fixture.read_bytes()
    matrix_boundaries = [
        {
            "kind": boundary.kind,
            "name": boundary.name,
            "source_object_path": boundary.source_object_path,
            "confidence": boundary.confidence,
        }
        for boundary in parse_opj_boundaries(sample_data)
        if boundary.kind == "matrix"
    ]
    assert matrix_boundaries == evidence["matrix_boundaries"]

    tree_links = [
        {
            "parent_name": link.parent_name,
            "child_name": link.child_name,
            "confidence": link.confidence,
        }
        for link in parse_opj_tree_ownership_links(sample_data)
    ]
    assert tree_links == evidence["tree_ownership_links"]

    discovered = discover_origin_objects(fixture, include_redundant_tokens=True)
    discovered_matrix = [
        {
            "name": obj.name,
            "source_object_path": obj.source_object_path,
            "parser_confirmed": obj.parser_confirmed,
        }
        for obj in discovered
        if obj.object_kind == "matrix" and obj.parser_confirmed
    ]
    assert discovered_matrix == evidence["discovered_matrix_objects"]


def test_parse_opj_tree_matrix_rows_are_not_parser_recoverable_from_data_sections() -> None:
    fixture = REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "tree.opj"
    if not fixture.exists():
        pytest.skip("tree fixture missing from checkout")

    sample_data = fixture.read_bytes()
    boundary_sections = iter_opj_data_sections(sample_data, max_sections=None)
    matrix_like_sections = [
        section
        for section in boundary_sections
        if section.name.lower().startswith(("mbook", "msheet", "matrix", "pdm"))
    ]
    assert not matrix_like_sections, f"Unexpected matrix-like OPJ sections in tree.opj: {matrix_like_sections}"

    references = [
        reference
        for reference in parse_opj_tree_references(sample_data)
        if reference.parent_name == "MBook1" and reference.child_name == "MSheet1"
    ]
    assert references, "Expected deterministic tree reference(s) for [MBook1]MSheet1"

    for reference in references:
        assert reference.end - reference.start > 0
        assert sample_data[reference.start : reference.end] == b"[MBook1]MSheet1"
        context = sample_data[max(0, reference.start - 64) : min(len(sample_data), reference.end + 192)]
        assert b"<orng" in context
        assert b"repeat: Repeat" in context
        assert not any(
            section.offset <= reference.start < section.offset + section.length
            and section.offset <= reference.end < section.offset + section.length
            for section in boundary_sections
        )

    matrix_rows, matrix_dims, _ = recover_matrix_metadata_from_opj_sections(
        sample_data,
        {"MSheet1"},
    )
    assert matrix_rows == {}
    assert matrix_dims == {}


def test_parse_opj_tree_matrix_reference_in_test_opj_has_deterministic_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=20,
        length=10,
        name="MBook1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args, **_kwargs: [section],
    )
    monkeypatch.setattr(
        "deopjufier.opj.parse_opj_note_sections",
        lambda *_args, **_kwargs: [],
    )

    fixture = REPO_ROOT / "refs" / "github" / "Ropj" / "inst" / "test.opj"
    if not fixture.exists():
        pytest.skip("test fixture missing from checkout")

    sample_data = fixture.read_bytes()
    matrix_boundaries = [boundary for boundary in parse_opj_boundaries(sample_data) if boundary.kind == "matrix"]
    matrix_reference_boundaries = [
        boundary for boundary in matrix_boundaries if boundary.parser_rule == "opj_tree_reference"
    ]
    assert matrix_reference_boundaries, "Expected deterministic matrix tree-reference boundaries"
    assert any(
        boundary.name == "MSheet1" and boundary.source_object_path.startswith("MBook1/")
        for boundary in matrix_reference_boundaries
    )


def test_parse_opj_tree_ownership_links_parses_bracket_references() -> None:
    data = b"CPYA 4.2673 552#\nprefix [Book4]Sheet1 [Graph1]Curve suffix"
    links = parse_opj_tree_ownership_links(data)
    assert links == [
        OpjTreeOwnership(child_name="Sheet1", parent_name="Book4"),
        OpjTreeOwnership(child_name="Curve", parent_name="Graph1"),
    ]


def test_parse_opj_tree_ownership_links_prefers_tree_blocks_when_present() -> None:
    tree_xml = (
        b"<Tree NodeID='268435456' Label='User_Tree'>"
        b"<Book Label='Book4' NodeID='10'>"
        b"<Sheet Label='Sheet1' NodeID='11'/>"
        b"</Book>"
        b"</Tree>"
    )
    data = (
        b"CPYA 4.2673 552#\n" + b"@${[0|4|TREE|%d|%d]}" % (len(tree_xml), len(tree_xml)) + tree_xml + b" [Graph1]Curve"
    )

    links = parse_opj_tree_ownership_links(data)
    assert OpjTreeOwnership("Book4", "User_Tree", 0.92) in links
    assert OpjTreeOwnership("Sheet1", "Book4", 0.92) in links
    assert OpjTreeOwnership("Curve", "Graph1", 0.92) not in links


def test_parse_opj_boundaries_uses_parsed_tree_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    section = OpjDataSection(
        offset=10,
        length=20,
        name="Sheet1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args, **_kwargs: [section],
    )
    monkeypatch.setattr("deopjufier.opj.parse_opj_note_sections", lambda *_args, **_kwargs: [])

    tree_xml = (
        b"<Tree NodeID='268435456' Label='User_Tree'>"
        b"<Book Label='Book4' NodeID='10'>"
        b"<Node Label='Sheet1' NodeID='11'/>"
        b"</Book>"
        b"</Tree>"
    )
    data = b"CPYA 4.2673 552#\n" + b"@${[0|4|TREE|%d|%d]}" % (len(tree_xml), len(tree_xml)) + tree_xml

    boundaries = parse_opj_boundaries(data)
    assert [entry.source_object_path for entry in boundaries] == ["Book4/Sheet1"]


def test_parse_opj_boundaries_preserves_overlapping_spans_and_exact_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    section_a = OpjDataSection(
        offset=16,
        length=60,
        name="Layer1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )
    section_b = OpjDataSection(
        offset=32,
        length=40,
        name="Layer1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )
    section_c = OpjDataSection(
        offset=16,
        length=60,
        name="Layer1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args, **_kwargs: [section_a, section_b, section_c],
    )
    monkeypatch.setattr(
        "deopjufier.opj.parse_opj_note_sections",
        lambda *_args, **_kwargs: [],
    )

    data = b"CPYA 4.2673 552#\n"
    boundaries = parse_opj_boundaries(data)

    assert len(boundaries) == 2
    assert boundaries[0].start_offset == 16
    assert boundaries[0].end_offset == 76
    assert boundaries[0].name == "Layer1"
    assert boundaries[0].length == 60
    assert boundaries[1].start_offset == 32
    assert boundaries[1].end_offset == 72
    assert boundaries[1].name == "Layer1"
    assert boundaries[1].length == 40


def test_parse_opj_boundaries_includes_window_payloads() -> None:
    header = _build_opj_walk_window("Function1", label="Function label")
    data = b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + header

    boundaries = parse_opj_boundaries(data)
    assert len(boundaries) == 1
    assert boundaries[0].kind == "function"
    assert boundaries[0].name == "Function1"
    assert boundaries[0].source_object_path == "Function/Function1"
    assert boundaries[0].parser_rule == "opj_window"


def test_parse_opj_boundaries_prefers_window_label_for_source_path_when_title_mode_is_label() -> None:
    header = _build_opj_walk_window_with_title_mode("Function1", label="GraphLabel", title_mode=0x01)
    data = b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + header

    boundaries = parse_opj_boundaries(data)
    assert len(boundaries) == 1
    assert boundaries[0].label == "GraphLabel"
    assert boundaries[0].name == "Function1"
    assert boundaries[0].source_object_path == "Graph/GraphLabel"


def test_parse_opj_boundaries_classifies_fit_column_as_worksheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=10,
        length=20,
        name="Data1_Fit",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    def fake_sections(_data: bytes, max_sections: int | None = None):
        return [section]

    monkeypatch.setattr("deopjufier.opj.iter_opj_data_sections", fake_sections)
    monkeypatch.setattr(
        "deopjufier.opj.parse_opj_note_sections",
        lambda *_args, **_kwargs: [],
    )

    data = b"CPYA 4.2673 552#\n"
    boundaries = parse_opj_boundaries(data)

    assert len(boundaries) == 1
    assert boundaries[0].kind == "worksheet"
    assert boundaries[0].name == "Data1_Fit"
    assert boundaries[0].source_object_path == "Data1/Data1_Fit"


@pytest.mark.parametrize(
    "name",
    [
        "Data1_Mt",
        "Data1_XMt",
        "Data1_Xt",
    ],
)
def test_parse_opj_boundaries_keeps_matrix_like_column_labels_in_worksheet(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    section = OpjDataSection(
        offset=10,
        length=20,
        name=name,
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    def fake_sections(_data: bytes, max_sections: int | None = None):
        return [section]

    monkeypatch.setattr("deopjufier.opj.iter_opj_data_sections", fake_sections)
    monkeypatch.setattr(
        "deopjufier.opj.parse_opj_note_sections",
        lambda *_args, **_kwargs: [],
    )

    data = b"CPYA 4.2673 552#\n"
    boundaries = parse_opj_boundaries(data)

    assert len(boundaries) == 1
    assert boundaries[0].kind == "worksheet"
    assert boundaries[0].name == name


def test_parse_opj_boundaries_classifies_matrix_signature_as_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=10,
        length=20,
        name="TestM",
        data_type=0x6001,
        data_type2=1,
        total_rows=1024,
        first_row=0,
        last_row=1024,
        value_size=8,
        data_type_u=3,
        data_type3=0x50CA,
        values=[],
    )

    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args, **_kwargs: [section],
    )
    monkeypatch.setattr(
        "deopjufier.opj.parse_opj_note_sections",
        lambda *_args, **_kwargs: [],
    )

    boundaries = parse_opj_boundaries(b"CPYA 4.2673 552#\n")

    assert len(boundaries) == 1
    assert boundaries[0].kind == "matrix"
    assert boundaries[0].name == "TestM"


def test_parse_opj_boundaries_includes_layer_graph_names() -> None:
    payload = _build_opj_walk_window("Layer1")
    data = b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + payload

    boundaries = parse_opj_boundaries(data)
    assert len(boundaries) == 1
    assert boundaries[0].kind == "layer"
    assert boundaries[0].name == "Layer1"
    assert boundaries[0].parser_rule == "opj_window"


def test_parse_opj_boundaries_uses_context_for_matrix_window_kind() -> None:
    section = OpjDataSection(
        offset=16,
        length=20,
        name="PdMSheet1",
        data_type=1,
        data_type2=0,
        total_rows=1,
        first_row=0,
        last_row=0,
        value_size=0,
        data_type_u=0,
        data_type3=0,
        values=[],
    )

    payload = b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + _build_opj_walk_window("Sheet1")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "deopjufier.opj.iter_opj_data_sections",
            lambda *_args, **_kwargs: [section],
        )
        mp.setattr(
            "deopjufier.opj.parse_opj_note_sections",
            lambda *_args, **_kwargs: [],
        )

        boundaries = parse_opj_boundaries(payload)

    window_boundaries = [boundary for boundary in boundaries if boundary.parser_rule == "opj_window"]
    assert len(window_boundaries) == 1
    assert window_boundaries[0].kind == "matrix"
    assert window_boundaries[0].name == "Sheet1"


def test_parse_opj_boundaries_includes_excel_payloads() -> None:
    payload = _build_opj_walk_window("Book1.xlsx")
    data = b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + payload

    boundaries = parse_opj_boundaries(data)
    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert boundary.kind == "excel"
    assert boundary.name == "Book1.xlsx"
    assert boundary.source_object_path == "Book/Book1.xlsx"
    assert boundary.parser_rule == "opj_window"


def test_parse_opj_boundaries_includes_excel_attachment_parent_when_available() -> None:
    payload = _build_opj_walk_window("Excel\\Book1.xlsx")
    data = b"CPYA 4.2673 552#\n" + _build_opj_global_header() + _u32(0) + b"\n" + payload

    boundaries = parse_opj_boundaries(data)
    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert boundary.kind == "meta"
    assert boundary.name == "Excel\\Book1.xlsx"
    assert boundary.source_object_path == "meta/Excel\\Book1.xlsx"


def test_parse_opj_worksheet_metadata_recovers_formula_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = OpjDataSection(
        offset=0,
        length=10,
        name="Book1_A",
        data_type=0,
        data_type2=0,
        total_rows=10,
        first_row=1,
        last_row=3,
        value_size=8,
        data_type_u=0,
        data_type3=0,
        values=[1.0, 2.0],
    )
    monkeypatch.setattr(
        "deopjufier.opj.iter_opj_data_sections",
        lambda *_args: [section],
    )
    data = b"CPYA 4.2673 552#\n"
    metadata_by_name = parse_opj_worksheet_metadata(data, worksheet_names={"Book1_A"})
    assert "Book1_A" in metadata_by_name
    assert metadata_by_name["Book1_A"].formula_rows == (1, 3)
    assert metadata_by_name["Book1_A"].long_name == "Book1_A"
