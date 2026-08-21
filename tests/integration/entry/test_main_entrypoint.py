"""Module entrypoint smoke coverage for `python -m deopjufier`."""

from __future__ import annotations

import runpy

import pytest


def test_dunder_main_executes_cli_and_exits_with_code(monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, object] = {}

    def _fake_main(_argv: list[str] | None = None) -> int:
        state["called"] = True
        return 42

    monkeypatch.setattr("deopjufier.cli.main", _fake_main)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("deopjufier.__main__", run_name="__main__")

    assert exc.value.code == 42
    assert state["called"] is True
