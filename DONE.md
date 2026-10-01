# deopjufier completed work

Outcomes are recorded newest first. Detailed historical fixture reconnaissance is
intentionally excluded from the publication tree.

## 2026-10-01

- Every CLI option now has help text (17 `extract` options and several
  `get`/`strings`/`table-scan`/`dump-block` options had none). Top-level help
  drops the ASCII mascot (it spelled "Doob") and the hand-written command list
  that duplicated argparse's. Regression: `test_every_option_has_help_text`.
- Removed the `extract` flags `--human-only` and `--human-artifacts-only`
  (breaking). Both behaved exactly like the default `--human` profile while
  the manual described different behavior. The profile group is now
  `--human | --extended | --map` with distinct help text, and `--parser-only`
  is a plain switch.
- `deopjufy ... | head` no longer prints `Exception ignored ... BrokenPipeError`
  and exits 120: the entry point flushes stdout itself and treats a closed
  reader as success. `python -m deopjufier` uses the same entry point.
  Regression: `test_closed_stdout_pipe_exits_quietly`.
- `dump-block` rejects a range that does not fit in the file as a usage error
  (exit 2) instead of exit 6 for a large offset and a `MemoryError` traceback
  for a large length; `io.dump_range` never reads past the file size.
- Truncated input is reported instead of passing as complete. A strict OPJ walk
  whose declared size overruns the file yields `input-truncated` and exit 6 from
  `inspect`, `list`, and `extract` (output is still written, extract status
  partial). An OPJU without the 50-byte end trailer shared by all reference
  files yields `opju-trailer-missing` and partial status. Evidence is recorded in
  `docs/format-notes.md`; regressions in `tests/core/misc/test_truncation_evidence.py`
  and `tests/real/contracts/test_real_truncation.py`.
- Detection now requires the `CPYA`/`CPYUA` signature. An `.opj`/`.opju`
  extension alone used to be accepted at 0.95 confidence, so random bytes
  extracted with `status=ok`; such files are now `detected_type=unknown` with
  reason `extension-without-origin-magic` (exit 3). Tests that fed
  extension-only fake inputs now carry an Origin header. OPJU `support_class`
  uses the OPJ rule: `parser` only when every listed item is parser-backed.
  AGENTS.md now names the published `support_class` vocabulary.
- Rerunning `extract` into an existing output without `--force` destroyed
  the earlier result: writers skipped existing files, the human projection
  then deleted every manifest path it did not retain (355 of 369 files on a
  local real project), and the manifest was rewritten, all with exit 0. `extract` and
  `images` now refuse a non-empty OUTDIR or an existing `--manifest` file
  without `--force` (exit 1, nothing written), and the human projection only
  deletes files written by the current run. Regressions:
  `test_rerun_into_non_empty_output_requires_force`,
  `test_extract_refuses_existing_manifest_path_without_force`,
  `test_human_projection_keeps_files_it_did_not_write`.
- The default human extraction profile no longer drops recovered items
  without a trace. Human-facing items it does not write (partial, unverified,
  empty, or ambiguous ownership) stay in the manifest as `status=skipped`
  with no path and a `human profile omits ...` reason, plus one count
  warning pointing to `--extended`. Never-materialized items keep their own
  status and reason. Before, `tree.opj` reported four partial worksheets as
  if they did not exist. Regressions in `tests/core/misc/test_human_artifacts.py`.
- `extract` and `images` now require `-o/--out`. Previously they wrote silently
  into a directory derived from the input path, outside any selected output
  directory. A missing `-o` is now a usage error (exit 2) and writes nothing.
  Regression: `test_multi_file_commands_require_explicit_output_dir`.
- `io.open_mmap` no longer swallows `OSError`/`ValueError` raised inside the
  caller's block. It re-yielded after the exception, so any I/O error during
  extraction surfaced as `RuntimeError: generator didn't stop after throw()`.
  Regression: `tests/core/misc/test_io_open_mmap.py`.

## 2026-09-12

- Cleared the static audit backlog: named the twelve format/UI constants flagged
  by Ruff, made cache-key-only parameters explicit, removed the inert OPJ payload
  flag and unreachable recovery branch, removed unused fixture imports, and
  clarified the test signal callback. Ruff, formatting, Ty, Vulture, and the
  full suite pass (`784 passed, 1 skipped`).

## 2026-08-21

- Replaced the long mixed-audience README with a compact manpage-style front
  page while retaining the top-level disclaimer. Added packaged manuals for the
  CLI, optional viewer, manifest/catalog contracts, and OPJ/OPJU support terms;
  detailed Markdown remains limited to developer and format-research contracts.
  Groff renders all pages without warnings, isolated wheel and source builds
  contain every manual in its correct section, and the full suite passes
  (`784 passed, 1 skipped`).
- Removed the complete local `refs/` namespace from version control, including
  stale Git pointers and the redundant vendored Ropj archive/source tree. Local
  public or private reference material remains ignored and available only to
  explicit development workflows. Repository hygiene now rejects every tracked
  path below `refs/`. Validation with the local reference directory physically
  absent: Ruff lint and format checks, Ty, and the complete distributable-tree
  suite pass (`508 passed, 46 skipped` optional public-corpus checks).
