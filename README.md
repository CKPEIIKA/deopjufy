# deopjufy

`deopjufy` is a native-only Unix command-line utility for inspecting and
extracting data from Origin project files.

## DISCLAIMER

This software is vibe-coded, use it carefully for one-off tasks.

## NAME

`deopjufy` — recover inspectable content from OPJ and OPJU files.

## SYNOPSIS

```text
deopjufy inspect FILE [--json]
deopjufy list FILE [--json]
deopjufy get FILE ITEM_ID [--json]
deopjufy extract FILE -o OUTDIR [--format csv|tsv|json|xlsx]
deopjufy strings FILE [--decoded]
deopjufy images FILE -o OUTDIR
deopjufy table-scan FILE
deopjufy walk FILE [--json]
deopjufy dump-block FILE --offset N --length N
deopjufy compare LEFT RIGHT [--json]
```

The optional read-only viewer is started with:

```text
deopjufy-view [FILE ...]
```

## DESCRIPTION

The parser is deterministic, native, offline, and intentionally partial. It
does not require Origin, Wine, R, an external parser, or a remote service.
Unsupported and heuristic recovery remains explicit in command output and
`manifest.json`; written output is not proof of complete project recovery.

OPJ and OPJU support is corpus-scoped. The program does not claim complete
format coverage, graph rendering, project editing, or parity with Origin.

## INSTALLATION

```bash
uv sync --extra dev
uv run deopjufy --help
```

Optional XLSX and viewer dependencies:

```bash
uv sync --extra dev --extra xlsx --extra viewer
```

## EXAMPLES

```bash
deopjufy inspect project.opju
deopjufy list project.opju --json
deopjufy extract project.opju -o output/
deopjufy extract project.opju -o complete/ --map
deopjufy-view project.opju
```

Primary output goes to stdout, diagnostics go to stderr, and extraction writes
only below the selected output directory. Existing files are not overwritten
unless `--force` is supplied.

## MANUALS

The installed user documentation is split by Unix manual section:

```bash
man deopjufy
man deopjufy-view
man 5 deopjufy-manifest
man 7 deopjufy-formats
```

From a checkout, use `man ./man/deopjufy.1` and the corresponding local files.
Developer architecture and reverse-engineering contracts remain indexed in
[docs/README.md](docs/README.md).

## DEVELOPMENT

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Real-world projects remain untracked. The repository contains only registered,
author-generated synthetic OPJ/OPJU fixtures; optional public corpora are fetched
explicitly and remain under ignored local paths.

## LICENSE

GPL-3.0-or-later. This is an independent interoperability utility containing no
Origin application code. Origin and OriginPro are trademarks of OriginLab
Corporation.
