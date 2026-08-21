"""OPJU parsing helpers."""

from __future__ import annotations

from .common import (
    MAGIC_OPJU,
    OPJU_HINTS_MAX_BLOCKS,
    OPJU_HINTS_MAX_CHARS,
    OPJU_HINTS_MAX_DESCRIPTION_BYTES,
    OPJU_REGION_KIND_COLUMN_DESCRIPTOR,
    OPJU_REGION_KIND_CONTAINER,
    OPJU_REGION_KIND_FOLDER_DIRECTORY,
    OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT,
    OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION,
    OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH,
    OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE,
    OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW,
    OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT,
    OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD,
    OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET,
    OPJU_REGION_KIND_PAGE_DIRECTORY,
    OPJU_REGION_KIND_TAGGED_BINARY,
)
from .decoded import (
    OpjuDecodedRegion,
    OpjuDecodedString,
    iter_decoded_region_strings,
    iter_opju_decoded_regions,
    iter_opju_decoded_strings,
)
from .decoded.payloads import (
    OpjuDecodedPayload,
    OpjuPayloadError,
    classify_decoded_payload,
    parse_mser_strings_pset,
    parse_storage_cell_refs,
    parse_style_holder_source_info,
)
from .directory import (
    OpjuFolderDirectoryRecord,
    OpjuPageDirectoryRecord,
    parse_opju_folder_directory,
    parse_opju_page_directory,
)
from .records import (
    OpjuHeaderRecord,
    OpjuRecords,
    OpjuRegionRecord,
    OpjuReportRecord,
    OpjuWorksheetRecord,
    parse_opju_records,
)
from .recovery import (
    descriptor_table_metadata,
    recover_matrix_rows_from_opju,
    recover_worksheet_metadata_from_opju,
    recover_worksheet_rows_from_opju,
)
from .recovery.byte_runs import (
    OpjuByteRunDecode,
    OpjuByteRunError,
    OpjuRecoveredXml,
    decode_origin_storage_byte_runs,
    recover_origin_storage_xml,
    recover_origin_storage_xml_records,
)
from .reports import (
    OpjuOriginStorageField,
    OpjuOriginStorageReport,
    parse_opju_origin_storage_reports,
    parse_origin_storage_leaf_fields,
)
from .tables import (
    OpjuColumnTable,
    parse_opju_column_tables,
)
from .tagged import (
    OpjuColumnDescriptor,
    OpjuColumnIdentity,
    OpjuColumnMetadata,
    OpjuDescriptorColumn,
    OpjuDescriptorTable,
    OpjuTaggedEnvelope,
    OpjuTaggedScalar,
    OpjuTaggedString,
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
    iter_opju_tagged_envelopes,
    iter_tagged_scalars,
    iter_tagged_strings,
    opju_column_post_payload_range,
    parse_opju_column_identity,
)
from .tagged.column_payloads import OpjuColumnPayload, decode_opju_column_payload
from .walker import OpjuWalkElement, walk_opju_file


def parse_opju_description(data: bytes) -> str | None:
    if not data.startswith(MAGIC_OPJU):
        return None
    scan_end = len(data) if len(data) < 256 else 512
    text = data[:scan_end]
    markers = (
        b"Requires OriginPro",
        b"Signed-rank",
        b"Origin",
        b"Project",
        b"analysis",
    )
    best_span = b""
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        start = max(0, idx - OPJU_HINTS_MAX_DESCRIPTION_BYTES // 4)
        end = min(len(text), idx + OPJU_HINTS_MAX_DESCRIPTION_BYTES)
        span = text[start:end]
        if len(span) > len(best_span):
            best_span = span
    if not best_span:
        return None
    decoded = best_span.decode("utf-8", errors="replace").replace("\x00", "").strip()
    if len(decoded) <= 1:
        return None
    if len(decoded) > OPJU_HINTS_MAX_DESCRIPTION_BYTES:
        decoded = decoded[: OPJU_HINTS_MAX_DESCRIPTION_BYTES - 3] + "..."
    return decoded


__all__ = [
    "MAGIC_OPJU",
    "OPJU_HINTS_MAX_BLOCKS",
    "OPJU_HINTS_MAX_CHARS",
    "OPJU_HINTS_MAX_DESCRIPTION_BYTES",
    "OPJU_REGION_KIND_COLUMN_DESCRIPTOR",
    "OPJU_REGION_KIND_CONTAINER",
    "OPJU_REGION_KIND_FOLDER_DIRECTORY",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_ATTACHMENT",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_FUNCTION",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_GRAPH",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_NOTE",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_PREVIEW",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_REPORT",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_UNKNOWN_PAYLOAD",
    "OPJU_REGION_KIND_ORIGIN_STORAGE_WORKSHEET",
    "OPJU_REGION_KIND_PAGE_DIRECTORY",
    "OPJU_REGION_KIND_TAGGED_BINARY",
    "OpjuByteRunDecode",
    "OpjuByteRunError",
    "OpjuColumnDescriptor",
    "OpjuColumnIdentity",
    "OpjuColumnMetadata",
    "OpjuColumnPayload",
    "OpjuColumnTable",
    "OpjuDecodedPayload",
    "OpjuDecodedRegion",
    "OpjuDecodedString",
    "OpjuDescriptorColumn",
    "OpjuDescriptorTable",
    "OpjuFolderDirectoryRecord",
    "OpjuHeaderRecord",
    "OpjuOriginStorageField",
    "OpjuOriginStorageReport",
    "OpjuPageDirectoryRecord",
    "OpjuPayloadError",
    "OpjuRecords",
    "OpjuRecoveredXml",
    "OpjuRegionRecord",
    "OpjuReportRecord",
    "OpjuTaggedEnvelope",
    "OpjuTaggedScalar",
    "OpjuTaggedString",
    "OpjuWalkElement",
    "OpjuWorksheetRecord",
    "classify_decoded_payload",
    "decode_opju_column_payload",
    "decode_origin_storage_byte_runs",
    "descriptor_table_metadata",
    "group_opju_column_descriptors",
    "iter_decoded_region_strings",
    "iter_opju_column_descriptors",
    "iter_opju_column_metadata",
    "iter_opju_decoded_regions",
    "iter_opju_decoded_strings",
    "iter_opju_tagged_envelopes",
    "iter_tagged_scalars",
    "iter_tagged_strings",
    "opju_column_post_payload_range",
    "parse_mser_strings_pset",
    "parse_opju_column_identity",
    "parse_opju_column_tables",
    "parse_opju_description",
    "parse_opju_folder_directory",
    "parse_opju_origin_storage_reports",
    "parse_opju_page_directory",
    "parse_opju_records",
    "parse_origin_storage_leaf_fields",
    "parse_storage_cell_refs",
    "parse_style_holder_source_info",
    "recover_matrix_rows_from_opju",
    "recover_origin_storage_xml",
    "recover_origin_storage_xml_records",
    "recover_worksheet_metadata_from_opju",
    "recover_worksheet_rows_from_opju",
    "walk_opju_file",
]
