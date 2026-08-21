"""Argument parser construction for the CLI."""

from __future__ import annotations

import argparse
from argparse import Action
from collections.abc import Sequence
from pathlib import Path

from deopjufier import __version__

from .metadata import _HELP_MASCOT, _format_help_epilog
from .render import _json_flag_argument_parser


def _build_parser() -> argparse.ArgumentParser:
    class _HumanProfileAction(Action):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            namespace.human = True

    class _HumanOnlyProfileAction(Action):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            namespace.human_only = True
            namespace.human = False
            namespace.human_artifacts_only = False

    class _HumanArtifactsOnlyProfileAction(Action):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            namespace.human_artifacts_only = True
            namespace.human = False
            namespace.human_only = False

    class _MachineProfileAction(Action):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            namespace.extended = True
            namespace.human = False

    class _MapProfileAction(_MachineProfileAction):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            super().__call__(parser, namespace, values, option_string)
            namespace.map = True

    class _ParserOnlyAction(Action):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            namespace.parser_only = True

    parser = argparse.ArgumentParser(
        prog="deopjufy",
        description=f"{_HELP_MASCOT}\nExtract useful content from OriginLab OPJ/OPJU files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_format_help_epilog(),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    def _add_verbosity_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--verbose", action="store_true", help="enable detailed messages")
        command_parser.add_argument("--quiet", action="store_true", help="suppress non-error output")

    commands = parser.add_subparsers(dest="command", required=True)

    inspect_p = commands.add_parser("inspect", help="print basic file detection metadata")
    inspect_p.add_argument("file", type=Path)
    _json_flag_argument_parser(inspect_p)
    _add_verbosity_options(inspect_p)

    list_p = commands.add_parser("list", help="list discoverable items")
    list_p.add_argument("file", type=Path)
    list_p.add_argument(
        "--include-raw-gaps",
        action="store_true",
        help="Include uncovered byte ranges as raw_gap items",
    )
    list_p.add_argument(
        "--exhaustive",
        action="store_true",
        help="Disable OPJU heuristic-kind capping in list output",
    )
    _json_flag_argument_parser(list_p)
    _add_verbosity_options(list_p)

    get_p = commands.add_parser("get", help="materialize one catalog item")
    get_p.add_argument("file", type=Path)
    get_p.add_argument("item_id")
    get_p.add_argument(
        "--format",
        default="json",
        choices=["json", "jsonl", "csv", "tsv", "xlsx", "bmp", "gif", "jpeg", "jpg", "png", "svg"],
    )
    get_p.add_argument("-o", "--output", type=Path, default=None)
    get_p.add_argument("--force", action="store_true", help="overwrite the selected output file")
    _json_flag_argument_parser(get_p)
    _add_verbosity_options(get_p)

    extract_p = commands.add_parser("extract", help="extract recognized content")
    extract_p.add_argument("file", type=Path)
    extract_p.add_argument("-o", "--out", dest="outdir", type=Path, default=None)
    extract_p.add_argument("--format", default="csv", choices=["csv", "tsv", "json", "xlsx"])
    extract_p.add_argument("--manifest", type=Path, default=None)
    extract_p.add_argument("--raw-dir", type=Path, default=None)
    extract_p.add_argument("--raw-min-bytes", type=int, default=1024)
    extract_p.add_argument("--text-dir", type=Path, default=None)
    extract_p.add_argument("--text-min-bytes", type=int, default=1024)
    extract_p.add_argument("--text-min-length", type=int, default=4)
    extract_p.add_argument("--no-images", action="store_true")
    extract_p.add_argument("--no-strings", action="store_true")
    extract_p.add_argument("--no-tables", action="store_true")
    extract_p.add_argument("--no-objects", action="store_true")
    extract_p.set_defaults(
        human=True,
        parser_only=False,
        human_only=False,
        human_artifacts_only=False,
        extended=False,
        map=False,
    )
    extract_profile = extract_p.add_mutually_exclusive_group()
    extract_profile.add_argument(
        "--human",
        action=_HumanProfileAction,
        nargs=0,
        help="extract human-facing artifacts only; skip machine-oriented provenance",
    )
    extract_p.add_argument(
        "--parser-only",
        action=_ParserOnlyAction,
        nargs=0,
        help="limit object discovery and collection to parser-backed candidates",
    )
    extract_profile.add_argument(
        "--human-only",
        action=_HumanOnlyProfileAction,
        nargs=0,
        help="extract human-facing artifacts only; skip unknown-region raw/text output",
    )
    extract_profile.add_argument(
        "--human-artifacts-only",
        action=_HumanArtifactsOnlyProfileAction,
        nargs=0,
        help=(
            "extract human-facing artifacts only; skip unknown-region raw/text output and "
            "skip machine-oriented provenance sidecars"
        ),
    )
    extract_profile.add_argument(
        "--extended",
        action=_MachineProfileAction,
        nargs=0,
        help="include machine-oriented outputs such as raw/text carving and provenance sidecars",
    )
    extract_profile.add_argument(
        "--map",
        action=_MapProfileAction,
        nargs=0,
        help="include machine outputs plus an exact reconstructable whole-file byte map",
    )
    extract_p.add_argument("--strings-min-length", type=int, default=4)
    extract_p.add_argument("--table-min-rows", type=int, default=1)
    extract_p.add_argument("--table-min-columns", type=int, default=2)
    extract_p.add_argument("--fail-on-partial", action="store_true")
    extract_p.add_argument("--force", action="store_true", help="overwrite extracted files")
    _add_verbosity_options(extract_p)

    strings_p = commands.add_parser("strings", help="print visible text strings")
    strings_p.add_argument("file", type=Path)
    strings_p.add_argument("--encoding", default="ascii", choices=["ascii", "utf16", "latin1", "utf-8"])
    strings_p.add_argument("--min-length", type=int, default=4)
    strings_p.add_argument(
        "--decoded",
        action="store_true",
        help="scan decoded OPJU LZ4 payloads instead of raw file bytes",
    )
    _add_verbosity_options(strings_p)

    images_p = commands.add_parser("images", help="extract embedded images")
    images_p.add_argument("file", type=Path)
    images_p.add_argument("-o", "--out", dest="outdir", type=Path, default=None)
    _json_flag_argument_parser(images_p)
    images_p.add_argument("--force", action="store_true", help="overwrite extracted files")
    _add_verbosity_options(images_p)

    table_p = commands.add_parser("table-scan", help="heuristically scan for numeric tables")
    table_p.add_argument("file", type=Path)
    table_p.add_argument("--min-rows", type=int, default=5)
    table_p.add_argument("--min-columns", type=int, default=2)
    table_p.add_argument("--format", default="csv", choices=["csv", "tsv", "json"])
    _json_flag_argument_parser(table_p)
    _add_verbosity_options(table_p)

    dump_p = commands.add_parser("dump-block", help="dump raw byte block by offset and length")
    dump_p.add_argument("file", type=Path)
    dump_p.add_argument("--offset", type=int, required=True)
    dump_p.add_argument("--length", type=int, required=True)
    _add_verbosity_options(dump_p)

    compare_p = commands.add_parser("compare", help="compare two manifest-backed extraction outputs")
    compare_p.add_argument("left", type=Path)
    compare_p.add_argument("right", type=Path)
    _json_flag_argument_parser(compare_p)
    compare_p.add_argument(
        "--compare-bytes",
        action="store_true",
        help="also compare extracted payload bytes",
    )

    walk_p = commands.add_parser("walk", help="walk parsed OPJ/OPJU stream structure")
    walk_p.add_argument("file", type=Path)
    _json_flag_argument_parser(walk_p)
    _add_verbosity_options(walk_p)

    return parser
