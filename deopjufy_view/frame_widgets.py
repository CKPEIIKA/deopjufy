"""wx widget factories; wxPython remains an optional, lazily imported dependency."""

from __future__ import annotations

import io
import time
from typing import Any

from deopjufy_view.model import TabularView
from deopjufy_view.presentation import plural, split_dropped_paths

from .frame_state import _MAX_PREVIEW_FIT_SCALE


# wx bases are loaded at runtime; Ruff counts each simple nested widget callback
# as part of these factories, so keep this narrow exception on the factory only.
def _grid_table_type(wx_grid: Any) -> type:  # noqa: C901
    class JsonGridTable(wx_grid.GridTableBase):
        data: TabularView

        def __init__(self, data: TabularView, stripe: Any | None = None) -> None:
            super().__init__()
            self.data = data
            self.stripe = stripe

        def GetAttr(self, row: int, col: int, kind: Any) -> Any:
            # Stripe alternate data rows; merge with provider attributes (metadata rows,
            # numeric alignment) rather than replacing them.
            attr = super().GetAttr(row, col, kind)
            data_row = row - len(self.data.metadata_rows)
            if self.stripe is None or data_row < 0 or data_row % 2 == 0:
                return attr
            if attr is None:
                self.stripe.IncRef()
                return self.stripe
            merged = attr.Clone()
            attr.DecRef()
            merged.SetBackgroundColour(self.stripe.GetBackgroundColour())
            return merged

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


def _image_preview_type(wx: Any) -> type:  # noqa: C901
    class ImagePreview(wx.Panel):
        def __init__(self, parent: Any, payload: bytes) -> None:
            super().__init__(parent, style=wx.BORDER_NONE)
            self.image = wx.Image(io.BytesIO(payload))
            self.zoom: float | None = None
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
            self.Bind(wx.EVT_PAINT, self._on_paint)
            self.Bind(wx.EVT_SIZE, self._on_size)
            self.Bind(wx.EVT_KEY_DOWN, self._on_key)

        def IsOk(self) -> bool:
            return bool(self.image.IsOk())

        def _fit_scale(self) -> float:
            width, height = self.GetClientSize()
            width = int(width)
            height = int(height)
            image_width = int(self.image.GetWidth())
            image_height = int(self.image.GetHeight())
            if width <= 0 or height <= 0 or image_width <= 0 or image_height <= 0:
                return 1.0
            # Stored previews are small thumbnails; enlarge them up to 2x to fill the view.
            return min(
                _MAX_PREVIEW_FIT_SCALE,
                (width - 48) / image_width,
                (height - 48) / image_height,
            )

        def _on_paint(self, _event: object) -> None:
            dc = wx.AutoBufferedPaintDC(self)
            dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
            dc.Clear()
            scale = self.zoom if self.zoom is not None else self._fit_scale()
            width = max(1, round(self.image.GetWidth() * scale))
            height = max(1, round(self.image.GetHeight() * scale))
            bitmap = wx.Bitmap(self.image.Scale(width, height, wx.IMAGE_QUALITY_HIGH))
            client_width, client_height = self.GetClientSize()
            left, top = max(0, (client_width - width) // 2), max(0, (client_height - height) // 2)
            dc.SetPen(wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNSHADOW)))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(left - 1, top - 1, width + 2, height + 2)
            dc.DrawBitmap(bitmap, left, top, True)

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

            self.elapsed = wx.StaticText(self, label="")
            outer.Add(self.elapsed, 0, wx.ALIGN_CENTER)
            self.SetSizer(outer)

            self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
            self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
            self.timer.Start(500)

        def _on_timer(self, _event: object) -> None:
            # The spinner shows activity; the counter appears once a wait is noticeable.
            seconds = round(time.monotonic() - self.started)
            if seconds >= 1:
                self.elapsed.SetLabel(f"{seconds} s elapsed")
                self.Layout()

        def _on_destroy(self, event: Any) -> None:
            if event.GetEventObject() is self:
                self.timer.Stop()
            event.Skip()

    return LoadingView


def _project_drop_target_type(wx: Any) -> type:
    class _ProjectDropTarget(wx.FileDropTarget):
        def __init__(self, frame: Any) -> None:
            super().__init__()
            self.frame = frame

        def OnDropFiles(self, _x: int, _y: int, filenames: list[str]) -> bool:
            accepted, rejected = split_dropped_paths(list(filenames))
            if accepted:
                self.frame.open_paths(accepted)
            if rejected:
                skipped = plural(len(rejected), "dropped file")
                self.frame._set_status(f"Not opened: {skipped} (only .opj and .opju projects)")
            return bool(accepted)

    return _ProjectDropTarget
