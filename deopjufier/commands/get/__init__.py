"""Materialize one versioned catalog item."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from deopjufier import __version__
from deopjufier.catalog import CATALOG_SCHEMA_VERSION, catalog_items, document_payload, find_catalog_item
from deopjufier.commands.support import (
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_MISSING_DEPENDENCY,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
    SUPPORTED_TYPES,
    _build_session,
)
from deopjufier.errors import CorruptedInputError, UnsupportedFileError
from deopjufier.extract import (
    extract_books,
    extract_excel,
    extract_functions,
    extract_graph_previews,
    extract_images,
    extract_matrices,
    extract_notes,
)
from deopjufier.inventory import OriginObject, ParserBackedDiscoveryRecord
from deopjufier.io import dump_range
from deopjufier.manifest import Manifest, ManifestItem, make_manifest
from deopjufier.session import ExtractionSession

_GRAPH_KINDS = frozenset({"graph", "layer", "opju_graph_payload", "opju_preview"})
_IMAGE_KINDS = frozenset({"bmp", "gif", "image", "jpeg", "png", "svg"})
_TEXT_SUFFIXES = frozenset({".csv", ".html", ".json", ".md", ".tsv", ".txt"})


def _semantic_kind(item: dict[str, object]) -> str:
    object_kind = item.get("object_kind")
    if isinstance(object_kind, str) and object_kind:
        return object_kind
    kind = item.get("kind")
    return kind if isinstance(kind, str) else "unknown"


def _confidence(item: dict[str, object]) -> float:
    value = item.get("confidence")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _catalog_for_get(session: ExtractionSession) -> list[dict[str, object]]:
    items = session.list_items(
        include_images=True,
        include_raw_gaps=True,
        include_raw_dump_crosswalk=session.detection.detected_type == "opju",
        heuristic_kind_limit=None,
        use_default_opju_limit=False,
    )
    ordered = sorted(
        items,
        key=lambda item: (
            item.get("offset", 0),
            item.get("kind", ""),
            item.get("source_object_path", ""),
            item.get("name", ""),
        ),
    )
    return catalog_items(ordered, session.sha256)


def _matches_object(obj: OriginObject, item: dict[str, object]) -> bool:
    return (
        obj.name == item.get("name")
        and obj.offset == item.get("offset")
        and obj.length == item.get("length")
        and obj.source_object_path == item.get("source_object_path")
    )


def _all_objects(session: ExtractionSession) -> list[OriginObject]:
    return session.objects(
        max_repeats_per_name=None,
        include_redundant_tokens=True,
        collect_heuristics=True,
        heuristic_kind_limit=None,
    )


def _target_object(objects: list[OriginObject], item: dict[str, object]) -> OriginObject | None:
    matched = next((obj for obj in objects if _matches_object(obj, item)), None)
    if matched is not None or item.get("discovery_type") != "opju_column_descriptor_table":
        return matched
    offset = item.get("offset")
    length = item.get("length")
    name = item.get("name")
    source_object_path = item.get("source_object_path")
    if not (
        isinstance(offset, int)
        and isinstance(length, int)
        and isinstance(name, str)
        and isinstance(source_object_path, str)
    ):
        return None
    return ParserBackedDiscoveryRecord(
        offset=offset,
        name=name,
        length=length,
        object_kind="worksheet",
        source_object_path=source_object_path,
        parser_rule="opju_column_descriptor_table",
        parser_confidence=0.99,
    )


def _add_unmaterialized_item(manifest: Manifest, item: dict[str, object]) -> None:
    kind = _semantic_kind(item)
    offset = item.get("offset")
    length = item.get("length")
    manifest.add_item(
        ManifestItem(
            kind=kind,
            name=str(item.get("name", kind)),
            status="partial",
            confidence=_confidence(item),
            discovery_type=str(item.get("discovery_type", "catalog")),
            heuristic=bool(item.get("heuristic", False)),
            object_kind=str(item.get("object_kind", kind)),
            source_object_path=(
                str(item["source_object_path"]) if item.get("source_object_path") is not None else None
            ),
            offset=offset if isinstance(offset, int) else None,
            length=length if isinstance(length, int) else None,
            error="catalog_item_has_no_materializer",
        )
    )


def _materialize_raw(item: dict[str, object], input_path: Path, out_dir: Path, manifest: Manifest) -> None:
    offset = item.get("offset")
    length = item.get("length")
    if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length < 0:
        _add_unmaterialized_item(manifest, item)
        return
    target = out_dir / "raw.bin"
    target.write_bytes(dump_range(input_path, offset, length))
    manifest.add_item(
        ManifestItem(
            kind="raw_dump",
            name=str(item.get("name", "raw_dump")),
            status="extracted",
            confidence=_confidence(item),
            discovery_type=str(item.get("discovery_type", "unknown_gap")),
            heuristic=bool(item.get("heuristic", True)),
            path=target.name,
            source_object_path=str(item.get("source_object_path", "raw_dump")),
            offset=offset,
            length=length,
            extraction_method="dump_range",
            verification="exact",
        )
    )


def _materialize_image(
    session: ExtractionSession,
    item: dict[str, object],
    out_dir: Path,
    manifest: Manifest,
) -> None:
    offset = item.get("offset")
    length = item.get("length")
    blocks = [block for block in session.image_blocks() if block.offset == offset and block.length == length]
    if not blocks:
        _add_unmaterialized_item(manifest, item)
        return
    extract_images(
        session.input_path,
        out_dir / "images",
        manifest,
        force=True,
        file_data=session.file_data(),
        image_blocks=blocks,
        manifest_root=out_dir,
    )


def _materialize_object(
    session: ExtractionSession,
    item: dict[str, object],
    obj: OriginObject,
    *,
    all_objects: list[OriginObject],
    out_dir: Path,
    manifest: Manifest,
    output_format: str,
) -> None:
    kind = _semantic_kind(item)
    file_data = session.file_data()
    selected_names = {obj.name}
    selected_object_keys = {(obj.offset, obj.name, obj.source_object_path)}
    if kind == "worksheet":
        objects, allow_parser_recovery = session.objects_for_tabular_extraction(
            file_data,
            object_kind="worksheet",
            supplied_objects=all_objects,
            prefer_supplied_objects=True,
            rewrite_worksheet_source_path=True,
            filter_non_parser_worksheet_duplicates=False,
        )
        extract_books(
            session.input_path,
            out_dir,
            manifest,
            output_format=output_format,
            force=True,
            file_data=file_data,
            objects=objects,
            allow_parser_recovery=allow_parser_recovery,
            allow_heuristic_scan=not obj.parser_confirmed,
            emit_unsupported_collection=False,
            precomputed_opju_descriptors=(
                session.opju_column_descriptors() if session.detection.detected_type == "opju" else None
            ),
            manifest_root=out_dir,
            selected_names=selected_names,
            selected_object_keys=selected_object_keys,
        )
        return
    if kind == "matrix":
        objects, allow_parser_recovery = session.objects_for_tabular_extraction(
            file_data,
            object_kind="matrix",
            supplied_objects=all_objects,
            prefer_supplied_objects=True,
        )
        extract_matrices(
            session.input_path,
            out_dir,
            manifest,
            output_format=output_format,
            force=True,
            file_data=file_data,
            objects=objects,
            allow_parser_recovery=allow_parser_recovery,
            allow_heuristic_scan=not obj.parser_confirmed,
            emit_unsupported_collection=False,
            manifest_root=out_dir,
            selected_object_keys=selected_object_keys,
        )
        return
    if kind == "excel":
        objects, allow_parser_recovery = session.objects_for_tabular_extraction(
            file_data,
            object_kind="excel",
            supplied_objects=all_objects,
            prefer_supplied_objects=True,
        )
        extract_excel(
            session.input_path,
            out_dir,
            manifest,
            output_format=output_format,
            force=True,
            file_data=file_data,
            objects=objects,
            allow_parser_recovery=allow_parser_recovery,
            allow_heuristic_scan=not obj.parser_confirmed,
            emit_unsupported_collection=False,
            manifest_root=out_dir,
            selected_object_keys=selected_object_keys,
        )
        return
    if kind == "note":
        extract_notes(
            session.input_path,
            out_dir,
            manifest,
            force=True,
            file_data=file_data,
            objects=all_objects,
            selected_names=selected_names,
            selected_object_keys=selected_object_keys,
            manifest_root=out_dir,
        )
        return
    if kind == "function":
        extract_functions(
            session.input_path,
            out_dir,
            manifest,
            force=True,
            file_data=file_data,
            objects=all_objects,
            allow_parser_recovery=obj.parser_confirmed,
            selected_object_keys=selected_object_keys,
            manifest_root=out_dir,
        )
        return
    if kind in _GRAPH_KINDS:
        extract_graph_previews(
            session.input_path,
            out_dir,
            manifest,
            force=True,
            file_data=file_data,
            image_blocks=session.image_blocks(),
            objects=all_objects,
            manifest_root=out_dir,
            selected_object_keys=selected_object_keys,
        )
        return
    _add_unmaterialized_item(manifest, item)


def _materialize_catalog_item(
    session: ExtractionSession,
    item: dict[str, object],
    out_dir: Path,
    output_format: str,
) -> Manifest:
    manifest = make_manifest(
        session.input_path,
        session.detection,
        "native-parser",
        size_bytes=session.size_bytes,
        sha256=session.sha256,
    )
    kind = _semantic_kind(item)
    if kind == "project_page" and isinstance(item.get("preview_offset"), int):
        preview_item = {
            **item,
            "kind": item.get("preview_kind", "image"),
            "object_kind": item.get("preview_kind", "image"),
            "offset": item["preview_offset"],
            "length": item.get("preview_length"),
        }
        _materialize_image(session, preview_item, out_dir, manifest)
    elif item.get("kind") == "raw_dump":
        _materialize_raw(item, session.input_path, out_dir, manifest)
    elif item.get("kind") in _IMAGE_KINDS or kind in _IMAGE_KINDS:
        _materialize_image(session, item, out_dir, manifest)
    else:
        all_objects = _all_objects(session)
        obj = _target_object(all_objects, item)
        if obj is not None:
            if obj not in all_objects:
                all_objects.append(obj)
            _materialize_object(
                session,
                item,
                obj,
                all_objects=all_objects,
                out_dir=out_dir,
                manifest=manifest,
                output_format=output_format,
            )
        else:
            _add_unmaterialized_item(manifest, item)

    if any(manifest_item.status == "extracted" for manifest_item in manifest.items):
        manifest.status = "ok"
        manifest.parser_status = "ok"
    elif manifest.items:
        manifest.status = "partial"
        manifest.parser_status = "unsupported"
    else:
        manifest.status = "unsupported"
        manifest.parser_status = "empty"
    manifest.support_class = "partial"
    manifest.coverage_scope = "partial"
    manifest.verification = "unverified"
    return manifest


def _safe_artifact_path(root: Path, relative_path: object) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path:
        return None
    root_resolved = root.resolve()
    candidate = (root / relative_path).resolve()
    return candidate if candidate.is_relative_to(root_resolved) and candidate.is_file() else None


def _artifact_content(path: Path) -> tuple[str, object]:
    payload = path.read_bytes()
    if path.suffix.lower() in _TEXT_SUFFIXES or payload.lstrip().startswith((b"{", b"[")):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            if payload.lstrip().startswith((b"{", b"[")):
                try:
                    return "json", json.loads(text)
                except json.JSONDecodeError:
                    pass
            return "text", text
    return "base64", base64.b64encode(payload).decode("ascii")


def _artifact_payloads(manifest: Manifest, out_dir: Path) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    for item in manifest.to_dict()["items"]:
        artifact = dict(cast(dict[str, object], item))
        path = _safe_artifact_path(out_dir, artifact.get("path"))
        if path is not None:
            encoding, content = _artifact_content(path)
            artifact["content_encoding"] = encoding
            artifact["content"] = content
        artifacts.append(artifact)
    return artifacts


def _primary_artifact(artifacts: list[dict[str, object]], semantic_kind: str) -> dict[str, object] | None:
    preferred_kinds = ("analysis_report", "note") if semantic_kind == "note" else (semantic_kind,)
    for preferred_kind in preferred_kinds:
        for artifact in artifacts:
            if artifact.get("kind") == preferred_kind and artifact.get("content") is not None:
                return artifact
    return next((artifact for artifact in artifacts if artifact.get("content") is not None), None)


def _write_jsonl(content: object, output: Path) -> None:
    content_dict = cast(dict[str, object], content) if isinstance(content, dict) else None
    if content_dict is not None and isinstance(content_dict.get("rows"), list):
        header = {"type": "table", "schema_version": 1, "headers": content_dict.get("headers", [])}
        rows = cast(list[object], content_dict["rows"])
    elif isinstance(content, list):
        header = {"type": "table", "schema_version": 1, "headers": []}
        rows = content
    else:
        raise ValueError("selected item does not expose tabular JSON rows")
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(header, ensure_ascii=False, sort_keys=True))
        stream.write("\n")
        for row in rows:
            stream.write(json.dumps({"type": "row", "row": row}, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _copy_primary_output(
    primary: dict[str, object] | None,
    out_dir: Path,
    output: Path,
    output_format: str,
    *,
    force: bool,
) -> None:
    if primary is None:
        raise ValueError("selected item produced no retrievable artifact")
    if output.exists() and not force:
        raise FileExistsError(f"output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "jsonl":
        _write_jsonl(primary.get("content"), output)
        return
    source = _safe_artifact_path(out_dir, primary.get("path"))
    if source is None:
        raise ValueError("selected item produced no file-backed artifact")
    shutil.copyfile(source, output)


def _render(payload: dict[str, object], *, as_json: bool, error: bool = False, quiet: bool = False) -> None:
    if quiet and not error:
        return
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    stream = sys.stderr if error else sys.stdout
    item = cast(dict[str, object], payload.get("item", {}))
    print(f"Item: {item.get('name', item.get('id', ''))}", file=stream)
    print(f"Kind: {_semantic_kind(item)}", file=stream)
    print(f"Status: {payload.get('status', '')}", file=stream)
    if payload.get("output") is not None:
        print(f"Output: {payload['output']}", file=stream)
    error_value = payload.get("error")
    if error_value is not None:
        print(f"Error: {error_value}", file=stream)


def _failure_payload(file_path: Path, item_id: str, error: str) -> dict[str, object]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "document": document_payload(
            path=str(file_path),
            size_bytes=0,
            sha256="",
            detected_type="unknown",
        ),
        "tool": {
            "name": "deopjufy",
            "version": __version__,
            "backend": "native-parser",
        },
        "item": {"id": item_id},
        "status": "error",
        "error": error,
        "artifacts": [],
        "warnings": [],
    }


def cmd_get(args: argparse.Namespace) -> int:
    file_path = cast(Path, args.file)
    item_id = cast(str, args.item_id)
    as_json = cast(bool, args.json)
    output_format = cast(str, args.format)
    output = cast(Path | None, args.output)
    force = cast(bool, args.force)
    quiet = cast(bool, args.quiet)
    if output_format != "json" and output is None:
        payload = _failure_payload(file_path, item_id, "non-JSON formats require --output")
        _render(payload, as_json=as_json, error=True)
        return EXIT_USAGE

    try:
        session = _build_session(file_path)
        if session.detection.detected_type not in SUPPORTED_TYPES:
            raise UnsupportedFileError("input is not a recognized Origin project")
        catalog = _catalog_for_get(session)
        item = find_catalog_item(catalog, item_id)
        if item is None:
            payload = _failure_payload(file_path, item_id, "catalog item does not exist for these input bytes")
            payload["document"] = document_payload(
                path=str(file_path),
                size_bytes=session.size_bytes,
                sha256=session.sha256,
                detected_type=session.detection.detected_type,
            )
            _render(payload, as_json=as_json, error=True)
            return EXIT_UNSUPPORTED
        formats = item.get("retrieval_formats")
        if not isinstance(formats, list) or output_format not in formats:
            payload = _failure_payload(
                file_path,
                item_id,
                f"format '{output_format}' is not available for this catalog item",
            )
            payload["document"] = document_payload(
                path=str(file_path),
                size_bytes=session.size_bytes,
                sha256=session.sha256,
                detected_type=session.detection.detected_type,
            )
            payload["item"] = item
            _render(payload, as_json=as_json, error=True)
            return EXIT_UNSUPPORTED

        extractor_format = "json" if output_format == "jsonl" else output_format
        with tempfile.TemporaryDirectory(prefix="deopjufy-get-") as temp_dir:
            out_dir = Path(temp_dir)
            manifest = _materialize_catalog_item(session, item, out_dir, extractor_format)
            artifacts = _artifact_payloads(manifest, out_dir)
            primary = _primary_artifact(artifacts, _semantic_kind(item))
            if output is not None:
                _copy_primary_output(primary, out_dir, output, output_format, force=force)
            payload: dict[str, object] = {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "document": document_payload(
                    path=str(file_path),
                    size_bytes=session.size_bytes,
                    sha256=session.sha256,
                    detected_type=session.detection.detected_type,
                ),
                "tool": {
                    "name": "deopjufy",
                    "version": __version__,
                    "backend": "native-parser",
                },
                "item": item,
                "status": manifest.status,
                "artifacts": artifacts,
                "warnings": manifest.warnings,
                **({"output": str(output)} if output is not None else {}),
            }
            if primary is not None:
                if primary.get("content") is not None:
                    payload["content"] = primary["content"]
                if primary.get("content_encoding") is not None:
                    payload["content_encoding"] = primary["content_encoding"]
        _render(payload, as_json=as_json, quiet=quiet)
        return EXIT_SUCCESS if payload["status"] == "ok" else EXIT_UNSUPPORTED
    except CorruptedInputError as exc:
        payload = _failure_payload(file_path, item_id, str(exc))
        _render(payload, as_json=as_json, error=True)
        return EXIT_CORRUPTED
    except UnsupportedFileError as exc:
        payload = _failure_payload(file_path, item_id, str(exc))
        _render(payload, as_json=as_json, error=True)
        return EXIT_UNSUPPORTED
    except ModuleNotFoundError as exc:
        if exc.name != "openpyxl":
            raise
        payload = _failure_payload(file_path, item_id, "optional dependency unavailable: openpyxl")
        _render(payload, as_json=as_json, error=True)
        return EXIT_MISSING_DEPENDENCY
    except ValueError as exc:
        payload = _failure_payload(file_path, item_id, str(exc))
        _render(payload, as_json=as_json, error=True)
        return EXIT_USAGE
    except (FileExistsError, FileNotFoundError) as exc:
        payload = _failure_payload(file_path, item_id, str(exc))
        _render(payload, as_json=as_json, error=True)
        return EXIT_GENERAL


__all__ = ["cmd_get"]
