# AGENTS.md

<!-- BEGIN COMMON ENGINEERING CONTRACT -->

This common engineering contract is mandatory for agents and contributors.
Project-specific rules may refine runtime versions, tool targets, architecture, protocols, and domain invariants, but may not weaken this contract silently.

## Common mission

Build small, deterministic Python software with explicit boundaries, stable behavior, and no hidden mechanisms.
Keep documentation aligned with actual behavior.

## Common principles

1. Prefer simple, direct implementations over frameworks and speculative abstractions.
2. Build strong domain modules instead of helper sprawl or convenience-wrapper layers.
3. Keep dependencies directional and domain logic independent of presentation, transport, storage, and external services.
4. Prefer composition, explicit data flow, explicit return types, and explicit errors.
5. Keep behavior and output deterministic. Do not add hidden network calls, silent fallbacks, or fake support claims.
6. Use one canonical path for each operation; different interfaces must reuse it.
7. Prefer deleting obsolete paths over adding compatibility shims.
8. Add a dependency only when it removes real complexity.
9. Keep changes minimal, focused, reviewable, and reversible.
10. Preserve user data and backward compatibility unless an intentional breaking change is documented.

## Common architecture rules

1. Each module owns one responsibility and one reason to change.
2. Public APIs are small, stable, typed, and documented where behavior is not obvious.
3. Avoid global mutable state, utility dumping grounds, import-time side effects, and cross-layer shortcuts.
4. Split modules when responsibilities diverge, not merely to satisfy a size metric.
5. Add an abstraction only after real uses establish a shared contract.
6. Keep project-specific boundaries and invariants in the project contract below.

## Common Unix-style rules

1. Prefer plain files and stable, inspectable formats.
2. Send primary command output to stdout and diagnostics to stderr.
3. Make tools scriptable and non-interactive by default.
4. Do not overwrite user data without explicit authorization.
5. Do not write outside an explicitly selected output or state directory.
6. Make partial failure visible; never silently discard or invent data.

## Common Python rules

1. Default to Python 3.11 or newer. An explicit project contract may retain an older supported runtime.
2. Type public functions and data contracts, plus internal boundaries where inference is not obvious.
3. Prefer dataclasses or small typed records for data and explicit exceptions for failures.
4. Keep control flow readable and functions focused.
5. Use boring Python; avoid clever metaprogramming.
6. Use pathlib for paths and context managers for owned resources.

## Common security and data rules

1. Never commit credentials, tokens, private data, proprietary fixtures, or machine-specific paths.
2. Read secrets from environment or settings, never source code.
3. Validate external input at boundaries.
4. Tests must not require private infrastructure or network access unless explicitly marked as integration tests.

## Common quality gate

Use uv as the environment, dependency, and command runner.
A project contract may narrow the Ty target or add stricter checks, but may not omit these checks.

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Ruff must enable at least E, F, I, UP, B, SIM, C90, PLR, and RUF.
The shared line length is 120 and the shared complexity ceiling is 7.
Existing project-specific rules may be stricter.
Every exception must be narrow, documented beside its configuration, and removed when the debt is fixed.

## Common testing rules

1. Test public behavior and contracts rather than implementation trivia.
2. Add a regression test for each bug fix when practical.
3. Keep fixtures small, deterministic, and legal to redistribute.
4. Mark slow, network, hardware, benchmark, and integration tests.
5. Do not weaken assertions merely to make tests pass.

## Common documentation rules

1. Document supported behavior, limitations, inputs, outputs, and failure modes plainly.
2. Keep examples copy-pasteable and free of real secrets and private hosts.
3. Update architecture documentation when a boundary or public contract changes.
4. Distinguish supported, partial, experimental, and unsupported behavior.

## Common work-tracking rules

1. Keep the active backlog in root `TODO.md` and completed work in root `DONE.md`.
2. `TODO.md` contains unfinished, concrete, and verifiable work; move meaningful completions to `DONE.md`.
3. `DONE.md` records outcomes and validation evidence, newest first.
4. A project contract may declare an operational path exception when tooling depends on it. `regression_vibe` retains `WIP/TODO.md` and `WIP/done.md` as that explicit exception.## Common definition of done

