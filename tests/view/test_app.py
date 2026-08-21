from __future__ import annotations

import pytest

from deopjufy_view import app


def test_viewer_missing_optional_dependency_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable() -> tuple[object, object]:
        raise RuntimeError("wxPython is required; install deopjufier[viewer]")

    monkeypatch.setattr(app, "_wx_modules", unavailable)

    assert app.main([]) == 5
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wxPython is required" in captured.err
