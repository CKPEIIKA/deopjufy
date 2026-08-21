# OPJ/OPJU support matrix

This matrix describes the current native parser surface. Every `partial` entry is
corpus-scoped and may reject unrecognized layouts.

| Family | OPJ | OPJU |
| --- | --- | --- |
| Detection and inspection | partial | partial |
| Versioned catalog and lazy `get` | partial | partial |
| Project tree | partial | partial |
| Worksheets | partial | partial |
| Worksheet metadata | partial | partial |
| Matrices | partial | partial |
| Notes | partial | partial |
| Functions | partial | partial |
| Analysis equations and bounded fields | partial | partial |
| Symbol/equation provenance relationships | unsupported | partial |
| Report-reference tables and state fields | unsupported | partial |
| Persistent graph-layer source bindings | partial | partial |
| Scripts | unsupported | unsupported |
| Graph metadata | partial | partial |
| Stored previews | partial | partial |
| Embedded images | partial | partial |
| Attachments | partial | partial |
| Unknown-region preservation | partial | partial |
| Whole-project parity | unsupported | unsupported |

`partial` means at least one bounded native rule exists. It does not mean every
value, field, relationship, version, or object in that family is decoded.

The optional viewer presents this same catalog and lazy-retrieval surface. It
adds grouped multisheet virtual tables, exact stored image/plot-preview display,
tree search, copy, formatted properties, keyboard operation, and
format-qualified table/image export. It does not add parser support, project
editing, script execution, or reconstruction of undecoded Origin graph styling,
and it does not provide whole-application parity.

OPJU project-page and folder directory names are parser-backed for the confirmed
tagged layouts. Page kind, full page-byte ownership, and page-to-folder
membership remain partial.

Promote a row only after legal fixtures, exact source-range tests, and independent
value evidence demonstrate the broader contract.
