# OPJU format status

OPJU support is native, partial, and evidence-driven. The current parser combines
confirmed bounded records with conservative signature and marker discovery. It
does not implement a complete container grammar.

## Confirmed capabilities

- extension and magic detection;
- selected framed-region and compressed-payload decoding;
- exact source ranges and decoded-length checks for accepted frames;
- bounded OriginStorage report, preview, attachment, and calculation records;
- parser-backed project-page and folder directory identities without guessed
  page kinds or hierarchy membership;
- exact page-to-preview links when the page record's PNG terminal offset matches
  one validated embedded PNG;
- complete XML recovery from the observed OriginStorage byte-run encoding, with
  exact decoded-byte source maps and support for multiple logical roots per
  discovered window;
- strictly decoded OriginStorage leaf fields with exact value byte ranges and
  syntactic tag paths, even when the enclosing record remains partial;
- bounded classification of decoded XML, string-property, calculation-reference,
  and style-holder payload families;
- exact target-column ownership for calculation references contained by a
  descriptor's bounded post-payload envelope, plus UID-based links to recovered
  functions;
- exact decoded report-cell references, recognized report-grid state fields,
  and persistent graph-layer X/Y source slots;
- exact report-reference table values when every descriptor integer resolves
  uniquely as a one-based offset into one bounded MSer string blob;
- retained structural labels plus conservative, confidence-qualified public
  aliases for confirmed directory, decoded-reference, string-property,
  persistent style-source, and resolved report-table roles;
- complete byte-run analysis-report XML with exact decoded-byte source maps,
  unique calculation-label/UID function links, and adjacent recognized state
  envelopes;
- a canonical symbol/analysis/relationship index with explicit unresolved and
  candidate states;
- typed column payloads for confirmed descriptor encodings;
- exact dataset ownership and table assembly for complete contiguous descriptor
  groups;
- ordinal-bound display metadata and bounded string/formula fields;
- embedded media validation and carving;
- exact external-workbook reference extraction without advertising a linked
  workbook as embedded content;
- decoded-string and validated numeric-run inventories;
- raw-region preservation and exact byte-map reconstruction.

## Descriptor tables

A descriptor table is promoted only when:

- every included column payload decodes through its exact terminator;
- dataset identities provide one workbook, sheet, and unique source column;
- source column identities form a complete contiguous set;
- display order follows the encoded Origin source-column ordinal;
- metadata is accepted only from confirmed ordinal or bounded post-payload
  records.

Absent metadata remains absent and is listed as unresolved. Parenthesized text,
nearby strings, or matching names are not converted into metadata without a
confirmed frame.

A scan-backed worksheet hint with no discovered rows remains partial. Its
`content_class=empty` describes the scanner result; it does not prove an empty
worksheet or establish object ownership. Only an exactly bounded descriptor
table with confirmed zero dimensions is emitted as a complete empty worksheet.

## Machine profiles

`--extended` writes decoded-region, tagged-record, string, numeric-run, and raw
recovery indexes. `--map` also writes ordered source segments that reconstruct the
input exactly.

Structural byte ownership is distinct from semantic decoding. A byte-map segment
may be preserved and reconstructable while its internal fields remain unknown.
Machine profiles also write `analyses/origin_storage_analysis_records.json` for
strict UTF-8 leaf fields recovered from calculation records. Raw-source fields
retain exact source ranges; decoded-only fields retain payload-relative ranges
without claiming an absolute source range. Every enclosing record remains partial
because unrecognized attributes, nested structures, or binary fields may still
exist.

Both human and machine profiles retain `provenance/semantic_index.json`,
`provenance/symbols.tsv`, and `provenance/relationships.tsv` when semantic
evidence exists. The index records exact descriptor symbols, worksheet aliases,
equations, parameters, result fields, report-cell references, state fields,
graph source slots, structural ranges, and bounded calculation links. It remains
partial because the full analysis and project relationship grammar is not
implemented. External code locations are explicitly not assessed.

Recovered byte-run functions and analysis reports are complete XML artifacts
even though discovery of the first run-control phase is heuristic. `--extended`
preserves each encoded window and a per-decoded-byte absolute source map. For
reports it also retains exact leaf fields and any immediately adjacent recognized
report-state envelope. Decoded-region indexes include their bounded payload
classification, and calculation-reference families also produce a UID-resolution
index when function owners are available.

Graph previews are tracked independently from graph definitions. Exact
page-to-preview links make stored preview bytes retrievable by the named page,
but preview presence or absence never promotes or rejects graph-definition
support by itself. Manifests expose that independent fact as
`preview_status=present|absent`.

## Gaps

The parser still lacks a complete container walk, complete record-family
catalogue, complete project object graph, and broad independent parity for
worksheets, matrices, notes, functions, graphs, and metadata. Source worksheet
short/long-name joins, report tables outside the exact MSer-reference family,
neutral state/style scalar meanings, and ID-based graph ownership remain
unresolved where no confirmed relationship record exists. Incompatible record
families must remain partial or raw.
