"""Structured semantic records recovered by the sequential OPJ walker."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..records import is_opj_signature
from ..stream import OpjStreamError
from ..walker import OpjWalkElement, walk_opj_file


@dataclass(frozen=True)
class OpjProjectNode:
    """One folder or owned object from the binary OPJ project tree."""

    kind: str
    name: str
    path: str
    parent_path: str
    start_offset: int
    end_offset: int
    object_id: int | None = None
    file_type: int | None = None
    active: bool | None = None
    creation_time: int | None = None
    modification_time: int | None = None


@dataclass(frozen=True)
class OpjAttachmentRecord:
    """One attachment payload with its exact source byte range."""

    name: str
    group: int
    index: int
    data_offset: int
    data_size: int
    attachment_type: int | None = None
    attachment_number: int | None = None


@dataclass(frozen=True)
class OpjNoteMetadata:
    """Window metadata and text range for one parser-backed OPJ note."""

    name: str
    start_offset: int
    end_offset: int
    text_offset: int
    text_size: int
    label: str | None = None
    frame_rect: tuple[int, int, int, int] | None = None
    state: str | None = None
    hidden: bool | None = None
    title_mode: str | None = None
    creation_time: int | None = None
    modification_time: int | None = None
    results_log: bool = False


@dataclass(frozen=True)
class OpjCurveRecord:
    """A worksheet column header or graph curve record from one window layer."""

    window_name: str
    layer_index: int
    name: str
    start_offset: int
    end_offset: int
    designation: str | None
    value_type: str
    value_type_specification: int | None
    significant_digits: int | None
    decimal_places: int | None
    width: int | None
    comment: str | None
    data_name: str | None
    x_data_name: str | None
    z_data_name: str | None
    plot_type: int | None
    hidden: bool | None


@dataclass(frozen=True)
class OpjAnnotationRecord:
    """A named layer annotation with exact payload ranges and decoded text."""

    window_name: str
    layer_index: int
    name: str
    start_offset: int
    end_offset: int
    annotation_kind: int | None
    data_1_offset: int | None
    data_1_size: int | None
    data_1_text: str | None
    data_2_offset: int | None
    data_2_size: int | None
    data_2_text: str | None


@dataclass(frozen=True)
class OpjLayerRecord:
    """One parsed OPJ window layer."""

    window_name: str
    index: int
    name: str
    start_offset: int
    end_offset: int
    x_range: tuple[float, float, float] | None
    y_range: tuple[float, float, float] | None
    x_scale: int | None
    y_scale: int | None
    client_rect: tuple[int, int, int, int] | None
    matrix_rows: int | None
    matrix_columns: int | None
    matrix_width: int | None
    matrix_view: str | None
    annotation_count: int
    curve_count: int


@dataclass(frozen=True)
class OpjWindowMetadata:
    """Window-level metadata plus its parsed nested records."""

    name: str
    object_id: int | None
    start_offset: int
    end_offset: int
    label: str | None
    frame_rect: tuple[int, int, int, int] | None
    state: str | None
    hidden: bool | None
    title_mode: str | None
    creation_time: int | None
    modification_time: int | None
    width: int | None
    height: int | None
    template_name: str | None
    connect_missing_data: bool | None
    active_sheet: int | None
    matrix_header: str | None
    layers: tuple[OpjLayerRecord, ...]
    curves: tuple[OpjCurveRecord, ...]
    annotations: tuple[OpjAnnotationRecord, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable semantic metadata mapping."""
        return asdict(self)


def _walk_semantic_elements(data: bytes) -> list[OpjWalkElement]:
    if not is_opj_signature(data):
        return []
    try:
        return walk_opj_file(data, tolerant=False)
    except OpjStreamError:
        try:
            return walk_opj_file(data, tolerant=True)
        except OpjStreamError:
            return []


