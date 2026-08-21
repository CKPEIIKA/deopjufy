# deopjufy

`deopjufy` is a native-only command-line utility for inspecting and extracting data
from Origin project files on Unix-like systems.

It focuses on deterministic recovery, plain output files, and explicit
provenance. It does not require Origin, Wine, R, a viewer, a remote service, or
network access during extraction.

## Support status

OPJ and OPJU support is partial. The parser can recover useful content from
tested file families, but it is not a complete implementation of either format
and does not claim whole-project parity with Origin.

The manifest distinguishes parser-backed, heuristic, partial, unsupported, and
exactly verified artifacts. Treat those fields as part of the data contract:
written output alone is not proof that every source object was recovered.

## Install

Development checkout:

```bash
uv sync --extra dev
uv run deopjufy --help
```

XLSX output is optional:

```bash
uv sync --extra xlsx
```

The read-only wxPython viewer is optional and does not change the CLI parser
path:

```bash
uv sync --extra dev --extra viewer
uv run deopjufy-view project.opju
```

## Commands

```text
deopjufy inspect FILE [--json]
deopjufy list FILE [--json]
deopjufy get FILE ITEM_ID [--json]
deopjufy extract FILE [-o OUTDIR] [--format csv|tsv|json|xlsx]
deopjufy strings FILE [--decoded]
deopjufy images FILE [-o OUTDIR]
deopjufy table-scan FILE
deopjufy walk FILE [--json]
deopjufy dump-block FILE --offset N --length N
deopjufy compare LEFT RIGHT [--json]
```

### Inspect and list

`inspect` reports the detected type, parser status, support class, file size,
digest, and warnings. `list` reports discoverable objects and source ranges.
Human-readable output is the default; `--json` is intended for scripts.

```bash
deopjufy inspect project.opju
deopjufy list project.opj --json
```

`list --json` schema version 1 includes the exact document digest and one opaque,
document-bound `id` per item. Do not parse IDs or reuse one after the input bytes
change. Use an ID from that response to retrieve one object without extracting
the whole project:

```bash
deopjufy get project.opju ITEM_ID --json
deopjufy get project.opju ITEM_ID --format csv -o sheet.csv
deopjufy get project.opju ITEM_ID --format jsonl -o sheet.jsonl
deopjufy get project.opju ITEM_ID --format xlsx -o sheet.xlsx
deopjufy get project.opju ITEM_ID --format png -o preview.png
```

The item's `retrieval_formats` field lists accepted formats. A successful JSON
response contains the selected catalog row, materialized artifact metadata, and
inline JSON, text, or base64 content. XLSX requires the `xlsx` extra. Image
formats are offered only for an exact recovered image or parser-linked page
preview. Unsupported materializers remain explicit and return exit code 3.

### Optional batch viewer

`deopjufy-view` is a small recovery browser, not an Origin replacement. It can
open several OPJ/OPJU files at once, builds each project tree from exhaustive
`list --json` output, and lazily calls `get` when an item is activated. Loaded
objects are cached for the document lifetime. Recovery-only, heuristic, raw,
parser-boundary payload, and unknown leaves are hidden initially and can be
exposed with
`View -> Show unknown/recovery evidence`. The window keeps a path-grouped Project
Explorer on the left and a tabbed document area on the right. Grouping
comes from exact catalog `source_object_path` components rather than invented
`Sheets`/`Graphs` type buckets. Native icons distinguish projects, workbooks,
worksheets, graphs, notes, functions, and raw evidence. `View` provides expand,
collapse, and single-child-group unwrapping controls.

Tables use a virtual grid with numeric alignment, rendered-text column sizing,
clipped cell boundaries, row labels, keyboard navigation, copy support, and
frozen metadata rows where real
column long names, units, comments, formulas, types, or X/Y roles were recovered.
Worksheets sharing one exact workbook path open in one document with visible
sheet buttons and lazy per-sheet loading. Parser-linked graph pages and recovered
images use fit-to-window image views with keyboard zoom; notes, graph metadata,
and other structured payloads use text views.

```bash
deopjufy-view first.opju second.opj
```

The action bar contains Open, Export, Export All, and Search. Item export supports
the complete item response, the recovered primary artifact, CLI-backed
CSV/TSV/JSONL/XLSX tables, recovered images or plot previews, and selected cells
as CSV or TSV. Export All invokes the canonical `extract` command and offers
readable CSV, readable XLSX, or complete recovery with an exact byte map. It
always creates a new project-named directory and never requests `--force`.
The same applicable exports are available from a tree leaf's context menu.
`Ctrl+O`, `Ctrl+S`, `Ctrl+F`, `Ctrl+C`, `Ctrl+W`, `Ctrl+Tab`, `Ctrl+PageUp`,
`Ctrl+PageDown`, `Alt+Enter`, `Shift+F10`, `F6`, and `F1` cover the interface
without a mouse; F1 presents the complete binding reference as a three-column
table. Properties are shown as labeled fields rather than raw JSON;
parser warnings remain under `View -> Diagnostics` instead of occupying
permanent screen space.

Opening a project immediately replaces the empty prompt with loading state and,
after catalog discovery, opens the first recoverable table (or the next most
useful object) automatically. Selecting another leaf retrieves it lazily.

The viewer communicates only through subprocess JSON and does not import parser
internals. It displays a plot only when the catalog links that named page to an
exact stored preview; it does not render graph definitions. It does not edit
projects, execute scripts, reconstruct undecoded Origin graph styling, or
broaden the parser's partial format coverage.