- Released version 0.6.0 with retained structural labels and conservative,
  confidence-qualified semantic aliases for OPJU directory entries, exact MSer
  string property sets, calculation-reference arrays and members, persistent
  plot-style source bindings, and fully resolved report-reference tables. Graph
  and preview records now expose preview presence independently from graph parse
  status. Unproven folder IDs, child-window types, recalculation states, graph
  ownership, sentinel types, flags, and affine tails remain explicitly
  unpromoted. Validation: Ruff lint and format checks, Ty, and the full offline
  suite pass (`782 passed, 1 skipped`).
- Removed unpublished local-project dependencies from the test suite and
  replaced them with synthetic or provenance-registered public fixtures.
  Removed stale tracked extraction outputs that repeated public source authors'
  machine paths, expanded repository-owned ignore rules for private projects,
  local agent settings, and recovery archives, and added regression checks for
  private fixture fingerprints and Unix, macOS, and Windows home paths. Ruff,
  formatting, Ty, and the full suite pass with 782 tests passed and one
  public-fixture skip.
- Polished the optional viewer's native layout with a readable labeled action
  bar, DPI-aware table widths, strict cell clipping, roomier document/sheet
  selectors, and staged elapsed-time loading views. F1 now presents keyboard
  bindings as an accessible table. Added asynchronous whole-project export via
  the canonical `extract` CLI in readable CSV, readable XLSX, and complete
  byte-map profiles without forced overwrite or persistent GUI state. Exact
  parser-boundary note payloads with no normal materializer are now hidden with
  recovery evidence by default and remain available through the explicit View
  toggle. Ruff, formatting, Ty, focused viewer/recovery tests, and the bounded
  full suite pass with 789 tests passed and one public-fixture skip.
- Recovered byte-run encoded OPJU analysis-report windows as complete validated
  OriginStorage XML instead of replacement-decoded notes. Machine profiles now
  preserve each encoded window, decoded-byte source map, exact leaf fields,
  uniquely matched function label/UID, and adjacent recognized report-state
  envelope. Added deterministic resolution of descriptor report tables whose
  integer cells are one-based offsets into exact MSer string blobs; resolved
  values and original offsets are both exported. Synthetic tests cover both
  grammars, two independent public-record projects lock exact report recovery,
  and private-reference validation recovered every applicable report and report
  table without adding the reference input or its identifiers.
- Removed a duplicate full OPJU descriptor decode between worksheet extraction
  and structural walking, and short-circuited byte-run phase selection only for
  an unbeatable validated XML candidate. The formerly timeout-marginal audited
  public extraction dropped from roughly 43 seconds to roughly 30 seconds while
  retaining the unchanged 45-second test guard.
- Completed the compact optional viewer workflow: unknown and recovery evidence
  is hidden by default but remains toggleable; exact-path sibling worksheets use
  visible lazy sheet selectors; parser-linked stored plot previews and recovered
  images render in fit/zoom views; properties are labeled fields; About reports
  the application, license, Python, wxPython, and openpyxl versions; menus, tree,
  document/sheet switching, search, copy, properties, context menus, export, and
  image zoom have keyboard paths. Tree context menus expose applicable exports,
  including canonical CLI-backed XLSX tables and exact image formats.
- Replaced native GTK notebook widgets with compact simple page containers and
  explicit tab strips, fixed loaded sheets retaining their lazy placeholder, and
  made worker callbacks safe during application teardown. Isolated wxGTK
  regressions cover a real multisheet load, named preview display, immediate
  close during loading, and absence of the prior GTK allocation/callback errors.
  Ruff, formatting, Ty, and the bounded full suite pass with 783 tests passed
  and one public-fixture skip.

## 2026-08-20

- Released package and CLI version 0.5.0 with the native semantic-provenance,
  object-catalog, object-granular retrieval, optional viewer, and bounded
  parallel-test work recorded below.
- Added a versioned `list --json` catalog with deterministic opaque IDs bound to
  exact input bytes, exact parent links where provable, and declared retrieval
  formats.
- Added object-granular `get` retrieval through existing native extractors,
  including canonical JSON/CSV/TSV tables, streaming-friendly JSONL, inline
  text/base64 content, exact raw-range retrieval, and explicit unsupported
  materializers.
- Added an optional read-only wxPython batch viewer whose backend consumes only
  subprocess JSON, validates the schema, loads catalogs with bounded concurrency,
  retrieves activated objects lazily, caches document objects, and presents
  real project trees beside tabbed virtual grids, recovered previews, and text.
  The stripped UI provides only Open/Export/Search, normal menus, metadata rows,
  numeric alignment, keyboard copy/navigation, on-demand diagnostics/properties,
  and format-qualified exports. Ruff, formatting, Ty, and the expanded full suite
  pass with 772 tests passed and one public-fixture skip.
