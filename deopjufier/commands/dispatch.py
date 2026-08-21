"""Command dispatch and error-coercion helpers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deopjufier.blocks import find_all_blocks
from deopjufier.commands.metadata import (
    _format_help_epilog,
    _inspect_failure_payload,
    _list_failure_payload,
)
from deopjufier.commands.parser import _build_parser
from deopjufier.commands.support import (
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
    NATIVE_BACKEND,
    SUPPORTED_TYPES,
    _default_output_dir,
    _ensure_file,
    _limit_extract_objects,
    _safe_detect_file,
    _support_class,
)
from deopjufier.detect import DetectedFile
from deopjufier.errors import CorruptedInputError, DeopjufyError, UnsupportedFileError
from deopjufier.session import ExtractionSession

from .get import cmd_get
from .inspect import cmd_inspect
from .list import cmd_list
from .simple import (
    cmd_compare,
    cmd_dump_block,
    cmd_extract,
    cmd_images,
    cmd_strings,
    cmd_table_scan,
    cmd_walk,
)
from .support import _coerce_counts_by_artifact, _has_origin_family_mismatch


def _coerce_input_failure_payload(file_path: Path | None, exc: Exception) -> tuple[dict[str, object], int]:
    detection = None
    if file_path is not None:
        try:
            detection = _safe_detect_file(file_path)
        except OSError:
            detection = None
    safe_path = file_path if file_path is not None else Path("")
    payload, code = _inspect_failure_payload(safe_path, exc, detection)
    return payload, code


def _coerce_command_failure_payload(
    args: argparse.Namespace, command: str, exc: Exception
) -> tuple[dict[str, object], int]:
    path = getattr(args, "file", None)
    if not isinstance(path, Path):
        path = None

    detection = None
    if not isinstance(exc, FileNotFoundError):
        if path is not None:
            try:
                detection = _safe_detect_file(path)
            except OSError:
                detection = None
    if command == "inspect" and path is not None:
        return _inspect_failure_payload(path, exc, detection)
    if command == "list" and path is not None:
        return _list_failure_payload(path, exc, detection)
    return _coerce_input_failure_payload(path, exc)


def _render_command_failure_payload(command: str, payload: dict[str, object], as_json: bool) -> None:
    if command == "inspect":
        from deopjufier.commands.render import _print_inspect_summary

        _print_inspect_summary(payload, as_json=as_json)
        return
    if command == "list":
        from deopjufier.commands.render import _print_list_summary

        _print_list_summary(payload, as_json=as_json)
        return


def _handle_cli_command_error(
    args: argparse.Namespace,
    command: str,
    exc: Exception,
    message: str,
    *,
    fallback_exit_code: int | None = None,
) -> int:
    payload, exit_code = _coerce_command_failure_payload(args, command, exc)
    if command in {"inspect", "list"}:
        _render_command_failure_payload(
            command,
            payload,
            getattr(args, "json", False),
        )
        return exit_code
    print(f"deopjufy: {message}", file=sys.stderr)
    return fallback_exit_code if fallback_exit_code is not None else exit_code


def _map_command_to_handler(command: str):
    handlers = {
        "inspect": cmd_inspect,
        "list": cmd_list,
        "get": cmd_get,
        "extract": cmd_extract,
        "strings": cmd_strings,
        "images": cmd_images,
        "table-scan": cmd_table_scan,
        "dump-block": cmd_dump_block,
        "compare": cmd_compare,
        "walk": cmd_walk,
    }
    return handlers[command]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE

    try:
        return _map_command_to_handler(args.command)(args)  # type: ignore[call-arg]
    except FileNotFoundError as exc:
        return _handle_cli_command_error(args, args.command, exc, f"{exc}")
    except ModuleNotFoundError as exc:
        print(f"deopjufy: missing optional dependency: {exc.name}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    except RuntimeError as exc:
        return _handle_cli_command_error(
            args,
            args.command,
            exc,
            f"error: {exc}",
            fallback_exit_code=EXIT_GENERAL,
        )
    except FileExistsError as exc:
        return _handle_cli_command_error(
            args,
            args.command,
            exc,
            f"error: {exc}",
            fallback_exit_code=EXIT_GENERAL,
        )
    except NotImplementedError as exc:
        return _handle_cli_command_error(
            args,
            args.command,
            exc,
            f"error: {exc}",
            fallback_exit_code=EXIT_GENERAL,
        )
    except CorruptedInputError as exc:
        return _handle_cli_command_error(args, args.command, exc, f"error: {exc}")
    except UnsupportedFileError as exc:
        return _handle_cli_command_error(args, args.command, exc, f"error: {exc}")
    except (TypeError, ValueError) as exc:
        print(f"deopjufy: usage: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_SUCCESS
    except OSError as exc:
        print(f"deopjufy: io error: {exc}", file=sys.stderr)
        return EXIT_GENERAL
    except DeopjufyError as exc:
        print(f"deopjufy: error: {exc}", file=sys.stderr)
        return EXIT_GENERAL


__all__ = [
    "EXIT_CORRUPTED",
    "EXIT_GENERAL",
    "EXIT_MISSING_DEPENDENCY",
    "EXIT_PARTIAL",
    "EXIT_SUCCESS",
    "EXIT_UNSUPPORTED",
    "EXIT_USAGE",
    "NATIVE_BACKEND",
    "SUPPORTED_TYPES",
    "DetectedFile",
    "ExtractionSession",
    "_build_parser",
    "_coerce_command_failure_payload",
    "_coerce_counts_by_artifact",
    "_coerce_input_failure_payload",
    "_default_output_dir",
    "_ensure_file",
    "_format_help_epilog",
    "_has_origin_family_mismatch",
    "_limit_extract_objects",
    "_map_command_to_handler",
    "_render_command_failure_payload",
    "_safe_detect_file",
    "_support_class",
    "find_all_blocks",
    "main",
]
