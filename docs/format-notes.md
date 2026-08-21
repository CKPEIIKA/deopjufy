# Confirmed format notes

These notes describe byte rules implemented by the native parser. They are
contracts for accepted layouts, not a complete specification of OPJ or OPJU.

## OPJU project directory identities

Observed OPJU project pages carry an ASCII name field inside a tagged page
header. The parser promotes a name only when the field has the observed tagged
prefix and bounded `SYSTEM` metadata, plus either an adjacent PNG terminal
record or a downstream `__FRAMESRCDATAINFOS` record. The first bounded printable
page-type field is retained as a syntactic template hint. It is not interpreted
as a graph class.

Project-folder entries use a little-endian name length, a tagged NUL-terminated
ASCII name, and a bounded `FolderLastUsed` property containing
`<OriginStorage/>`. The parser exposes the entry names and exact name ranges.
The subsequent numeric membership fields are not yet decoded, so page-to-folder
membership and nesting are not claimed.

Public JSON retains the wire labels `opju_page_directory_name` and
`opju_folder_directory_name` as `structural_name`. Their conservative object-role
aliases are `project_page_directory_entry` and
`project_folder_directory_entry`; `semantic_confidence=corpus_high` does not
claim a decoded hierarchy or child-window type.

When a page record carries adjacent PNG-terminal evidence, the recorded terminal
offset may be joined to a carved image only when it equals that valid PNG's exact
`IEND` terminal offset. The catalog then records the image offset, length,
extension, and opaque item ID on the named page. No proximity-only or
name-similarity association is accepted. This proves preview-byte ownership for
that page record; it does not decode the graph definition or identify the page
template as a graph type.

## OriginStorage leaf fields

An exact leaf field has the bounded form
`<Tag ...>UTF-8 text</Tag>`. The opening and closing tag names must match, the
value must decode strictly as UTF-8, and the value may not contain disallowed
control characters or nested markup.

Machine extraction writes accepted fields in encounter order with their tag,
syntactic tag path, payload range, encoding, and exact verification marker. Raw
source candidates also retain an absolute source range; decoded-only candidates
do not invent one. Invalid or nested values are not coerced. A syntactic path is
context from the bounded tag stream, not proof of a complete enclosing grammar.
Exact field recovery does not promote the enclosing OriginStorage calculation
record to complete semantic support.

## OPJ records

Confirmed OPJ families use explicit little-endian size fields and record-specific
line-feed framing. The sequential walker owns dataset, window/layer, parameter,
note, project-tree, and attachment boundaries.

Dataset decoding is driven by the stored type and element width. Active row
bounds, masks, workbook/sheet suffixes, and column metadata are retained as
separate evidence. Missing or unsupported metadata is not inferred from adjacent
text.

## OPJU framed regions

Accepted compressed regions must provide:

- a recognized bounded framing rule;
- an in-range source span;
- a declared decoded length;
- successful decompression matching that length;
- deterministic provenance offsets.

Ambiguous framing candidates are rejected. Decoded payload ownership remains
separate from the compressed source range.

### Decoded payload families

Every accepted LZ4 region is classified independently after exact decompression.
The current bounded payload grammars are:

- a strict `OriginStorage` XML root, optionally followed by one terminal NUL;
- `0x11111177`, a fixed header followed by a declared NUL-terminated UTF-8
  string blob, a matching string count, and one terminal word;
- calculation-reference arrays with a declared count and fixed 24-byte records;
  accepted records require the observed type, ordinal, sentinel, UID, and
  terminator invariants;
- `0x11111172` style-holder source records containing the declared number of
  `0x1111116d` child records and one terminal word.

Exact MSer payloads retain `structural_name=mser_strings_pset` and expose
`semantic_alias=origin_string_property_set` with `wire_exact` semantic
confidence. Calculation-reference arrays retain `storage_cell_ref_data` and
each original member while adding the aliases
`analysis_result_reference_array`, `analysis_result_slot_ordinal`,
`source_analysis_operation_uid`, `analysis_result_reference_type_code`, and
`unresolved_or_not_applicable_index_sentinel`. The array-level role is
`corpus_high`; the numeric type code and sentinel remain present verbatim.

