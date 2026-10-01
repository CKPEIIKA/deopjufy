"""Optional-viewer layout handlers for the lazily loaded wx frame."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deopjufy_view.model import payload_bytes
from deopjufy_view.presentation import recovered_image

from .frame_state import _CHART_ICON_RGB, ViewerFrameProtocol


class LayoutMixin:
    def _build_menu(self: ViewerFrameProtocol) -> None:
        file_menu = self.wx.Menu()
        file_menu.Append(self.wx.ID_OPEN, "&Open projects…\tCtrl+O")
        file_menu.AppendSubMenu(self._export_menu(), "&Export")
        self.export_all_menu_item = file_menu.Append(
            self.ids.export_all_id,
            "Export &all project content…\tCtrl+Shift+S",
        )
        file_menu.Append(self.ids.close_tab_id, "&Close tab\tCtrl+W")
        file_menu.AppendSeparator()
        file_menu.Append(self.wx.ID_EXIT, "E&xit")

        view_menu = self.wx.Menu()
        view_menu.Append(self.ids.find_id, "&Find in project…\tCtrl+F")
        view_menu.Append(self.ids.properties_id, "&Properties…\tAlt+Enter")
        view_menu.Append(self.ids.diagnostics_id, "&Diagnostics…")
        view_menu.AppendSeparator()
        view_menu.Append(self.ids.expand_all_id, "&Expand all branches\tCtrl+Shift+E")
        view_menu.Append(self.ids.collapse_all_id, "&Collapse all branches\tCtrl+Shift+C")
        unwrap_item = view_menu.AppendCheckItem(self.ids.unwrap_groups_id, "&Unwrap single-child groups")
        unwrap_item.Check(self.unwrap_single_child_groups)
        evidence_item = view_menu.AppendCheckItem(self.ids.show_evidence_id, "Show &unknown/recovery evidence")
        evidence_item.Check(self.show_recovery_evidence)

        help_menu = self.wx.Menu()
        help_menu.Append(self.ids.shortcuts_id, "&Keyboard shortcuts\tF1")
        help_menu.Append(self.wx.ID_ABOUT, "&About")

        menu_bar = self.wx.MenuBar()
        menu_bar.Append(file_menu, "&File")
        menu_bar.Append(view_menu, "&View")
        menu_bar.Append(help_menu, "&Help")
        self.SetMenuBar(menu_bar)

    def _export_menu(self: ViewerFrameProtocol, target: tuple[Path, str] | None = None) -> Any:
        menu = self.wx.Menu()
        json_item = menu.Append(self.ids.export_json_id, "Item response (JSON)…")
        artifact_item = menu.Append(self.ids.export_artifact_id, "Recovered artifact…")
        menu.AppendSeparator()
        format_items = {
            "csv": menu.Append(self.ids.export_csv_id, "Table as CSV…"),
            "tsv": menu.Append(self.ids.export_tsv_id, "Table as TSV…"),
            "jsonl": menu.Append(self.ids.export_jsonl_id, "Table as JSONL…"),
            "xlsx": menu.Append(self.ids.export_xlsx_id, "Table as Excel workbook (XLSX)…"),
        }
        image_item = menu.Append(self.ids.export_image_id, "Image or plot preview…")
        menu.AppendSeparator()
        selection_items = (
            menu.Append(self.ids.export_selection_csv_id, "Selected cells as CSV…"),
            menu.Append(self.ids.export_selection_tsv_id, "Selected cells as TSV…"),
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

    def _build_toolbar(self: ViewerFrameProtocol) -> None:
        self.action_bar = self.wx.Panel(self, style=self.wx.BORDER_NONE)
        action_sizer = self.wx.BoxSizer(self.wx.HORIZONTAL)
        self.open_button = self.wx.Button(self.action_bar, self.wx.ID_OPEN, "Open…")
        self.open_button.SetToolTip("Open one or more OPJ/OPJU projects (Ctrl+O)")
        self.export_button = self.wx.Button(self.action_bar, self.ids.export_tool_id, "Export ▾")
        self.export_button.SetToolTip("Export the current item (Ctrl+S)")
        self.export_all_button = self.wx.Button(self.action_bar, self.ids.export_all_id, "Export All…")
        self.export_all_button.SetToolTip("Extract all content from the active project (Ctrl+Shift+S)")
        for button in (self.open_button, self.export_button, self.export_all_button):
            button.SetMinSize((-1, self.FromDIP(32)))
            action_sizer.Add(button, 0, self.wx.ALIGN_CENTER_VERTICAL | self.wx.RIGHT, self.FromDIP(6))
        action_sizer.AddStretchSpacer()
        self.search = self.wx.SearchCtrl(
            self.action_bar,
            style=self.wx.TE_PROCESS_ENTER,
            size=(self.FromDIP(270), self.FromDIP(32)),
        )
        self.search.SetDescriptiveText("Search project")
        self.search.ShowCancelButton(True)
        action_sizer.Add(self.search, 0, self.wx.ALIGN_CENTER_VERTICAL)
        self.action_bar.SetSizer(action_sizer)
        action_sizer.SetSizeHints(self.action_bar)

    def _build_content(self: ViewerFrameProtocol) -> None:
        self.splitter = self.wx.SplitterWindow(self)
        self.splitter.SetMinimumPaneSize(180)
        self.splitter.SetSashGravity(0.25)
        project_panel = self.wx.Panel(self.splitter)
        project_sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        project_header = self.wx.StaticText(project_panel, label="Project Explorer")
        project_font = project_header.GetFont()
        project_font.MakeBold()
        project_header.SetFont(project_font)
        project_sizer.Add(
            project_header,
            0,
            self.wx.EXPAND | self.wx.LEFT | self.wx.RIGHT | self.wx.TOP,
            self.FromDIP(10),
        )
        project_sizer.AddSpacer(self.FromDIP(7))
        self.tree = self.wx.TreeCtrl(
            project_panel,
            style=(
                self.wx.TR_HAS_BUTTONS
                | self.wx.TR_LINES_AT_ROOT
                | self.wx.TR_SINGLE
                | self.wx.TR_HIDE_ROOT
                | self.wx.TR_FULL_ROW_HIGHLIGHT
            ),
        )
        self.tree.SetMinSize((200, -1))
        self._assign_tree_images()
        self.root = self.tree.AddRoot("Projects")
        project_sizer.Add(self.tree, 1, self.wx.EXPAND)
        project_panel.SetSizer(project_sizer)

        self.preview_host = self.wx.Simplebook(self.splitter)
        self._build_message_page()
        documents_panel = self.wx.Panel(self.preview_host)
        documents_sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        self.document_tab_bar = self.wx.ScrolledWindow(documents_panel, style=self.wx.HSCROLL | self.wx.BORDER_NONE)
        self.document_tab_bar.SetMinSize((-1, self.FromDIP(34)))
        self.document_tab_sizer = self.wx.BoxSizer(self.wx.HORIZONTAL)
        self.document_tab_bar.SetSizer(self.document_tab_sizer)
        self.document_tab_bar.SetScrollRate(12, 0)
        self.document_buttons: dict[object, Any] = {}
        self.notebook = self.wx.Simplebook(documents_panel)
        documents_sizer.Add(self.document_tab_bar, 0, self.wx.EXPAND)
        documents_sizer.Add(self.notebook, 1, self.wx.EXPAND)
        documents_panel.SetSizer(documents_sizer)
        self.preview_host.AddPage(documents_panel, "Documents")
        self.splitter.SplitVertically(project_panel, self.preview_host, 250)

        frame_sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        frame_sizer.Add(
            self.action_bar,
            0,
            self.wx.EXPAND | self.wx.LEFT | self.wx.RIGHT | self.wx.TOP | self.wx.BOTTOM,
            self.FromDIP(8),
        )
        frame_sizer.Add(self.splitter, 1, self.wx.EXPAND)
        self.SetSizer(frame_sizer)

    def _build_message_page(self: ViewerFrameProtocol) -> None:
        self.message_panel = self.wx.Panel(self.preview_host)
        self.message_sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        self.message_panel.SetSizer(self.message_sizer)
        self.preview_host.AddPage(self.message_panel, "Message")

    def _set_initial_sash(self: ViewerFrameProtocol) -> None:
        width = self.splitter.GetClientSize().GetWidth()
        self.splitter.SetSashPosition(max(220, min(280, round(width * 0.23))))

    def _assign_tree_images(self: ViewerFrameProtocol) -> None:
        image_list = self.wx.ImageList(16, 16)
        art = {
            "project": self.wx.ART_HARDDISK,
            "folder": self.wx.ART_FOLDER,
            "folder_open": self.wx.ART_FOLDER_OPEN,
            "workbook": self.wx.ART_REPORT_VIEW,
            "worksheet": self.wx.ART_LIST_VIEW,
            "graph": self.wx.ART_MISSING_IMAGE,
            "note": self.wx.ART_NORMAL_FILE,
            "function": self.wx.ART_EXECUTABLE_FILE,
            "raw": self.wx.ART_WARNING,
            "generic": self.wx.ART_NORMAL_FILE,
        }
        self.tree_icons: dict[str, int] = {}
        for key, art_id in art.items():
            bitmap = (
                self._chart_bitmap(16)
                if key == "graph"
                else self.wx.ArtProvider.GetBitmap(art_id, self.wx.ART_OTHER, (16, 16))
            )
            self.tree_icons[key] = image_list.Add(bitmap)
        self.tree.AssignImageList(image_list)

    def _chart_bitmap(self: ViewerFrameProtocol, size: int) -> Any:
        # The stock art set has no chart glyph (ART_MISSING_IMAGE reads as a broken image).
        bitmap = self.wx.Bitmap.FromRGBA(size, size, 0, 0, 0, 0)
        dc = self.wx.MemoryDC(bitmap)
        context = self.wx.GraphicsContext.Create(dc)
        axis = self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_WINDOWTEXT)
        # Amber stays visible on light, dark, and selected (highlighted) rows alike.
        line = self.wx.Colour(*_CHART_ICON_RGB)
        context.SetPen(self.wx.Pen(axis, 1))
        context.StrokeLine(2, 1, 2, size - 2)
        context.StrokeLine(2, size - 2, size - 1, size - 2)
        context.SetPen(self.wx.Pen(line, 2))
        points = [(4, size - 5), (7, size - 9), (10, size - 7), (14, 3)]
        context.StrokeLines([self.wx.Point2D(x, y) for x, y in points])
        del context
        dc.SelectObject(self.wx.NullBitmap)
        return bitmap

    def _bind_events(self: ViewerFrameProtocol) -> None:
        # Dropping .opj/.opju files anywhere on the window opens them.
        for window in (self, self.tree):
            window.SetDropTarget(self.widgets.project_drop_target(self))
        self.Bind(self.wx.EVT_MENU, self._on_open, id=self.wx.ID_OPEN)
        self.open_button.Bind(self.wx.EVT_BUTTON, self._on_open)
        self.export_button.Bind(self.wx.EVT_BUTTON, self._on_export_popup)
        self.export_all_button.Bind(self.wx.EVT_BUTTON, self._on_export_all)
        self.Bind(self.wx.EVT_MENU, self._on_export_all, id=self.ids.export_all_id)
        self.Bind(self.wx.EVT_MENU, self._on_export_json, id=self.ids.export_json_id)
        self.Bind(self.wx.EVT_MENU, self._on_export_artifact, id=self.ids.export_artifact_id)
        self.Bind(self.wx.EVT_MENU, lambda _event: self._export_table("csv"), id=self.ids.export_csv_id)
        self.Bind(self.wx.EVT_MENU, lambda _event: self._export_table("tsv"), id=self.ids.export_tsv_id)
        self.Bind(self.wx.EVT_MENU, lambda _event: self._export_table("jsonl"), id=self.ids.export_jsonl_id)
        self.Bind(self.wx.EVT_MENU, lambda _event: self._export_table("xlsx"), id=self.ids.export_xlsx_id)
        self.Bind(self.wx.EVT_MENU, self._export_image, id=self.ids.export_image_id)
        self.Bind(
            self.wx.EVT_MENU,
            lambda _event: self._export_selection(",", ".csv"),
            id=self.ids.export_selection_csv_id,
        )
        self.Bind(
            self.wx.EVT_MENU,
            lambda _event: self._export_selection("\t", ".tsv"),
            id=self.ids.export_selection_tsv_id,
        )
        self.Bind(self.wx.EVT_MENU, self._on_close_tab, id=self.ids.close_tab_id)
        self.Bind(self.wx.EVT_MENU, lambda _event: self.Close(), id=self.wx.ID_EXIT)
        self.Bind(self.wx.EVT_MENU, self._focus_search, id=self.ids.find_id)
        self.Bind(self.wx.EVT_MENU, self._show_properties, id=self.ids.properties_id)
        self.Bind(self.wx.EVT_MENU, self._show_diagnostics, id=self.ids.diagnostics_id)
        self.Bind(self.wx.EVT_MENU, self._expand_all, id=self.ids.expand_all_id)
        self.Bind(self.wx.EVT_MENU, self._collapse_all, id=self.ids.collapse_all_id)
        self.Bind(self.wx.EVT_MENU, self._toggle_unwrap_groups, id=self.ids.unwrap_groups_id)
        self.Bind(self.wx.EVT_MENU, self._toggle_recovery_evidence, id=self.ids.show_evidence_id)
        self.Bind(self.wx.EVT_MENU, self._open_context_item, id=self.ids.open_item_id)
        self.Bind(self.wx.EVT_MENU, self._show_shortcuts, id=self.ids.shortcuts_id)
        self.Bind(self.wx.EVT_MENU, self._show_about, id=self.wx.ID_ABOUT)
        self.tree.Bind(self.wx.EVT_TREE_SEL_CHANGED, self._on_select)
        self.tree.Bind(self.wx.EVT_TREE_ITEM_ACTIVATED, self._on_tree_activate)
        self.tree.Bind(self.wx.EVT_TREE_ITEM_MENU, self._on_tree_menu)
        self.search.Bind(self.wx.EVT_TEXT_ENTER, self._search_next)
        self.search.Bind(self.wx.EVT_SEARCHCTRL_SEARCH_BTN, self._search_next)
        self.search.Bind(self.wx.EVT_SEARCHCTRL_CANCEL_BTN, self._clear_search)
        self.search.Bind(self.wx.EVT_TEXT, self._search_text_changed)
        self.Bind(self.wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(self.wx.EVT_CLOSE, self._on_close)

    def _show_welcome(self: ViewerFrameProtocol) -> None:
        if self.notebook.GetPageCount():
            return
        self._show_message(
            "Open an Origin project",
            "Read-only recovery for OPJ and OPJU files. Drop project files here or use Open.",
            show_open=True,
        )

    def _show_loading(self: ViewerFrameProtocol, label: str) -> None:
        if not self.notebook.GetPageCount():
            self._show_message(
                "Reading project catalog",
                label,
                show_open=False,
                busy=True,
                detail="Listing worksheets, graphs, notes, and other recoverable objects. "
                "Large projects can take a while.",
            )

    def _show_select_item(self: ViewerFrameProtocol) -> None:
        if not self.notebook.GetPageCount():
            self._show_message(
                "Select a project item",
                "Choose a worksheet, graph, note, or recovered object in Project Explorer",
                show_open=False,
            )

    def _show_message(
        self: ViewerFrameProtocol,
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
            view = self.widgets.loading_view(self.message_panel, title, hint, detail)
            self.message_sizer.Add(view, 0, self.wx.EXPAND | self.wx.LEFT | self.wx.RIGHT, self.FromDIP(40))
        else:
            title_control = self.wx.StaticText(self.message_panel, label=title)
            title_font = title_control.GetFont()
            title_font.MakeLarger()
            title_font.MakeBold()
            title_control.SetFont(title_font)
            self.message_sizer.Add(title_control, 0, self.wx.ALIGN_CENTER | self.wx.BOTTOM, self.FromDIP(10))
            hint_control = self.wx.StaticText(self.message_panel, label=hint, style=self.wx.ALIGN_CENTER)
            hint_control.Wrap(self.FromDIP(560))
            self.message_sizer.Add(hint_control, 0, self.wx.ALIGN_CENTER | self.wx.BOTTOM, self.FromDIP(16))
            if show_open:
                button = self.wx.Button(self.message_panel, self.wx.ID_OPEN, "Open projects…")
                button.Bind(self.wx.EVT_BUTTON, self._on_open)
                self.message_sizer.Add(button, 0, self.wx.ALIGN_CENTER)
        self.message_sizer.AddStretchSpacer()
        self.message_panel.Layout()
        self.preview_host.ChangeSelection(0)

    def _remove_welcome(self: ViewerFrameProtocol) -> None:
        self.preview_host.ChangeSelection(1)
