from __future__ import annotations

from deopjufy_view.project_tree import build_project_tree, catalog_leaves, preferred_leaf, sibling_sheets


def _payload() -> dict[str, object]:
    return {
        "items": [
            {
                "id": "sheet-10-2",
                "kind": "worksheet",
                "object_kind": "worksheet",
                "name": "Book10/Sheet2",
                "source_object_path": "Book10/Sheet2",
            },
            {
                "id": "sheet-2-10",
                "kind": "worksheet",
                "object_kind": "worksheet",
                "name": "Book2/Sheet10",
                "source_object_path": "Book2/Sheet10",
            },
            {
                "id": "sheet-2-2",
                "kind": "worksheet",
                "object_kind": "worksheet",
                "name": "Book2/Sheet2",
                "source_object_path": "Book2/Sheet2",
            },
            {
                "id": "image-10",
                "kind": "png",
                "name": "png@10",
                "source_object_path": "embedded/png/10",
                "heuristic": True,
            },
            {
                "id": "raw-root",
                "kind": "raw_dump",
                "object_kind": "unknown_high_entropy",
                "name": "unknown gap",
                "source_object_path": "unknown_gap:0:20",
            },
            {
                "id": "opaque-note-boundary",
                "kind": "origin_object",
                "object_kind": "opju_note_payload",
                "name": "synthetic_boundary_note",
                "source_object_path": "origin_storage/synthetic_boundary_note",
                "discovery_type": "opj_boundary",
                "heuristic": False,
            },
        ]
    }


def test_catalog_tree_groups_exact_paths_and_sorts_numbers_naturally() -> None:
    leaves = catalog_leaves(_payload(), show_recovery_evidence=True)
    tree = build_project_tree(leaves)

    assert [branch.label for branch in tree.branches] == ["Book2", "Book10", "embedded", "origin_storage"]
    assert [leaf.label for leaf in tree.branches[0].leaves] == ["Sheet2", "Sheet10"]
    assert [leaf.label for leaf in tree.leaves] == ["unknown_gap:0:20"]
    assert tree.leaves[0].kind == "raw_dump"
    preferred = preferred_leaf(leaves)
    assert preferred is not None
    assert preferred.item_id == "sheet-2-2"


def test_catalog_tree_can_unwrap_single_child_groups_without_losing_path() -> None:
    tree = build_project_tree(
        catalog_leaves(_payload(), show_recovery_evidence=True),
        unwrap_single_child_groups=True,
    )
    embedded = next(branch for branch in tree.branches if branch.label.startswith("embedded"))

    assert embedded.label == "embedded / png"
    assert embedded.path == ("embedded", "png")
    assert [leaf.item_id for leaf in embedded.leaves] == ["image-10"]


def test_catalog_tree_hides_heuristic_and_unknown_evidence_by_default() -> None:
    leaves = catalog_leaves(_payload())

    assert [leaf.item_id for leaf in leaves] == ["sheet-10-2", "sheet-2-10", "sheet-2-2"]
    assert all(not leaf.hidden_by_default for leaf in leaves)


def test_catalog_tree_shows_boundary_note_payload_only_as_recovery_evidence() -> None:
    hidden = catalog_leaves(_payload())
    complete = catalog_leaves(_payload(), show_recovery_evidence=True)

    assert "opaque-note-boundary" not in {leaf.item_id for leaf in hidden}
    boundary = next(leaf for leaf in complete if leaf.item_id == "opaque-note-boundary")
    assert boundary.hidden_by_default


def test_sibling_sheets_build_one_naturally_ordered_workbook_tab_set() -> None:
    leaves = catalog_leaves(_payload())
    selected = next(leaf for leaf in leaves if leaf.item_id == "sheet-2-10")

    siblings = sibling_sheets(leaves, selected)

    assert [leaf.item_id for leaf in siblings] == ["sheet-2-2", "sheet-2-10"]
