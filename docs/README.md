# deopjufy documentation

## User manuals

The installed command and format documentation lives in Unix man pages:

- [`deopjufy(1)`](../man/deopjufy.1)
- [`deopjufy-view(1)`](../man/deopjufy-view.1)
- [`deopjufy-manifest(5)`](../man/deopjufy-manifest.5)
- [`deopjufy-formats(7)`](../man/deopjufy-formats.7)

From a checkout, render one with `man ./man/deopjufy.1`. The documents below
are developer contracts and detailed reverse-engineering notes.

## User and compatibility contracts

- [Compatibility status](compatibility.md)
- [Support matrix](support-matrix.md)
- [Manifest schema](manifest-schema.md)
- [Fixture handling](fixture-handling.md)

## Architecture and formats

- [Architecture](architecture.md)
- [OPJ parser boundaries](opj-parser-boundaries.md)
- [OPJU format](opju-format.md)
- [Confirmed format notes](format-notes.md)
- [Cache policy](cache-policy.md)

## Development

- [Coverage scope](coverage.md)

The root [README](../README.md) is intentionally a short front page. This
directory contains stable developer contracts, not local reconnaissance logs or
machine-specific evidence snapshots.