Style-holder children are byte-bounded completely, but fields without confirmed
business meaning keep neutral names. Cross-serialization differential evidence
identifies the parent as persistent graph-layer data-plot style-holder source
metadata and maps observed descriptor roles `(2, 1)` and `(2, 2)` to X and Y
source columns. The emitted semantic confidence is separate from exact byte
verification: the object is not assumed to be the current live-curve table.
The retained structural name is `data_plot_style_holder_source_info`; its public
role alias is `data_plot_style_prototype_source_binding`.
Opaque child blobs and invariant preamble/tail scalars remain neutral raw values.
A recognized family with invalid framing is reported as invalid rather than
falling through to a different semantic guess.

Calculation references resolve by their stored calculation UID against recovered
function records. Name similarity is not used. The link index is complete only
when every referenced UID resolves.

When a calculation-reference region is wholly contained by a column
descriptor's exact post-payload envelope, that envelope establishes the target
column owner. The contained dependency ordinals are not reinterpreted as target
column ordinals. A recovered calculation UID can then link the owned column to
exact function XML. Regions outside one unique bounded column envelope remain
unowned.

## OPJU tagged records

Tagged machine output preserves raw envelopes and only promotes inner values when
their lengths and terminators are exact. Self-bounded strings must decode as UTF-8
without replacement. Scalar rows retain the original bytes; a mechanical integer
interpretation is not a semantic type claim.

### Column descriptors

A confirmed descriptor contains a bounded dataset name, a declared payload
length, a fixed prelude, and exactly that many payload bytes. Supported payloads
must consume their terminator with no trailing ambiguity.

The implemented payload families include:

- float sequences with explicit row capacity, literals, repeated values, and
  missing-cell runs;
- segmented float sequences;
- compact double literals;
- length-prefixed UTF-8 strings with distinct empty and missing cells;
- unsigned variable-width integers;
- empty columns.

Float cells retain their original 64-bit bit patterns in machine output. Text
exports render explicit missing cells as empty fields while the descriptor index
retains typed missing markers.

### Worksheet ownership

Dataset identities are accepted only when the entire name matches the confirmed
workbook, source-column, and optional sheet grammar. A worksheet is promoted only
when decoded identities are unique and source column indices form one contiguous
set beginning with the first column.

Display order follows the encoded Origin source-column ordinal (`A` through `Z`,
then `AA` and onward). Descriptor encounter order remains recoverable from each
column's exact source range and ordinal-bound metadata.

### Column metadata

Confirmed metadata records bind to a one-based descriptor ordinal. Accepted
fields include bounded display names, X/Y designations, long names, units,
comments, ownership labels, and formulas. Duplicate ordinal bindings are
rejected.

Post-payload metadata must be contained in the exact length-bounded envelope for
that descriptor. Formula text is accepted only from the confirmed single-string
property-set frame and must begin with `=`. Missing fields are reported as
unresolved and are never synthesized.

### Semantic provenance relationships

The canonical OPJU provenance index joins confirmed relationship families:

- a bracketed Origin range resolves only through one exact workbook, sheet
  alias, and source-column identity;
- a `cell://[book]sheet!path` string-property field retains its decoded range and
  compressed source region; unique containment in a descriptor-owned
  post-payload envelope establishes a worksheet identity alias;
- a decoded calculation-reference payload resolves to a target column only
  through containment in that descriptor's bounded post-payload envelope, then
  to function XML through its stored calculation UID;
- style-holder source slots expose exact worksheet, X-column, and Y-column
  selectors. They resolve to a dataset only when one parser-owned worksheet has
  the sheet alias and both ordinal-consistent columns.

Recognized tagged report-grid state envelopes retain every framed string and
scalar. Operation names such as `COKOGrid_SetTree`, `COKOGrid_MainRange`, and
`_TableRange` are literal decoded fields; neutral scalar meanings and a
state-record-to-report owner ID are not inferred.

