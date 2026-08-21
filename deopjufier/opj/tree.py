"""OPJ tree-block parsing helpers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .records import is_opj_signature

_OPJ_TREE_REFERENCE_PATTERN = re.compile(rb"\[([A-Za-z][A-Za-z0-9_]+)\]([A-Za-z][A-Za-z0-9_]*)")
_OPJ_TREE_BLOCK_PATTERN = re.compile(rb"@\$\{\[0\|4\|TREE\|(\d+)\|\d+\]\}")


@dataclass(frozen=True)
class OpjTreeReference:
    parent_name: str
    child_name: str
    start: int
    end: int


@dataclass(frozen=True)
class OpjTreeNode:
    path: str
    name: str
    node_id: int | None
    parent_node_id: int | None
    start_offset: int
    end_offset: int
    length: int
    parser_rule: str = "opj_tree"
    confidence: float = 0.78


@dataclass(frozen=True)
class OpjTreeOwnership:
    child_name: str
    parent_name: str
    confidence: float = 0.92


def _sanitize_opj_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return sanitized or "item"


def _extract_tree_reference_map(data: bytes) -> dict[str, list[str]]:
    if not data:
        return {}
    mapping: dict[str, list[str]] = {}
    for match in _OPJ_TREE_REFERENCE_PATTERN.finditer(data):
        container = match.group(1).decode("ascii", errors="ignore")
        item = match.group(2).decode("ascii", errors="ignore")
        if not container or not item:
            continue
        mapping.setdefault(item, [])
        if container not in mapping[item]:
            mapping[item].append(container)
    return mapping


def parse_opj_tree_references(data: bytes) -> list[OpjTreeReference]:
    if not data:
        return []

    references: list[OpjTreeReference] = []
    for match in _OPJ_TREE_REFERENCE_PATTERN.finditer(data):
        parent = match.group(1).decode("ascii", errors="ignore")
        child = match.group(2).decode("ascii", errors="ignore")
        if not parent or not child:
            continue
        references.append(
            OpjTreeReference(
                parent_name=parent,
                child_name=child,
                start=match.start(),
                end=match.end(),
            )
        )
    return references


def _parse_tree_node_label(node: ET.Element) -> str:
    label = node.get("Label")
    if label:
        label = label.strip()
        if label:
            return label
    return node.tag


def _parse_tree_node_id(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _iter_opj_tree_blocks(data: bytes) -> list[tuple[int, int, bytes]]:
    blocks: list[tuple[int, int, bytes]] = []
    for match in _OPJ_TREE_BLOCK_PATTERN.finditer(data):
        payload_size = int(match.group(1))
        if payload_size <= 0:
            continue
        payload_start = match.end()
        payload_end = payload_start + payload_size
        if payload_end > len(data):
            continue
        blocks.append((match.start(), payload_end, data[payload_start:payload_end]))
    return blocks


def parse_opj_tree_nodes(data: bytes, *, max_nodes: int | None = None) -> list[OpjTreeNode]:
    if not is_opj_signature(data) or (max_nodes is not None and max_nodes < 0):
        return []

    nodes: list[OpjTreeNode] = []
    for block_start, block_end, payload in _iter_opj_tree_blocks(data):
        if not payload:
            continue
        try:
            root = ET.fromstring(payload.decode("utf-8", errors="replace"))
        except ET.ParseError:
            continue

        def walk(
            node: ET.Element,
            parent_node_id: int | None,
            path: tuple[str, ...],
            block_start: int = block_start,
            block_end: int = block_end,
        ) -> None:
            if max_nodes is not None and len(nodes) >= max_nodes:
                return
            node_name = _parse_tree_node_label(node)
            sanitized = _sanitize_opj_name(node_name)
            next_path = (*path, sanitized)
            node_id = _parse_tree_node_id(node.get("NodeID"))
            nodes.append(
                OpjTreeNode(
                    path="/".join(next_path),
                    name=sanitized,
                    node_id=node_id,
                    parent_node_id=parent_node_id,
                    start_offset=block_start,
                    end_offset=block_end,
                    length=block_end - block_start,
                )
            )
            for child in list(node):
                if max_nodes is not None and len(nodes) >= max_nodes:
                    return
                walk(child, node_id, next_path)

        walk(root, None, ("tree",))
        if max_nodes is not None and len(nodes) >= max_nodes:
            break
    return nodes


def parse_opj_tree_ownership_links(data: bytes) -> list[OpjTreeOwnership]:
    if not is_opj_signature(data):
        return []

    links: list[OpjTreeOwnership] = []
    nodes = parse_opj_tree_nodes(data)
    by_id: dict[int, OpjTreeNode] = {}
    for node in nodes:
        if node.node_id is not None:
            by_id[node.node_id] = node

    for node in nodes:
        if node.parent_node_id is None:
            continue
        parent_node = by_id.get(node.parent_node_id)
        if parent_node is None or not node.name or not parent_node.name:
            continue
        links.append(OpjTreeOwnership(child_name=node.name, parent_name=parent_node.name))

    if not links:
        for item, parents in _extract_tree_reference_map(data).items():
            lowered = item.lower()
            if lowered.startswith(("mbook", "msheet", "matrix", "pdm")) and len(parents) != 1:
                continue
            for parent in parents:
                links.append(OpjTreeOwnership(child_name=item, parent_name=parent))
        return links

    link_pairs = {(link.child_name, link.parent_name) for link in links}
    reference_map = _extract_tree_reference_map(data)
    for item, parents in reference_map.items():
        lowered = item.lower()
        if not lowered.startswith(("mbook", "msheet", "matrix", "pdm")):
            continue
        if len(parents) != 1:
            continue
        parent = parents[0]
        key = (item, parent)
        if key not in link_pairs:
            links.append(OpjTreeOwnership(child_name=item, parent_name=parent))
            link_pairs.add(key)

    return links


def _parse_tree_ownership_index(data: bytes) -> dict[str, list[str]]:
    links = parse_opj_tree_ownership_links(data)
    if not links:
        return {}

    ownership_map: dict[str, list[str]] = {}
    for link in links:
        child = _sanitize_opj_name(link.child_name)
        parent = _sanitize_opj_name(link.parent_name)
        if not child or not parent:
            continue
        ownership_map.setdefault(child, [])
        if parent not in ownership_map[child]:
            ownership_map[child].append(parent)
    return ownership_map
