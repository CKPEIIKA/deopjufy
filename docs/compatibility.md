# Compatibility status

Last updated: 2026-08-21.

`deopjufy` provides partial native recovery for OPJ and OPJU files. Compatibility
statements are limited to confirmed layouts exercised by synthetic fixtures and
samples tied to public records. They are not promises of complete Origin
compatibility.

## Status terms

- `parser_status=ok`: a parser path ran and produced evidence.
- `support_class=parser`: parser-backed evidence exists; it is not a whole-file
  grade.
- `support_class=partial`: at least one relevant gap remains.
- `status=extracted`: an artifact was written.
- `heuristic=true`: scanning, carving, proximity, or token evidence was used.
- `verification=exact`: the emitted bytes or values satisfy a bounded parser
  contract; it does not imply complete project parity.

## OPJ

Confirmed layouts can expose typed datasets, workbook and sheet ownership,
worksheet metadata, matrix shape, notes, functions, project-tree records,
attachments, and selected graph structure.

Coverage remains incomplete for version variants, mask semantics, scripts,
uncommon attachment records, graph styling, stored-preview ownership, and full
unknown-byte classification.

## OPJU

Confirmed layouts can expose selected framed or compressed regions,
OriginStorage records, media, attachments, reports, descriptor-owned worksheets,
typed column payloads, bounded metadata, decoded strings, numeric runs, and raw
source regions. Confirmed relationships can join exact Origin ranges to unique
descriptor columns and post-payload calculation records to their target columns
and recovered functions. Decoded report-cell paths, recognized report-grid state
fields, uniquely resolvable MSer report-table values, byte-run analysis-report
XML, and persistent graph-layer source slots are exposed with exact source
provenance; dataset or graph owners remain candidates unless uniquely proven.
Conservative object-role aliases retain their structural labels and carry a
separate semantic-confidence field. They do not promote unresolved folder IDs,
child-window types, recalculation states, or graph owners.

OPJU discovery is still partly scan-anchored. The parser does not implement the
complete container grammar, complete object graph, or every worksheet, matrix,
function, graph, and metadata encoding.

## Catalog and optional viewer

`list --json` exposes a versioned catalog with opaque IDs bound to the exact
input digest. `get` can lazily materialize supported individual objects through
the same native extraction functions used by directory extraction. Catalog
presence does not guarantee a usable materializer; unsupported retrieval remains
explicit.

The optional wxPython browser is a subprocess client of this contract. It can
batch-open project catalogs, group exact-path sibling sheets, display retrieved
tables and text, display parser-linked stored previews, and request XLSX or image
exports. It does not decode additional worksheets or graph definitions and does
not emulate the full Origin application.

## Human and machine profiles

The default human profile retains content-bearing primary artifacts and the
canonical semantic provenance index while removing low-level machine indexes,
unsupported placeholders, empty or reference-only tables, and discarded
duplicate files. OPJU tables survive only when they are nonempty, parser-owned,
and exactly verified.

`--extended` preserves machine-oriented parser evidence and recovery artifacts.
`--map` additionally partitions the complete input into reconstructable source
segments. Byte reconstruction proves preservation, not semantic decoding.

## Non-claims

The project does not claim:

- full OPJ or OPJU support;
- whole-project parity with Origin;
- whole-application or Origin Viewer parity;
- graph rendering;
- complete version coverage;
- that a parser-backed item proves every related object was found;
- that heuristic output is confirmed structure.