- Corrected complete OPJU descriptor tables to emit encoded Origin column order
  (`A` through `Z`, then `AA` onward) while retaining exact descriptor ranges
  and ordinal-bound metadata; added synthetic and public-record regression locks.
- Bumped the package and CLI version to 0.4.0.
- Added a bounded two-worker test path with work-stealing scheduling, a locked
  cross-worker cache for immutable completed extractions, repository-local
  temporary storage, automatic cleanup, and an explicit serial fallback. The
  expanded full suite completed in 355.82 seconds with 753 passes and one skip,
  down from the 707.89-second serial baseline on the development host.
- Recovered parser-backed OPJU project-page and project-folder directory names
  from confirmed tagged layouts, retaining exact name ranges and syntactic page
  template hints without guessing page kinds, folder membership, or nesting.
- Recovered generic OPJU worksheet identity records from descriptor names,
  exact SYSTEM aliases, and descriptor-owned report-cell URIs. Analysis aliases
  now expose exact or complete structural candidate sets without fuzzy matching.
- Decoded repeated `cell://` report references with decoded/source ranges,
  linked uniquely enclosed report identities to parser-owned worksheets, and
  preserved all framed strings and scalars from recognized report-grid state
  records.
- Exported persistent graph-layer style-holder X/Y source slots, exact candidate
  worksheet/symbol pairs, and separately qualified graph-owner candidates.
- Added a human-readable `provenance/relationships.tsv` projection and synthetic
  regression fixtures for identity, report/state, and graph-binding rules.
- Added a deterministic OPJU semantic provenance index and TSV symbol map that
  expose exact worksheet-column identity, aliases, metadata, formulas, equations,
  parameters, result fields, structural references, and explicit unresolved or
  not-assessed states.
- Linked decoded storage-cell calculation records to their owning descriptor
  columns through exact post-payload envelope containment, then to recovered
  function XML through stored calculation UIDs without name matching.
- Kept byte/source verification separate from semantic completeness and retained
  the canonical provenance artifacts in both human and machine profiles.
- Added synthetic regression coverage for exact long-sheet range resolution,
  column-to-calculation-to-equation attribution, report/state ownership, and
  graph source binding.

## 2026-08-02

- Corrected the OriginStorage repeat-run grammar to its three-based count,
  separated strict field decoding from forensic parent-boundary stopping, and
  validated recovered XML and per-byte source maps against independent local
  differential evidence.
- Added confidence-labeled style-holder source-slot and X/Y descriptor semantics
  while retaining exact neutral representations for unnamed scalar and opaque
  fields.
- Recovered complete OriginStorage function XML from the observed byte-run
  encoding, including multiple logical roots per source window and exact
  per-decoded-byte source maps.
- Classified bounded decoded XML, string-property, calculation-reference, and
  style-holder payload families; calculation UIDs now resolve to recovered
  functions without name guessing.
- Separated graph-definition status from preview availability, promoted only
  structurally proven empty descriptor tables, and recovered external-workbook
  references without claiming linked workbooks are embedded.
- Recovered strict OriginStorage analysis leaf fields into a structured machine
  index with syntactic tag paths and exact per-value raw-source ranges; human
  extraction surfaces every bounded equation in its analysis summary.
- Bumped the package and CLI version to 0.3.0.
- Promoted a confirmed OPJU descriptor family to parser-owned worksheets with
  exact source ownership, encoded column order, typed missing cells, bounded metadata,
  and canonical tabular writers.
- Added lossless machine extraction for recognized OPJU tagged records and column
  payload encodings, while preserving unsupported fields as raw evidence.
- Added exact byte-map reconstruction for machine-profile extraction without
  treating structural ownership as semantic decoding.
- Tightened the human profile so it retains content-bearing parser-owned OPJU
  tables and removes manifest-owned discarded artifacts.
- Fixed tagged-envelope accounting so machine indexes and byte maps use parser
  boundaries consistently.
- Added public-record and synthetic regression locks for confirmed parser rules.
- Simplified publication documentation and removed private fixture names,
  fingerprints, local paths, and stale reconnaissance snapshots.
- Added repository-hygiene tests that require tracked Origin files to be
  author-generated, registered, and checksum-verified, while rejecting private
  reference paths and machine-local paths in tracked text.
- Validated the release tree, exact analysis/function recovery, decoded payload
  classification, and relationship resolution with Ruff, formatting, Ty, and
  the full test suite: 743 passed and 1 skipped.

## Earlier completed foundations

- Implemented native OPJ dataset, window, layer, note, project-tree, attachment,
  worksheet, matrix, function, and graph recovery for confirmed layouts.
- Implemented OPJU detection, framed-region probing, selected decompression,
  OriginStorage reports, media carving, decoded strings, numeric runs, and raw
  region preservation.
- Established deterministic manifests, sanitized output naming, stable exit
  codes, stdout/stderr discipline, and human versus machine extraction profiles.
- Added small author-generated fixtures, public-record download tooling, CLI
  contracts, corruption tests, parity checks, and mandatory quality gates.
