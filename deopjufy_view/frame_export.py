"""Optional-viewer export handlers for the lazily loaded wx frame."""

from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from deopjufy_view.backend import DeopjufyCommandError
from deopjufy_view.model import default_artifact_suffix, payload_bytes, table_region_text
from deopjufy_view.presentation import export_summary, recovered_image

from .frame_state import BranchTarget, ViewerFrameProtocol


class ExportMixin:
    def _active_project_path(self: ViewerFrameProtocol) -> Path | None:
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

    def _choose_export_all_profile(self: ViewerFrameProtocol) -> tuple[str, bool] | None:
        choices = (
            "Readable files — CSV tables, notes, and images",
            "Excel tables — XLSX workbooks, notes, and images",
            "Complete recovery — machine evidence and exact byte map",
        )
        dialog = self.wx.SingleChoiceDialog(
            self,
            "Choose the extraction profile. Complete recovery is larger and slower.",
            "Export all project content",
            choices,
        )
        try:
            if dialog.ShowModal() == self.wx.ID_CANCEL:
                return None
            selection = dialog.GetSelection()
        finally:
            dialog.Destroy()
        if selection == 0:
            return "csv", False
        if selection == 1:
            return "xlsx", False
        return "csv", True

    def _on_export_all(self: ViewerFrameProtocol, _event: object) -> None:
        path = self._active_project_path()
        if path is None:
            self._set_status("Select an open project before exporting all content")
            return
        profile = self._choose_export_all_profile()
        if profile is None:
            return
        safe_stem = "".join(character if character.isalnum() or character in "-_" else "_" for character in path.stem)
        directory_name = f"{safe_stem or 'project'}_extracted"
        with self.wx.DirDialog(
            self,
            f"Choose where to create {directory_name}",
            style=self.wx.DD_DEFAULT_STYLE | self.wx.DD_DIR_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() == self.wx.ID_CANCEL:
                return
            target = Path(dialog.GetPath()) / directory_name
        if target.exists():
            self.wx.MessageBox(
                f"The output directory already exists:\n{target}\n\nChoose another location or move it first.",
                "Export all",
                self.wx.OK | self.wx.ICON_WARNING,
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
        self: ViewerFrameProtocol,
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
        status = str(manifest.get("status", "complete"))
        self._set_status(export_summary(manifest, target), status)

    def _on_export_popup(self: ViewerFrameProtocol, _event: object) -> None:
        target = self._export_target()
        if target is None:
            self._set_status("Select an item before exporting")
            return
        menu = self._export_menu(target)
        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _on_export_json(self: ViewerFrameProtocol, _event: object) -> None:
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

    def _on_export_artifact(self: ViewerFrameProtocol, _event: object) -> None:
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

    def _export_table(self: ViewerFrameProtocol, output_format: str) -> None:
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

    def _export_image(self: ViewerFrameProtocol, _event: object) -> None:
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

    def _export_selection(self: ViewerFrameProtocol, delimiter: str, suffix: str) -> None:
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

    def _export_done(self: ViewerFrameProtocol, target: Path, future: Future[dict[str, Any]]) -> None:
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
        self: ViewerFrameProtocol,
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
        style = self.wx.FD_SAVE | self.wx.FD_OVERWRITE_PROMPT
        with self.wx.FileDialog(
            self,
            title,
            defaultFile=default_name,
            wildcard=wildcard,
            style=style,
        ) as dialog:
            return None if dialog.ShowModal() == self.wx.ID_CANCEL else Path(dialog.GetPath())

    def _write_export(self: ViewerFrameProtocol, target: Path, data: bytes) -> None:
        try:
            target.write_bytes(data)
        except OSError as exc:
            self._record_diagnostic(target.name, str(exc))
            self._set_status(f"Export failed: {exc}")
            return
        self._set_status(f"Exported {target}")
