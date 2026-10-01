from __future__ import annotations

import subprocess
import sys

import pytest

from deopjufy_view import app


def test_importing_viewer_handlers_does_not_load_wx() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import deopjufy_view.app; assert 'wx' not in sys.modules",
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


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