def _metadata_int(element: OpjWalkElement, key: str) -> int | None:
    value = element.metadata.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _metadata_str(element: OpjWalkElement, key: str) -> str | None:
    value = element.metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_float(element: OpjWalkElement, key: str) -> float | None:
    value = element.metadata.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _metadata_bool(element: OpjWalkElement, key: str) -> bool | None:
    value = element.metadata.get(key)
    return value if isinstance(value, bool) else None


def _metadata_rect(element: OpjWalkElement, key: str) -> tuple[int, int, int, int] | None:
    value = element.metadata.get(key)
    if not isinstance(value, tuple) or len(value) != 4 or not all(isinstance(item, int) for item in value):
        return None
    return value[0], value[1], value[2], value[3]


def _metadata_range(
    element: OpjWalkElement,
    keys: tuple[str, str, str],
) -> tuple[float, float, float] | None:
    first = _metadata_float(element, keys[0])
    second = _metadata_float(element, keys[1])
    third = _metadata_float(element, keys[2])
    if first is None or second is None or third is None:
        return None
    return first, second, third


def _curve_value_format(
    format_code: int | None,
    digits_code: int | None,
) -> tuple[str, int | None, int | None, int | None]:
    if format_code is None:
        return "unknown", None, None, None
    numeric_codes = {0x00, 0x10, 0x20, 0x30}
    text_numeric_codes = {0x09, 0x19, 0x29, 0x39}
    if format_code in numeric_codes | text_numeric_codes:
        value_type = "text_numeric" if format_code in text_numeric_codes else "numeric"
        specification = format_code // 0x10
        if digits_code is not None and digits_code >= 0x80:
            return value_type, specification, digits_code - 0x80, None
        if digits_code is not None and digits_code > 0:
            return value_type, specification, None, digits_code - 0x03
        return value_type, specification, None, None
    value_types = {
        0x02: "time",
        0x03: "date",
        0x33: "date",
        0x31: "text",
        0x04: "month",
        0x34: "month",
        0x05: "day",
        0x35: "day",
    }
    return value_types.get(format_code, "text"), digits_code, None, None


def _curve_designation(code: int | None) -> str | None:
    if code is None:
        return None
    return {3: "X", 0: "Y", 5: "Z", 6: "XErr", 2: "YErr", 4: "Label"}.get(code)


def _dataset_name_by_id(dataset_names: list[str | None], raw_id: int | None) -> str | None:
    if raw_id is None or raw_id <= 0:
        return None
    index = raw_id - 1
    return dataset_names[index] if index < len(dataset_names) else None


