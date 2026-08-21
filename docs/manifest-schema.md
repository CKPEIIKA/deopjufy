# manifest.json Schema

This schema documents what is currently emitted by native extraction runs.

## Top level

- `input` object
  - `path` (string, required): input path requested by user.
  - `size_bytes` (number, required): exact byte length of input at run time.
  - `sha256` (string, required): digest of the full input bytes.
  - `detected_type` (string, required): `"opj"` or `"opju"`.
- `tool` object
  - `name` (string, required): CLI tool label, currently `"deopjufy"`.
  - `version` (string, required): application version.
  - `backend` (string, required): currently `"native-parser"` in native mode.
- `status` (string, required): extraction command outcome.
  - `ok`
  - `partial`
  - `unsupported`
- `items` (array of objects, required): normalized extraction results.
- `warnings` (array of strings, required): non-fatal issues and parser caveats.

Parser-vs-heuristic distinction:

- Use manifest `status` as the primary command outcome state for extraction runs.
  - Use item `status` for per-artifact extraction states.
- Use `confidence` as the evidence strength; values below `0.75` generally indicate
  heuristic discovery or inferred boundaries.
- A low confidence path should never be interpreted as a hard parser claim.

## Item object

Fields:

- `kind` (string, required): item category.
- `name` (string, required): object name or synthetic label.
- `status` (string, required): one of
  - `extracted`
  - `skipped`
  - `partial`
  - `unsupported`
  - `error`
- `confidence` (number, required): parser confidence score from `0.0` to `1.0`.
- `discovery_type` (string, optional): evidence source such as `parser_window`,
  `parser_backed_hint`, `heuristic_object_scan`, `object_discovery`, `carved`, or
  `unknown_gap`.
- `discovery_method` (string, optional): alias for `discovery_type` preserved for
  explicit per-item discovery reporting.
- `heuristic` (boolean, optional): `false` for parser-backed items, `true` when
  the item depends on carving, token discovery, adjacent-window inference, or
  other heuristic recovery.
- `extraction_method` (string, optional): extractor rule for the produced artifact,
  for example `parser_window`, `table_scan_recon`, `numeric_table_scan`, or
  `metadata_extraction`.
- `extraction_method` defaults to `discovery_method` when omitted.
- `object_kind` (string, optional): workbook/matrix/note/function/graph classification.
- `content_class` (string, optional): conservative content classification. Tables
  currently use `data`, `empty`, `internal_references`, or `corrupt_text`; graph
  preview rows use `image` or `absent`.
- `path` (string, optional): relative output path, where applicable.
- `signature` (string, optional): low-level extracted signature, for example
  `png`, `jpeg`, `gif`, `svg`, or `pdf`.
- `source_object_path` (string, optional): best-effort logical path from parsed/discovered object.
- `rows` (number, optional): row count metadata for tabular artifacts.
- `columns` (number, optional): column count metadata for tabular artifacts.
- `note_payload_type` (string, optional): for note artifacts, one of
  `plain_text`, `markdown_like`, `html_like`, or `unknown_text`.
- `function_name` (string, optional): parser-backed function label.
- `function_formula` (string, optional): parser-backed formula string.
- `function_range` (array[string, string], optional): parser-backed function domain range.
- `function_total_points` (number, optional): parser-backed sample-count for function payload.
- `calculation_label` (string, optional): label stored on an OriginStorage
  calculation and used only for exact, unique report/function attribution.
- `calculation_uid` (number, optional): stored calculation identifier used for
  exact relationship resolution.
- `payload_family` (string, optional): bounded decoded-payload classification.
- `structural_name` (string, optional): retained wire/parser label when a
  conservative public object-role alias is available.
- `semantic_alias` (string, optional): public object-role name supported by the
  stated semantic evidence; it never replaces `structural_name`.
- `semantic_confidence` (string, optional): one of `wire_exact`, `corpus_high`,
  `corpus_medium`, or `hypothesis`. This rates the alias, not scientific
  accuracy or byte verification.
- `preview_status` (string, optional): `present` or `absent`, independent from
  graph-definition parsing and artifact-write `status`.
- `embedded_payload` (boolean, optional): whether the named attachment content is
  physically embedded. External workbook links set this to `false`.
- `source_map_path` (string, optional): machine-profile sidecar mapping every
  decoded output byte to its absolute source-byte offset.
- `replacement_character_count` (number, optional): count of Unicode replacement
  characters that replacement decoding would introduce. A nonzero value means no
  structured text artifact was emitted.
