"""Shared OPJU constants."""

from __future__ import annotations

MAGIC_OPJU = b"CPYUA"
OPJU_HINTS_MAX_BLOCKS = 4
OPJU_HINTS_MAX_CHARS = 1200
OPJU_HINTS_MAX_DESCRIPTION_BYTES = 160

OPJU_REGION_KIND_CONTAINER = "opju_container"
OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT = "origin_storage_report"
OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD = "origin_storage_unknown_payload"
OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW = "origin_storage_preview"
OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT = "origin_storage_attachment"
OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET = "origin_storage_worksheet"
OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE = "origin_storage_note"
OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION = "origin_storage_function"
OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH = "origin_storage_graph"
OPJU_REGION_KIND_TAGGED_BINARY = "opju_tagged_binary"
OPJU_REGION_KIND_COLUMN_DESCRIPTOR = "opju_column_descriptor"
OPJU_REGION_KIND_FOLDER_DIRECTORY = "opju_folder_directory"
OPJU_REGION_KIND_PAGE_DIRECTORY = "opju_page_directory"
