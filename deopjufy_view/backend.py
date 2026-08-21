"""Subprocess-only adapter for the versioned deopjufy JSON contract."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Final

SUPPORTED_SCHEMA_VERSION: Final[int] = 1
_STRUCTURED_NONZERO_CODES: Final[frozenset[int]] = frozenset({3, 4})


class DeopjufyCommandError(RuntimeError):
    """A CLI invocation failed or violated the JSON boundary."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.payload = payload


def _file_key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_size, stat.st_mtime_ns


class DeopjufyBackend:
    """Run catalog/get commands with bounded batch concurrency and document caching."""

    def __init__(
        self,
        command: Sequence[str] = ("deopjufy",),
        *,
        max_workers: int = 2,
        timeout_seconds: float = 600.0,
    ) -> None:
        if not command:
            raise ValueError("deopjufy command cannot be empty")
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._command = tuple(command)
        self._timeout_seconds = timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="deopjufy-view")
        self._catalog_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._object_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._closed = False

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        if self._closed:
            raise DeopjufyCommandError("backend is closed")
        try:
            return subprocess.run(
                [*self._command, *arguments],
                check=False,
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeopjufyCommandError(str(exc)) from exc

    def _run_json(self, *arguments: str) -> dict[str, Any]:
        completed = self._run(*arguments)

        try:
            decoded = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no command output"
            raise DeopjufyCommandError(
                f"deopjufy returned invalid JSON: {detail}",
                returncode=completed.returncode,
                stderr=completed.stderr,
            ) from exc
        if not isinstance(decoded, dict):
            raise DeopjufyCommandError(
                "deopjufy JSON root is not an object",
                returncode=completed.returncode,
                stderr=completed.stderr,
            )
        payload = decoded
        schema_version = payload.get("schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise DeopjufyCommandError(
                f"unsupported deopjufy schema version: {schema_version!r}",
                returncode=completed.returncode,
                stderr=completed.stderr,
                payload=payload,
            )
        if completed.returncode != 0 and completed.returncode not in _STRUCTURED_NONZERO_CODES:
            raise DeopjufyCommandError(
                str(payload.get("error") or completed.stderr.strip() or "deopjufy command failed"),
                returncode=completed.returncode,
                stderr=completed.stderr,
                payload=payload,
            )
        return payload

    def export_all(
        self,
        path: Path,
        output: Path,
        *,
        output_format: str = "csv",
        complete: bool = False,
    ) -> dict[str, Any]:
        """Extract one whole project through the canonical CLI contract."""
        if output.exists():
            raise DeopjufyCommandError(f"output directory already exists: {output}")
        profile = "--map" if complete else "--human"
        completed = self._run(
            "extract",
            str(path),
            "--out",
            str(output),
            "--format",
            output_format,
            profile,
            "--quiet",
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "deopjufy extract failed"
            raise DeopjufyCommandError(detail, returncode=completed.returncode, stderr=completed.stderr)
        manifest_path = output / "manifest.json"
        try:
            decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeopjufyCommandError(f"export completed without a valid manifest: {exc}") from exc
        if not isinstance(decoded, dict):
            raise DeopjufyCommandError("export manifest root is not an object")
        return decoded

    def catalog(self, path: Path) -> dict[str, Any]:
        """Return one versioned project catalog, cached until the input changes."""
        key = _file_key(path)
        with self._lock:
            cached = self._catalog_cache.get(key)
        if cached is not None:
            return cached
        payload = self._run_json(
            "list",
            str(path),
            "--json",
            "--exhaustive",
            "--include-raw-gaps",
        )
        with self._lock:
            self._catalog_cache[key] = payload
        return payload

    def get(self, path: Path, item_id: str) -> dict[str, Any]:
        """Materialize one item and cache it for this exact document digest."""
        catalog = self.catalog(path)
        document = catalog.get("document")
        document_sha256 = document.get("sha256") if isinstance(document, dict) else None
        if not isinstance(document_sha256, str) or not document_sha256:
            raise DeopjufyCommandError("catalog has no document digest", payload=catalog)
        key = document_sha256, item_id
        with self._lock:
            cached = self._object_cache.get(key)
        if cached is not None:
            return cached
        payload = self._run_json("get", str(path), item_id, "--json")
        with self._lock:
            self._object_cache[key] = payload
        return payload

    def submit_catalogs(self, paths: Iterable[Path]) -> dict[Path, Future[dict[str, Any]]]:
        """Submit independent project opens to the bounded worker pool."""
        return {path: self._executor.submit(self.catalog, path) for path in paths}

    def submit_get(self, path: Path, item_id: str) -> Future[dict[str, Any]]:
        """Submit one lazy object retrieval."""
        return self._executor.submit(self.get, path, item_id)

    def export_item(
        self,
        path: Path,
        item_id: str,
        output_format: str,
        output: Path,
    ) -> dict[str, Any]:
        """Write one selected item through the canonical CLI exporter."""
        catalog = self.catalog(path)
        items = catalog.get("items")
        catalog_items = items if isinstance(items, list) else []
        selected = next(
            (item for item in catalog_items if isinstance(item, dict) and item.get("id") == item_id),
            None,
        )
        formats = selected.get("retrieval_formats") if isinstance(selected, dict) else None
        if not isinstance(formats, list) or output_format not in formats:
            raise DeopjufyCommandError(f"format '{output_format}' is not available for this item")
        return self._run_json(
            "get",
            str(path),
            item_id,
            "--format",
            output_format,
            "--output",
            str(output),
            "--force",
            "--json",
        )

    def submit_export(
        self,
        path: Path,
        item_id: str,
        output_format: str,
        output: Path,
    ) -> Future[dict[str, Any]]:
        """Submit one item export without blocking the GUI thread."""
        return self._executor.submit(self.export_item, path, item_id, output_format, output)

    def submit_export_all(
        self,
        path: Path,
        output: Path,
        *,
        output_format: str = "csv",
        complete: bool = False,
    ) -> Future[dict[str, Any]]:
        """Submit one whole-project extraction without blocking the GUI thread."""
        return self._executor.submit(
            self.export_all,
            path,
            output,
            output_format=output_format,
            complete=complete,
        )

    def close(self) -> None:
        """Stop accepting work and release worker threads."""
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["SUPPORTED_SCHEMA_VERSION", "DeopjufyBackend", "DeopjufyCommandError"]
