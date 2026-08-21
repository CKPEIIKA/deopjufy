# OPJ native parser boundaries

OPJ parsing follows a deterministic native sequence for confirmed layouts:

1. global header;
2. datasets;
3. windows and layers;
4. parameters;
5. notes;
6. project tree;
7. attachments.

Records use explicit size and framing fields where the family defines them. The
walker emits exact start/end ranges and typed records; boundary adapters expose
those records to discovery and extraction.

## Implemented records

- dataset headers, payloads, masks, types, row bounds, and typed values;
- window and layer identity, dimensions, state, timestamps, and selected view
  fields;
- curve and column bindings, designations, display metadata, comments, and
  formulas where present;
- annotation names, types, source ranges, and bounded text;
- note metadata and exact text ranges;
- recursive project folders and object ownership;
- confirmed attachment groups and exact payload ranges.

Embedded XML-like tree records are supplemental and do not replace the binary
project hierarchy.

## Remaining risks

- version branches outside the tested corpus;
- mask meaning beyond byte preservation;
- scripts and uncommon annotation or attachment families;
- complete graph styling, legends, 3D records, and preview ownership;
- complete classification of padding and unknown ranges.

Unsupported structures remain visible as machine-profile provenance and must not
be guessed into semantic objects.
