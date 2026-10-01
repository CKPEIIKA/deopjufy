"""Argument parser construction for the CLI."""

from __future__ import annotations

import argparse
from argparse import Action
from collections.abc import Sequence
from pathlib import Path

from deopjufier import __version__

from .metadata import _format_help_epilog
from .render import _json_flag_argument_parser


def _build_parser() -> argparse.ArgumentParser:
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

    parser = argparse.ArgumentParser(
        prog="deopjufy",
        description="Extract useful content from OriginLab OPJ/OPJU files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_format_help_epilog(),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    def _add_verbosity_options(command_parser: argparse.ArgumentParser, *, verbose: bool = False) -> None:
        # --verbose is only offered where a command has step messages to show.
        if verbose:
            command_parser.add_argument("--verbose", action="store_true", help="report extraction steps on stderr")
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
        help="materialized format (default: json); see the item's retrieval_formats",
    )
    get_p.add_argument(
        "-o", "--output", type=Path, default=None, help="output file (default: stdout for non-JSON formats)"
    )
    get_p.add_argument("--force", action="store_true", help="overwrite the selected output file")
    get_p.add_argument(
        "--catalog",
        metavar="FILE",
        default=None,
        help="reuse a 'list --json' catalog of this input ('-' for stdin) instead of rebuilding it",
    )
    _json_flag_argument_parser(get_p)
    _add_verbosity_options(get_p)

    extract_p = commands.add_parser("extract", help="extract recognized content")
    extract_p.add_argument("file", type=Path)
    extract_p.add_argument("-o", "--out", dest="outdir", type=Path, required=True, help="output directory")
    extract_p.add_argument(
        "--format",
        default="csv",
        choices=["csv", "tsv", "json", "xlsx"],
        help="tabular output format (default: csv; xlsx needs openpyxl)",
    )
    extract_p.add_argument("--manifest", type=Path, default=None, help="manifest path (default: OUTDIR/manifest.json)")
    extract_p.add_argument(
        "--raw-dir", type=Path, default=None, help="directory for unknown-region dumps (--extended/--map only)"
    )
    extract_p.add_argument(
        "--raw-min-bytes", type=int, default=1024, help="smallest unknown region to dump (default: 1024)"
    )
    extract_p.add_argument(
        "--text-dir", type=Path, default=None, help="directory for carved text regions (--extended/--map only)"
    )
    extract_p.add_argument(
        "--text-min-bytes", type=int, default=1024, help="smallest text region to carve (default: 1024)"
    )
    extract_p.add_argument(
        "--text-min-length", type=int, default=4, help="shortest printable run inside a text region (default: 4)"
    )
    extract_p.add_argument("--no-images", action="store_true", help="skip embedded image carving")
    extract_p.add_argument("--no-strings", action="store_true", help="skip the strings export (--extended/--map)")
    extract_p.add_argument("--no-tables", action="store_true", help="skip the numeric table scan (--extended/--map)")
    extract_p.add_argument("--no-objects", action="store_true", help="skip Origin object (book, note, graph) export")
    extract_p.set_defaults(human=True, extended=False, map=False)
    extract_profile = extract_p.add_mutually_exclusive_group()
    extract_profile.add_argument(
        "--human",
        action="store_true",
        help="default profile: write trusted human-facing artifacts; omitted ones are listed as skipped",
    )
    extract_profile.add_argument(
        "--extended",
        action=_MachineProfileAction,
        nargs=0,
        help="also write machine outputs: raw and text regions, decoded payload indexes, provenance sidecars",
    )
    extract_profile.add_argument(
        "--map",
        action=_MapProfileAction,
        nargs=0,
        help="--extended plus an exact reconstructable whole-file byte map",
    )
    extract_p.add_argument(
        "--parser-only",
        action="store_true",
        help="limit object discovery and collection to parser-backed candidates",
    )
    extract_p.add_argument(
        "--strings-min-length", type=int, default=4, help="shortest string in the strings export (default: 4)"
    )
    extract_p.add_argument(
        "--table-min-rows", type=int, default=1, help="fewest rows for a scanned numeric table (default: 1)"
    )
    extract_p.add_argument(
        "--table-min-columns", type=int, default=2, help="fewest columns for a scanned numeric table (default: 2)"
    )
    extract_p.add_argument("--fail-on-partial", action="store_true", help="exit 4 when the extraction is partial")
    extract_p.add_argument("--force", action="store_true", help="overwrite extracted files")
    _add_verbosity_options(extract_p, verbose=True)

    strings_p = commands.add_parser("strings", help="print visible text strings")
    strings_p.add_argument("file", type=Path)
    strings_p.add_argument(
        "--encoding", default="ascii", choices=["ascii", "utf16", "latin1", "utf-8"], help="text encoding to scan for"
    )
    strings_p.add_argument("--min-length", type=int, default=4, help="shortest string to print (default: 4)")
    strings_p.add_argument(
        "--decoded",
        action="store_true",
        help="scan decoded OPJU LZ4 payloads instead of raw file bytes",
    )
    _json_flag_argument_parser(strings_p)
    _add_verbosity_options(strings_p)

    images_p = commands.add_parser("images", help="extract embedded images")
    images_p.add_argument("file", type=Path)
    images_p.add_argument("-o", "--out", dest="outdir", type=Path, required=True, help="output directory")
    _json_flag_argument_parser(images_p)
    images_p.add_argument("--force", action="store_true", help="overwrite extracted files")
    _add_verbosity_options(images_p)

    table_p = commands.add_parser("table-scan", help="heuristically scan for numeric tables")
    table_p.add_argument("file", type=Path)
    table_p.add_argument("--min-rows", type=int, default=5, help="fewest rows for a reported table (default: 5)")
    table_p.add_argument("--min-columns", type=int, default=2, help="fewest columns per row (default: 2)")
    table_p.add_argument("--format", default="csv", choices=["csv", "tsv", "json"], help="output format (default: csv)")
    _json_flag_argument_parser(table_p)
    _add_verbosity_options(table_p)

    dump_p = commands.add_parser("dump-block", help="dump raw byte block by offset and length")
    dump_p.add_argument("file", type=Path)
    dump_p.add_argument("--offset", type=int, required=True, help="zero-based start offset")
    dump_p.add_argument("--length", type=int, required=True, help="number of bytes to copy to stdout")
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
    compare_p.add_argument("--quiet", action="store_true", help="print nothing; report only through exit status")

    walk_p = commands.add_parser("walk", help="walk parsed OPJ/OPJU stream structure")
    walk_p.add_argument("file", type=Path)
    _json_flag_argument_parser(walk_p)
    _add_verbosity_options(walk_p)

    return parser