### MSer report-reference tables

The confirmed `0x11111177` MSer layout has a 24-byte header followed by its
declared NUL-terminated UTF-8 string blob. Descriptor-backed report tables store
one-based offsets into that blob, so a string beginning at decoded byte `N`
has stored reference `N - 23`.

Resolution is promoted only when the report-table owner is unique, every source
range identifies one complete exact MSer record, every table cell is an integer,
and each complete column maps to exactly one source record. Ambiguous or partial
columns remain unresolved. Human output contains the resolved strings; machine
output also retains every original integer and its column source range.
Only after complete exact resolution does the table expose
`semantic_alias=analysis_report_placeholder_reference_table`; unresolved integer
tables keep their existing structural status without that promotion.

Long names are symbol aliases, not relationship keys. Missing or ambiguous
matches remain unresolved, with complete parser-owned candidate sets. A column
with no linked equation is reported as `no_attributable_equation_recovered`;
this is not evidence that no equation ever existed. External source-code mapping
is outside the file parser and is reported as `not_assessed`.

## OriginStorage

OriginStorage filenames are hints, not proof of file type. Attachments are
promoted only when their payload signature matches the requested artifact family.
Malformed or unsupported payloads remain raw with explicit partial status.

Calculation summaries use only bounded fields from recognized records. Tolerant
text parsing does not change source ownership or imply complete note/function
decoding.

### Byte-run encoded XML

Some OriginStorage function windows use an observed byte-run encoding:

- controls `0x01..0x7f` copy the following control-count bytes literally;
- controls `0xc0..0xff` repeat the following byte `(control & 0x3f) + 3`
  times, so `0xc0` emits three bytes;
- `0x00` and `0x80..0xbf` are not byte-run operations. Strict field decoding
  rejects them. Forensic recovery may stop at one only when the remaining bytes
  belong to a parent-bounded envelope, and records the exact control and offset.

A discovered window can begin in an already-open literal run. Recovery therefore
tests a bounded set of possible first-control phases and accepts only complete,
strictly parseable `OriginStorage` XML. This phase selection remains heuristic
and is labeled as such. Each decoded byte retains the absolute source offset that
produced it; repeated bytes map to the repeated-value source byte. A window may
contain more than one complete logical XML root, and each root is emitted
separately.

Parser-owned note-family windows that decode to a calculation with a stored
label are emitted as analysis reports, not replacement-decoded notes. A report
links to a function only through one exact UID match or, when the report omits a
UID, one exact calculation-label match. A recognized tagged state envelope is
linked only when it starts exactly at the report window end and contains a known
report-grid operation literal. Machine output retains the encoded report window,
decoded-byte map, exact leaf fields, and linked state bytes.

### External workbook references

A spreadsheet-looking object is not an embedded workbook unless its bounded
payload has the matching ZIP/OOXML or OLE signature. A bounded NUL-terminated
UTF-8 reference containing a bracketed spreadsheet path and an `[Excel]` marker
is emitted as an external workbook link with its exact source range and
`embedded_payload=false`. The surrounding unclassified source bytes remain
preserved as raw evidence.

## Graph definitions and previews

Graph-definition evidence and preview-image evidence are independent. A valid
preview is an extracted preview artifact, not proof that graph semantics were
decoded. A named OPJU page exposes that preview through `get` only under the
exact terminal-offset relationship described above. An absent preview is
recorded as absent and does not make the graph definition unsupported. Graph
records remain partial until their structural and semantic fields are parsed.

## Images

Image carving validates signatures and format-specific end boundaries before
writing an artifact. Malformed candidates are reported separately and are not
advertised as extracted images.

## Evidence policy

Every promoted byte rule requires a redistributable synthetic fixture and focused
tests. Real-world regression inputs must be tied to a public record and fetched
outside the tracked tree. Local or unknown-license inputs must not appear in
tracked paths, hashes, prose, test identifiers, or expected-output locks.