A change is done when behavior is implemented, relevant tests and documentation are updated, mandatory quality checks pass, and no known contract mismatch is hidden.

<!-- END COMMON ENGINEERING CONTRACT -->

## Project contract

The rules below are specific to this repository. Where they specify tool targets or runtime support, they refine the common contract.


This file defines the working rules for agents and contributors building this project.

Project name used in this document: `deopjufy`.

`deopjufy` is a small Python command-line utility for inspecting and extracting data from OriginLab project files, mainly `.opju` and `.opj`, on Linux and other Unix-like systems.

The tool must follow a Unix style: small surface area, deterministic behavior, plain files, stdout/stderr discipline, no GUI dependency, no hidden network calls, no project database, and no mandatory Origin installation.

The right mental model is a suckless-style data utility:

- small, sharp, and scriptable
- stable output contract first
- no ornamental architecture
- no magic fallbacks
- no fake support claims
- no convenience feature that weakens determinism

## Mission

Build a simple extractor that can recover useful content from Origin project files:

- worksheets and matrices as CSV/TSV/JSON;
- notes as plain text or Markdown;
- embedded or preview images as PNG/JPEG/SVG where possible;
- graph metadata where recoverable;
- raw blocks with offsets when full parsing is not yet possible;
- a `manifest.json` that records exactly what was found, extracted, skipped, or failed.

The tool does not need to be a full Origin clone. It should extract data first, preserve provenance second, and avoid pretending that unsupported structures are parsed.

## Non-goals

Do not implement these unless explicitly approved:

- editing or writing `.opju` / `.opj` files;
- full Origin graph rendering;
- a graphical interface;
- cloud upload or remote parsing;
- automatic licensing workarounds;
- mandatory Origin/OriginPro runtime;
- silent use of Wine, Origin Viewer, or Windows-only tools;
- a large framework architecture.

## Fixture policy

Treat fixtures as redistributable only when the license is clear.

Preferred order for fixtures:

1. Synthetic `.opj`/`.opju` files you create yourself and explicitly license.
2. Public parser fixtures with clear licenses, for example OpenOPJ's MIT repo.
3. Download scripts for third-party samples instead of committing them.
4. No bundled OriginLab sample projects unless their redistribution license is clear.

Do not publish:

- Origin binaries, SDK files, DLL headers, private symbols
- decompiled Origin code
- large copied chunks of Origin documentation
- Origin sample projects unless redistribution is clearly allowed
- keys, activation/license bypasses, DRM circumvention tools
- confidential files from any source

## Core principles

1. One command should do one thing well.
2. Data goes to stdout when it is a single stream.
3. Logs, warnings, and diagnostics go to stderr.
4. Multi-file extraction requires `-o OUTDIR`.
5. Every extraction should produce a machine-readable manifest.
6. Partial extraction is valid if the manifest clearly marks partial status.
7. Unsupported data must be reported, not guessed.
8. No network access during extraction.
9. No telemetry.
10. No hidden state outside the output directory.
11. Prefer the Python standard library unless a dependency removes real complexity.
12. Prefer fewer moving parts over broader feature claims.
13. Prefer losing a speculative feature over weakening the contract.
14. If behavior cannot be made deterministic, it is not ready.

## Development philosophy

Build this like a rock-solid Unix utility, not like a product platform.

- Keep the CLI obvious and stable.
- Keep modules boring and direct.
- Avoid framework-shaped abstractions until repeated reality demands them.
- Keep optional integrations outside the native core path.
- Preserve unknown bytes instead of inventing structure.
- Treat parser confidence as part of the user contract.
- When in doubt, emit diagnostics and raw artifacts rather than silent guesses.

## Local development workflow

- Use `uv` as the local tool runner for development checks.
- `uv run ruff check deopjufier` for lint.
- `uv run ty check deopjufier` for type checking.
- `uv run pytest` for test execution.
- Coverage work is roadmap work, not a required pre-commit gate.

## Change discipline

- Before every commit, run `ruff`, `ty`, and the test suite.
- Commit each meaningful addition as its own non-amended commit.
- Update `TODO.md` when scope or status changes.
- Update `DONE.md` when a meaningful addition is finished.
- Keep `README.md` aligned with actual behavior. No overclaims.
- Prefer tightening contracts and tests before adding new surface area.
- If a feature is heuristic, mark it as heuristic in code, manifest semantics, and docs.