- `control_character_count` (number, optional): count of disallowed controls in a
  structured text candidate, excluding tab and line endings.
- `offset` (number, optional): byte offset origin used for carving or listing.
- `length` (number, optional): byte length for raw or carved artifacts.
- `decoded_length` (number, optional): exact decoded byte length when `length`
  describes the compressed source span of an OPJU region.
- `compression` (string, optional): compression framing, currently `lz4-block`
  for decoded OPJU regions.
- `declared_length` (number, optional): decoded byte count declared by the OPJU
  framing header; this is checked independently from `decoded_length`.
- `family_marker` (string, optional): lowercase hexadecimal marker bytes for a
  known OPJU family framing.
- `marker_offset` (number, optional): absolute family-marker offset.
- `header_offset` (number, optional): absolute decoded-length header offset.
- `stream_offset` (number, optional): LZ4 stream offset relative to the header.
- `framing_rule` (string, optional): one of `origin_storage_anchor`,
  `canonical_family_marker`, or `inferred_family_marker` for current decoded
  OPJU items.
- `range_start` (number, optional): begin offset for a dumped raw range.
- `range_end` (number, optional): end offset (exclusive) for a dumped raw range.
- `error` (string, optional): parser/extractor failure details when status is `error`.
- `source_ranges` (array[object], optional): list of source byte ranges used to derive
  this item, each as `{start: <int>, end: <int>}`.
- `completeness` (string, optional): parser completeness level for the manifest row:
  `complete`, `partial`, or other explicit states used by consumers.
- `completeness` defaults to:
  - `complete` for non-heuristic extracted rows,
  - `partial` for heuristic extracts and all non-extracted rows.
- `verification` (string, optional): item-level evidence marker, one of:
  `unverified`, `synthetic`, `external-parity`, or `exact`.
- `verification` defaults to `unverified` when omitted.

`analysis_summary` items represent a human-readable roll-up of bounded OPJU
calculation records. Their underlying report JSON can include an `equation` field;
absence of that field means it was not recoverable, not that the source had none.
When the human profile collapses byte-identical artifacts, alternate logical names
are preserved in `overlapping_objects` on the retained item.

`analysis_records` is the machine-profile JSON index at
`analyses/origin_storage_analysis_records.json`. Each record has ordered exact
leaf fields. Every field records its tag, syntactic tag path, strict UTF-8 value,
payload range, encoding, and verification. Raw-source fields and records also
record absolute source ranges; decoded-only candidates omit those ranges rather
than approximating them. The item uses `verification=exact` only when every
emitted record is source-attributed, while retaining `completeness=partial` for
the enclosing calculation grammar. Older tolerant semantic values remain in the
separate report and human-summary artifacts and are not mixed into this exact
index.

`semantic_provenance` items point to `provenance/semantic_index.json`,
`provenance/symbols.tsv`, and `provenance/relationships.tsv`. They are retained
by human and machine profiles. Semantic index schema version 2 contains:

- exact descriptor-owned worksheet symbols, aliases, source ranges, metadata,
  formulas, and value shape;
- exact OriginStorage equations and selected parameter, result, operation, and
  table fields with syntactic paths and source attribution;
- bracketed range references resolved only by a unique exact workbook, sheet
  alias, and source-column key;
- calculation-reference regions assigned to a target column only when the
  decoded region lies inside that descriptor's bounded post-payload envelope,
  then assigned to recovered function XML by calculation UID;
- worksheet identities with exact descriptor, SYSTEM-metadata, and
  descriptor-owned report-cell aliases;
- every repeated decoded report-cell URI occurrence, recognized report-grid
  state string/scalar field, and persistent graph-layer X/Y source slot;
- exact graph dataset candidates when the source sheet and ordinal-consistent
  columns match; ambiguous candidates and heuristic graph owners remain
  separately qualified;
- explicit unresolved, ambiguous, no-attributable-equation, and
  `external_code_status=not_assessed` states.

These items use `verification=exact` for emitted values and structural links but
remain `completeness=partial`: exact attribution is not a claim that every
semantic relationship in the project has been decoded. An
`unresolved_semantic_relationships` error marks unresolved links without
discarding the successfully extracted index.

