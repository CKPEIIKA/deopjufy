"""Project-tree and attachment tail records for the sequential OPJ walker."""

from __future__ import annotations

import struct

from ..stream import OpjStream, OpjStreamError
from ..walker import (
    OpjWalkElement,
    _decode_blob_name,
    _decode_julian_timestamp,
    _read_object_size_or_raise,
    _read_or_skip_object,
    _read_u32_le,
)


def _read_project_leaf(
    cursor: OpjStream,
    *,
    tolerate: bool,
    parent_path: str,
    windows_by_id: dict[int, str],
    notes_by_id: dict[int, str],
) -> OpjWalkElement | None:
    leaf_start = cursor.offset
    preamble_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if preamble_size is None:
        return None
    if _read_or_skip_object(cursor, size=preamble_size, tolerate=tolerate) is None:
        return None

    data_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if data_size is None:
        return None
    data_payload = _read_or_skip_object(cursor, size=data_size, tolerate=tolerate)
    if data_payload is None:
        return None
    post_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if post_size is None:
        return None
    if post_size not in {0, None}:
        if tolerate:
            return None
        raise OpjStreamError("wrong project leaf post-mark", offset=cursor.offset - 4)
    file_type = _read_u32_le(data_payload[:4])
    object_id = _read_u32_le(data_payload[4:8]) if len(data_payload) >= 8 else None
    object_type = "note" if file_type == 0x100000 else "window"
    object_names = notes_by_id if object_type == "note" else windows_by_id
    name = object_names.get(object_id, f"{object_type}_{object_id}") if object_id is not None else object_type
    return OpjWalkElement(
        kind="project_leaf",
        start_offset=leaf_start,
        end_offset=cursor.offset,
        name=name,
        metadata={
            "parent_path": parent_path,
            "object_type": object_type,
            "file_type": file_type,
            "object_id": object_id,
        },
    )


def _walk_project_folder(
    cursor: OpjStream,
    *,
    tolerate: bool,
    depth: int,
    parent_path: str,
    windows_by_id: dict[int, str],
    notes_by_id: dict[int, str],
) -> list[OpjWalkElement]:
    folder_start = cursor.offset
    header_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if header_size is None:
        return []
    folder_header = _read_or_skip_object(cursor, size=header_size, tolerate=tolerate)
    if folder_header is None:
        return []

    folder_end_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if folder_end_size is None:
        return []
    if folder_end_size != 0 and tolerate is False:
        raise OpjStreamError("wrong folder end marker", offset=cursor.offset - 4)
    if folder_end_size != 0 and tolerate:
        folder_end_size = 0

    folder_name_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if folder_name_size is None:
        return []
    folder_name_payload = _read_or_skip_object(cursor, size=folder_name_size, tolerate=tolerate)
    if folder_name_payload is None:
        return []

    folder_name = _decode_blob_name(folder_name_payload) or f"folder_{depth}"
    folder_path = f"{parent_path}/{folder_name}" if parent_path else folder_name

    folder_properties_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if folder_properties_size is None:
        return []
    for _ in range(folder_properties_size):
        property_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if property_size is None:
            return []
        if _read_or_skip_object(cursor, size=property_size, tolerate=tolerate) is None:
            return []

    file_count_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if file_count_size is None:
        return []
    file_count_payload = _read_or_skip_object(cursor, size=file_count_size, tolerate=tolerate)
    if file_count_payload is None:
        return []
    file_count = _read_u32_le(file_count_payload) or 0
    child_elements: list[OpjWalkElement] = []
    for _ in range(file_count):
        leaf = _read_project_leaf(
            cursor,
            tolerate=tolerate,
            parent_path=folder_path,
            windows_by_id=windows_by_id,
            notes_by_id=notes_by_id,
        )
        if leaf is None:
            break
        child_elements.append(leaf)

    folder_count_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if folder_count_size is None:
        return []
    folder_count_payload = _read_or_skip_object(cursor, size=folder_count_size, tolerate=tolerate)
    if folder_count_payload is None:
        return []
    folder_count = _read_u32_le(folder_count_payload) or 0
    for _ in range(folder_count):
        child_elements.extend(
            _walk_project_folder(
                cursor,
                tolerate=tolerate,
                depth=depth + 1,
                parent_path=folder_path,
                windows_by_id=windows_by_id,
                notes_by_id=notes_by_id,
            )
        )

    folder = OpjWalkElement(
        kind="project_folder",
        start_offset=folder_start,
        end_offset=cursor.offset,
        name=folder_name,
        metadata={
            "path": folder_path,
            "parent_path": parent_path,
            "depth": depth,
            "active": len(folder_header) > 0x02 and folder_header[0x02] == 1,
            "creation_time": _decode_julian_timestamp(folder_header, 0x10),
            "modification_time": _decode_julian_timestamp(folder_header, 0x18),
            "files": file_count,
            "folders": folder_count,
        },
    )
    return [folder, *child_elements]


