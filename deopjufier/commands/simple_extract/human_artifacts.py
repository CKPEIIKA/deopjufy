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
_MATERIALIZED_STATUSES = frozenset({"extracted", "partial"})


def _is_origin_storage_markup(target: Path) -> bool:
    try:
        with target.open("rb") as fp:
            prefix = fp.read(512).decode("utf-8", errors="ignore").lstrip()
    except OSError:
        return False
    return prefix.lower().startswith("<originstorage")


def _semantic_omission(manifest: Manifest, item: ManifestItem, target: Path) -> str | None:
    """Return why a materialized artifact is not a trusted human-facing result."""
    if item.kind in _TABULAR_KINDS:
        if item.content_class in {"corrupt_text", "empty", "internal_references"}:
            return f"{item.content_class.replace('_', ' ')} content"
        if item.kind == "matrix" and item.name.startswith("origin_storage_family_"):
            return "unowned storage family"
        if manifest.input.detected_type == "opju":
            expected_method = (
                "opju_report_table_reference_resolution" if item.kind == "report_table" else "opju_descriptor_table"
            )
            if item.extraction_method != expected_method or item.verification != "exact":
                return "unverified recovery"
        return None
    if item.kind == "function" and not any((item.function_formula, item.function_range, item.function_total_points)):
        if item.extraction_method != "origin_storage_byte_run_decode" or item.verification != "exact":
            return "functions without a decoded formula"
        return None
    if item.kind == "note" and _is_origin_storage_markup(target):
        return "raw OriginStorage markup"
    return None


def _omission_reason(manifest: Manifest, out_dir: Path, item: ManifestItem) -> str | None:
    """Return why a human-kind item is omitted, or None when its file is retained."""
    if item.status == "partial":
        return "partial artifacts"
    if not item.path:
        return "items without an artifact file"
    target = out_dir / item.path
    try:
        target.resolve(strict=False).relative_to(out_dir.resolve(strict=False))
    except ValueError:
        return "paths outside the output directory"
    if not target.is_file() or target.stat().st_size == 0:
        return "empty artifact files"
    return _semantic_omission(manifest, item, target)


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


def _omit(item: ManifestItem, reason: str) -> None:
    item.status = "skipped"
    item.path = None
    item.error = f"human profile omits {reason}"


def _remove_unretained_files(manifest: Manifest, out_dir: Path, retained_paths: set[Path]) -> None:
    for item in manifest.items:
        # Only files written by this run are candidates; skipped items may name pre-existing files.
        if not item.path or item.status not in _MATERIALIZED_STATUSES:
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


def retain_human_artifacts(manifest: Manifest, out_dir: Path) -> None:
    """Keep trusted primary artifacts and record every other human-kind item as skipped.

    Machine-only kinds are dropped, content duplicates become aliases of the
    retained item, and untrusted human-kind items stay in the manifest with
    ``status=skipped`` and a reason so the projection never hides a recovery.
    """
    candidates: list[tuple[int, ManifestItem, Path]] = []
    omitted: dict[int, tuple[ManifestItem, str]] = {}
    preserved: dict[int, ManifestItem] = {}
    for index, item in enumerate(manifest.items):
        if item.kind not in _HUMAN_ARTIFACT_KINDS:
            continue
        if item.status not in _MATERIALIZED_STATUSES:
            # Never-materialized results (skipped, unsupported, error) keep their own reason.
            preserved[index] = item
            continue
        reason = _omission_reason(manifest, out_dir, item)
        if reason is not None:
            omitted[index] = (item, reason)
        elif item.path:
            candidates.append((index, item, out_dir / item.path))

    retained_by_index: dict[int, ManifestItem] = {}
    retained_by_path: dict[Path, ManifestItem] = {}
    retained_by_content: dict[tuple[str, str], ManifestItem] = {}
    for index, item, target in sorted(candidates, key=lambda candidate: (_human_priority(candidate[1]), candidate[0])):
        resolved_target = target.resolve(strict=False)
        previous = retained_by_path.get(resolved_target) or retained_by_content.get(
            (_content_group(item), _content_digest(target))
        )
        if previous is not None:
            _record_duplicate(previous, item)
            continue
        retained_by_index[index] = item
        retained_by_path[resolved_target] = item
        retained_by_content[(_content_group(item), _content_digest(target))] = item

    for index, item in tuple(retained_by_index.items()):
        if _is_ambiguous_opju_table(manifest, item):
            del retained_by_index[index]
            omitted[index] = (item, "ambiguous table ownership")

    retained_paths = {(out_dir / item.path).resolve(strict=False) for item in retained_by_index.values() if item.path}
    _remove_unretained_files(manifest, out_dir, retained_paths)

    for item, reason in omitted.values():
        _omit(item, reason)
    for item in preserved.values():
        # Collection markers point at family directories that cleanup may have removed.
        if item.path and not (out_dir / item.path).exists():
            item.path = None
    kept = retained_by_index | preserved | {index: item for index, (item, _reason) in omitted.items()}
    manifest.items[:] = [kept[index] for index in sorted(kept)]
    if omitted:
        manifest.add_warning(
            f"{len(omitted)} recovered items were omitted by the human profile; use --extended to keep them."
        )
