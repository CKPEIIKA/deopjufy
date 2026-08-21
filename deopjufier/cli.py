"""CLI adapter for the deopjufy application layer."""

from __future__ import annotations

from deopjufier.commands import (
    EXIT_CORRUPTED,
    EXIT_GENERAL,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    EXIT_USAGE,
    NATIVE_BACKEND,
)
from deopjufier.commands import (
    main as app_main,
)


def main(argv: list[str] | None = None) -> int:
    return app_main(argv)


def cli_entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_CORRUPTED",
    "EXIT_GENERAL",
    "EXIT_MISSING_DEPENDENCY",
    "EXIT_PARTIAL",
    "EXIT_SUCCESS",
    "EXIT_UNSUPPORTED",
    "EXIT_USAGE",
    "NATIVE_BACKEND",
    "cli_entrypoint",
    "main",
]
