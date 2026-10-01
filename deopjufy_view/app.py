"""Optional wxPython project browser backed only by deopjufy subprocess JSON."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from deopjufy_view.backend import DeopjufyBackend
from deopjufy_view.project_tree import ProjectLeaf

from .frame_catalog import CatalogMixin
from .frame_export import ExportMixin
from .frame_input import InputMixin
from .frame_layout import LayoutMixin
from .frame_state import FrameIds, FrameWidgets, TabState, WorkbookState
from .frame_tabs import TabsMixin
from .frame_widgets import (
    _grid_table_type,
    _image_preview_type,
    _loading_view_type,
    _project_drop_target_type,
)


def _wx_modules() -> tuple[Any, Any]:
    try:
        wx = importlib.import_module("wx")
        wx_grid = importlib.import_module("wx.grid")
    except ModuleNotFoundError as exc:
        raise RuntimeError("wxPython is required; install deopjufier[viewer]") from exc
    return wx, wx_grid


def _frame_type(wx: Any, wx_grid: Any) -> type:
    ids = FrameIds(
        export_json_id=int(wx.NewIdRef()),
        export_artifact_id=int(wx.NewIdRef()),
        export_csv_id=int(wx.NewIdRef()),
        export_tsv_id=int(wx.NewIdRef()),
        export_jsonl_id=int(wx.NewIdRef()),
        export_xlsx_id=int(wx.NewIdRef()),
        export_image_id=int(wx.NewIdRef()),
        export_selection_csv_id=int(wx.NewIdRef()),
        export_selection_tsv_id=int(wx.NewIdRef()),
        export_tool_id=int(wx.NewIdRef()),
        export_all_id=int(wx.NewIdRef()),
        close_tab_id=int(wx.NewIdRef()),
        find_id=int(wx.NewIdRef()),
        properties_id=int(wx.NewIdRef()),
        diagnostics_id=int(wx.NewIdRef()),
        shortcuts_id=int(wx.NewIdRef()),
        expand_all_id=int(wx.NewIdRef()),
        collapse_all_id=int(wx.NewIdRef()),
        unwrap_groups_id=int(wx.NewIdRef()),
        show_evidence_id=int(wx.NewIdRef()),
        open_item_id=int(wx.NewIdRef()),
    )
    widgets = FrameWidgets(
        grid_table=_grid_table_type(wx_grid),
        image_preview=_image_preview_type(wx),
        loading_view=_loading_view_type(wx),
        project_drop_target=_project_drop_target_type(wx),
    )

    class ViewerFrame(
        wx.Frame,
        LayoutMixin,
        CatalogMixin,
        TabsMixin,
        ExportMixin,
        InputMixin,
    ):
        def __init__(self, initial_paths: list[Path]) -> None:
            super().__init__(None, title="deopjufy viewer", size=(1080, 700))
            self.wx = wx
            self.wx_grid = wx_grid
            self.ids = ids
            self.widgets = widgets
            self.backend = DeopjufyBackend(max_workers=2)
            self.closed = False
            self.active_target: tuple[Path, str] | None = None
            self.document_nodes: dict[Path, object] = {}
            self.catalogs: dict[Path, dict[str, Any]] = {}
            self.catalog_leaves: dict[Path, tuple[ProjectLeaf, ...]] = {}
            self.target_leaves: dict[tuple[Path, str], ProjectLeaf] = {}
            self.catalog_rows: dict[tuple[Path, str], dict[str, Any]] = {}
            self.target_nodes: dict[tuple[Path, str], object] = {}
            self.tabs: dict[tuple[Path, str], TabState] = {}
            self.workbooks: dict[tuple[Path, tuple[str, ...]], WorkbookState] = {}
            self.workbooks_by_page: dict[object, WorkbookState] = {}
            self.search_entries: list[tuple[str, object]] = []
            self.pending_targets: set[tuple[Path, str]] = set()
            self.unwrap_single_child_groups = False
            self.show_recovery_evidence = False
            self.context_target: tuple[Path, str] | None = None
            self.search_query = ""
            self.search_index = -1
            self.diagnostics: list[str] = []
            self.pending_project_exports: set[Path] = set()

            self._build_menu()
            self._build_toolbar()
            self._build_content()
            self.status = self.CreateStatusBar(2)
            self.status.SetStatusWidths([-1, self.FromDIP(340)])
            self._bind_events()
            self._show_welcome()
            self._update_export_enabled()
            wx.CallAfter(self._set_initial_sash)
            if initial_paths:
                self.open_paths(initial_paths)

    return ViewerFrame


def main(argv: list[str] | None = None) -> int:
    """Run the optional viewer and return a process exit code."""
    try:
        wx, wx_grid = _wx_modules()
    except RuntimeError as exc:
        print(f"deopjufy-view: {exc}", file=sys.stderr)
        return 5
    paths = [Path(argument) for argument in (sys.argv[1:] if argv is None else argv)]
    wx.Log.SetLogLevel(wx.LOG_Warning)
    application = wx.App(False)
    frame_type = _frame_type(wx, wx_grid)
    frame = frame_type(paths)
    frame.Show()
    application.MainLoop()
    return 0


def cli_entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli_entrypoint()


__all__ = ["cli_entrypoint", "main"]
