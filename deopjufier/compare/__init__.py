"""Manifest/output comparison helpers used by the optional `compare` command."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Any, cast

from deopjufier.io import sha256_file

Manifest = dict[str, Any]
CompareArtifact = dict[str, Any]


@dataclass(frozen=True)
class CompareItemIdentity:
    """Stable identity for a manifest item used for deterministic diffs."""

    kind: str
    name: str
    source_object_path: str
    path: str

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> CompareItemIdentity:
        return cls(
            kind=str(item.get("kind", "")),
            name=str(item.get("name", "")),
            source_object_path=str(item.get("source_object_path", "")),
            path=str(item.get("path", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "source_object_path": self.source_object_path,
            "path": self.path,
        }


def _resolve_manifest_target(target: Path) -> tuple[Path, Path]:
    """Return manifest.json path and artifact root for directory or file targets."""

    if not target.exists():
        raise FileNotFoundError(f"compare target not found: {target}")
    if target.is_dir():
        manifest = target / "manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(f"manifest.json not found under {target}")
        return manifest, target

    if target.suffix.lower() != ".json":
        raise ValueError(f"unsupported compare target: {target}")

    return target, target.parent


def _load_manifest(path: Path) -> Manifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid manifest payload: {path}")
    return payload


def _coerce_items(payload: Manifest) -> list[dict[str, Any]]:
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            items.append(cast(dict[str, Any], item))
    return items


def _canonicalize_item(item: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "kind",
        "name",
        "status",
        "source_object_path",
        "path",
        "confidence",
        "discovery_type",
        "heuristic",
        "object_kind",
        "rows",
        "columns",
        "offset",
        "length",
        "range_start",
        "range_end",
        "error",
    )

    return {key: item.get(key) for key in keep}


def _artifact_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter(item.get("kind", "") for item in items)
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _signature_blob(item: dict[str, Any]) -> str:
    return json.dumps(_canonicalize_item(item), sort_keys=True, separators=(",", ":"))


def _is_table_like(path: Path) -> bool:
    return path.suffix.lower() in {".csv", ".tsv"}


def _table_delimiter(path: Path) -> str:
    return "\t" if path.suffix.lower() == ".tsv" else ","


def _read_table_rows(path: Path) -> list[list[str]]:
    delimiter = _table_delimiter(path)
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        return [row for row in reader]


def _to_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        return None


def _compare_table_rows(
    left_path: Path,
    right_path: Path,
    *,
    identity: dict[str, str],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    try:
        left_rows = _read_table_rows(left_path)
    except OSError as exc:
        mismatches.append(
            {
                "identity": identity,
                "status": "table_read_error",
                "side": "left",
                "path": str(left_path),
                "error": str(exc),
            }
        )
        return mismatches
    try:
        right_rows = _read_table_rows(right_path)
    except OSError as exc:
        mismatches.append(
            {
                "identity": identity,
                "status": "table_read_error",
                "side": "right",
                "path": str(right_path),
                "error": str(exc),
            }
        )
        return mismatches

    left_rows_count = len(left_rows)
    right_rows_count = len(right_rows)
    left_cols = max((len(row) for row in left_rows), default=0)
    right_cols = max((len(row) for row in right_rows), default=0)

    if left_rows_count != right_rows_count or left_cols != right_cols:
        mismatches.append(
            {
                "identity": identity,
                "status": "table_shape_mismatch",
                "left": {"rows": left_rows_count, "columns": left_cols},
                "right": {"rows": right_rows_count, "columns": right_cols},
                "left_path": str(left_path),
                "right_path": str(right_path),
            }
        )
        return mismatches

    for row_idx, (left_row, right_row) in enumerate(zip(left_rows, right_rows, strict=False)):
        left_len = len(left_row)
        right_len = len(right_row)
        if left_len != right_len:
            mismatches.append(
                {
                    "identity": identity,
                    "status": "table_shape_mismatch",
                    "row": row_idx,
                    "left": {"row_index": row_idx, "columns": left_len},
                    "right": {"row_index": row_idx, "columns": right_len},
                    "left_path": str(left_path),
                    "right_path": str(right_path),
                }
            )
            break

        for col_idx, (left_raw, right_raw) in enumerate(zip(left_row, right_row, strict=False)):
            left_value = left_raw.strip()
            right_value = right_raw.strip()
            left_number = _to_float(left_value)
            right_number = _to_float(right_value)
            if left_number is None or right_number is None:
                if left_value != right_value:
                    mismatches.append(
                        {
                            "identity": identity,
                            "status": "table_text_mismatch",
                            "row": row_idx,
                            "column": col_idx,
                            "left": left_value,
                            "right": right_value,
                            "left_path": str(left_path),
                            "right_path": str(right_path),
                        }
                    )
                    return mismatches
                continue

            if not isclose(left_number, right_number, rel_tol=1e-12, abs_tol=1e-12):
                mismatches.append(
                    {
                        "identity": identity,
                        "status": "table_numeric_mismatch",
                        "row": row_idx,
                        "column": col_idx,
                        "left": left_value,
                        "right": right_value,
                        "left_path": str(left_path),
                        "right_path": str(right_path),
                    }
                )
                return mismatches

    return mismatches


def _item_path(root: Path, rel_path: str) -> Path | None:
    if not rel_path:
        return None
    candidate = Path(rel_path)
    if candidate.is_absolute():
        return None
    return root / candidate


def _group_items_by_identity(
    items: list[CompareArtifact],
) -> dict[CompareItemIdentity, dict[str, list[CompareArtifact]]]:
    groups: dict[CompareItemIdentity, dict[str, list[CompareArtifact]]] = {}
    for item in items:
        identity = CompareItemIdentity.from_item(item)
        signature = _signature_blob(item)
        groups.setdefault(identity, {}).setdefault(signature, []).append(item)

    for identity_signatures in groups.values():
        for signature_items in identity_signatures.values():
            signature_items.sort(
                key=lambda item: (
                    str(item.get("path", "")),
                    str(item.get("source_object_path", "")),
                    str(item.get("name", "")),
                )
            )
    return groups


def _compare_signatures(
    left_signature_counter: Counter[str],
    right_signature_counter: Counter[str],
) -> list[dict[str, Any]]:
    mismatched_signatures: list[dict[str, Any]] = []
    for signature in sorted(set(left_signature_counter) | set(right_signature_counter)):
        left_count = left_signature_counter.get(signature, 0)
        right_count = right_signature_counter.get(signature, 0)
        if left_count != right_count:
            mismatched_signatures.append(
                {
                    "signature": json.loads(signature),
                    "left_count": left_count,
                    "right_count": right_count,
                    "delta": left_count - right_count,
                }
            )
    return mismatched_signatures


def compare_manifests(
    left: Path,
    right: Path,
    *,
    compare_bytes: bool = False,
) -> dict[str, Any]:
    """Compare two manifests or extraction roots and return a deterministic diff payload."""

    left_manifest, left_root = _resolve_manifest_target(left)
    right_manifest, right_root = _resolve_manifest_target(right)

    left_payload = _load_manifest(left_manifest)
    right_payload = _load_manifest(right_manifest)

    left_items = _coerce_items(left_payload)
    right_items = _coerce_items(right_payload)

    left_counts = _artifact_counts(left_items)
    right_counts = _artifact_counts(right_items)

    left_signature_counter: Counter[str] = Counter(_signature_blob(item) for item in left_items)
    right_signature_counter: Counter[str] = Counter(_signature_blob(item) for item in right_items)
    mismatched_signatures = _compare_signatures(
        left_signature_counter,
        right_signature_counter,
    )

    byte_mismatches: list[dict[str, Any]] = []
    left_only: list[dict[str, Any]] = []
    right_only: list[dict[str, Any]] = []
    if compare_bytes:
        left_groups = _group_items_by_identity(left_items)
        right_groups = _group_items_by_identity(right_items)
        for identity in sorted(
            set(left_groups) | set(right_groups),
            key=lambda item: (
                item.kind,
                item.name,
                item.source_object_path,
                item.path,
            ),
        ):
            left_signature_map = left_groups.get(identity, {})
            right_signature_map = right_groups.get(identity, {})
            all_signatures = set(left_signature_map) | set(right_signature_map)

            for signature in sorted(all_signatures):
                left_bucket = left_signature_map.get(signature, [])
                right_bucket = right_signature_map.get(signature, [])
                if not left_bucket and not right_bucket:
                    continue

                paired = min(len(left_bucket), len(right_bucket))
                for (
                    left_item,
                    right_item,
                ) in zip(left_bucket[:paired], right_bucket[:paired], strict=False):
                    left_path = _item_path(left_root, str(left_item.get("path", "")))
                    right_path = _item_path(right_root, str(right_item.get("path", "")))
                    path_for_log = identity.to_dict()
                    path_for_log["path"] = str(left_item.get("path", ""))

                    if left_path is None or right_path is None:
                        byte_mismatches.append(
                            {
                                "identity": path_for_log,
                                "status": "path_not_comparable",
                                "left_path": str(left_item.get("path", "")),
                                "right_path": str(right_item.get("path", "")),
                            }
                        )
                        continue

                    if not left_path.exists() or not right_path.exists():
                        if not left_path.exists() and not right_path.exists():
                            continue
                        byte_mismatches.append(
                            {
                                "identity": path_for_log,
                                "status": "missing_file",
                                "left_exists": left_path.exists(),
                                "right_exists": right_path.exists(),
                                "left_path": str(left_path),
                                "right_path": str(right_path),
                            }
                        )
                        continue

                    if _is_table_like(left_path) and _is_table_like(right_path):
                        table_mismatches = _compare_table_rows(
                            left_path,
                            right_path,
                            identity=path_for_log,
                        )
                        byte_mismatches.extend(table_mismatches)
                        if table_mismatches:
                            continue

                    if left_path.is_dir() or right_path.is_dir():
                        continue

                    if left_path.stat().st_size != right_path.stat().st_size:
                        byte_mismatches.append(
                            {
                                "identity": path_for_log,
                                "status": "size_mismatch",
                                "left_size": left_path.stat().st_size,
                                "right_size": right_path.stat().st_size,
                                "left_path": str(left_path),
                                "right_path": str(right_path),
                            }
                        )
                        continue

                    if sha256_file(left_path) != sha256_file(right_path):
                        byte_mismatches.append(
                            {
                                "identity": path_for_log,
                                "status": "hash_mismatch",
                                "left_path": str(left_path),
                                "right_path": str(right_path),
                                "sha256": {
                                    "left": sha256_file(left_path),
                                    "right": sha256_file(right_path),
                                },
                            }
                        )

                if left_bucket[paired:]:
                    for item in left_bucket[paired:]:
                        left_only.append(item)
                if right_bucket[paired:]:
                    for item in right_bucket[paired:]:
                        right_only.append(item)

        for item in left_only:
            byte_mismatches.append(
                {
                    "identity": CompareItemIdentity.from_item(item).to_dict(),
                    "status": "missing_in_right",
                    "artifact": _canonicalize_item(item),
                    "left_path": str(_item_path(left_root, str(item.get("path", "")))),
                }
            )

        for item in right_only:
            byte_mismatches.append(
                {
                    "identity": CompareItemIdentity.from_item(item).to_dict(),
                    "status": "missing_in_left",
                    "artifact": _canonicalize_item(item),
                    "right_path": str(_item_path(right_root, str(item.get("path", "")))),
                }
            )

    result: dict[str, Any] = {
        "left": {
            "path": str(left),
            "status": left_payload.get("status"),
            "item_count": len(left_items),
            "artifact_counts": left_counts,
        },
        "right": {
            "path": str(right),
            "status": right_payload.get("status"),
            "item_count": len(right_items),
            "artifact_counts": right_counts,
        },
        "summary": {
            "left_items": len(left_items),
            "right_items": len(right_items),
            "left_only_items": max(0, len(left_only)),
            "right_only_items": max(0, len(right_only)),
            "signature_mismatches": len(mismatched_signatures),
            "file_mismatches": len(byte_mismatches),
        },
        "mismatches": {
            "manifest_signatures": mismatched_signatures,
        },
    }

    if compare_bytes:
        result["mismatches"]["files"] = byte_mismatches

    result["match"] = not mismatched_signatures and not byte_mismatches
    return result


def compare_results_as_text(result: dict[str, Any]) -> str:
    lines = [
        f"left={result['left']['path']} status={result['left']['status']}",
        f"right={result['right']['path']} status={result['right']['status']}",
        f"match={result['match']}",
    ]
    lines.append("missing_signatures={}".format(len(result.get("mismatches", {}).get("manifest_signatures", []))))
    return "\n".join(lines)