The viewer is stateless and XDG-friendly: it creates no application config,
cache, recent-file list, or project database. Process-local caches disappear on
exit, lazy retrieval uses the CLI's cleaned system-temporary directory, and the
only persistent output is a path explicitly selected for export. There are no
hidden network calls.

To test the GUI against a local private project without adding it to the
repository:

```bash
uv sync --extra dev --extra viewer
uv run deopjufy-view /path/to/private-project.opju
```

The repository ignores OPJ/OPJU inputs. Keep private filenames, screenshots,
exports, and diagnostics outside tracked documentation and tests.

### Extract

Extraction writes a directory of artifacts and a `manifest.json`:

```bash
deopjufy extract project.opju -o output/
deopjufy extract project.opj -o output/ --format tsv
```

Possible artifacts include worksheets, matrices, notes, graph metadata or
previews, images, attachments, structured analysis records, human-readable
analysis summaries, exact recovered function and analysis-report XML, resolved
MSer-backed report-reference tables with original offset sidecars,
calculation-reference links, canonical symbol/equation provenance, parser-backed
OPJU project-page and folder directory identities, external-workbook references,
and preserved raw regions. Availability depends on the input and parser evidence.

Version 0.6 adds conservative semantic aliases beside the retained wire-level
names for confirmed directory entries, decoded string-property and
calculation-reference arrays, persistent plot-style source bindings, and exactly
resolved report-reference tables. `semantic_confidence` describes the evidence
for an alias and remains distinct from byte-level `verification`. Preview
presence is likewise reported independently from graph-definition support.

OPJU extraction writes `provenance/semantic_index.json`,
`provenance/symbols.tsv`, and `provenance/relationships.tsv` when semantic
evidence exists. These artifacts expose exact worksheet aliases, report-cell
references and state fields, persistent graph-layer source slots, structural
ranges, and bounded calculation UIDs. A graph binding resolves only when one
parser-owned worksheet matches its sheet and X/Y columns; all candidates remain
visible otherwise. Unresolved links and the absence of an attributable equation
remain explicit. The extractor does not assess external source-code locations.

The default human profile keeps content-bearing primary artifacts. Machine
profiles preserve parser provenance and unresolved bytes:

```bash
deopjufy extract project.opju -o output/ --extended
deopjufy extract project.opju -o output/ --map
```

- `--extended` includes machine-oriented indexes, exact bounded analysis fields,
  decoded-payload classifications, source maps for recovered byte-run functions
  and reports, report-state evidence, and raw recovery artifacts.
- `--map` also writes an ordered byte map whose segments reconstruct the input.
- `--parser-only` disables heuristic object discovery.
- `--fail-on-partial` returns exit code 4 when any required result is partial.
- `--force` permits overwriting existing targets.

Multi-file extraction requires an output directory. Output paths are sanitized,
remain below that directory, and are recorded relative to it in the manifest.

### Strings and images

```bash
deopjufy strings project.opj --min-length 8
deopjufy strings project.opju --decoded
deopjufy images project.opju -o images/
```

`strings --decoded` is OPJU-only and scans parser-decoded payloads. Image carving
validates supported signatures before writing files.

### Table scan

`table-scan` is explicitly heuristic and is separate from parser-owned worksheet
extraction:

```bash
deopjufy table-scan project.opju --format json
```

### Walk and dump-block

```bash
deopjufy walk project.opj
deopjufy walk project.opju --json
deopjufy dump-block project.opju --offset 4096 --length 1024 > block.bin
```

`walk` reports parser-known records and ranges. `dump-block` copies exactly the
requested byte range to stdout.

### Compare

```bash
deopjufy compare output-a/ output-b/
deopjufy compare output-a/manifest.json output-b/manifest.json --compare-bytes
```

## Output contract

Every directory extraction writes `manifest.json`. Important fields include:

- top-level input identity, tool version, status, items, and warnings;
- per-item kind, status, confidence, path, source ranges, extraction method,
  completeness, verification, and conservative semantic alias where available;
- explicit partial or unsupported records for recognized content that could not
  be recovered safely.

Diagnostics go to stderr. Primary command output goes to stdout. Extraction does
not use telemetry, hidden state, or network access.

See [the manifest schema](docs/manifest-schema.md) for the complete field
contract.

## Exit status

- `0`: success
- `1`: general failure
- `2`: invalid command usage
- `3`: unsupported input or required feature
- `4`: partial extraction with `--fail-on-partial`
- `5`: requested optional dependency unavailable
- `6`: corrupted or truncated input

## Fixture and data policy

The repository tracks only small, author-generated Origin fixtures with recorded
provenance. Real-world samples are obtained from documented public records at
test time and are not committed. Unknown-license or private inputs must never be
named, fingerprinted, or described in tracked files.

See [fixture handling](docs/fixture-handling.md).

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

The bounded fast path uses two work-stealing workers, shares completed immutable
fixture extractions between them, and keeps large test artifacts out of the
system temporary filesystem:

```bash
make test
make test-serial
```

Set `PYTEST_WORKERS=N` to choose another bounded worker count. The runner
removes its repository-local temporary tree on success, failure, or interrupt.

Architecture, compatibility boundaries, format notes, and contributor-facing
contracts are indexed in [docs/README.md](docs/README.md).

## License and trademarks

The project is licensed under GPL-3.0-or-later. It is an independent
interoperability utility and contains no Origin application code. Origin and
OriginPro are trademarks of OriginLab Corporation.
