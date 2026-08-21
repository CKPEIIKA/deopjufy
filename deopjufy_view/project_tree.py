"""Path-derived project-tree presentation for catalog clients."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUMBER = re.compile(r"(\d+)")
_TABULAR_KINDS = frozenset({"excel", "matrix", "worksheet"})
_MEDIA_KINDS = frozenset({"bmp", "gif", "graph", "image", "jpeg", "layer", "png", "svg"})
_TEXT_KINDS = frozenset({"function", "note", "opju_report", "origin_storage_report"})
_RECOVERY_ONLY_KINDS = frozenset({"meta", "opju_note_payload", "opju_raw_payload"})
_RECOVERY_ONLY_DISCOVERY_TYPES = frozenset({"opj_boundary", "unknown_gap"})


@dataclass(frozen=True)
class ProjectLeaf:
    """One materializable catalog item placed under exact source-path groups."""

    item_id: str
    label: str
    kind: str
    folders: tuple[str, ...]
    search_text: str
    hidden_by_default: bool


@dataclass(frozen=True)
class ProjectBranch:
    """One display branch derived from source-path components."""

    label: str
    path: tuple[str, ...]
    branches: tuple[ProjectBranch, ...]
    leaves: tuple[ProjectLeaf, ...]
    kinds: frozenset[str]


@dataclass(frozen=True)
class ProjectTree:
    """The grouped branches and root-level leaves for one document."""

    branches: tuple[ProjectBranch, ...]
    leaves: tuple[ProjectLeaf, ...]


@dataclass
class _MutableBranch:
    label: str
    path: tuple[str, ...]
    branches: dict[str, _MutableBranch] = field(default_factory=dict)
    leaves: list[ProjectLeaf] = field(default_factory=list)


def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in _NUMBER.split(value) if part)


def _semantic_kind(item: dict[str, Any]) -> str:
    object_kind = item.get("object_kind")
    kind = item.get("kind")
    if isinstance(object_kind, str) and object_kind and object_kind not in {"unknown", "unknown_high_entropy"}:
        return object_kind
    return kind if isinstance(kind, str) and kind else "unknown"


def _source_parts(item: dict[str, Any]) -> tuple[str, ...]:
    source_path = item.get("source_object_path")
    name = item.get("name")
    candidate = source_path if isinstance(source_path, str) and source_path else name
    if not isinstance(candidate, str):
        return ()
    return tuple(part for part in candidate.strip("/").split("/") if part and part != ".")


def _hidden_by_default(item: dict[str, Any], kind: str) -> bool:
    return (
        bool(item.get("heuristic", False))
        or kind in {"raw_dump", "unknown"}
        or kind.startswith("unknown_")
        or kind in _RECOVERY_ONLY_KINDS
        or item.get("discovery_type") in _RECOVERY_ONLY_DISCOVERY_TYPES
    )


def catalog_leaves(
    payload: dict[str, Any],
    *,
    show_recovery_evidence: bool = False,
) -> tuple[ProjectLeaf, ...]:
    """Convert a catalog into user-facing leaves, hiding recovery evidence by default."""
    items = payload.get("items")
    rows = items if isinstance(items, list) else []
    leaves: list[ProjectLeaf] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = row.get("id")
        if not isinstance(item_id, str) or not item_id:
            continue
        parts = _source_parts(row)
        name = row.get("name")
        fallback = name if isinstance(name, str) and name else item_id
        label = parts[-1] if parts else fallback
        kind = _semantic_kind(row)
        search_fields = (fallback, "/".join(parts), kind)
        leaf = ProjectLeaf(
            item_id=item_id,
            label=label,
            kind=kind,
            folders=parts[:-1],
            search_text=" ".join(field for field in search_fields if field),
            hidden_by_default=_hidden_by_default(row, kind),
        )
        if show_recovery_evidence or not leaf.hidden_by_default:
            leaves.append(leaf)
    return tuple(leaves)


def _freeze_branch(branch: _MutableBranch, unwrap_single_child_groups: bool) -> ProjectBranch:
    label = branch.label
    path = branch.path
    current = branch
    while unwrap_single_child_groups and not current.leaves and len(current.branches) == 1:
        current = next(iter(current.branches.values()))
        label = f"{label} / {current.label}"
        path = current.path

    children = tuple(
        _freeze_branch(child, unwrap_single_child_groups)
        for child in sorted(current.branches.values(), key=lambda value: _natural_key(value.label))
    )
    leaves = tuple(sorted(current.leaves, key=lambda value: _natural_key(value.label)))
    kinds = frozenset({leaf.kind for leaf in leaves}.union(*(set(child.kinds) for child in children)))
    return ProjectBranch(label=label, path=path, branches=children, leaves=leaves, kinds=kinds)


def build_project_tree(
    leaves: tuple[ProjectLeaf, ...],
    *,
    unwrap_single_child_groups: bool = False,
) -> ProjectTree:
    """Group leaves by exact source-path components without inventing type buckets."""
    root = _MutableBranch(label="", path=())
    for leaf in leaves:
        branch = root
        for component in leaf.folders:
            path = (*branch.path, component)
            branch = branch.branches.setdefault(component, _MutableBranch(label=component, path=path))
        branch.leaves.append(leaf)
    branches = tuple(
        _freeze_branch(branch, unwrap_single_child_groups)
        for branch in sorted(root.branches.values(), key=lambda value: _natural_key(value.label))
    )
    root_leaves = tuple(sorted(root.leaves, key=lambda value: _natural_key(value.label)))
    return ProjectTree(branches=branches, leaves=root_leaves)


def preferred_leaf(leaves: tuple[ProjectLeaf, ...]) -> ProjectLeaf | None:
    """Choose a useful initial preview, preferring tabular content over evidence dumps."""

    def rank(leaf: ProjectLeaf) -> tuple[int, tuple[tuple[int, int | str], ...]]:
        if leaf.kind in _TABULAR_KINDS:
            priority = 0
        elif leaf.kind in _MEDIA_KINDS or leaf.kind == "project_page":
            priority = 1
        elif leaf.kind in _TEXT_KINDS:
            priority = 2
        elif leaf.kind == "raw_dump":
            priority = 9
        else:
            priority = 5
        return priority, _natural_key("/".join((*leaf.folders, leaf.label)))

    return min(leaves, key=rank, default=None)


def sibling_sheets(leaves: tuple[ProjectLeaf, ...], selected: ProjectLeaf) -> tuple[ProjectLeaf, ...]:
    """Return naturally ordered tabular leaves sharing one exact workbook path."""
    if selected.kind not in _TABULAR_KINDS or not selected.folders:
        return ()
    siblings = [leaf for leaf in leaves if leaf.kind in _TABULAR_KINDS and leaf.folders == selected.folders]
    return tuple(sorted(siblings, key=lambda leaf: _natural_key(leaf.label)))


__all__ = [
    "ProjectBranch",
    "ProjectLeaf",
    "ProjectTree",
    "build_project_tree",
    "catalog_leaves",
    "preferred_leaf",
    "sibling_sheets",
]