def _parse_curve_record(element: OpjWalkElement, dataset_names: list[str | None]) -> OpjCurveRecord | None:
    window_name = _metadata_str(element, "window_name")
    layer_index = _metadata_int(element, "layer_index")
    if window_name is None or layer_index is None:
        return None
    format_code = _metadata_int(element, "format_code")
    digits_code = _metadata_int(element, "digits_code")
    value_type, specification, significant_digits, decimal_places = _curve_value_format(format_code, digits_code)
    width_raw = _metadata_int(element, "width_raw")
    comment = _metadata_str(element, "comment")
    return OpjCurveRecord(
        window_name=window_name,
        layer_index=layer_index,
        name=element.name or "curve",
        start_offset=element.start_offset,
        end_offset=element.end_offset,
        designation=_curve_designation(_metadata_int(element, "designation_code")),
        value_type=value_type,
        value_type_specification=specification,
        significant_digits=significant_digits,
        decimal_places=decimal_places,
        width=max(1, width_raw // 10) if width_raw else 8 if width_raw == 0 else None,
        comment=comment or None,
        data_name=_dataset_name_by_id(dataset_names, _metadata_int(element, "data_id")),
        x_data_name=_dataset_name_by_id(dataset_names, _metadata_int(element, "x_data_id")),
        z_data_name=_dataset_name_by_id(dataset_names, _metadata_int(element, "z_data_id")),
        plot_type=_metadata_int(element, "plot_type"),
        hidden=_metadata_bool(element, "hidden"),
    )


def parse_opj_project_nodes(
    data: bytes,
    *,
    elements: list[OpjWalkElement] | None = None,
) -> list[OpjProjectNode]:
    """Parse exact folders and object ownership from the binary project tree."""
    nodes: list[OpjProjectNode] = []
    semantic_elements = _walk_semantic_elements(data) if elements is None else elements
    for element in semantic_elements:
        if element.kind == "project_folder":
            path = _metadata_str(element, "path") or element.name or "folder"
            parent_path = _metadata_str(element, "parent_path") or ""
            active = element.metadata.get("active")
            nodes.append(
                OpjProjectNode(
                    kind="folder",
                    name=element.name or path.rsplit("/", 1)[-1],
                    path=path,
                    parent_path=parent_path,
                    start_offset=element.start_offset,
                    end_offset=element.end_offset,
                    active=active if isinstance(active, bool) else None,
                    creation_time=_metadata_int(element, "creation_time"),
                    modification_time=_metadata_int(element, "modification_time"),
                )
            )
        elif element.kind == "project_leaf":
            name = element.name or "object"
            parent_path = _metadata_str(element, "parent_path") or ""
            nodes.append(
                OpjProjectNode(
                    kind=_metadata_str(element, "object_type") or "window",
                    name=name,
                    path=f"{parent_path}/{name}" if parent_path else name,
                    parent_path=parent_path,
                    start_offset=element.start_offset,
                    end_offset=element.end_offset,
                    object_id=_metadata_int(element, "object_id"),
                    file_type=_metadata_int(element, "file_type"),
                )
            )
    return nodes


def parse_opj_attachments(
    data: bytes,
    *,
    elements: list[OpjWalkElement] | None = None,
) -> list[OpjAttachmentRecord]:
    """Return attachment payloads from both native OPJ attachment groups."""
    records: list[OpjAttachmentRecord] = []
    semantic_elements = _walk_semantic_elements(data) if elements is None else elements
    for element in semantic_elements:
        if element.kind != "attachment":
            continue
        group = _metadata_int(element, "group")
        index = _metadata_int(element, "index")
        data_offset = _metadata_int(element, "data_offset")
        data_size = _metadata_int(element, "data_size")
        if group is None or index is None or data_offset is None or data_size is None:
            continue
        records.append(
            OpjAttachmentRecord(
                name=element.name or f"attachment_{index + 1}",
                group=group,
                index=index,
                data_offset=data_offset,
                data_size=data_size,
                attachment_type=_metadata_int(element, "attachment_type"),
                attachment_number=_metadata_int(element, "attachment_number"),
            )
        )
    return records


def parse_opj_note_metadata(data: bytes) -> list[OpjNoteMetadata]:
    """Return exact note metadata, including Results Log records."""
    notes: list[OpjNoteMetadata] = []
    for element in _walk_semantic_elements(data):
        if element.kind != "note":
            continue
        contents_offset = _metadata_int(element, "note_contents_start")
        contents_size = _metadata_int(element, "contents_size")
        text_offset = _metadata_int(element, "text_offset")
        if contents_offset is None or contents_size is None:
            continue
        if text_offset is None:
            text_offset = contents_offset
        text_size = max(0, contents_size - (text_offset - contents_offset))
        hidden = element.metadata.get("hidden")
        results_log = element.metadata.get("results_log")
        notes.append(
            OpjNoteMetadata(
                name=element.name or "note",
                start_offset=element.start_offset,
                end_offset=element.end_offset,
                text_offset=text_offset,
                text_size=text_size,
                label=_metadata_str(element, "embedded_label") or _metadata_str(element, "label"),
                frame_rect=_metadata_rect(element, "frame_rect"),
                state=_metadata_str(element, "state"),
                hidden=hidden if isinstance(hidden, bool) else None,
                title_mode=_metadata_str(element, "title_mode"),
                creation_time=_metadata_int(element, "creation_time"),
                modification_time=_metadata_int(element, "modification_time"),
                results_log=results_log if isinstance(results_log, bool) else False,
            )
        )
    return notes


def parse_opj_window_metadata(
    data: bytes,
    *,
    elements: list[OpjWalkElement] | None = None,
) -> list[OpjWindowMetadata]:
    """Parse windows, layers, annotations, and curve/column header records."""
    semantic_elements = _walk_semantic_elements(data) if elements is None else elements
    dataset_names = [element.name for element in semantic_elements if element.kind == "dataset"]
    curves: list[OpjCurveRecord] = []
    for element in semantic_elements:
        if element.kind != "curve":
            continue
        record = _parse_curve_record(element, dataset_names)
        if record is not None:
            curves.append(record)
    annotations: list[OpjAnnotationRecord] = []
    layers: list[OpjLayerRecord] = []

    for element in semantic_elements:
        window_name = _metadata_str(element, "window_name")
        layer_index = _metadata_int(element, "layer_index")
        if element.kind == "annotation" and window_name is not None and layer_index is not None:
            annotations.append(
                OpjAnnotationRecord(
                    window_name=window_name,
                    layer_index=layer_index,
                    name=element.name or "annotation",
                    start_offset=element.start_offset,
                    end_offset=element.end_offset,
                    annotation_kind=_metadata_int(element, "annotation_kind"),
                    data_1_offset=_metadata_int(element, "data_1_offset"),
                    data_1_size=_metadata_int(element, "data_1_size"),
                    data_1_text=_metadata_str(element, "data_1_text") or None,
                    data_2_offset=_metadata_int(element, "data_2_offset"),
                    data_2_size=_metadata_int(element, "data_2_size"),
                    data_2_text=_metadata_str(element, "data_2_text") or None,
                )
            )
        elif element.kind == "layer" and window_name is not None and layer_index is not None:
            view_code = _metadata_int(element, "matrix_view_code")
            layers.append(
                OpjLayerRecord(
                    window_name=window_name,
                    index=layer_index,
                    name=element.name or f"layer_{layer_index + 1}",
                    start_offset=element.start_offset,
                    end_offset=element.end_offset,
                    x_range=_metadata_range(element, ("x_min", "x_max", "x_step")),
                    y_range=_metadata_range(element, ("y_min", "y_max", "y_step")),
                    x_scale=_metadata_int(element, "x_scale"),
                    y_scale=_metadata_int(element, "y_scale"),
                    client_rect=_metadata_rect(element, "client_rect"),
                    matrix_rows=_metadata_int(element, "matrix_rows"),
                    matrix_columns=_metadata_int(element, "matrix_columns"),
                    matrix_width=_metadata_int(element, "matrix_width"),
                    matrix_view="data" if view_code in {0x32, 0x28} else "image" if view_code is not None else None,
                    annotation_count=_metadata_int(element, "annotations") or 0,
                    curve_count=_metadata_int(element, "curves") or 0,
                )
            )

    windows: list[OpjWindowMetadata] = []
    for element in semantic_elements:
        if element.kind != "window":
            continue
        name = element.name or "window"
        windows.append(
            OpjWindowMetadata(
                name=name,
                object_id=_metadata_int(element, "object_id"),
                start_offset=element.start_offset,
                end_offset=element.end_offset,
                label=_metadata_str(element, "window_label"),
                frame_rect=_metadata_rect(element, "frame_rect"),
                state=_metadata_str(element, "window_state"),
                hidden=_metadata_bool(element, "window_hidden"),
                title_mode=_metadata_str(element, "window_title_mode"),
                creation_time=_metadata_int(element, "creation_time"),
                modification_time=_metadata_int(element, "modification_time"),
                width=_metadata_int(element, "width"),
                height=_metadata_int(element, "height"),
                template_name=_metadata_str(element, "template_name"),
                connect_missing_data=_metadata_bool(element, "connect_missing_data"),
                active_sheet=_metadata_int(element, "active_sheet"),
                matrix_header=_metadata_str(element, "matrix_header"),
                layers=tuple(layer for layer in layers if layer.window_name == name),
                curves=tuple(curve for curve in curves if curve.window_name == name),
                annotations=tuple(annotation for annotation in annotations if annotation.window_name == name),
            )
        )
    return windows
