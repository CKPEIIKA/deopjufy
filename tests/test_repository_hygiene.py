"""Publication-tree checks for fixture provenance and sensitive references."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from tests.test_core_unit_coverage_utils import _repo_root

ROOT = _repo_root(Path(__file__))
PROVENANCE_PATH = ROOT / "tests" / "fixtures" / "opj-opju-provenance.json"


def _tracked_paths() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(ROOT / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw)


def _tracked_text() -> tuple[tuple[Path, str], ...]:
    text_files: list[tuple[Path, str]] = []
    for path in _tracked_paths():
        if not path.is_file() or path.suffix.lower() in {".opj", ".opju"}:
            continue
        try:
            text_files.append((path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return tuple(text_files)


def test_tracked_origin_fixtures_are_synthetic_and_registered() -> None:
    payload = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    records = payload["fixtures"]
    registered = {ROOT / record["path"]: record for record in records}
    tracked = {path for path in _tracked_paths() if path.is_file() and path.suffix.lower() in {".opj", ".opju"}}

    assert tracked == set(registered)
    for path in sorted(tracked):
        record = registered[path]
        assert path.is_relative_to(ROOT / "tests" / "fixtures" / "synthetic")
        assert record["provenance"] == "synthetic"
        assert record["license_status"] == "author_generated"
        assert record["distribution"] == "in_repo"
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_local_reference_tree_is_not_tracked() -> None:
    tracked_refs = [path.relative_to(ROOT) for path in _tracked_paths() if path.is_relative_to(ROOT / "refs")]

    assert not tracked_refs, "local reference material must remain untracked: " + ", ".join(map(str, tracked_refs))


def test_private_workfiles_and_recovery_bundles_are_ignored() -> None:
    candidates = (
        "refs/private-project." + "opj",
        "refs/private-project." + "opju",
        "private-recovery.zip",
        "private-recovery.7z",
        ".claude/settings.local.json",
    )
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=ROOT,
        input="\n".join(candidates),
        text=True,
        check=True,
        capture_output=True,
    )

    assert set(result.stdout.splitlines()) == set(candidates)


def test_tracked_text_has_no_private_fixture_fingerprints_or_machine_paths() -> None:
    origin_reference = re.compile(r"refs/[A-Za-z0-9_./@-]+\.opju?\b")
    allowed_reference_prefixes = (
        "refs/public/",
        "refs/github/",
        "refs/ropj/",
        "refs/openopj/",
    )
    machine_home = re.compile(
        r"(?:/home/[A-Za-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+\\)",
        re.IGNORECASE,
    )
    private_names = ("v" + "ss.opju", "origin_storage_note_" + "023")
    private_fixture = re.compile(r"\b(?:" + "|".join(map(re.escape, private_names)) + r")\b", re.IGNORECASE)
    split_private_fixture = re.compile(
        r"""["']refs["']\s*/\s*["'](?:test\.opj|vss\.opju)["']""",
        re.IGNORECASE,
    )
    digest = re.compile(r"\b[a-f0-9]{64}\b")

    failures: list[str] = []
    for path, text in _tracked_text():
        relative = path.relative_to(ROOT)
        for match in origin_reference.finditer(text):
            if not match.group().startswith(allowed_reference_prefixes):
                failures.append(f"{relative}: Origin fixture reference has no approved public scope")
        if machine_home.search(text):
            failures.append(f"{relative}: machine-specific home path")
        if private_fixture.search(text) or split_private_fixture.search(text):
            failures.append(f"{relative}: unpublished fixture fingerprint")
        if path.suffix.lower() in {".md", ".py", ".toml", ".sh"} and digest.search(text):
            failures.append(f"{relative}: raw digest belongs in a provenance or checksum registry")

    assert not failures, "\n".join(sorted(set(failures)))