## Expected command contract

The CLI should expose these commands:

```bash
deopjufy inspect FILE
deopjufy list FILE
deopjufy extract FILE -o out/
deopjufy strings FILE
deopjufy images FILE -o images/
deopjufy table-scan FILE
deopjufy walk FILE
deopjufy dump-block FILE --offset N --length N
deopjufy compare LEFT RIGHT
```

Recommended options:

```bash
--format csv|tsv|json|xlsx
--manifest manifest.json
--verbose
--quiet
--raw-dir raw/
--raw-min-bytes 1024
--no-images
--no-strings
--no-tables
--fail-on-partial
```

Do not make the default command destructive. Do not overwrite files unless `--force` is passed.

## Exit codes

Use stable exit codes:

- `0`: success;
- `1`: general failure;
- `2`: invalid CLI usage;
- `3`: unsupported file or unsupported required feature;
- `4`: partial extraction with `--fail-on-partial`;
- `5`: optional dependency unavailable;
- `6`: corrupted or truncated input.

## Suggested repository layout

```text
deopjufier/
  __init__.py
  app.py
  cli.py
  detect.py
  inventory.py
  session.py
  manifest.py
  errors.py
  io.py
  compare.py
  strings.py
  blocks.py
  extract/
    __init__.py
    discovery_helpers.py
    object_tables.py
    objects.py
    media.py
    metadata.py
    raw_regions.py
    tables.py
    tabular_helpers.py
    path_helpers.py
    graphs.py
    storage_reports.py
  opj/
  opju/
    __init__.py
  tests/
    ...
pyproject.toml
README.md
AGENTS.md
LICENSE
```

Keep module boundaries boring. Avoid abstract class hierarchies until at least two real backends need the same interface.

Repository growth should be resisted unless it buys real clarity:

- split files when they become hard to reason about
- do not split just to simulate architecture
- do not add backends, adapters, or plugin systems speculatively

## Backend policy

**Strict rule:** No external backends are allowed.
This project is native-only. It must not add, depend on, or route parsing work through:
- `liborigin` or related binaries/libraries.
- `Ropj` / R.
- `originpro` / OriginLab runtime tooling.
- Origin Viewer or similar OS-specific viewers.

- No runtime backend switching, adapters, or fallback chains are permitted.
- No optional backend dependencies are part of the CLI contract.
- Feature proposals that expand to external parsing paths are out of scope and must remain rejected.

### Native parser

This is the Linux-first parser backend.

It may perform:

- extension and magic-byte detection;
- container probing;
- compressed-stream probing;
- embedded image detection;
- embedded text detection;
- numeric table heuristics;
- OPJU block inventory;
- raw block export.

It must not claim full `.opju` support unless the structure is actually parsed.

## Manifest contract

Every extraction into a directory should produce `manifest.json`.

Minimal schema:

```json
{
  "input": {
    "path": "file.opju",
    "size_bytes": 123456,
    "sha256": "...",
    "detected_type": "opju"
  },
  "tool": {
    "name": "deopjufy",
    "version": "0.1.0",
    "backend": "native-parser"
  },
  "status": "ok",
  "items": [
    {
      "kind": "worksheet",
      "name": "Book1/Sheet1",
      "status": "extracted",
      "path": "tables/Book1_Sheet1.csv",
      "rows": 100,
      "columns": 4,
      "confidence": 0.98
    },
    {
      "kind": "graph_preview",
      "name": "Graph1",
      "status": "extracted",
      "path": "images/Graph1.png",
      "confidence": 0.9
    },
    {
      "kind": "unknown_block",
      "status": "saved_raw",
      "path": "raw/block_000042.bin",
      "offset": 83210,
      "length": 4096,
      "confidence": 0.0
    }
  ],
  "warnings": []
}
```

Confidence must mean parser confidence, not scientific accuracy.

Inspect/list command output should also include:

- `parser_status`:
  - `ok`, `empty`, `error`, or `unsupported`
- `support_class`:
  - `supported-opj`, `partial-opju`, `unknown`, `corrupt`

## Output naming rules

Use stable, sanitized paths.

Recommended directories:

