# deopjufier TODO

Last audited: 2026-08-21.

This file contains unfinished, concrete work only. Completed outcomes belong in
`DONE.md`, newest first.

## Current status

The native parser provides useful partial OPJ and OPJU recovery. It does not
claim complete format support or whole-project parity.

## U01 — complete OPJU structural ownership

Replace remaining scan-anchored discovery with confirmed container records and
stable object identifiers.

Acceptance:

- byte rules are demonstrated by redistributable synthetic fixtures;
- public-record fixtures exercise each supported family;
- unknown regions remain preserved and visible;
- incompatible layouts are rejected instead of guessed.

## U02 — expand independent value parity

Add independently generated expected values for worksheets, matrices, notes,
functions, and metadata using sources that are legal to publish.

Acceptance:

- at least two independent public or author-generated fixtures per promoted
  family;
- complete typed values, dimensions, ownership, missing cells, and metadata are
  compared;
- fixture provenance and license are recorded;
- support wording is promoted only after the parity checks pass.

## U03 — broaden OPJ version and object coverage

Cover additional version branches and currently unsupported records without
weakening existing parser boundaries.

Open areas include mask semantics, scripts, graph styling, preview ownership,
less common attachments, and complete unknown-byte accounting.

Acceptance:

- each new branch has a small legal fixture and exact source-range tests;
- existing output remains deterministic;
- unsupported records stay explicit in the manifest.

## U04 — stabilize public contracts

Finalize the manifest schema, command output, and tabular writer behavior before
the next stable release.

Acceptance:

- schema examples match emitted output;
- CSV, TSV, JSON, and optional XLSX use one canonical data path;
- stdout/stderr and exit-code contracts have CLI tests;
- compatibility changes are documented as intentional.

Schema version 1 catalog IDs and object-granular `get` now provide the CLI/GUI
boundary, including canonical CSV/TSV/JSONL/XLSX tables and exact stored-image
formats. Remaining work is to exercise every promoted object family through
`get`, settle compatibility policy for future schema versions, and freeze the
contract only after that evidence exists.

## U05 — release and repository hygiene

Keep the publication tree free of private data and stale generated evidence.

Acceptance:

- tracked Origin binaries are author-generated and listed in the provenance
  registry;
- real-world regression inputs have a public record and are fetched rather than
  committed;
- tracked text contains no machine-specific paths or unpublished fixture
  fingerprints;
- repository hygiene checks run in the normal test suite;
- package and command smoke tests pass from a clean environment.

## U06 — complete OPJU analysis semantics

Continue beyond canonical symbols, exact MSer-backed report-reference values,
decoded analysis-report XML, state fields, persistent graph source slots, exact
range links, and target-column calculation UIDs into other typed report values,
fit results, custom source-sheet aliases, page-to-folder membership, and ID-based
graph ownership only where the enclosing grammar is confirmed.

Acceptance:

- typed records retain every repeated field occurrence and exact provenance;
- table identifiers and ranges resolve to parser-owned tables without name-only
  guessing;
- equations and parameter arrays remain attributable to their owning analysis;
- unparsed attributes, nested structures, and binary fields remain explicit and
  preserved;
- each promoted grammar has synthetic byte-rule tests and independent public
  fixture coverage.

Remaining semantic names for report-state/style-holder scalars and opaque blobs,
report tables outside the exact MSer-reference family, source worksheet
short/long-name joins, and exact graph-owner IDs require cross-version evidence.
OPJU page and folder names are now recovered, but the numeric directory
membership fields remain uninterpreted. Byte ownership alone is not a
business-field name.

Version 0.6 exposes conservative aliases for roles already supported by exact
wire grammars or high-corpus relationships. Recalculation mode/state,
page-to-folder membership, child-window type codes, image ownership beyond exact
containment, neutral flags, 128-bit sentinels, and affine-tail hypotheses remain
unfinished until the differential-fixture acceptance rules above are met.

## Working rules

For every parser change:

1. Add the smallest legal synthetic fixture that demonstrates the byte rule.
2. Document the confirmed layout in `docs/format-notes.md`.
3. Add focused unit and public-fixture regression tests where practical.
4. Inspect generated artifacts and manifests, not only return codes.
5. Run Ruff, formatting, Ty, and pytest before committing.
