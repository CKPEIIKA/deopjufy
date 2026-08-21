"""Helpers for note-like metadata rendering."""

from __future__ import annotations

from pathlib import Path


def infer_note_format(text: str) -> str:
    """Infer a best-effort note serialization format."""
    lowered = text.lower()
    if "<html" in lowered or "</html>" in lowered:
        return "html"
    if any(marker in text for marker in ("# ", "## ", "### ", "- ", "* ", "```", "> ")):
        return "md"
    return "txt"


def write_note_file(target: Path, text: str) -> int:
    """Write note text as UTF-8 and return line count."""
    with target.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write(text.rstrip("\0"))
    return 1 if text else 0
