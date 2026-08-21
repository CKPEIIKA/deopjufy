# Fixture handling policy

## Allowed tracked fixtures

The repository may track an Origin project fixture only when it is:

- author-generated for this project;
- small and deterministic;
- explicitly listed in `tests/fixtures/opj-opju-provenance.json`;
- licensed for redistribution.

Tracked synthetic fixtures live under `tests/fixtures/synthetic/`.

## Public real-world samples

Real-world samples must have a stable public record and clear terms. They are
downloaded by an explicit development script, verified by checksum, and remain
untracked. Tests skip cleanly when those files are unavailable.

The tracked tree may contain the public record identifier, expected checksum, and
derived regression contract needed to reproduce the test.

## Disallowed material

Unknown-license, confidential, or private inputs must not be committed. Tracked
files must not contain their:

- filenames or local paths;
- hashes, sizes, offsets, object names, screenshots, or extracted values;
- test identifiers, benchmark rows, manifests, or reconnaissance logs;
- download locations or access instructions.

Such files may be inspected locally, but conclusions must be reproduced with a
legal synthetic fixture before entering parser contracts.

## Required checks

Before adding or changing a fixture:

1. Confirm provenance and redistribution terms.
2. Add or update the provenance registry.
3. Keep the fixture minimal.
4. Add deterministic behavior tests.
5. Run the repository hygiene test and mandatory quality gates.
