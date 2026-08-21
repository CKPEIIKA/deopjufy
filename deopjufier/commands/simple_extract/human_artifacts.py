"""Human-profile projection for primary extracted artifacts."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from pathlib import Path

from deopjufier.manifest import Manifest, ManifestItem

_HUMAN_ARTIFACT_KINDS = frozenset(
    {
        "analysis_summary",
        "analysis_report",
        "attachment",
        "excel",
        "external_workbook_link",
        "function",
        "graph",
        "graph_preview",
        "image",
        "matrix",
        "note",
        "parser_backed_graph_preview",
        "report_table",
        "semantic_provenance",
        "worksheet",
    }
)
_TABULAR_KINDS = frozenset({"excel", "matrix", "report_table", "worksheet"})
_MEDIA_KINDS = frozenset({"graph", "graph_preview", "image", "parser_backed_graph_preview"})


def _is_origin_storage_markup(target: Path) -> bool:
    try:
        with target.open("rb") as fp:
            prefix = fp.read(512).decode("utf-8", errors="ignore").lstrip()
    except OSError:
        return False
    return prefix.lower().startswith("<originstorage")


def _is_semantic_human_item(manifest: Manifest, item: ManifestItem, target: Path) -> bool:
    if item.kind in _TABULAR_KINDS:
        if item.content_class in {"corrupt_text", "empty", "internal_references"}:
            return False
        if item.kind == "matrix" and item.name.startswith("origin_storage_family_"):
            return False
        if manifest.input.detected_type == "opju":
            if item.kind == "report_table":
                return (
                    item.extraction_method == "opju_report_table_reference_resolution" and item.verification == "exact"
                )
            return item.extraction_method == "opju_descriptor_table" and item.verification == "exact"
    if item.kind == "function" and not any((item.function_formula, item.function_range, item.function_total_points)):
        return item.extraction_method == "origin_storage_byte_run_decode" and item.verification == "exact"
    if item.kind == "note" and _is_origin_storage_markup(target):
        return False
    return True


def _artifact_target(manifest: Manifest, out_dir: Path, item: ManifestItem) -> Path | None:
    if item.status != "extracted" or item.kind not in _HUMAN_ARTIFACT_KINDS or not item.path:
        return None
    target = out_dir / item.path
    try:
        target.resolve(strict=False).relative_to(out_dir.resolve(strict=False))
    except ValueError:
        return None
    if not target.is_file() or target.stat().st_size == 0:
        return None
    if not _is_semantic_human_item(manifest, item, target):
        return None
    return target


def _content_group(item: ManifestItem) -> str:
    if item.kind in {"analysis_report", "report_table"}:
        return f"{item.kind}:{item.source_object_path or item.name}"
    if item.kind in _TABULAR_KINDS:
        return "table"
    if item.kind in _MEDIA_KINDS:
        return "media"
    if item.kind in {"analysis_report", "function", "note"}:
        return "text"
    return item.kind


def _content_digest(target: Path) -> str:
    digest = hashlib.sha256()
    with target.open("rb") as fp:
        while chunk := fp.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _human_priority(item: ManifestItem) -> tuple[int, int]:
    if item.kind in {"graph_preview", "parser_backed_graph_preview"}:
        media_priority = 0
    elif item.kind == "graph":
        media_priority = 1
    else:
        media_priority = 2
    generic_priority = 1 if item.name.startswith("origin_storage_family_") else 0
    return media_priority, generic_priority


def _record_duplicate(primary: ManifestItem, duplicate: ManifestItem) -> None:
    alias = duplicate.source_object_path or duplicate.name
    aliases = list(primary.overlapping_objects or [])
    if alias not in aliases:
        aliases.append(alias)
    primary.overlapping_objects = aliases


def _is_ambiguous_opju_table(manifest: Manifest, item: ManifestItem) -> bool:
    return (
        manifest.input.detected_type == "opju"
        and item.kind in _TABULAR_KINDS
        and item.kind != "report_table"
        and len(item.overlapping_objects or ()) >= 3
    )


def retain_human_artifacts(manifest: Manifest, out_dir: Path) -> None:
    """Keep non-empty primary artifacts and remove machine-profile files made by this run."""
    candidates: list[tuple[int, ManifestItem, Path]] = []
    for index, item in enumerate(manifest.items):
        target = _artifact_target(manifest, out_dir, item)
        if target is not None:
            candidates.append((index, item, target))

    retained_by_index: dict[int, ManifestItem] = {}
    retained_paths: set[Path] = set()
    retained_by_path: dict[Path, ManifestItem] = {}
    retained_by_content: dict[tuple[str, str], ManifestItem] = {}
    for index, item, target in sorted(candidates, key=lambda candidate: (_human_priority(candidate[1]), candidate[0])):
        resolved_target = target.resolve(strict=False)
        previous = retained_by_path.get(resolved_target)
        if previous is not None:
            _record_duplicate(previous, item)
            continue

        content_key = (_content_group(item), _content_digest(target))
        previous = retained_by_content.get(content_key)
        if previous is not None:
            _record_duplicate(previous, item)
            continue

        retained_by_index[index] = item
        retained_paths.add(resolved_target)
        retained_by_path[resolved_target] = item
        retained_by_content[content_key] = item

    for index, item in tuple(retained_by_index.items()):
        if not _is_ambiguous_opju_table(manifest, item):
            continue
        retained_by_index.pop(index)
        if item.path:
            retained_paths.discard((out_dir / item.path).resolve(strict=False))

    for item in manifest.items:
        if not item.path:
            continue
        target = out_dir / item.path
        resolved_target = target.resolve(strict=False)
        try:
            resolved_target.relative_to(out_dir.resolve(strict=False))
        except ValueError:
            continue
        if resolved_target not in retained_paths and target.is_file():
            target.unlink()

    for directory in sorted(
        (path for path in out_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        with suppress(OSError):
            directory.rmdir()

    manifest.items[:] = [retained_by_index[index] for index in sorted(retained_by_index)]
