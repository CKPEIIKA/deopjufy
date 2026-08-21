# Architecture

`deopjufy` has one native parsing path. The command layer selects an operation,
the parser and discovery modules produce typed evidence, and extraction modules
write artifacts plus a manifest. There are no external parser backends or runtime
fallback chains.

## Boundaries

- `cli.py`, `app.py`, and `commands/` own argument parsing, command orchestration,
  stdout/stderr behavior, and exit codes.
- `detect/` identifies the input family from extension and byte signatures.
- `opj/` owns confirmed legacy OPJ records, boundaries, metadata, project trees,
  and value recovery.
- `opju/` owns confirmed OPJU records, decoded regions, tagged payloads, reports,
  tables, and byte-region walking.
- `discovery/` provides bounded heuristic discovery. Its results remain marked as
  heuristic and never become parser claims implicitly.
- `inventory.py` combines parser evidence and optional heuristic discoveries into
  the object inventory used by commands.
- `session.py` owns per-command input state and memoized scans.
- `catalog.py` assigns versioned, document-bound opaque IDs to inventory rows,
  records only parent links justified by exact source paths, and exposes exact
  image-preview links already established by parser evidence.
- `extract/` writes tables, matrices, notes, media, metadata, canonical semantic
  provenance, raw regions, and exact byte-map artifacts from parser evidence.
- `manifest.py` owns the machine-readable extraction record.

Dependencies point from commands to domain parsing and extraction. Parser modules
do not depend on command rendering or output-directory policy.

## Optional viewer boundary

`deopjufy_view/` is an optional read-only client of the public command contract.
It invokes `list --json` and `get --json` with argument vectors, validates schema
version 1, and never imports parser or extractor modules. Batch catalog loading
uses a bounded worker pool; selected objects are retrieved at object granularity
and cached by document digest and item ID. CSV, TSV, JSONL, XLSX, and image file
export invokes the same `get` contract; the GUI does not maintain a second
tabular or image writer. Whole-project export invokes `extract` into a new,
user-selected output directory without forcing overwrites.

The presentation hierarchy is deliberately small: menu bar, an
Open/Export/Export All/Search action bar, a splitter with a path-derived catalog
tree, compact document and sheet
selectors backed by simple page containers, virtual grids or read-only previews,
and a status bar. Recovery evidence is filtered only in the presentation and is
available through a View toggle; the complete catalog remains the backend source.
Diagnostics and formatted properties are on-demand dialogs rather than
persistent parser-development panels.

wxPython and the viewer's XLSX dependency are loaded only by optional paths. The
base package and native CLI retain no GUI dependency. Viewer presentation cannot
promote parser support: partial and unsupported `get` responses remain partial
or unsupported in the UI.

## Parser rules

New structural rules belong in `opj/` or `opju/` and require tests. Extraction
code may serialize or transform parsed records, but it must not create a second
source of parser truth. Generic carving and token scans remain explicitly
heuristic.

Unknown bytes are preserved by machine extraction profiles. Exact byte-map
reconstruction proves byte coverage; it does not imply that every region has a
known semantic meaning.

## State and side effects

The program performs no network access during inspection or extraction. It keeps
no project database and writes only to paths selected by the user. Process-local
caches are bounded and are not persisted.

The optional viewer likewise persists no preferences, recent-file list, cache,
or window state. It therefore does not create non-XDG dotfiles; future persistent
state must use the corresponding XDG base directory rather than the working
directory or an ad hoc home-directory path.
