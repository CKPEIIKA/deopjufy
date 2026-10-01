"""Optional-viewer catalog handlers for the lazily loaded wx frame."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import Any

from deopjufy_view.backend import DeopjufyCommandError
from deopjufy_view.presentation import plural
from deopjufy_view.project_tree import ProjectBranch, ProjectLeaf, build_project_tree, catalog_leaves, preferred_leaf

from .frame_state import BranchTarget, ViewerFrameProtocol


class CatalogMixin:
    def _defer_until_documents_visible(self: ViewerFrameProtocol, callback: Any, *args: object) -> bool:
        if self.preview_host.GetSelection() == 1:
            return False
        self._remove_welcome()
        self.Layout()
        self.splitter.Layout()
        self.preview_host.Layout()
        self.wx.CallAfter(callback, *args)
        return True

    def _on_open(self: ViewerFrameProtocol, _event: object) -> None:
        style = self.wx.FD_OPEN | self.wx.FD_FILE_MUST_EXIST | self.wx.FD_MULTIPLE
        wildcard = "Origin projects (*.opj;*.opju)|*.opj;*.opju|All files|*"
        with self.wx.FileDialog(self, "Open Origin projects", wildcard=wildcard, style=style) as dialog:
            if dialog.ShowModal() == self.wx.ID_CANCEL:
                return
            self.open_paths([Path(path) for path in dialog.GetPaths()])

    def open_paths(self: ViewerFrameProtocol, paths: list[Path]) -> None:
        unique_paths = list(dict.fromkeys(path.resolve() for path in paths))
        new_paths = [path for path in unique_paths if path not in self.document_nodes]
        if not new_paths:
            self._set_status("All selected projects are already open")
            return
        self._set_status(f"Opening {plural(len(new_paths), 'project')}…")
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

    def _catalog_done(self: ViewerFrameProtocol, path: Path, future: Future[dict[str, Any]]) -> None:
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
        hidden = f" · {plural(hidden_count, 'evidence item')} hidden" if hidden_count else ""
        self._set_status(f"{path.name} · {str(detected).upper()} · {plural(item_count, 'item')}{hidden}")
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
        self: ViewerFrameProtocol,
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

    def _append_branch(self: ViewerFrameProtocol, path: Path, branch: ProjectBranch, parent: object) -> None:
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

    def _append_leaf(self: ViewerFrameProtocol, path: Path, leaf: ProjectLeaf, parent: object) -> None:
        target = path, leaf.item_id
        node = self.tree.AppendItem(parent, leaf.label, self.tree_icons[self._leaf_icon(leaf.kind)])
        self.tree.SetItemData(node, target)
        self.target_nodes[target] = node
        self.search_entries.append((leaf.search_text, node))

    def _leaf_icon(self: ViewerFrameProtocol, kind: str) -> str:
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

    def _rebuild_catalog_trees(self: ViewerFrameProtocol) -> None:
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

    def _expand_all(self: ViewerFrameProtocol, _event: object) -> None:
        self.tree.ExpandAll()

    def _collapse_all(self: ViewerFrameProtocol, _event: object) -> None:
        for document_node in self.document_nodes.values():
            self.tree.Collapse(document_node)

    def _toggle_unwrap_groups(self: ViewerFrameProtocol, event: Any) -> None:
        self.unwrap_single_child_groups = bool(event.IsChecked())
        self._rebuild_catalog_trees()

    def _toggle_recovery_evidence(self: ViewerFrameProtocol, event: Any) -> None:
        self.show_recovery_evidence = bool(event.IsChecked())
        self._rebuild_catalog_trees()

    def _on_select(self: ViewerFrameProtocol, event: Any) -> None:
        selection = event.GetItem()
        target = self.tree.GetItemData(selection)
        if not self._is_target(target):
            self._update_export_enabled()
            return
        self._activate_target(target, self.tree.GetItemText(selection))

    def _on_tree_activate(self: ViewerFrameProtocol, event: Any) -> None:
        item = event.GetItem()
        data = self.tree.GetItemData(item)
        if self._is_target(data):
            self._activate_target(data, self.tree.GetItemText(item))
        elif self.tree.ItemHasChildren(item):
            self.tree.Collapse(item) if self.tree.IsExpanded(item) else self.tree.Expand(item)

    def _on_tree_menu(self: ViewerFrameProtocol, event: Any) -> None:
        self._show_tree_context(event.GetItem())

    def _show_tree_context(self: ViewerFrameProtocol, item: object) -> None:
        if not item:
            return
        self.tree.SelectItem(item)
        data = self.tree.GetItemData(item)
        menu = self.wx.Menu()
        if self._is_target(data):
            self.context_target = data
            menu.Append(self.ids.open_item_id, "&Open\tEnter")
            menu.Append(self.ids.properties_id, "&Properties…\tAlt+Enter")
            menu.AppendSeparator()
            menu.AppendSubMenu(self._export_menu(data), "&Export")
        else:
            expand_item = menu.Append(self.wx.ID_ANY, "&Expand branch")
            collapse_item = menu.Append(self.wx.ID_ANY, "&Collapse branch")
            menu.Bind(self.wx.EVT_MENU, lambda _event: self.tree.Expand(item), expand_item)
            menu.Bind(self.wx.EVT_MENU, lambda _event: self.tree.Collapse(item), collapse_item)
            if isinstance(data, (Path, BranchTarget)):
                menu.AppendSeparator()
                export_item = menu.Append(self.ids.export_all_id, "Export &all project content…")
                export_item.Enable(self._active_project_path() is not None)
        try:
            self.tree.PopupMenu(menu)
        finally:
            self.context_target = None
            menu.Destroy()

    def _open_context_item(self: ViewerFrameProtocol, _event: object) -> None:
        target = self._export_target()
        if target is not None:
            leaf = self.target_leaves.get(target)
            self._activate_target(target, leaf.label if leaf is not None else target[1])

    def _add_document_page(self: ViewerFrameProtocol, page: Any, label: str, *, select: bool = False) -> None:
        self.notebook.AddPage(page, label)
        button = self.wx.ToggleButton(self.document_tab_bar, label=label, style=self.wx.BU_EXACTFIT)
        button.Bind(self.wx.EVT_TOGGLEBUTTON, lambda event, selected=page: self._on_document_button(event, selected))
        self.document_buttons[page] = button
        self.document_tab_sizer.Add(
            button,
            0,
            self.wx.ALIGN_CENTER_VERTICAL | self.wx.RIGHT,
            self.FromDIP(2),
        )
        self.document_tab_bar.FitInside()
        self.document_tab_bar.Layout()
        if select or self.notebook.GetPageCount() == 1:
            self._select_outer_page(page)

    def _on_document_button(self: ViewerFrameProtocol, event: Any, page: object) -> None:
        if not event.IsChecked():
            event.GetEventObject().SetValue(True)
            return
        self._select_outer_page(page)
        self._document_selected()

    def _sync_document_buttons(self: ViewerFrameProtocol, selected_page: object | None) -> None:
        for page, button in self.document_buttons.items():
            button.SetValue(page is selected_page)

    def _delete_document_page(self: ViewerFrameProtocol, page: object, index: int) -> None:
        button = self.document_buttons.pop(page, None)
        if button is not None:
            self.document_tab_sizer.Detach(button)
            button.Destroy()
            self.document_tab_bar.FitInside()
            self.document_tab_bar.Layout()
        self.notebook.DeletePage(index)
        self._sync_document_buttons(self._current_outer_page())