def _walk_project_tree(
    cursor: OpjStream,
    *,
    tolerate: bool,
    windows_by_id: dict[int, str],
    notes_by_id: dict[int, str],
) -> list[OpjWalkElement]:
    project_tree_start = cursor.offset
    pre1_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if pre1_size is None:
        return []
    if _read_or_skip_object(cursor, size=pre1_size, tolerate=tolerate) is None:
        return []

    pre2_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if pre2_size is None:
        return []
    if _read_or_skip_object(cursor, size=pre2_size, tolerate=tolerate) is None:
        return []

    tree_elements = _walk_project_folder(
        cursor,
        tolerate=tolerate,
        depth=0,
        parent_path="",
        windows_by_id=windows_by_id,
        notes_by_id=notes_by_id,
    )

    post_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
    if post_size is None:
        if tolerate:
            return [
                OpjWalkElement(
                    kind="project_tree",
                    start_offset=project_tree_start,
                    end_offset=cursor.offset,
                    name="project_tree",
                    metadata={"file_tree": True},
                ),
                *tree_elements,
            ]
        raise

    if post_size != 0 and tolerate is False:
        raise OpjStreamError("wrong project tree end marker", offset=cursor.offset - 4)

    return [
        OpjWalkElement(
            kind="project_tree",
            start_offset=project_tree_start,
            end_offset=cursor.offset,
            name="project_tree",
            metadata={"file_tree": True},
        ),
        *tree_elements,
    ]


def _walk_attachments(cursor: OpjStream, *, tolerate: bool) -> list[OpjWalkElement]:
    start = cursor.offset
    if cursor.at_eof:
        return []

    try:
        first_u32 = cursor.read_u32_le()
    except OpjStreamError:
        return []

    # liborigin prefix for first attachment group is marker=4096 followed by count.
    attachment_elements: list[OpjWalkElement] = []
    first_group_count = 0
    if first_u32 == 8:
        cursor.seek(cursor.offset - 4)
        group_size = _read_object_size_or_raise(cursor, tolerate=tolerate, start_fallback=cursor.offset)
        if group_size is None:
            return []
        group_payload = _read_or_skip_object(cursor, size=group_size, tolerate=tolerate)
        if group_payload is None or len(group_payload) < 8:
            return []

        first = _read_u32_le(group_payload[:4])
        count = _read_u32_le(group_payload[4:8])
        if first != 0x1000 or count is None:
            if not tolerate:
                raise OpjStreamError("malformed attachment header")
            return [
                OpjWalkElement(
                    kind="attachment_list",
                    start_offset=start,
                    end_offset=cursor.offset,
                    name="attachment_list",
                    metadata={"attachments": 0},
                )
            ]

        first_group_count = count
        for attachment_index in range(count):
            attachment_start = cursor.offset
            header = _read_or_skip_object(
                cursor,
                size=7 * 4,
                tolerate=tolerate,
            )
            if header is None or len(header) < 12:
                return []
            marker = _read_u32_le(header[:4])
            attachment_number = _read_u32_le(header[4:8])
            att_size = _read_u32_le(header[8:12]) or 0
            data_offset = cursor.offset
            if (
                _read_or_skip_object(
                    cursor,
                    size=att_size,
                    tolerate=tolerate,
                    allow_zero_payload=True,
                )
                is None
            ):
                return []
            attachment_elements.append(
                OpjWalkElement(
                    kind="attachment",
                    start_offset=attachment_start,
                    end_offset=cursor.offset,
                    name=f"attachment_{attachment_index + 1}",
                    metadata={
                        "group": 1,
                        "index": attachment_index,
                        "marker": marker,
                        "attachment_number": attachment_number,
                        "data_offset": data_offset,
                        "data_size": att_size,
                    },
                )
            )

    # Second group is raw triples without newline-terminated object sizes.
    attachment_count = 0
    while cursor.offset + 12 <= len(cursor.data):
        attachment_start = cursor.offset
        att_header = cursor.read(12)
        if len(att_header) != 12:
            break
        block_size, attachment_type, payload_size = struct.unpack("<III", att_header)
        if block_size < 12:
            cursor.seek(attachment_start)
            break
        name_size = max(0, block_size - 12)
        if cursor.offset + name_size > len(cursor.data):
            break
        raw_name = cursor.read(name_size)
        attachment_name = _decode_blob_name(raw_name) or f"attachment_{attachment_count + 1}"
        if cursor.offset + payload_size > len(cursor.data):
            cursor.seek(attachment_start)
            break
        data_offset = cursor.offset
        cursor.seek(cursor.offset + payload_size)
        attachment_elements.append(
            OpjWalkElement(
                kind="attachment",
                start_offset=attachment_start,
                end_offset=cursor.offset,
                name=attachment_name,
                metadata={
                    "group": 2,
                    "index": attachment_count,
                    "attachment_type": attachment_type,
                    "header_size": block_size,
                    "name_size": name_size,
                    "data_offset": data_offset,
                    "data_size": payload_size,
                },
            )
        )
        attachment_count += 1

    return [
        OpjWalkElement(
            kind="attachment_list",
            start_offset=start,
            end_offset=cursor.offset,
            name="attachment_list",
            metadata={
                "attachments": first_group_count + attachment_count,
                "first_group_attachments": first_group_count,
                "second_group_attachments": attachment_count,
            },
        ),
        *attachment_elements,
    ]
