"""Optional wxPython project browser backed only by deopjufy subprocess JSON."""

from __future__ import annotations

import importlib
import io
import json
import sys
import time
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from deopjufy_view.backend import DeopjufyBackend, DeopjufyCommandError
from deopjufy_view.model import (
    TabularView,
    default_artifact_suffix,
    find_next_label,
    payload_bytes,
    payload_text,
    table_region_text,
    tabular_view,
)
from deopjufy_view.presentation import SHORTCUT_ROWS, about_text, property_rows, recovered_image
from deopjufy_view.project_tree import (
    ProjectBranch,
    ProjectLeaf,
    build_project_tree,
    catalog_leaves,
    preferred_leaf,
    sibling_sheets,
)


@dataclass
class TabState:
    target: tuple[Path, str]
    page: Any
    host_page: Any
    payload: dict[str, Any]
    table: TabularView | None = None
    grid: Any | None = None


@dataclass
class WorkbookState:
    key: tuple[Path, tuple[str, ...]]
    page: Any
    book: Any
    sheet_pages: dict[tuple[Path, str], Any]
    targets_by_page: dict[object, tuple[Path, str]]
    sheet_buttons: dict[tuple[Path, str], Any]


@dataclass(frozen=True)
class BranchTarget:
    path: Path
    branch: ProjectBranch


def _wx_modules() -> tuple[Any, Any]:
    try:
        wx = importlib.import_module("wx")
        wx_grid = importlib.import_module("wx.grid")
    except ModuleNotFoundError as exc:
        raise RuntimeError("wxPython is required; install deopjufier[viewer]") from exc
    return wx, wx_grid


def _grid_table_type(wx_grid: Any) -> type:
    class JsonGridTable(wx_grid.GridTableBase):
        def __init__(self, data: TabularView) -> None:
            super().__init__()
            self.data = data

        def GetNumberRows(self) -> int:
            return self.data.grid_row_count

        def GetNumberCols(self) -> int:
            return self.data.column_count

        def GetValue(self, row: int, col: int) -> str:
            return self.data.value(row, col)

        def GetRowLabelValue(self, row: int) -> str:
            return self.data.row_label(row)

        def GetColLabelValue(self, col: int) -> str:
            return self.data.headers[col] if col < len(self.data.headers) else f"Column {col + 1}"

        def IsEmptyCell(self, row: int, col: int) -> bool:
            return self.GetValue(row, col) == ""

    return JsonGridTable


