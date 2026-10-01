"""Optional-viewer input handlers for the lazily loaded wx frame."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeGuard

from deopjufy_view.model import TabularView, find_next_label, table_region_text
from deopjufy_view.presentation import SHORTCUT_ROWS, about_text, property_rows, status_detail

from .frame_state import _TARGET_COMPONENT_COUNT, TabState, ViewerFrameProtocol


class InputMixin:
    def _on_grid_key(self: ViewerFrameProtocol, event: Any) -> None:
        if event.ControlDown() and event.GetKeyCode() in (ord("C"), ord("c")):
            self._copy_grid_selection(event.GetEventObject())
            return
        event.Skip()

    def _copy_grid_selection(self: ViewerFrameProtocol, grid: Any) -> None:
        state = self._current_state()
        if state is None or state.table is None:
            return
        text = table_region_text(state.table, *self._selection_bounds(grid, state.table))
        if self.wx.TheClipboard.Open():
            try:
                self.wx.TheClipboard.SetData(self.wx.TextDataObject(text))
                self._set_status("Copied selected cells")
            finally:
                self.wx.TheClipboard.Close()

    def _selection_bounds(self: ViewerFrameProtocol, grid: Any, table: TabularView) -> tuple[int, int, int, int]:
        top_left = grid.GetSelectionBlockTopLeft()
        bottom_right = grid.GetSelectionBlockBottomRight()
        if top_left and bottom_right:
            return (
                int(top_left[0].GetRow()),
                int(top_left[0].GetCol()),
                int(bottom_right[0].GetRow()),
                int(bottom_right[0].GetCol()),
            )
        rows = [int(row) for row in grid.GetSelectedRows()]
        if rows:
            return min(rows), 0, max(rows), max(0, table.column_count - 1)
        columns = [int(column) for column in grid.GetSelectedCols()]
        if columns:
            return 0, min(columns), max(0, table.grid_row_count - 1), max(columns)
        cells = list(grid.GetSelectedCells())
        if cells:
            row = int(cells[0].GetRow())
            column = int(cells[0].GetCol())
            return row, column, row, column
        row = max(0, int(grid.GetGridCursorRow()))
        column = max(0, int(grid.GetGridCursorCol()))
        return row, column, row, column

    def _focus_search(self: ViewerFrameProtocol, _event: object) -> None:
        self.search.SetFocus()
        self.search.SelectAll()

    def _search_text_changed(self: ViewerFrameProtocol, event: Any) -> None:
        if event.GetString().casefold() != self.search_query.casefold():
            self.search_index = -1
        event.Skip()

    def _search_next(self: ViewerFrameProtocol, _event: object) -> None:
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

    def _clear_search(self: ViewerFrameProtocol, _event: object) -> None:
        self.search.Clear()
        self.search_query = ""
        self.search_index = -1

    def _show_properties(self: ViewerFrameProtocol, _event: object) -> None:
        target = self._export_target()
        if target is None:
            self._set_status("Select an item to view its properties")
            return
        state = self.tabs.get(target)
        rows = property_rows(
            self.catalog_rows.get(target, {}),
            state.payload if state is not None else None,
        )
        dialog = self.wx.Dialog(
            self,
            title="Properties",
            size=self.FromDIP(self.wx.Size(860, 560)),
            style=self.wx.DEFAULT_DIALOG_STYLE | self.wx.RESIZE_BORDER,
        )
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        control = self.wx.ListCtrl(dialog, style=self.wx.LC_REPORT | self.wx.LC_SINGLE_SEL | self.wx.BORDER_SUNKEN)
        control.InsertColumn(0, "Section", width=self.FromDIP(100))
        control.InsertColumn(1, "Property", width=self.FromDIP(250))
        control.InsertColumn(2, "Value", width=self.FromDIP(440))
        control.Bind(self.wx.EVT_SIZE, self._fill_last_column)
        previous_section = None
        for index, row in enumerate(rows):
            # Name each section once so the groups read as groups.
            inserted = control.InsertItem(index, row.section if row.section != previous_section else "")
            previous_section = row.section
            control.SetItem(inserted, 1, row.name)
            control.SetItem(inserted, 2, row.value)
            if index % 2:
                control.SetItemBackgroundColour(inserted, self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_BTNFACE))
        sizer.Add(control, 1, self.wx.EXPAND | self.wx.ALL, 8)
        sizer.Add(
            dialog.CreateButtonSizer(self.wx.OK),
            0,
            self.wx.ALIGN_RIGHT | self.wx.LEFT | self.wx.RIGHT | self.wx.BOTTOM,
            8,
        )
        dialog.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()

    def _fill_last_column(self: ViewerFrameProtocol, event: Any) -> None:
        control = event.GetEventObject()
        used = sum(control.GetColumnWidth(column) for column in range(control.GetColumnCount() - 1))
        available = control.GetClientSize().width - used
        if available > self.FromDIP(120):
            control.SetColumnWidth(control.GetColumnCount() - 1, available)
        event.Skip()

    def _show_diagnostics(self: ViewerFrameProtocol, _event: object) -> None:
        text = "\n".join(self.diagnostics) if self.diagnostics else "No parser diagnostics have been reported."
        self._show_text_dialog("Diagnostics", text)

    def _show_shortcuts(self: ViewerFrameProtocol, _event: object) -> None:
        dialog = self.wx.Dialog(self, title="Keyboard shortcuts", size=(780, 560))
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        intro = self.wx.StaticText(
            dialog,
            label="All primary project, export, table, and navigation actions are available from the keyboard.",
        )
        sizer.Add(intro, 0, self.wx.EXPAND | self.wx.ALL, self.FromDIP(10))
        control = self.wx.ListCtrl(dialog, style=self.wx.LC_REPORT | self.wx.LC_SINGLE_SEL | self.wx.BORDER_SUNKEN)
        control.InsertColumn(0, "Area", width=self.FromDIP(110))
        control.InsertColumn(1, "Shortcut", width=self.FromDIP(190))
        control.InsertColumn(2, "Action", width=self.FromDIP(440))
        control.Bind(self.wx.EVT_SIZE, self._fill_last_column)
        previous_section = None
        for index, (section, key, action) in enumerate(SHORTCUT_ROWS):
            inserted = control.InsertItem(index, section if section != previous_section else "")
            previous_section = section
            control.SetItem(inserted, 1, key)
            control.SetItem(inserted, 2, action)
            if index % 2:
                control.SetItemBackgroundColour(inserted, self.wx.SystemSettings.GetColour(self.wx.SYS_COLOUR_BTNFACE))
        sizer.Add(control, 1, self.wx.EXPAND | self.wx.LEFT | self.wx.RIGHT, self.FromDIP(10))
        sizer.Add(
            dialog.CreateButtonSizer(self.wx.OK),
            0,
            self.wx.ALIGN_RIGHT | self.wx.ALL,
            self.FromDIP(10),
        )
        dialog.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()

    def _show_about(self: ViewerFrameProtocol, _event: object) -> None:
        self.wx.MessageBox(
            about_text(str(getattr(self.wx, "__version__", self.wx.version()))),
            "About deopjufier",
            self.wx.OK | self.wx.ICON_INFORMATION,
            self,
        )

    def _show_text_dialog(self: ViewerFrameProtocol, title: str, text: str) -> None:
        dialog = self.wx.Dialog(self, title=title, size=(760, 520))
        sizer = self.wx.BoxSizer(self.wx.VERTICAL)
        control = self.wx.TextCtrl(
            dialog, value=text, style=self.wx.TE_MULTILINE | self.wx.TE_READONLY | self.wx.HSCROLL
        )
        sizer.Add(control, 1, self.wx.EXPAND | self.wx.ALL, 8)
        sizer.Add(dialog.CreateButtonSizer(self.wx.OK), 0, self.wx.ALIGN_RIGHT | self.wx.ALL, 8)
        dialog.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()

    def _on_char_hook(self: ViewerFrameProtocol, event: Any) -> None:
        key = event.GetKeyCode()
        if self._handle_command_key(event, key) or self._handle_tree_key(event, key):
            return
        if key == self.wx.WXK_F6:
            self._switch_focus()
            return
        event.Skip()

    def _handle_command_key(self: ViewerFrameProtocol, event: Any, key: int) -> bool:
        if key == self.wx.WXK_F1:
            self._show_shortcuts(event)
        elif event.ControlDown() and event.ShiftDown() and key in {ord("S"), ord("s")}:
            self._on_export_all(event)
        elif event.ControlDown() and key in {ord("S"), ord("s")}:
            self._on_export_popup(event)
        elif event.ControlDown() and key in {self.wx.WXK_PAGEUP, self.wx.WXK_PAGEDOWN}:
            self._cycle_sheet(-1 if key == self.wx.WXK_PAGEUP else 1)
        elif event.ControlDown() and key == self.wx.WXK_TAB:
            self._cycle_document(-1 if event.ShiftDown() else 1)
        elif event.AltDown() and key in {self.wx.WXK_RETURN, self.wx.WXK_NUMPAD_ENTER}:
            self._show_properties(event)
        else:
            return False
        return True

    def _handle_tree_key(self: ViewerFrameProtocol, event: Any, key: int) -> bool:
        if self.tree.HasFocus() and event.ShiftDown() and key == self.wx.WXK_F10:
            self._show_tree_context(self.tree.GetSelection())
            return True
        if self.tree.HasFocus() and key in {self.wx.WXK_RETURN, self.wx.WXK_NUMPAD_ENTER, self.wx.WXK_SPACE}:
            item = self.tree.GetSelection()
            data = self.tree.GetItemData(item)
            if self._is_target(data):
                self._activate_target(data, self.tree.GetItemText(item))
            elif self.tree.ItemHasChildren(item):
                self.tree.Expand(item)
            return True
        return False

    def _switch_focus(self: ViewerFrameProtocol) -> None:
        if not self.tree.HasFocus():
            self.tree.SetFocus()
            return
        state = self._current_state()
        focus: Any = state.grid if state is not None and state.grid is not None else self._current_outer_page()
        (focus if focus is not None else self.notebook).SetFocus()

    def _cycle_sheet(self: ViewerFrameProtocol, delta: int) -> None:
        workbook = self.workbooks_by_page.get(self._current_outer_page())
        if workbook is None or not workbook.book.GetPageCount():
            return
        selection = workbook.book.GetSelection()
        index = (max(0, selection) + delta) % workbook.book.GetPageCount()
        target = workbook.targets_by_page.get(workbook.book.GetPage(index))
        if target is not None:
            self._activate_target(target, self.target_leaves[target].label)

    def _cycle_document(self: ViewerFrameProtocol, delta: int) -> None:
        count = self.notebook.GetPageCount()
        if not count:
            return
        index = (max(0, self.notebook.GetSelection()) + delta) % count
        page = self.notebook.GetPage(index)
        self._select_outer_page(page)
        self._document_selected()

    def _record_diagnostic(self: ViewerFrameProtocol, source: str, message: str) -> None:
        row = f"{source}: {message}"
        if row not in self.diagnostics:
            self.diagnostics.append(row)

    def _call_after(self: ViewerFrameProtocol, callback: Any, *args: object) -> None:
        """Post a worker result only while the wx application still exists."""
        if self.closed or self.wx.GetApp() is None:
            return
        try:
            self.wx.CallAfter(callback, *args)
        except AssertionError:
            # wxGTK can destroy wx.App between the check and CallAfter.
            return

    def _collect_payload_diagnostics(self: ViewerFrameProtocol, source: str, payload: dict[str, Any]) -> None:
        warnings = payload.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if warning:
                    self._record_diagnostic(source, str(warning))
        status = payload.get("status")
        if status not in {None, "ok"}:
            self._record_diagnostic(source, f"status={status}")

    def _update_tab_status(self: ViewerFrameProtocol, state: TabState) -> None:
        item = state.payload.get("item")
        name = str(item.get("name") or state.target[1]) if isinstance(item, dict) else state.target[1]
        document = state.payload.get("document")
        detected = str(document.get("detected_type", "")).upper() if isinstance(document, dict) else ""
        detail = status_detail(
            state.payload,
            table_shape=(len(state.table.rows), state.table.column_count) if state.table is not None else None,
            image_shape=state.image_shape,
        )
        self._set_status(f"{state.target[0].name} · {detected} · {name}", detail)

    def _set_status(self: ViewerFrameProtocol, message: str, detail: str = "") -> None:
        self.status.SetStatusText(message, 0)
        self.status.SetStatusText(detail, 1)

    def _update_export_enabled(self: ViewerFrameProtocol) -> None:
        self.export_button.Enable(self._export_target() is not None)
        project = self._active_project_path()
        can_export_all = project is not None and project not in self.pending_project_exports
        self.export_all_button.Enable(can_export_all)
        self.export_all_menu_item.Enable(can_export_all)

    def _export_target(self: ViewerFrameProtocol) -> tuple[Path, str] | None:
        if self.context_target is not None:
            return self.context_target
        state = self._current_state()
        if state is not None:
            return state.target
        return self.active_target if self.active_target in self.catalog_rows else None

    def _export_state(self: ViewerFrameProtocol) -> TabState | None:
        target = self._export_target()
        return self.tabs.get(target) if target is not None else None

    def _current_outer_page(self: ViewerFrameProtocol) -> object | None:
        selection = self.notebook.GetSelection()
        if selection < 0 or selection >= self.notebook.GetPageCount():
            return None
        return self.notebook.GetPage(selection)

    def _current_state(self: ViewerFrameProtocol) -> TabState | None:
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

    def _state_for_page(self: ViewerFrameProtocol, page: object) -> TabState | None:
        return next((state for state in self.tabs.values() if state.page is page), None)

    def _page_index(self: ViewerFrameProtocol, page: object) -> int | None:
        return next(
            (index for index in range(self.notebook.GetPageCount()) if self.notebook.GetPage(index) is page),
            None,
        )

    def _select_outer_page(self: ViewerFrameProtocol, page: object) -> None:
        index = self._page_index(page)
        if index is not None:
            self.notebook.ChangeSelection(index)
            self._sync_document_buttons(page)

    def _is_target(self: ViewerFrameProtocol, value: object) -> TypeGuard[tuple[Path, str]]:
        return (
            isinstance(value, tuple)
            and len(value) == _TARGET_COMPONENT_COUNT
            and isinstance(value[0], Path)
            and isinstance(value[1], str)
        )

    def _on_close(self: ViewerFrameProtocol, event: Any) -> None:
        self.closed = True
        self.backend.close()
        event.Skip()