```text
out/
  manifest.json
  tables/
  matrices/
  notes/
  images/
  metadata/
  raw/
```

Sanitize names by replacing unsafe path characters with `_`. Keep original names in `manifest.json`.

## Reverse-engineering protocol

Follow a clean and reproducible protocol:

1. Start with `file`, `xxd`, `strings`, and size/entropy checks.
2. Record byte offsets and signatures in tests or fixtures.
3. Prefer small, legal sample files created for the project.
4. Never commit proprietary user data.
5. Never claim that a byte block means something unless tested on multiple samples.
6. Add parser notes to `docs/format-notes.md` when a structure is confirmed.
7. Keep raw-block extraction available for unknown structures.

Useful low-level tools:

```bash
file sample.opju
xxd -g 1 -l 256 sample.opju
strings -a sample.opju | head
binwalk sample.opju
7z l sample.opju
```

## Coding style

Use boring Python.

Required:

- Python 3.11+;
- type hints for public functions;
- `argparse` unless there is a strong reason to use a CLI framework;
- dataclasses for simple records;
- explicit exceptions;
- no global mutable parser state;
- streaming reads for large files;
- tests for every parser rule;
- deterministic output order.

Avoid:

- clever metaprogramming;
- hidden caches;
- background services;
- implicit downloads;
- importing optional heavy dependencies at module import time;
- writing files outside the requested output directory.

## Dependency policy

Base install should be minimal.

Suggested extras:

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff", "ty"]
xlsx = ["openpyxl"]
image = ["pillow"]
re = ["python-magic", "construct", "kaitaistruct"]
```

Do not add pandas to the core path unless needed. CSV output can be written with the standard library.

## Local development workflow

Use a local `uv` environment for tool execution:

```bash
cd /path/to/deopjufier
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Before pushing changes:

- `uv run ruff check deopjufier`
- `uv run ty check deopjufier`
- `uv run pytest`

Equivalent shortcuts:

- `make sync` installs/updates dev deps.
- `make check` runs lint/typecheck/tests.

## Testing policy

Tests must cover:

- file-type detection;
- CLI argument parsing;
- manifest generation;
- output path sanitization;
- text extraction;
- image signature extraction;
- numeric table heuristics;
- partial extraction behavior;
- corrupted input behavior;
- unsupported/partial behavior.

Golden files should be tiny and legal to redistribute.

Do not use network in tests.

## Documentation policy

Keep documentation practical.

Every supported command should have:

- one short explanation;
- one example;
- expected output shape;
- failure mode if relevant.

Document limitations plainly. Do not say “supports OPJU” when the actual support is “extracts visible strings, embedded images, and guessed numeric tables from OPJU.”

## Agent roles

Agents may split work this way:

### Parser agent

Responsible for detection, binary probing, stream extraction, and parser notes.

Must update tests and `docs/format-notes.md` for every new confirmed structure.

### CLI agent

Responsible for command behavior, stdout/stderr discipline, exit codes, and shell-friendly examples.

Must keep commands scriptable.

### Backend agent

Reserved for future work while the project stays native-only.
No runtime adapters are active in this phase.

### Test agent

Responsible for fixtures, golden outputs, fuzz/corruption tests, and CI.

Must prevent regressions in output naming and manifest schema.

### Documentation agent

Responsible for `README.md`, examples, limitations, and troubleshooting.

Must keep links current and avoid overpromising.

## Implementation milestones

### v0.1

- `inspect`
- `strings`
- basic manifest
- embedded image carving
- raw block dump
- basic tests

### v0.2

- `.opj` native extraction and discovery
- CSV export
- notes extraction where available

### v0.3

- native `.opju` container/block inventory
- compressed stream probing
- table scanner
- better graph preview extraction

### v0.4

- stable manifest schema
- JSON output mode
- reproducible examples
- packaging with `pipx` / `uv tool`

### v1.0

- stable CLI
- documented backend behavior
- robust partial extraction
- no silent data loss
- useful on real project files

## Definition of done

A change is done only when:

- command behavior is documented;
- output format is deterministic;
- tests pass;
- partial failure is represented in the manifest;
- optional dependencies are not imported unless used;
- no unsupported feature is advertised as supported;
- no user data is committed.