def _image_preview_type(wx: Any) -> type:
    class ImagePreview(wx.Panel):
        def __init__(self, parent: Any, payload: bytes) -> None:
            super().__init__(parent, style=wx.BORDER_NONE)
            self.image = wx.Image(io.BytesIO(payload))
            self.zoom: float | None = None
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
            self.SetToolTip("Plot preview: +/- zoom, 0 fit")
            self.Bind(wx.EVT_PAINT, self._on_paint)
            self.Bind(wx.EVT_SIZE, self._on_size)
            self.Bind(wx.EVT_KEY_DOWN, self._on_key)

        def IsOk(self) -> bool:
            return bool(self.image.IsOk())

        def _fit_scale(self) -> float:
            width, height = self.GetClientSize()
            if width <= 0 or height <= 0 or self.image.GetWidth() <= 0 or self.image.GetHeight() <= 0:
                return 1.0
            return min(1.0, (width - 24) / self.image.GetWidth(), (height - 24) / self.image.GetHeight())

        def _on_paint(self, _event: object) -> None:
            dc = wx.AutoBufferedPaintDC(self)
            dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
            dc.Clear()
            scale = self.zoom if self.zoom is not None else self._fit_scale()
            width = max(1, round(self.image.GetWidth() * scale))
            height = max(1, round(self.image.GetHeight() * scale))
            bitmap = wx.Bitmap(self.image.Scale(width, height, wx.IMAGE_QUALITY_HIGH))
            client_width, client_height = self.GetClientSize()
            dc.DrawBitmap(bitmap, max(0, (client_width - width) // 2), max(0, (client_height - height) // 2), True)

        def _on_size(self, event: Any) -> None:
            self.Refresh()
            event.Skip()

        def _on_key(self, event: Any) -> None:
            key = event.GetKeyCode()
            if key in {ord("+"), wx.WXK_ADD, wx.WXK_NUMPAD_ADD}:
                self.zoom = min(8.0, (self.zoom or self._fit_scale()) * 1.25)
            elif key in {ord("-"), wx.WXK_SUBTRACT, wx.WXK_NUMPAD_SUBTRACT}:
                self.zoom = max(0.1, (self.zoom or self._fit_scale()) / 1.25)
            elif key in {ord("0"), wx.WXK_NUMPAD0}:
                self.zoom = None
            else:
                event.Skip()
                return
            self.Refresh()

    return ImagePreview


def _loading_view_type(wx: Any) -> type:
    class LoadingView(wx.Panel):
        def __init__(self, parent: Any, title: str, stage: str, detail: str) -> None:
            super().__init__(parent, style=wx.BORDER_NONE)
            self.started = time.monotonic()
            self.timer = wx.Timer(self)
            outer = wx.BoxSizer(wx.VERTICAL)

            heading = wx.BoxSizer(wx.HORIZONTAL)
            activity = wx.ActivityIndicator(self)
            activity.Start()
            heading.Add(activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
            title_control = wx.StaticText(self, label=title)
            title_font = title_control.GetFont()
            title_font.MakeLarger()
            title_font.MakeBold()
            title_control.SetFont(title_font)
            heading.Add(title_control, 0, wx.ALIGN_CENTER_VERTICAL)
            outer.Add(heading, 0, wx.ALIGN_CENTER | wx.BOTTOM, self.FromDIP(12))

            stage_control = wx.StaticText(self, label=stage)
            stage_font = stage_control.GetFont()
            stage_font.MakeBold()
            stage_control.SetFont(stage_font)
            outer.Add(stage_control, 0, wx.ALIGN_CENTER | wx.BOTTOM, self.FromDIP(6))
            detail_control = wx.StaticText(self, label=detail, style=wx.ALIGN_CENTER)
            detail_control.Wrap(self.FromDIP(560))
            outer.Add(detail_control, 0, wx.ALIGN_CENTER | wx.BOTTOM, self.FromDIP(14))

            self.progress = wx.Gauge(self, range=100, size=(self.FromDIP(420), self.FromDIP(8)))
            outer.Add(self.progress, 0, wx.ALIGN_CENTER | wx.BOTTOM, self.FromDIP(8))
            self.elapsed = wx.StaticText(self, label="Starting native parser…")
            outer.Add(self.elapsed, 0, wx.ALIGN_CENTER)
            self.SetSizer(outer)

            self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
            self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
            self.timer.Start(120)

        def _on_timer(self, _event: object) -> None:
            self.progress.Pulse()
            seconds = max(0, round(time.monotonic() - self.started))
            self.elapsed.SetLabel(f"Native parser working · {seconds} s elapsed")

        def _on_destroy(self, event: Any) -> None:
            if event.GetEventObject() is self:
                self.timer.Stop()
            event.Skip()

    return LoadingView


def _frame_type(wx: Any, wx_grid: Any) -> type:
    grid_table = _grid_table_type(wx_grid)
    image_preview = _image_preview_type(wx)
    loading_view = _loading_view_type(wx)
    export_json_id = int(wx.NewIdRef())
    export_artifact_id = int(wx.NewIdRef())
    export_csv_id = int(wx.NewIdRef())
    export_tsv_id = int(wx.NewIdRef())
    export_jsonl_id = int(wx.NewIdRef())
    export_xlsx_id = int(wx.NewIdRef())
    export_image_id = int(wx.NewIdRef())
    export_selection_csv_id = int(wx.NewIdRef())
    export_selection_tsv_id = int(wx.NewIdRef())
    export_tool_id = int(wx.NewIdRef())
    export_all_id = int(wx.NewIdRef())
    close_tab_id = int(wx.NewIdRef())
    find_id = int(wx.NewIdRef())
    properties_id = int(wx.NewIdRef())
    diagnostics_id = int(wx.NewIdRef())
    shortcuts_id = int(wx.NewIdRef())
    expand_all_id = int(wx.NewIdRef())
    collapse_all_id = int(wx.NewIdRef())
    unwrap_groups_id = int(wx.NewIdRef())
    show_evidence_id = int(wx.NewIdRef())
    open_item_id = int(wx.NewIdRef())

    class ViewerFrame(wx.Frame):
        def __init__(self, initial_paths: list[Path]) -> None:
            super().__init__(None, title="deopjufy viewer", size=(1080, 700))
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
            self.status.SetStatusWidths([-1, 250])
            self._bind_events()
            self._show_welcome()
            self._update_export_enabled()
            wx.CallAfter(self._set_initial_sash)
            if initial_paths:
                self.open_paths(initial_paths)

        def _build_menu(self) -> None:
            file_menu = wx.Menu()
            file_menu.Append(wx.ID_OPEN, "&Open projects…\tCtrl+O")
            file_menu.AppendSubMenu(self._export_menu(), "&Export")
            self.export_all_menu_item = file_menu.Append(
                export_all_id,
                "Export &all project content…\tCtrl+Shift+S",
            )
            file_menu.Append(close_tab_id, "&Close tab\tCtrl+W")
            file_menu.AppendSeparator()
            file_menu.Append(wx.ID_EXIT, "E&xit")

            view_menu = wx.Menu()
            view_menu.Append(find_id, "&Find in project…\tCtrl+F")
            view_menu.Append(properties_id, "&Properties…\tAlt+Enter")
            view_menu.Append(diagnostics_id, "&Diagnostics…")
            view_menu.AppendSeparator()
            view_menu.Append(expand_all_id, "&Expand all branches\tCtrl+Shift+E")
            view_menu.Append(collapse_all_id, "&Collapse all branches\tCtrl+Shift+C")
            unwrap_item = view_menu.AppendCheckItem(unwrap_groups_id, "&Unwrap single-child groups")
            unwrap_item.Check(self.unwrap_single_child_groups)
            evidence_item = view_menu.AppendCheckItem(show_evidence_id, "Show &unknown/recovery evidence")
            evidence_item.Check(self.show_recovery_evidence)

            help_menu = wx.Menu()
            help_menu.Append(shortcuts_id, "&Keyboard shortcuts\tF1")
            help_menu.Append(wx.ID_ABOUT, "&About")

            menu_bar = wx.MenuBar()
            menu_bar.Append(file_menu, "&File")
            menu_bar.Append(view_menu, "&View")
            menu_bar.Append(help_menu, "&Help")
            self.SetMenuBar(menu_bar)

        def _export_menu(self, target: tuple[Path, str] | None = None) -> Any:
            menu = wx.Menu()
            json_item = menu.Append(export_json_id, "Item response (JSON)…")
            artifact_item = menu.Append(export_artifact_id, "Recovered artifact…")
            menu.AppendSeparator()
            format_items = {
                "csv": menu.Append(export_csv_id, "Table as CSV…"),
                "tsv": menu.Append(export_tsv_id, "Table as TSV…"),
                "jsonl": menu.Append(export_jsonl_id, "Table as JSONL…"),
                "xlsx": menu.Append(export_xlsx_id, "Table as Excel workbook (XLSX)…"),
            }
            image_item = menu.Append(export_image_id, "Image or plot preview…")
            menu.AppendSeparator()
            selection_items = (
                menu.Append(export_selection_csv_id, "Selected cells as CSV…"),
                menu.Append(export_selection_tsv_id, "Selected cells as TSV…"),
            )
            if target is not None:
                row = self.catalog_rows.get(target, {})
                formats = row.get("retrieval_formats")
                available = set(formats) if isinstance(formats, list) else set()
                state = self.tabs.get(target)
                json_item.Enable(state is not None)
                artifact_item.Enable(state is not None and payload_bytes(state.payload) is not None)
                for output_format, item in format_items.items():
                    item.Enable(output_format in available)
                image_item.Enable(
                    bool(available.intersection({"bmp", "gif", "jpeg", "jpg", "png", "svg"}))
                    or (state is not None and recovered_image(state.payload) is not None)
                )
                for item in selection_items:
                    item.Enable(state is not None and state.table is not None)
            return menu

        def _build_toolbar(self) -> None:
            self.action_bar = wx.Panel(self, style=wx.BORDER_NONE)
            action_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.open_button = wx.Button(self.action_bar, wx.ID_OPEN, "Open…")
            self.open_button.SetToolTip("Open one or more OPJ/OPJU projects (Ctrl+O)")
            self.export_button = wx.Button(self.action_bar, export_tool_id, "Export ▾")
            self.export_button.SetToolTip("Export the current item (Ctrl+S)")
            self.export_all_button = wx.Button(self.action_bar, export_all_id, "Export All…")
            self.export_all_button.SetToolTip("Extract all content from the active project (Ctrl+Shift+S)")
            for button in (self.open_button, self.export_button, self.export_all_button):
                button.SetMinSize((-1, self.FromDIP(32)))
                action_sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
            action_sizer.AddStretchSpacer()
            self.search = wx.SearchCtrl(
                self.action_bar,
                style=wx.TE_PROCESS_ENTER,
                size=(self.FromDIP(270), self.FromDIP(32)),
            )
            self.search.SetDescriptiveText("Search project")
            self.search.ShowCancelButton(True)
            action_sizer.Add(self.search, 0, wx.ALIGN_CENTER_VERTICAL)
            self.action_bar.SetSizer(action_sizer)
            action_sizer.SetSizeHints(self.action_bar)

        def _build_content(self) -> None:
            self.splitter = wx.SplitterWindow(self)
            self.splitter.SetMinimumPaneSize(180)
            self.splitter.SetSashGravity(0.25)
            project_panel = wx.Panel(self.splitter)
            project_sizer = wx.BoxSizer(wx.VERTICAL)
            project_header = wx.StaticText(project_panel, label="Project Explorer")
            project_font = project_header.GetFont()
            project_font.MakeBold()
            project_header.SetFont(project_font)
            project_sizer.Add(
                project_header,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
                self.FromDIP(10),
            )
            project_sizer.AddSpacer(self.FromDIP(7))
            self.tree = wx.TreeCtrl(
                project_panel,
                style=(
                    wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE | wx.TR_HIDE_ROOT | wx.TR_FULL_ROW_HIGHLIGHT
                ),
            )
            self.tree.SetMinSize((200, -1))
            self._assign_tree_images()
            self.root = self.tree.AddRoot("Projects")
            project_sizer.Add(self.tree, 1, wx.EXPAND)
            project_panel.SetSizer(project_sizer)

            self.preview_host = wx.Simplebook(self.splitter)
            self._build_message_page()
            documents_panel = wx.Panel(self.preview_host)
            documents_sizer = wx.BoxSizer(wx.VERTICAL)
            self.document_tab_bar = wx.ScrolledWindow(documents_panel, style=wx.HSCROLL | wx.BORDER_NONE)
            self.document_tab_bar.SetMinSize((-1, self.FromDIP(34)))
            self.document_tab_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.document_tab_bar.SetSizer(self.document_tab_sizer)
            self.document_tab_bar.SetScrollRate(12, 0)
            self.document_buttons: dict[object, Any] = {}
            self.notebook = wx.Simplebook(documents_panel)
            documents_sizer.Add(self.document_tab_bar, 0, wx.EXPAND)
            documents_sizer.Add(self.notebook, 1, wx.EXPAND)
            documents_panel.SetSizer(documents_sizer)
            self.preview_host.AddPage(documents_panel, "Documents")
            self.splitter.SplitVertically(project_panel, self.preview_host, 250)

            frame_sizer = wx.BoxSizer(wx.VERTICAL)
            frame_sizer.Add(
                self.action_bar,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
                self.FromDIP(8),
            )
            frame_sizer.Add(self.splitter, 1, wx.EXPAND)
            self.SetSizer(frame_sizer)

        def _build_message_page(self) -> None:
            self.message_panel = wx.Panel(self.preview_host)
            self.message_sizer = wx.BoxSizer(wx.VERTICAL)
            self.message_panel.SetSizer(self.message_sizer)
            self.preview_host.AddPage(self.message_panel, "Message")

        def _set_initial_sash(self) -> None:
            width = self.splitter.GetClientSize().GetWidth()
            self.splitter.SetSashPosition(max(220, min(280, round(width * 0.23))))

        def _assign_tree_images(self) -> None:
            image_list = wx.ImageList(16, 16)
            art = {
                "project": wx.ART_HARDDISK,
                "folder": wx.ART_FOLDER,
                "folder_open": wx.ART_FOLDER_OPEN,
                "workbook": wx.ART_REPORT_VIEW,
                "worksheet": wx.ART_LIST_VIEW,
                "graph": wx.ART_MISSING_IMAGE,
                "note": wx.ART_NORMAL_FILE,
                "function": wx.ART_EXECUTABLE_FILE,
                "raw": wx.ART_WARNING,
                "generic": wx.ART_NORMAL_FILE,
            }
            self.tree_icons: dict[str, int] = {}
            for key, art_id in art.items():
                bitmap = wx.ArtProvider.GetBitmap(art_id, wx.ART_OTHER, (16, 16))
                self.tree_icons[key] = image_list.Add(bitmap)
            self.tree.AssignImageList(image_list)

        def _bind_events(self) -> None:
            self.Bind(wx.EVT_MENU, self._on_open, id=wx.ID_OPEN)
            self.open_button.Bind(wx.EVT_BUTTON, self._on_open)
            self.export_button.Bind(wx.EVT_BUTTON, self._on_export_popup)
            self.export_all_button.Bind(wx.EVT_BUTTON, self._on_export_all)
            self.Bind(wx.EVT_MENU, self._on_export_all, id=export_all_id)
            self.Bind(wx.EVT_MENU, self._on_export_json, id=export_json_id)
            self.Bind(wx.EVT_MENU, self._on_export_artifact, id=export_artifact_id)
            self.Bind(wx.EVT_MENU, lambda _event: self._export_table("csv"), id=export_csv_id)
            self.Bind(wx.EVT_MENU, lambda _event: self._export_table("tsv"), id=export_tsv_id)
            self.Bind(wx.EVT_MENU, lambda _event: self._export_table("jsonl"), id=export_jsonl_id)
            self.Bind(wx.EVT_MENU, lambda _event: self._export_table("xlsx"), id=export_xlsx_id)
            self.Bind(wx.EVT_MENU, self._export_image, id=export_image_id)
            self.Bind(
                wx.EVT_MENU,
                lambda _event: self._export_selection(",", ".csv"),
                id=export_selection_csv_id,
            )
            self.Bind(
                wx.EVT_MENU,
                lambda _event: self._export_selection("\t", ".tsv"),
                id=export_selection_tsv_id,
            )
            self.Bind(wx.EVT_MENU, self._on_close_tab, id=close_tab_id)
            self.Bind(wx.EVT_MENU, lambda _event: self.Close(), id=wx.ID_EXIT)
            self.Bind(wx.EVT_MENU, self._focus_search, id=find_id)
            self.Bind(wx.EVT_MENU, self._show_properties, id=properties_id)
            self.Bind(wx.EVT_MENU, self._show_diagnostics, id=diagnostics_id)
            self.Bind(wx.EVT_MENU, self._expand_all, id=expand_all_id)
            self.Bind(wx.EVT_MENU, self._collapse_all, id=collapse_all_id)
            self.Bind(wx.EVT_MENU, self._toggle_unwrap_groups, id=unwrap_groups_id)
            self.Bind(wx.EVT_MENU, self._toggle_recovery_evidence, id=show_evidence_id)
            self.Bind(wx.EVT_MENU, self._open_context_item, id=open_item_id)
            self.Bind(wx.EVT_MENU, self._show_shortcuts, id=shortcuts_id)
            self.Bind(wx.EVT_MENU, self._show_about, id=wx.ID_ABOUT)
            self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_select)
            self.tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_tree_activate)
            self.tree.Bind(wx.EVT_TREE_ITEM_MENU, self._on_tree_menu)
            self.search.Bind(wx.EVT_TEXT_ENTER, self._search_next)
            self.search.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._search_next)
            self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self._clear_search)
            self.search.Bind(wx.EVT_TEXT, self._search_text_changed)
            self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _show_welcome(self) -> None:
            if self.notebook.GetPageCount():
                return
            self._show_message(
                "Open an Origin project",
                "Read-only recovery for OPJ and OPJU files",
                show_open=True,
            )

        def _show_loading(self, label: str) -> None:
            if not self.notebook.GetPageCount():
                self._show_message(
                    "Reading project catalog",
                    label,
                    show_open=False,
                    busy=True,
                    detail=(
                        "Scanning parser records, byte ranges, and recoverable objects through "
                        "deopjufy list --json. Large projects can take a while."
                    ),
                )

        def _show_select_item(self) -> None:
            if not self.notebook.GetPageCount():
                self._show_message(
                    "Select a project item",
                    "Choose a worksheet, graph, note, or recovered object in Project Explorer",
                    show_open=False,
                )

        def _show_message(
            self,
            title: str,
            hint: str,
            *,
            show_open: bool,
            busy: bool = False,
            detail: str = "",
        ) -> None:
            self.message_sizer.Clear(delete_windows=True)
            self.message_sizer.AddStretchSpacer()
            if busy:
                view = loading_view(self.message_panel, title, hint, detail)
                self.message_sizer.Add(view, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(40))
            else:
                title_control = wx.StaticText(self.message_panel, label=title)
                title_font = title_control.GetFont()
                title_font.MakeLarger()
                title_font.MakeBold()
                title_control.SetFont(title_font)
                self.message_sizer.Add(title_control, 0, wx.ALIGN_CENTER | wx.BOTTOM, self.FromDIP(10))
                hint_control = wx.StaticText(self.message_panel, label=hint, style=wx.ALIGN_CENTER)
                hint_control.Wrap(self.FromDIP(560))
                self.message_sizer.Add(hint_control, 0, wx.ALIGN_CENTER | wx.BOTTOM, self.FromDIP(16))
                if show_open:
                    button = wx.Button(self.message_panel, wx.ID_OPEN, "Open projects…")
                    button.Bind(wx.EVT_BUTTON, self._on_open)
                    self.message_sizer.Add(button, 0, wx.ALIGN_CENTER)
            self.message_sizer.AddStretchSpacer()
            self.message_panel.Layout()
            self.preview_host.ChangeSelection(0)

        def _remove_welcome(self) -> None:
            self.preview_host.ChangeSelection(1)

        def _defer_until_documents_visible(self, callback: Any, *args: object) -> bool:
            if self.preview_host.GetSelection() == 1:
                return False
            self._remove_welcome()
            self.Layout()
            self.splitter.Layout()
            self.preview_host.Layout()
            wx.CallAfter(callback, *args)
            return True

        def _on_open(self, _event: object) -> None:
            style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
            wildcard = "Origin projects (*.opj;*.opju)|*.opj;*.opju|All files|*"
            with wx.FileDialog(self, "Open Origin projects", wildcard=wildcard, style=style) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return
                self.open_paths([Path(path) for path in dialog.GetPaths()])

        def open_paths(self, paths: list[Path]) -> None:
            unique_paths = list(dict.fromkeys(path.resolve() for path in paths))
            new_paths = [path for path in unique_paths if path not in self.document_nodes]
            if not new_paths:
                self._set_status("All selected projects are already open")
                return
            self._set_status(f"Opening {len(new_paths)} project(s)…")
            self._show_loading(", ".join(path.name for path in new_paths))
            for path in new_paths:
                node = self.tree.AppendItem(
                    self.root,
                    f"{path.name} [loading]",
                    self.tree_icons["project"],
                )
                self.tree.SetItemData(node, path)
                self.document_nodes[path] = node
            for path, future in self.backend.submit_catalogs(new_paths).items():
                future.add_done_callback(
                    lambda completed, document_path=path: self._call_after(
                        self._catalog_done,
                        document_path,
                        completed,
                    )
                )

        def _catalog_done(self, path: Path, future: Future[dict[str, Any]]) -> None:
            if self.closed:
                return
            try:
                payload = future.result()
            except (DeopjufyCommandError, OSError) as exc:
                document_node = self.document_nodes[path]
                self.tree.SetItemText(document_node, f"{path.name} [failed]")
                self._record_diagnostic(path.name, str(exc))
                self._set_status(f"Failed to open {path.name}: {exc}")
                if not self.notebook.GetPageCount() and not self.pending_targets:
                    self._show_message("Could not open project", str(exc), show_open=True)
                return
            self.catalogs[path] = payload
            self._update_export_enabled()
            document_node = self.document_nodes[path]
            self.tree.SetItemText(document_node, path.name)
            item_count, hidden_count = self._append_catalog_items(path, document_node, payload)
            self._collect_payload_diagnostics(path.name, payload)
            self.tree.Expand(document_node)
            self.SetTitle(f"deopjufy — {path.name}" if len(self.catalogs) == 1 else "deopjufy — multiple projects")
            document = payload.get("document")
            detected = document.get("detected_type", "") if isinstance(document, dict) else ""
            hidden = f" · {hidden_count} evidence item(s) hidden" if hidden_count else ""
            self._set_status(f"{path.name} · {str(detected).upper()} · {item_count} item(s){hidden}")
            if not self.notebook.GetPageCount() and not self.pending_targets:
                leaf = preferred_leaf(self.catalog_leaves[path])
                if leaf is None:
                    self._show_select_item()
                else:
                    target = path, leaf.item_id
                    node = self.target_nodes[target]
                    self.tree.EnsureVisible(node)
                    self.tree.SelectItem(node)
                    self._activate_target(target, leaf.label)

        def _append_catalog_items(
            self,
            path: Path,
            document_node: object,
            payload: dict[str, Any],
        ) -> tuple[int, int]:
            all_leaves = catalog_leaves(payload, show_recovery_evidence=True)
            leaves = catalog_leaves(payload, show_recovery_evidence=self.show_recovery_evidence)
            self.catalog_leaves[path] = leaves
            self.target_leaves.update({(path, leaf.item_id): leaf for leaf in leaves})
            items = payload.get("items")
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    self.catalog_rows[(path, item["id"])] = item
            project_tree = build_project_tree(
                leaves,
                unwrap_single_child_groups=self.unwrap_single_child_groups,
            )
            for branch in project_tree.branches:
                self._append_branch(path, branch, document_node)
            for leaf in project_tree.leaves:
                self._append_leaf(path, leaf, document_node)
            return len(leaves), len(all_leaves) - len(leaves)

        def _append_branch(self, path: Path, branch: ProjectBranch, parent: object) -> None:
            icon = "workbook" if branch.kinds.intersection({"excel", "matrix", "worksheet"}) else "folder"
            node = self.tree.AppendItem(
                parent,
                branch.label,
                self.tree_icons[icon],
                self.tree_icons["folder_open"],
            )
            self.tree.SetItemData(node, BranchTarget(path=path, branch=branch))
            for child in branch.branches:
                self._append_branch(path, child, node)
            for leaf in branch.leaves:
                self._append_leaf(path, leaf, node)

        def _append_leaf(self, path: Path, leaf: ProjectLeaf, parent: object) -> None:
            target = path, leaf.item_id
            node = self.tree.AppendItem(parent, leaf.label, self.tree_icons[self._leaf_icon(leaf.kind)])
            self.tree.SetItemData(node, target)
            self.target_nodes[target] = node
            self.search_entries.append((leaf.search_text, node))

        def _leaf_icon(self, kind: str) -> str:
            if kind in {"excel", "matrix", "worksheet"}:
                return "worksheet"
            if kind in {
                "bmp",
                "gif",
                "graph",
                "graph_preview",
                "image",
                "jpeg",
                "layer",
                "png",
                "project_page",
                "svg",
            }:
                return "graph"
            if kind in {"note", "opju_report", "origin_storage_report"}:
                return "note"
            if kind == "function":
                return "function"
            if kind == "raw_dump" or kind.startswith("unknown"):
                return "raw"
            return "generic"

        def _rebuild_catalog_trees(self) -> None:
            selected_target = self.active_target
            self.target_nodes.clear()
            self.target_leaves.clear()
            self.search_entries.clear()
            for path, document_node in self.document_nodes.items():
                if path not in self.catalogs:
                    continue
                self.tree.DeleteChildren(document_node)
                self._append_catalog_items(path, document_node, self.catalogs[path])
                self.tree.Expand(document_node)
            if selected_target is not None and selected_target in self.target_nodes:
                node = self.target_nodes[selected_target]
                self.tree.EnsureVisible(node)
                self.tree.SelectItem(node)

        def _expand_all(self, _event: object) -> None:
            self.tree.ExpandAll()

        def _collapse_all(self, _event: object) -> None:
            for document_node in self.document_nodes.values():
                self.tree.Collapse(document_node)

        def _toggle_unwrap_groups(self, event: Any) -> None:
            self.unwrap_single_child_groups = bool(event.IsChecked())
            self._rebuild_catalog_trees()

        def _toggle_recovery_evidence(self, event: Any) -> None:
            self.show_recovery_evidence = bool(event.IsChecked())
            self._rebuild_catalog_trees()

        def _on_select(self, event: Any) -> None:
            selection = event.GetItem()
            target = self.tree.GetItemData(selection)
            if not self._is_target(target):
                self._update_export_enabled()
                return
            self._activate_target(target, self.tree.GetItemText(selection))

        def _on_tree_activate(self, event: Any) -> None:
            item = event.GetItem()
            data = self.tree.GetItemData(item)
            if self._is_target(data):
                self._activate_target(data, self.tree.GetItemText(item))
            elif self.tree.ItemHasChildren(item):
                self.tree.Collapse(item) if self.tree.IsExpanded(item) else self.tree.Expand(item)

        def _on_tree_menu(self, event: Any) -> None:
            self._show_tree_context(event.GetItem())

        def _show_tree_context(self, item: object) -> None:
            if not item:
                return
            self.tree.SelectItem(item)
            data = self.tree.GetItemData(item)
            menu = wx.Menu()
            if self._is_target(data):
                self.context_target = data
                menu.Append(open_item_id, "&Open\tEnter")
                menu.Append(properties_id, "&Properties…\tAlt+Enter")
                menu.AppendSeparator()
                menu.AppendSubMenu(self._export_menu(data), "&Export")
            else:
                expand_item = menu.Append(wx.ID_ANY, "&Expand branch")
                collapse_item = menu.Append(wx.ID_ANY, "&Collapse branch")
                menu.Bind(wx.EVT_MENU, lambda _event: self.tree.Expand(item), expand_item)
                menu.Bind(wx.EVT_MENU, lambda _event: self.tree.Collapse(item), collapse_item)
                if isinstance(data, (Path, BranchTarget)):
                    menu.AppendSeparator()
                    export_item = menu.Append(export_all_id, "Export &all project content…")
                    export_item.Enable(self._active_project_path() is not None)
            try:
                self.tree.PopupMenu(menu)
            finally:
                self.context_target = None
                menu.Destroy()

        def _open_context_item(self, _event: object) -> None:
            target = self._export_target()
            if target is not None:
                leaf = self.target_leaves.get(target)
                self._activate_target(target, leaf.label if leaf is not None else target[1])

        def _add_document_page(self, page: Any, label: str, *, select: bool = False) -> None:
            self.notebook.AddPage(page, label)
            button = wx.ToggleButton(self.document_tab_bar, label=label, style=wx.BU_EXACTFIT)
            button.Bind(wx.EVT_TOGGLEBUTTON, lambda event, selected=page: self._on_document_button(event, selected))
            self.document_buttons[page] = button
            self.document_tab_sizer.Add(
                button,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                self.FromDIP(2),
            )
            self.document_tab_bar.FitInside()
            self.document_tab_bar.Layout()
            if select or self.notebook.GetPageCount() == 1:
                self._select_outer_page(page)

        def _on_document_button(self, event: Any, page: object) -> None:
            if not event.IsChecked():
                event.GetEventObject().SetValue(True)
                return
            self._select_outer_page(page)
            self._document_selected()

        def _sync_document_buttons(self, selected_page: object | None) -> None:
            for page, button in self.document_buttons.items():
                button.SetValue(page is selected_page)

        def _delete_document_page(self, page: object, index: int) -> None:
            button = self.document_buttons.pop(page, None)
            if button is not None:
                self.document_tab_sizer.Detach(button)
                button.Destroy()
                self.document_tab_bar.FitInside()
                self.document_tab_bar.Layout()
            self.notebook.DeletePage(index)
            self._sync_document_buttons(self._current_outer_page())

        def _workbook_for_target(self, target: tuple[Path, str]) -> WorkbookState | None:
            leaf = self.target_leaves.get(target)
            if leaf is None:
                return None
            sheets = sibling_sheets(self.catalog_leaves.get(target[0], ()), leaf)
            if len(sheets) < 2:
                return None
            key = target[0], leaf.folders
            existing = self.workbooks.get(key)
            if existing is not None:
                return existing
            page = wx.Panel(self.notebook)
            sizer = wx.BoxSizer(wx.VERTICAL)
            sheet_book = wx.Simplebook(page)
            tab_bar = wx.ScrolledWindow(page, style=wx.HSCROLL | wx.BORDER_NONE)
            tab_bar.SetMinSize((-1, self.FromDIP(34)))
            tab_sizer = wx.BoxSizer(wx.HORIZONTAL)
            tab_bar.SetSizer(tab_sizer)
            tab_bar.SetScrollRate(12, 0)
            sizer.Add(sheet_book, 1, wx.EXPAND)
            sizer.Add(tab_bar, 0, wx.EXPAND)
            page.SetSizer(sizer)
            state = WorkbookState(
                key=key,
                page=page,
                book=sheet_book,
                sheet_pages={},
                targets_by_page={},
                sheet_buttons={},
            )
            label = leaf.folders[-1] if leaf.folders else target[0].stem
            self.workbooks[key] = state
            self.workbooks_by_page[page] = state
            self._add_document_page(page, label)
            self.notebook.Layout()
            page.Layout()
            for sheet in sheets:
                sheet_target = target[0], sheet.item_id
                sheet_page = self._make_sheet_placeholder(sheet_book, sheet.label)
                state.sheet_pages[sheet_target] = sheet_page
                state.targets_by_page[sheet_page] = sheet_target
                sheet_book.AddPage(sheet_page, sheet.label)
                button = wx.ToggleButton(tab_bar, label=sheet.label, style=wx.BU_EXACTFIT)
                button.Bind(
                    wx.EVT_TOGGLEBUTTON,
                    lambda event, selected=sheet_target: self._on_sheet_button(event, selected),
                )
                state.sheet_buttons[sheet_target] = button
                tab_sizer.Add(
                    button,
                    0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                    self.FromDIP(2),
                )
            tab_bar.FitInside()
            return state

        def _make_sheet_placeholder(self, parent: Any, label: str) -> Any:
            panel = wx.Panel(parent)
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.AddStretchSpacer()
            message = wx.StaticText(panel, label=f"Select {label} to load")
            sizer.Add(message, 0, wx.ALIGN_CENTER)
            sizer.AddStretchSpacer()
            panel.SetSizer(sizer)
            return panel

        def _set_sheet_message(
            self,
            workbook: WorkbookState,
            target: tuple[Path, str],
            message: str,
        ) -> None:
            panel = workbook.sheet_pages[target]
            for child in panel.GetChildren():
                child.Destroy()
            sizer = panel.GetSizer() or wx.BoxSizer(wx.VERTICAL)
            sizer.Clear(delete_windows=False)
            sizer.AddStretchSpacer()
            sizer.Add(wx.StaticText(panel, label=message), 0, wx.ALIGN_CENTER)
            sizer.AddStretchSpacer()
            panel.SetSizer(sizer)
            panel.Layout()

        def _set_sheet_loading(
            self,
            workbook: WorkbookState,
            target: tuple[Path, str],
            label: str,
        ) -> None:
            panel = workbook.sheet_pages[target]
            for child in panel.GetChildren():
                child.Destroy()
            sizer = panel.GetSizer() or wx.BoxSizer(wx.VERTICAL)
            sizer.Clear(delete_windows=False)
            sizer.AddStretchSpacer()
            view = loading_view(
                panel,
                f"Loading {label}",
                "Retrieving the selected object",
                "Running deopjufy get --json, matching recovered artifacts, then preparing the preview.",
            )
            sizer.Add(view, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(40))
            sizer.AddStretchSpacer()
            panel.SetSizer(sizer)
            panel.Layout()

        def _select_target_page(self, target: tuple[Path, str]) -> None:
            state = self.tabs.get(target)
            workbook = self._workbook_for_target(target)
            if workbook is not None:
                self._select_outer_page(workbook.page)
                page = workbook.sheet_pages[target]
                index = next(
                    (
                        page_index
                        for page_index in range(workbook.book.GetPageCount())
                        if workbook.book.GetPage(page_index) is page
                    ),
                    None,
                )
                if index is not None:
                    workbook.book.ChangeSelection(index)
                for sheet_target, button in workbook.sheet_buttons.items():
                    button.SetValue(sheet_target == target)
                return
            if state is not None:
                self._select_outer_page(state.host_page)

        def _activate_target(self, target: tuple[Path, str], label: str) -> None:
            self.active_target = target
            leaf = self.target_leaves.get(target)
            if (
                leaf is not None
                and len(sibling_sheets(self.catalog_leaves.get(target[0], ()), leaf)) >= 2
                and self._defer_until_documents_visible(self._activate_target, target, label)
            ):
                return
            workbook = self._workbook_for_target(target)
            if workbook is not None:
                self._remove_welcome()
                self._select_target_page(target)
            existing = self.tabs.get(target)
            if existing is not None:
                self._select_target_page(target)
                self._update_tab_status(existing)
                return
            if target in self.pending_targets:
                return
            self.pending_targets.add(target)
            self._set_status(f"Loading {label}…")
            if workbook is not None:
                self._set_sheet_loading(workbook, target, label)
            else:
                self._show_loading(label)
            future = self.backend.submit_get(*target)
            future.add_done_callback(
                lambda completed, requested_target=target: self._call_after(
                    self._get_done,
                    requested_target,
                    completed,
                )
            )

        def _get_done(
            self,
            requested_target: tuple[Path, str],
            future: Future[dict[str, Any]],
        ) -> None:
            self.pending_targets.discard(requested_target)
            if self.closed:
                return
            try:
                payload = future.result()
            except (DeopjufyCommandError, OSError) as exc:
                self._record_diagnostic(requested_target[0].name, str(exc))
                self._set_status(f"Failed to load item: {exc}")
                if not self.notebook.GetPageCount():
                    self._show_message("Could not load item", str(exc), show_open=False)
                workbook = self._workbook_for_target(requested_target)
                if workbook is not None:
                    self._set_sheet_message(workbook, requested_target, f"Could not load: {exc}")
                return
            if self._defer_until_documents_visible(self._complete_get, requested_target, payload):
                return
            self._complete_get(requested_target, payload)

        def _complete_get(self, requested_target: tuple[Path, str], payload: dict[str, Any]) -> None:
            if self.closed:
                return
            state = self._open_payload_tab(requested_target, payload)
            self._collect_payload_diagnostics(requested_target[0].name, payload)
            if requested_target == self.active_target:
                self._select_target_page(state.target)
                self._update_tab_status(state)

        def _open_payload_tab(self, target: tuple[Path, str], payload: dict[str, Any]) -> TabState:
            existing = self.tabs.get(target)
            if existing is not None:
                return existing
            table = tabular_view(payload)
            workbook = self._workbook_for_target(target) if table is not None else None
            panel = workbook.sheet_pages[target] if workbook is not None else wx.Panel(self.notebook)
            for child in panel.GetChildren():
                child.Destroy()
            sizer = panel.GetSizer() or wx.BoxSizer(wx.VERTICAL)
            sizer.Clear(delete_windows=False)
            panel.SetSizer(sizer)
            grid = None
            image_payload = recovered_image(payload)
            if table is not None:
                grid = self._make_grid(panel, table)
                sizer.Add(grid, 1, wx.EXPAND)
            elif image_payload is not None:
                image_view = self._make_image_view(panel, image_payload.data)
                if image_view is not None:
                    sizer.Add(image_view, 1, wx.EXPAND)
                else:
                    sizer.Add(self._make_text_view(panel, payload), 1, wx.EXPAND)
            else:
                sizer.Add(self._make_text_view(panel, payload), 1, wx.EXPAND)
            item = payload.get("item")
            label = (
                str(item.get("name") or item.get("source_object_path") or "Item") if isinstance(item, dict) else "Item"
            )
            host_page = workbook.page if workbook is not None else panel
            if workbook is None:
                self._add_document_page(panel, label, select=target == self.active_target)
            panel.Layout()
            state = TabState(
                target=target,
                page=panel,
                host_page=host_page,
                payload=payload,
                table=table,
                grid=grid,
            )
            self.tabs[target] = state
            self._update_export_enabled()
            return state

        def _make_grid(self, parent: Any, table: TabularView) -> Any:
            grid = wx_grid.Grid(parent)
            grid.SetTable(grid_table(table), True)
            grid.EnableEditing(False)
            grid.SetSelectionMode(wx_grid.Grid.SelectCells)
            grid.SetMargins(0, 0)
            if hasattr(grid, "SetDefaultCellOverflow"):
                grid.SetDefaultCellOverflow(False)
            row_label_width = grid.GetTextExtent("Formula")[0] + self.FromDIP(22)
            grid.SetRowLabelSize(max(self.FromDIP(64), row_label_width))
            grid.SetColLabelSize(self.FromDIP(30))
            for row in range(len(table.metadata_rows)):
                attr = wx_grid.GridCellAttr()
                attr.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE))
                attr.SetReadOnly(True)
                attr.SetOverflow(False)
                grid.SetRowAttr(row, attr)
            if table.metadata_rows and hasattr(grid, "FreezeTo"):
                grid.FreezeTo(len(table.metadata_rows), 0)
            for column in range(table.column_count):
                if table.column_is_numeric(column):
                    attr = wx_grid.GridCellAttr()
                    attr.SetAlignment(wx.ALIGN_RIGHT, wx.ALIGN_CENTER_VERTICAL)
                    attr.SetOverflow(False)
                    grid.SetColAttr(column, attr)
                grid.SetColSize(column, self._column_width(grid, table, column))
            grid.Bind(wx.EVT_KEY_DOWN, self._on_grid_key)
            return grid

        def _make_image_view(self, parent: Any, payload: bytes) -> Any | None:
            preview = image_preview(parent, payload)
            if not preview.IsOk():
                preview.Destroy()
                return None
            return preview

        def _make_text_view(self, parent: Any, payload: dict[str, Any]) -> Any:
            return wx.TextCtrl(
                parent,
                value=payload_text(payload),
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            )

        def _column_width(self, grid: Any, table: TabularView, column: int) -> int:
            values = [table.headers[column] if column < len(table.headers) else ""]
            values.extend(row[1][column] for row in table.metadata_rows if column < len(row[1]))
            values.extend(row[column] for row in table.rows[:100] if column < len(row))
            text_width = max((grid.GetTextExtent(value)[0] for value in values), default=self.FromDIP(72))
            return min(self.FromDIP(340), max(self.FromDIP(104), text_width + self.FromDIP(28)))

        def _document_selected(self) -> None:
            state = self._current_state()
            if state is not None:
                self.active_target = state.target
                self._sync_tree_selection(state.target)
                self._update_tab_status(state)
            else:
                self._activate_current_workbook_sheet()
            self._update_export_enabled()

        def _on_sheet_button(self, event: Any, target: tuple[Path, str]) -> None:
            if not event.IsChecked():
                event.GetEventObject().SetValue(True)
                return
            self.active_target = target
            self._sync_tree_selection(target)
            self._activate_target(target, self.target_leaves[target].label)

        def _activate_current_workbook_sheet(self) -> None:
            outer = self._current_outer_page()
            workbook = self.workbooks_by_page.get(outer)
            if workbook is None:
                return
            selection = workbook.book.GetSelection()
            if 0 <= selection < workbook.book.GetPageCount():
                target = workbook.targets_by_page.get(workbook.book.GetPage(selection))
                if target is not None:
                    self._activate_target(target, self.target_leaves[target].label)

        def _sync_tree_selection(self, target: tuple[Path, str]) -> None:
            node = self.target_nodes.get(target)
            if node is not None and self.tree.GetSelection() != node:
                self.tree.EnsureVisible(node)
                self.tree.SelectItem(node)

        def _on_close_tab(self, _event: object) -> None:
            page = self._current_outer_page()
            if page is None:
                return
            workbook = self.workbooks_by_page.pop(page, None)
            if workbook is not None:
                self.workbooks.pop(workbook.key, None)
                for target in workbook.sheet_pages:
                    self.tabs.pop(target, None)
                    self.pending_targets.discard(target)
            else:
                state = self._state_for_page(page)
                if state is not None:
                    self.tabs.pop(state.target, None)
                    self.pending_targets.discard(state.target)
            index = self._page_index(page)
            if index is not None:
                self._delete_document_page(page, index)
            current = self._current_state()
            self.active_target = current.target if current is not None else None
            if current is not None:
                self._update_tab_status(current)
            if current is None:
                self._show_select_item() if self.catalogs else self._show_welcome()
            self._update_export_enabled()

        def _active_project_path(self) -> Path | None:
            selected = self.tree.GetSelection()
            data = self.tree.GetItemData(selected) if selected else None
            if isinstance(data, Path) and data in self.catalogs:
                return data
            if isinstance(data, BranchTarget):
                return data.path
            if self._is_target(data):
                return data[0]
            if self.active_target is not None:
                return self.active_target[0]
            return next(iter(self.catalogs), None) if len(self.catalogs) == 1 else None

        def _choose_export_all_profile(self) -> tuple[str, bool] | None:
            choices = (
                "Readable files — CSV tables, notes, and images",
                "Excel tables — XLSX workbooks, notes, and images",
                "Complete recovery — machine evidence and exact byte map",
            )
            dialog = wx.SingleChoiceDialog(
                self,
                "Choose the extraction profile. Complete recovery is larger and slower.",
                "Export all project content",
                choices,
            )
            try:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return None
                selection = dialog.GetSelection()
            finally:
                dialog.Destroy()
            if selection == 0:
                return "csv", False
            if selection == 1:
                return "xlsx", False
            return "csv", True

        def _on_export_all(self, _event: object) -> None:
            path = self._active_project_path()
            if path is None:
                self._set_status("Select an open project before exporting all content")
                return
            profile = self._choose_export_all_profile()
            if profile is None:
                return
            safe_stem = "".join(
                character if character.isalnum() or character in "-_" else "_" for character in path.stem
            )
            directory_name = f"{safe_stem or 'project'}_extracted"
            with wx.DirDialog(
                self,
                f"Choose where to create {directory_name}",
                style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
            ) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return
                target = Path(dialog.GetPath()) / directory_name
            if target.exists():
                wx.MessageBox(
                    f"The output directory already exists:\n{target}\n\nChoose another location or move it first.",
                    "Export all",
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
                return
            output_format, complete = profile
            self.pending_project_exports.add(path)
            profile_label = "complete recovery" if complete else f"readable {output_format.upper()} export"
            self._set_status(f"Exporting {path.name} · {profile_label}…", "Native parser working")
            self._update_export_enabled()
            future = self.backend.submit_export_all(
                path,
                target,
                output_format=output_format,
                complete=complete,
            )
            future.add_done_callback(lambda completed: self._call_after(self._export_all_done, path, target, completed))

        def _export_all_done(
            self,
            path: Path,
            target: Path,
            future: Future[dict[str, Any]],
        ) -> None:
            self.pending_project_exports.discard(path)
            self._update_export_enabled()
            if self.closed:
                return
            try:
                manifest = future.result()
            except (DeopjufyCommandError, OSError) as exc:
                self._record_diagnostic(path.name, str(exc))
                self._set_status(f"Export all failed: {exc}")
                return
            items = manifest.get("items")
            item_count = len(items) if isinstance(items, list) else 0
            status = str(manifest.get("status", "complete"))
            self._set_status(f"Exported {item_count} manifest item(s) to {target}", status)

        def _on_export_popup(self, _event: object) -> None:
            target = self._export_target()
            if target is None:
                self._set_status("Select an item before exporting")
                return
            menu = self._export_menu(target)
            try:
                self.PopupMenu(menu)
            finally:
                menu.Destroy()

        def _on_export_json(self, _event: object) -> None:
            state = self._export_state()
            if state is None:
                return
            target = self._choose_save_path(
                "Export item response",
                ".json",
                "JSON files (*.json)|*.json",
                state.target,
            )
            if target is not None:
                data = (json.dumps(state.payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
                self._write_export(target, data)

        def _on_export_artifact(self, _event: object) -> None:
            state = self._export_state()
            if state is None:
                return
            data = payload_bytes(state.payload)
            if data is None:
                self._set_status("The selected item has no recovered file-backed content")
                return
            suffix = default_artifact_suffix(state.payload)
            target = self._choose_save_path("Export recovered artifact", suffix, "All files|*", state.target)
            if target is not None:
                self._write_export(target, data)

        def _export_table(self, output_format: str) -> None:
            selected = self._export_target()
            if selected is None:
                return
            row = self.catalog_rows.get(selected, {})
            formats = row.get("retrieval_formats")
            if not isinstance(formats, list) or output_format not in formats:
                self._set_status(f"{output_format.upper()} is not available for this item")
                return
            suffix = f".{output_format}"
            target = self._choose_save_path(
                f"Export table as {output_format.upper()}",
                suffix,
                f"{output_format.upper()} files (*{suffix})|*{suffix}",
                selected,
            )
            if target is None:
                return
            self._set_status(f"Exporting {target.name}…")
            future = self.backend.submit_export(*selected, output_format, target)
            future.add_done_callback(lambda completed: self._call_after(self._export_done, target, completed))

        def _export_image(self, _event: object) -> None:
            selected = self._export_target()
            if selected is None:
                return
            state = self.tabs.get(selected)
            image = recovered_image(state.payload) if state is not None else None
            if image is not None:
                target = self._choose_save_path(
                    "Export image or plot preview",
                    image.suffix,
                    f"Image files (*{image.suffix})|*{image.suffix}",
                    selected,
                )
                if target is not None:
                    self._write_export(target, image.data)
                return
            row = self.catalog_rows.get(selected, {})
            formats = row.get("retrieval_formats")
            image_formats = (
                [value for value in formats if value in {"bmp", "gif", "jpeg", "jpg", "png", "svg"}]
                if isinstance(formats, list)
                else []
            )
            if not image_formats:
                self._set_status("The selected item has no recoverable image preview")
                return
            output_format = image_formats[0]
            suffix = f".{output_format}"
            target = self._choose_save_path(
                "Export image or plot preview",
                suffix,
                f"Image files (*{suffix})|*{suffix}",
                selected,
            )
            if target is not None:
                future = self.backend.submit_export(*selected, output_format, target)
                future.add_done_callback(lambda completed: self._call_after(self._export_done, target, completed))

        def _export_selection(self, delimiter: str, suffix: str) -> None:
            state = self._current_state()
            if state is None or state.table is None or state.grid is None:
                self._set_status("The current tab has no table selection")
                return
            bounds = self._selection_bounds(state.grid, state.table)
            data = table_region_text(state.table, *bounds, delimiter=delimiter).encode("utf-8")
            target = self._choose_save_path(
                "Export selected cells",
                suffix,
                f"Tables (*{suffix})|*{suffix}",
                state.target,
            )
            if target is not None:
                self._write_export(target, data)

        def _export_done(self, target: Path, future: Future[dict[str, Any]]) -> None:
            if self.closed:
                return
            try:
                payload = future.result()
            except (DeopjufyCommandError, OSError) as exc:
                self._record_diagnostic(target.name, str(exc))
                self._set_status(f"Export failed: {exc}")
                return
            self._collect_payload_diagnostics(target.name, payload)
            self._set_status(f"Exported {target}")

        def _choose_save_path(
            self,
            title: str,
            suffix: str,
            wildcard: str,
            selected: tuple[Path, str] | None = None,
        ) -> Path | None:
            name = "item"
            row = self.catalog_rows.get(selected, {}) if selected is not None else {}
            if row:
                name = str(row.get("name") or row.get("source_object_path") or "item")
            safe_name = "".join(character if character.isalnum() or character in "-_." else "_" for character in name)
            base_name = safe_name or "item"
            default_name = base_name if base_name.lower().endswith(suffix.lower()) else f"{base_name}{suffix}"
            style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
            with wx.FileDialog(
                self,
                title,
                defaultFile=default_name,
                wildcard=wildcard,
                style=style,
            ) as dialog:
                return None if dialog.ShowModal() == wx.ID_CANCEL else Path(dialog.GetPath())

        def _write_export(self, target: Path, data: bytes) -> None:
            try:
                target.write_bytes(data)
            except OSError as exc:
                self._record_diagnostic(target.name, str(exc))
                self._set_status(f"Export failed: {exc}")
                return
            self._set_status(f"Exported {target}")

        def _on_grid_key(self, event: Any) -> None:
            if event.ControlDown() and event.GetKeyCode() in (ord("C"), ord("c")):
                self._copy_grid_selection(event.GetEventObject())
                return
            event.Skip()

        def _copy_grid_selection(self, grid: Any) -> None:
            state = self._current_state()
            if state is None or state.table is None:
                return
            text = table_region_text(state.table, *self._selection_bounds(grid, state.table))
            if wx.TheClipboard.Open():
                try:
                    wx.TheClipboard.SetData(wx.TextDataObject(text))
                    self._set_status("Copied selected cells")
                finally:
                    wx.TheClipboard.Close()

        def _selection_bounds(self, grid: Any, table: TabularView) -> tuple[int, int, int, int]:
            top_left = grid.GetSelectionBlockTopLeft()
            bottom_right = grid.GetSelectionBlockBottomRight()
            if top_left and bottom_right:
                return (
                    top_left[0].GetRow(),
                    top_left[0].GetCol(),
                    bottom_right[0].GetRow(),
                    bottom_right[0].GetCol(),
                )
            rows = list(grid.GetSelectedRows())
            if rows:
                return min(rows), 0, max(rows), max(0, table.column_count - 1)
            columns = list(grid.GetSelectedCols())
            if columns:
                return 0, min(columns), max(0, table.grid_row_count - 1), max(columns)
            cells = list(grid.GetSelectedCells())
            if cells:
                row = cells[0].GetRow()
                column = cells[0].GetCol()
                return row, column, row, column
            row = max(0, grid.GetGridCursorRow())
            column = max(0, grid.GetGridCursorCol())
            return row, column, row, column

        def _focus_search(self, _event: object) -> None:
            self.search.SetFocus()
            self.search.SelectAll()

        def _search_text_changed(self, event: Any) -> None:
            if event.GetString().casefold() != self.search_query.casefold():
                self.search_index = -1
            event.Skip()

        def _search_next(self, _event: object) -> None:
            query = self.search.GetValue()
            labels = tuple(label for label, _node in self.search_entries)
            start = self.search_index if query.casefold() == self.search_query.casefold() else -1
            index = find_next_label(labels, query, start)
            self.search_query = query
            if index is None:
                self._set_status(f"No project item matches '{query}'")
                return
            self.search_index = index
            node = self.search_entries[index][1]
            self.tree.EnsureVisible(node)
            self.tree.SelectItem(node)

        def _clear_search(self, _event: object) -> None:
            self.search.Clear()
            self.search_query = ""
            self.search_index = -1

        def _show_properties(self, _event: object) -> None:
            target = self._export_target()
            if target is None:
                self._set_status("Select an item to view its properties")
                return
            state = self.tabs.get(target)
            rows = property_rows(
                self.catalog_rows.get(target, {}),
                state.payload if state is not None else None,
            )
            dialog = wx.Dialog(self, title="Properties", size=(840, 540))
            sizer = wx.BoxSizer(wx.VERTICAL)
            control = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
            control.InsertColumn(0, "Section", width=110)
            control.InsertColumn(1, "Property", width=260)
            control.InsertColumn(2, "Value", width=430)
            for index, row in enumerate(rows):
                inserted = control.InsertItem(index, row.section)
                control.SetItem(inserted, 1, row.name)
                control.SetItem(inserted, 2, row.value)
                if index % 2:
                    control.SetItemBackgroundColour(inserted, wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE))
            sizer.Add(control, 1, wx.EXPAND | wx.ALL, 8)
            sizer.Add(dialog.CreateButtonSizer(wx.OK), 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
            dialog.SetSizer(sizer)
            dialog.ShowModal()
            dialog.Destroy()

        def _show_diagnostics(self, _event: object) -> None:
            text = "\n".join(self.diagnostics) if self.diagnostics else "No parser diagnostics have been reported."
            self._show_text_dialog("Diagnostics", text)

        def _show_shortcuts(self, _event: object) -> None:
            dialog = wx.Dialog(self, title="Keyboard shortcuts", size=(780, 560))
            sizer = wx.BoxSizer(wx.VERTICAL)
            intro = wx.StaticText(
                dialog,
                label="All primary project, export, table, and navigation actions are available from the keyboard.",
            )
            sizer.Add(intro, 0, wx.EXPAND | wx.ALL, self.FromDIP(10))
            control = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
            control.InsertColumn(0, "Area", width=self.FromDIP(110))
            control.InsertColumn(1, "Shortcut", width=self.FromDIP(190))
            control.InsertColumn(2, "Action", width=self.FromDIP(440))
            for index, (section, key, action) in enumerate(SHORTCUT_ROWS):
                inserted = control.InsertItem(index, section)
                control.SetItem(inserted, 1, key)
                control.SetItem(inserted, 2, action)
                if index % 2:
                    control.SetItemBackgroundColour(inserted, wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE))
            sizer.Add(control, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(10))
            sizer.Add(
                dialog.CreateButtonSizer(wx.OK),
                0,
                wx.ALIGN_RIGHT | wx.ALL,
                self.FromDIP(10),
            )
            dialog.SetSizer(sizer)
            dialog.ShowModal()
            dialog.Destroy()

        def _show_about(self, _event: object) -> None:
            wx.MessageBox(
                about_text(str(getattr(wx, "__version__", wx.version()))),
                "About deopjufier",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

        def _show_text_dialog(self, title: str, text: str) -> None:
            dialog = wx.Dialog(self, title=title, size=(760, 520))
            sizer = wx.BoxSizer(wx.VERTICAL)
            control = wx.TextCtrl(dialog, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
            sizer.Add(control, 1, wx.EXPAND | wx.ALL, 8)
            sizer.Add(dialog.CreateButtonSizer(wx.OK), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
            dialog.SetSizer(sizer)
            dialog.ShowModal()
            dialog.Destroy()

        def _on_char_hook(self, event: Any) -> None:
            key = event.GetKeyCode()
            if self._handle_command_key(event, key) or self._handle_tree_key(event, key):
                return
            if key == wx.WXK_F6:
                self._switch_focus()
                return
            event.Skip()

        def _handle_command_key(self, event: Any, key: int) -> bool:
            if key == wx.WXK_F1:
                self._show_shortcuts(event)
            elif event.ControlDown() and event.ShiftDown() and key in {ord("S"), ord("s")}:
                self._on_export_all(event)
            elif event.ControlDown() and key in {ord("S"), ord("s")}:
                self._on_export_popup(event)
            elif event.ControlDown() and key in {wx.WXK_PAGEUP, wx.WXK_PAGEDOWN}:
                self._cycle_sheet(-1 if key == wx.WXK_PAGEUP else 1)
            elif event.ControlDown() and key == wx.WXK_TAB:
                self._cycle_document(-1 if event.ShiftDown() else 1)
            elif event.AltDown() and key in {wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER}:
                self._show_properties(event)
            else:
                return False
            return True

        def _handle_tree_key(self, event: Any, key: int) -> bool:
            if self.tree.HasFocus() and event.ShiftDown() and key == wx.WXK_F10:
                self._show_tree_context(self.tree.GetSelection())
                return True
            if self.tree.HasFocus() and key in {wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE}:
                item = self.tree.GetSelection()
                data = self.tree.GetItemData(item)
                if self._is_target(data):
                    self._activate_target(data, self.tree.GetItemText(item))
                elif self.tree.ItemHasChildren(item):
                    self.tree.Expand(item)
                return True
            return False

        def _switch_focus(self) -> None:
            if not self.tree.HasFocus():
                self.tree.SetFocus()
                return
            state = self._current_state()
            focus: Any = state.grid if state is not None and state.grid is not None else self._current_outer_page()
            (focus if focus is not None else self.notebook).SetFocus()

        def _cycle_sheet(self, delta: int) -> None:
            workbook = self.workbooks_by_page.get(self._current_outer_page())
            if workbook is None or not workbook.book.GetPageCount():
                return
            selection = workbook.book.GetSelection()
            index = (max(0, selection) + delta) % workbook.book.GetPageCount()
            target = workbook.targets_by_page.get(workbook.book.GetPage(index))
            if target is not None:
                self._activate_target(target, self.target_leaves[target].label)

        def _cycle_document(self, delta: int) -> None:
            count = self.notebook.GetPageCount()
            if not count:
                return
            index = (max(0, self.notebook.GetSelection()) + delta) % count
            page = self.notebook.GetPage(index)
            self._select_outer_page(page)
            self._document_selected()

        def _record_diagnostic(self, source: str, message: str) -> None:
            row = f"{source}: {message}"
            if row not in self.diagnostics:
                self.diagnostics.append(row)

        def _call_after(self, callback: Any, *args: object) -> None:
            """Post a worker result only while the wx application still exists."""
            if self.closed or wx.GetApp() is None:
                return
            try:
                wx.CallAfter(callback, *args)
            except AssertionError:
                # wxGTK can destroy wx.App between the check and CallAfter.
                return

        def _collect_payload_diagnostics(self, source: str, payload: dict[str, Any]) -> None:
            warnings = payload.get("warnings")
            if isinstance(warnings, list):
                for warning in warnings:
                    if warning:
                        self._record_diagnostic(source, str(warning))
            status = payload.get("status")
            if status not in {None, "ok"}:
                self._record_diagnostic(source, f"status={status}")

        def _update_tab_status(self, state: TabState) -> None:
            item = state.payload.get("item")
            name = str(item.get("name") or state.target[1]) if isinstance(item, dict) else state.target[1]
            document = state.payload.get("document")
            detected = str(document.get("detected_type", "")).upper() if isinstance(document, dict) else ""
            if state.table is not None:
                detail = f"{len(state.table.rows)} x {state.table.column_count}"
            else:
                detail = str(state.payload.get("status", ""))
            self._set_status(f"{state.target[0].name} · {detected} · {name}", detail)

        def _set_status(self, message: str, detail: str = "") -> None:
            self.status.SetStatusText(message, 0)
            self.status.SetStatusText(detail, 1)

        def _update_export_enabled(self) -> None:
            self.export_button.Enable(self._export_target() is not None)
            project = self._active_project_path()
            can_export_all = project is not None and project not in self.pending_project_exports
            self.export_all_button.Enable(can_export_all)
            self.export_all_menu_item.Enable(can_export_all)

        def _export_target(self) -> tuple[Path, str] | None:
            if self.context_target is not None:
                return self.context_target
            state = self._current_state()
            if state is not None:
                return state.target
            return self.active_target if self.active_target in self.catalog_rows else None

        def _export_state(self) -> TabState | None:
            target = self._export_target()
            return self.tabs.get(target) if target is not None else None

        def _current_outer_page(self) -> object | None:
            selection = self.notebook.GetSelection()
            if selection < 0 or selection >= self.notebook.GetPageCount():
                return None
            return self.notebook.GetPage(selection)

        def _current_state(self) -> TabState | None:
            page = self._current_outer_page()
            if page is None:
                return None
            workbook = self.workbooks_by_page.get(page)
            if workbook is None:
                return self._state_for_page(page)
            selection = workbook.book.GetSelection()
            if selection < 0 or selection >= workbook.book.GetPageCount():
                return None
            target = workbook.targets_by_page.get(workbook.book.GetPage(selection))
            return self.tabs.get(target) if target is not None else None

        def _state_for_page(self, page: object) -> TabState | None:
            return next((state for state in self.tabs.values() if state.page is page), None)

        def _page_index(self, page: object) -> int | None:
            return next(
                (index for index in range(self.notebook.GetPageCount()) if self.notebook.GetPage(index) is page),
                None,
            )

        def _select_outer_page(self, page: object) -> None:
            index = self._page_index(page)
            if index is not None:
                self.notebook.ChangeSelection(index)
                self._sync_document_buttons(page)

        def _is_target(self, value: object) -> TypeGuard[tuple[Path, str]]:
            return (
                isinstance(value, tuple)
                and len(value) == 2
                and isinstance(value[0], Path)
                and isinstance(value[1], str)
            )

        def _on_close(self, event: Any) -> None:
            self.closed = True
            self.backend.close()
            event.Skip()

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


__all__ = ["cli_entrypoint", "main"]