An OPJU attachment filename is only a type hint. Spreadsheet extensions require a
matching ZIP/OOXML or OLE container signature. A mismatch is preserved as an
`origin_storage_region` raw artifact with `status: partial`, never as `.xlsx`/`.xls`.
When a bounded external workbook reference is present, an additional
`external_workbook_link` JSON artifact records the exact UTF-8 reference and
source range with `embedded_payload=false`.

Byte-run decoded function XML uses `payload_family=origin_storage_xml` and
`verification=exact`. Machine profiles also retain the encoded source and a
`function_source_map` sidecar. Function discovery remains heuristic when the
input window begins inside an open literal run. A single discovered window may
emit multiple function items. Regions that still cannot be decoded without
replacement or disallowed controls remain `function.raw.bin` partial artifacts.

Byte-run decoded `analysis_report` items follow the same exact XML and source-map
contract. Machine profiles additionally emit the encoded report window, exact
leaf fields, report attribution metadata, and adjacent recognized report-state
bytes. A missing report UID is restored only from one exact calculation-label
match to a recovered function; ambiguous labels remain unresolved. Parser-backed
note windows that are neither strict text nor exact report XML remain raw partial
artifacts rather than replacement-decoded text.

`report_table` items contain resolved strings only when every descriptor integer
in every column maps uniquely to one complete `mser_strings_pset` source region.
The companion `report_table_offsets` JSON preserves all stored integers, the
one-based string-blob offset rule, and each selected decoded source range. Both
items use exact verification; unsupported or ambiguous reference layouts are not
materialized. Resolved tables retain `structural_name=report_table` beside
`semantic_alias=analysis_report_placeholder_reference_table`.

`byte_map` is emitted only by `extract --map`. Its `byte-map/index.json` sidecar
partitions `[0, input.size_bytes)` into ordered, non-overlapping binary segments.
Concatenating those segment files reconstructs the input exactly, and the index
records both source and reconstructed SHA-256 values. Segment classes describe
evidence boundaries (`parser_bounded`, `carved`, `heuristic`, or `unknown`); they
must not be interpreted as field-level semantic decoding.

`opju_tagged_index` is emitted for OPJU machine profiles. It inventories exact
tagged-family source gaps, hashes, raw paths, explicitly length-framed UTF-8
strings, and exact self-bounded scalar wire frames. Scalar rows expose the field
code, declared size, descriptor bytes, value width, exact value bytes, and a
mechanical little-endian unsigned interpretation; that interpretation does not
claim the Origin field's semantic type. The item remains heuristic and
`completeness=partial` because its outer boundaries come from gaps between stronger
records and the complete container grammar is not decoded.

`opju_column_descriptor_index` points to the companion
`column_descriptors.json`. Each recognized column row records its declared payload
extent, payload encoding, row capacity, stored/missing/trailing-missing counts,
typed `values`, per-cell `cell_kinds`, and lossless hexadecimal `value_bits` for
float cells. Empty strings remain distinct from missing cells. The item is
`complete`/`exact` only when every included column payload matches a supported byte
layout exactly through its terminator.

An assembled OPJU descriptor worksheet uses
`discovery_type=opju_column_descriptor_table`,
`extraction_method=opju_descriptor_table`, `verification=exact`, and
`completeness=complete`. Its `source_ranges` list contains every contributing
column descriptor range. `rows` is the maximum exact row capacity and `columns`
is the number of uniquely owned contiguous dataset columns. Missing cells are
written as empty tabular fields but remain typed as missing in the machine
descriptor index.

The optional worksheet metadata sidecar can include `column_labels`,
`column_types`, `formulas`, and per-column `designation`, `long_name`, `units`,
`comment`, and `formula`. `metadata_status=available_column_metadata_decoded`
means only explicitly framed fields were emitted. `unresolved_fields` names
metadata families that are not complete; absence must not be interpreted as an
empty user value.

## Versioned catalog and item retrieval

`list --json` schema version 1 is the stable catalog boundary for clients. Its
top level includes:

- `schema_version=1`;
- `document`, containing path, exact size, SHA-256, and detected type;
- `tool`, containing name, version, and native backend;
- command status, parser status, warnings, evidence fields, and `items`.

Each item retains its inventory evidence and adds:

- `id`: an opaque `item:v1:` identifier bound to the exact document digest and
  item identity fields;
- `retrieval_formats`: formats accepted by `get` for that item;
- `parent_id` when one unique immediate parent is proven by exact source paths.

IDs are deterministic for unchanged input bytes and inventory identity. Clients
must not parse them, persist them as cross-document identities, or reuse them
after the input changes.

