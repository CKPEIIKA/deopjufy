"""Optional-viewer tabs handlers for the lazily loaded wx frame."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import Any

from deopjufy_view.backend import DeopjufyCommandError
from deopjufy_view.model import TabularView, payload_text, tabular_view
from deopjufy_view.presentation import recovered_image, unreadable_item_summary
from deopjufy_view.project_tree import sibling_sheets

from .frame_state import (
    _MIN_WORKBOOK_SHEETS,
    _STRIPE_BLEND,
    _TEXT_MARGIN_DIP,
    TabState,
    ViewerFrameProtocol,
    WorkbookState,
)


class TabsMixin:
    def _workbook_for_target(self: ViewerFrameProtocol, target: tuple[Path, str]) -> WorkbookState | None:
        leaf = self.target_leaves.get(target)
        if leaf is None:
            return None
        sheets = sibling_sheets(self.catalog_leaves.get(target[0], ()), leaf)
        if len(sheets) < _MIN_WORKBOOK_SHEETS:
            return None
        key = target[0], leaf.folders
        existing = self.workbooks.get(key)
        if existing is not None:
            return existing
        page = self.wx.Panel(self.notebook)
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        sheet_book = self.wx.Simplebook(page)
        tab_bar = self.wx.ScrolledWindow(page, style=self.wx.HSCROLL | self.wx.BORDER_NONE)
        tab_bar.SetMinSize((-1, self.FromDIP(34)))
        tab_sizer = self.wx.BoxSizer(self.wx.HORIZONTAL)
        tab_bar.SetSizer(tab_sizer)
        tab_bar.SetScrollRate(12, 0)
        sizer.Add(sheet_book, 1, self.wx.EXPAND)
        sizer.Add(tab_bar, 0, self.wx.EXPAND)
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
            button = self.wx.ToggleButton(tab_bar, label=sheet.label, style=self.wx.BU_EXACTFIT)
            button.Bind(
                self.wx.EVT_TOGGLEBUTTON,
                lambda event, selected=sheet_target: self._on_sheet_button(event, selected),
            )
            state.sheet_buttons[sheet_target] = button
            tab_sizer.Add(
                button,
                0,
                self.wx.ALIGN_CENTER_VERTICAL | self.wx.RIGHT,
                self.FromDIP(2),
            )
        tab_bar.FitInside()
        return state

    def _make_sheet_placeholder(self: ViewerFrameProtocol, parent: Any, label: str) -> Any:
        panel = self.wx.Panel(parent)
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        sizer.AddStretchSpacer()
        message = self.wx.StaticText(panel, label=f"Select {label} to load")
        sizer.Add(message, 0, self.wx.ALIGN_CENTER)
        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _set_sheet_message(
        self: ViewerFrameProtocol,
        workbook: WorkbookState,
        target: tuple[Path, str],
        message: str,
    ) -> None:
        panel = workbook.sheet_pages[target]
        for child in panel.GetChildren():
            child.Destroy()
        sizer = panel.GetSizer() or self.wx.BoxSizer(self.wx.VERTICAL)
        sizer.Clear(delete_windows=False)
        sizer.AddStretchSpacer()
        sizer.Add(self.wx.StaticText(panel, label=message), 0, self.wx.ALIGN_CENTER)
        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        panel.Layout()

    def _set_sheet_loading(
        self: ViewerFrameProtocol,
        workbook: WorkbookState,
        target: tuple[Path, str],
        label: str,
    ) -> None:
        panel = workbook.sheet_pages[target]
        for child in panel.GetChildren():
            child.Destroy()
        sizer = panel.GetSizer() or self.wx.BoxSizer(self.wx.VERTICAL)
        sizer.Clear(delete_windows=False)
        sizer.AddStretchSpacer()
        view = self.widgets.loading_view(
            panel,
            f"Loading {label}",
            f"Reading from {target[0].name}",
            "Decoding the stored values and preparing the view.",
        )
        sizer.Add(view, 0, self.wx.EXPAND | self.wx.LEFT | self.wx.RIGHT, self.FromDIP(40))
        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        panel.Layout()

    def _select_target_page(self: ViewerFrameProtocol, target: tuple[Path, str]) -> None:
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

    def _activate_target(self: ViewerFrameProtocol, target: tuple[Path, str], label: str) -> None:
        self.active_target = target
        leaf = self.target_leaves.get(target)
        if (
            leaf is not None
            and len(sibling_sheets(self.catalog_leaves.get(target[0], ()), leaf)) >= _MIN_WORKBOOK_SHEETS
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
        self: ViewerFrameProtocol,
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

    def _complete_get(self: ViewerFrameProtocol, requested_target: tuple[Path, str], payload: dict[str, Any]) -> None:
        if self.closed:
            return
        state = self._open_payload_tab(requested_target, payload)
        self._collect_payload_diagnostics(requested_target[0].name, payload)
        if requested_target == self.active_target:
            self._select_target_page(state.target)
            self._update_tab_status(state)

    def _open_payload_tab(self: ViewerFrameProtocol, target: tuple[Path, str], payload: dict[str, Any]) -> TabState:
        existing = self.tabs.get(target)
        if existing is not None:
            return existing
        table = tabular_view(payload)
        workbook = self._workbook_for_target(target) if table is not None else None
        panel = workbook.sheet_pages[target] if workbook is not None else self.wx.Panel(self.notebook)
        for child in panel.GetChildren():
            child.Destroy()
        sizer = panel.GetSizer() or self.wx.BoxSizer(self.wx.VERTICAL)
        sizer.Clear(delete_windows=False)
        panel.SetSizer(sizer)
        grid, image_shape = self._populate_tab_panel(panel, payload, table)
        item = payload.get("item")
        label = str(item.get("name") or item.get("source_object_path") or "Item") if isinstance(item, dict) else "Item"
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
            image_shape=image_shape,
        )
        self.tabs[target] = state
        self._update_export_enabled()
        return state

    def _populate_tab_panel(
        self: ViewerFrameProtocol,
        panel: Any,
        payload: dict[str, Any],
        table: TabularView | None,
    ) -> tuple[Any | None, tuple[str, int, int] | None]:
        sizer = panel.GetSizer()
        if table is not None:
            grid = self._make_grid(panel, table)
            sizer.Add(grid, 1, self.wx.EXPAND)
            return grid, None
        image_payload = recovered_image(payload)
        if image_payload is not None:
            image_view = self._make_image_view(panel, image_payload.data)
            if image_view is not None:
                sizer.Add(image_view, 1, self.wx.EXPAND)
                image_shape = (
                    image_payload.output_format,
                    int(image_view.image.GetWidth()),
                    int(image_view.image.GetHeight()),
                )
                return None, image_shape
        sizer.Add(self._make_content_view(panel, payload), 1, self.wx.EXPAND)
        return None, None

    def _make_grid(self: ViewerFrameProtocol, parent: Any, table: TabularView) -> Any:
        grid = self.wx_grid.Grid(parent)
        stripe = self.wx_grid.GridCellAttr()
        stripe.SetBackgroundColour(self._stripe_colour())
        grid.SetTable(self.widgets.grid_table(table, stripe), True)
        grid.EnableEditing(False)
        grid.SetSelectionMode(self.wx_grid.Grid.SelectCells)
        grid.SetMargins(0, 0)
        if hasattr(grid, "SetDefaultCellOverflow"):
            grid.SetDefaultCellOverflow(False)
        row_label_width = grid.GetTextExtent("Formula")[0] + self.FromDIP(22)
        grid.SetRowLabelSize(max(self.FromDIP(64), row_label_width))
        grid.SetColLabelSize(self.FromDIP(30))
        for row in range(len(table.metadata_rows)):
            attr = self.wx_grid.GridCellAttr()
            attr.SetBackgroundColour(self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_BTNFACE))
            attr.SetReadOnly(True)
            attr.SetOverflow(False)
            grid.SetRowAttr(row, attr)
        if table.metadata_rows and hasattr(grid, "FreezeTo"):
            grid.FreezeTo(len(table.metadata_rows), 0)
        for column in range(table.column_count):
            if table.column_is_numeric(column):
                attr = self.wx_grid.GridCellAttr()
                attr.SetAlignment(self.wx.ALIGN_RIGHT, self.wx.ALIGN_CENTER_VERTICAL)
                attr.SetOverflow(False)
                grid.SetColAttr(column, attr)
            grid.SetColSize(column, self._column_width(grid, table, column))
        grid.Bind(self.wx.EVT_KEY_DOWN, self._on_grid_key)
        return grid

    def _stripe_colour(self: ViewerFrameProtocol) -> Any:
        background = self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_WINDOW)
        text = self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_WINDOWTEXT)
        channels = zip(background.Get(includeAlpha=False), text.Get(includeAlpha=False), strict=True)
        return self.wx.Colour(*(round(back + (fore - back) * _STRIPE_BLEND) for back, fore in channels))

    def _make_image_view(self: ViewerFrameProtocol, parent: Any, payload: bytes) -> Any | None:
        preview = self.widgets.image_preview(parent, payload)
        if not preview.IsOk():
            preview.Destroy()
            return None
        return preview

    def _make_content_view(self: ViewerFrameProtocol, parent: Any, payload: dict[str, Any]) -> Any:
        summary = unreadable_item_summary(payload)
        if summary is not None:
            return self._make_unreadable_view(parent, *summary)
        return self._make_text_view(parent, payload)

    def _make_unreadable_view(self: ViewerFrameProtocol, parent: Any, title: str, detail: str) -> Any:
        panel = self.wx.Panel(parent)
        panel.SetBackgroundColour(self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_WINDOW))
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        title_control = self.wx.StaticText(panel, label=title)
        title_font = title_control.GetFont()
        title_font.MakeLarger()
        title_font.MakeBold()
        title_control.SetFont(title_font)
        detail_control = self.wx.StaticText(panel, label=detail, style=self.wx.ALIGN_CENTER)
        detail_control.Wrap(self.FromDIP(560))
        sizer.AddStretchSpacer()
        sizer.Add(title_control, 0, self.wx.ALIGN_CENTER | self.wx.BOTTOM, self.FromDIP(10))
        sizer.Add(detail_control, 0, self.wx.ALIGN_CENTER)
        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _make_text_view(self: ViewerFrameProtocol, parent: Any, payload: dict[str, Any]) -> Any:
        # A padded host keeps prose off the edges; explicit colours avoid GTK's
        # greyed look for read-only text controls.
        host = self.wx.Panel(parent)
        background = self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_WINDOW)
        host.SetBackgroundColour(background)
        text = self.wx.TextCtrl(
            host,
            value=payload_text(payload),
            style=self.wx.TE_MULTILINE | self.wx.TE_READONLY | self.wx.TE_WORDWRAP | self.wx.BORDER_NONE,
        )
        text.SetBackgroundColour(background)
        text.SetForegroundColour(self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_WINDOWTEXT))
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        sizer.Add(text, 1, self.wx.EXPAND | self.wx.ALL, self.FromDIP(_TEXT_MARGIN_DIP))
        host.SetSizer(sizer)
        return host

    def _column_width(self: ViewerFrameProtocol, grid: Any, table: TabularView, column: int) -> int:
        values = [table.headers[column] if column < len(table.headers) else ""]
        values.extend(row[1][column] for row in table.metadata_rows if column < len(row[1]))
        values.extend(row[column] for row in table.rows[:100] if column < len(row))
        text_width = max((int(grid.GetTextExtent(value)[0]) for value in values), default=self.FromDIP(72))
        return min(self.FromDIP(340), max(self.FromDIP(104), text_width + self.FromDIP(28)))

    def _document_selected(self: ViewerFrameProtocol) -> None:
        state = self._current_state()
        if state is not None:
            self.active_target = state.target
            self._sync_tree_selection(state.target)
            self._update_tab_status(state)
        else:
            self._activate_current_workbook_sheet()
        self._update_export_enabled()

    def _on_sheet_button(self: ViewerFrameProtocol, event: Any, target: tuple[Path, str]) -> None:
        if not event.IsChecked():
            event.GetEventObject().SetValue(True)
            return
        self.active_target = target
        self._sync_tree_selection(target)
        self._activate_target(target, self.target_leaves[target].label)

    def _activate_current_workbook_sheet(self: ViewerFrameProtocol) -> None:
        outer = self._current_outer_page()
        workbook = self.workbooks_by_page.get(outer)
        if workbook is None:
            return
        selection = workbook.book.GetSelection()
        if 0 <= selection < workbook.book.GetPageCount():
            target = workbook.targets_by_page.get(workbook.book.GetPage(selection))
            if target is not None:
                self._activate_target(target, self.target_leaves[target].label)

    def _sync_tree_selection(self: ViewerFrameProtocol, target: tuple[Path, str]) -> None:
        node = self.target_nodes.get(target)
        if node is not None and self.tree.GetSelection() != node:
            self.tree.EnsureVisible(node)
            self.tree.SelectItem(node)

    def _on_close_tab(self: ViewerFrameProtocol, _event: object) -> None:
        page = self._current_outer_page()
        if page is None:
            return
        self._forget_page_state(page)
        index = self._page_index(page)
        if index is not None:
            self._delete_document_page(page, index)
        self._restore_after_page_close()
        self._update_export_enabled()

    def _forget_page_state(self: ViewerFrameProtocol, page: object) -> None:
        workbook = self.workbooks_by_page.pop(page, None)
        if workbook is not None:
            self.workbooks.pop(workbook.key, None)
            for target in workbook.sheet_pages:
                self.tabs.pop(target, None)
                self.pending_targets.discard(target)
            return
        state = self._state_for_page(page)
        if state is not None:
            self.tabs.pop(state.target, None)
            self.pending_targets.discard(state.target)

    def _restore_after_page_close(self: ViewerFrameProtocol) -> None:
        current = self._current_state()
        self.active_target = current.target if current is not None else None
        if current is not None:
            self._update_tab_status(current)
        if current is None:
            self._show_select_item() if self.catalogs else self._show_welcome()