`get FILE ITEM_ID --json` rebuilds the exhaustive catalog for the exact input,
validates the ID, and materializes only the selected target through the canonical
extractor path. Its schema version 1 response includes `document`, `tool`, `item`,
`status`, `artifacts`, and `warnings`. A primary artifact additionally supplies
`content` with `content_encoding` set to `json`, `text`, or `base64`.

Tabular items may also be written as CSV, TSV, JSONL, or optional XLSX with an
explicit output path. JSONL begins with one versioned table/header record
followed by one record per row. Valid carved images advertise their exact image
extension. A parser-confirmed OPJU page with an exact PNG-terminal relationship
adds `preview_offset`, `preview_length`, `preview_extension`, and
`preview_item_id`, and can be retrieved as that stored preview format. A
recognized catalog row without a safe materializer returns an explicit partial
response; no guessed content is substituted.

## Command-output model (list/inspect)

For non-manifest command JSON:

- `parser_status` uses:
  - `ok` (items found)
  - `empty` (recognized format, nothing listable)
  - `error` (parse failure)
  - `unsupported` (format not supported)
- `status` is retained for backward compatibility and reflects command-level outcome.
- `support_class` is included for inspect/list and is one of:
  - `parser`
  - `partial`
  - `heuristic`
  - `failed`
- `coverage_scope` (new): a compatibility-safe support envelope when support_class values are too coarse. It is one of:
  - `recognized`
  - `recovered`
  - `partial`
  - `verified`
  - `failed`
- `verification` (new): evidence confidence marker for recovered/verified claims.
  - `unverified` (default)
  - `synthetic` (reserved for reproducible in-repo generated fixtures)
  - `external-parity` (reserved for externally verified value/parity sources)
- `format_hints` is optional and may include:
  - `magic_type`
  - `magic_offset`
  - `magic_verified`
  - `family_hint`

## Determinism requirements

- `items` are sorted before writing by `(path, kind, name)`.
- Relative paths must never be absolute for extracted artifacts.
- Missing fields are omitted from JSON (not serialized as `null`).
- Parser-backed and heuristic items must remain distinguishable through
  `discovery_type`, `heuristic`, and `confidence`.
- `kind="function_metadata"` records are deterministic sidecars (`function.metadata.json`)
  for parser-backed functions that expose recoverable metadata. Sidecar content is emitted
  as a stable sorted JSON payload with parser evidence and payload window bounds.
- `kind="opju_decoded_region"` records are exact LZ4-decoded payload files. Their
  `offset`/`length` and `range_start`/`range_end` identify the compressed input
  span; `decoded_length` identifies the output byte count. They do not imply that
  the payload has been assigned to a semantic Origin object. `payload_family`
  and the index `classification` object describe the bounded
  post-decompression grammar; unknown and invalid payloads remain explicit.
- `kind="opju_decoded_index"` is the deterministic
  `metadata/opju_decoded/index.json` inventory emitted by the machine profile.
- `kind="opju_calculation_links"` points to the deterministic UID-resolution
  index for calculation-reference payloads. It is complete only when every UID
  resolves to at least one recovered function item.
- `kind="semantic_provenance"` points to the canonical OPJU symbol and analysis
  relationship artifacts. They record worksheet/report ownership, state fields,
  graph source candidates, and target-column ownership in addition to UID
  resolution, and never resolve relationships by long-name similarity.
- `kind="opju_decoded_strings"` is the deterministic TSV inventory of printable
  strings inside decoded regions. Rows retain region/source provenance and are
  omitted by `--no-strings` and all human profiles.
- `kind="opju_numeric_run_inventory"` is a JSON inventory of validated
  `BlobArrElementaryType` base64 runs. It records primitive type, element count,
  payload offset, first values, and source range, but does not claim worksheet or
  matrix ownership. It is omitted by `--no-tables` and all human profiles.

Graph and preview rows have independent status. A graph preview may be extracted
while the corresponding graph definition remains partial. A parser-bounded
missing preview uses `status=skipped`, `content_class=absent`, and an exact
absence marker. Both graph and preview rows expose `preview_status` as `present`
or `absent`; it does not make the graph definition unsupported. Graph item
paths refer to graph metadata rather than preview image bytes.

## Output contract constraints

- `extract` writes `manifest.json` even in partial mode.
- `manifest` entries should describe skipped/failed extraction attempts when relevant, not hide losses.
- All emitted output paths should stay under the requested output or raw directories.
