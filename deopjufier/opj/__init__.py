"""Parser-only OPJ record helpers."""

from __future__ import annotations

from .boundaries import parse_opj_boundaries
from .metadata import (
    parse_opj_matrix_metadata,
    parse_opj_worksheet_metadata,
)
from .records import (
    MAGIC_OPJ,
    MAGIC_OPJU,
    OPJ_HEADER_MARKER,
    OPJ_NOTE_SECTION_NAMES,
    OPJ_NOTES_MAX_BLOCKS,
    OPJ_NOTES_MAX_CHARS,
    OPJ_PARAMETERS_MAX_RECORDS,
    OPJ_PARAMETERS_SCAN_WINDOW,
    OpjColumnMetadata,
    OpjDataSection,
    OpjFunctionMetadata,
    OpjMatrixMetadata,
    OpjMatrixSheetMetadata,
    OpjNoteSection,
    OpjObjectBoundary,
    OpjParameter,
    OpjSignature,
    OpjWorksheetMetadata,
    is_opj_signature,
    iter_opj_data_sections,
    parse_opj_function_metadata,
    parse_opj_function_payload,
    parse_opj_note_sections,
    parse_opj_parameters,
    parse_opj_signature,
)
from .recovery import (
    recover_excel_sheets_from_opj_sections,
    recover_matrix_metadata_from_opj_sections,
    recover_opj_note_sections,
    recover_parser_function_records,
    recover_worksheet_metadata_from_opj_sections,
)
from .structures.semantics import (
    OpjAnnotationRecord,
    OpjAttachmentRecord,
    OpjCurveRecord,
    OpjLayerRecord,
    OpjNoteMetadata,
    OpjProjectNode,
    OpjWindowMetadata,
    parse_opj_attachments,
    parse_opj_note_metadata,
    parse_opj_project_nodes,
    parse_opj_window_metadata,
)
from .tree import (
    OpjTreeNode,
    OpjTreeOwnership,
    parse_opj_tree_nodes,
    parse_opj_tree_ownership_links,
    parse_opj_tree_references,
)
from .walker import OpjWalkElement, walk_opj_file

# Re-export stable parser-owned record builders.
OPJ_NOTES_MAX_CHARS = OPJ_NOTES_MAX_CHARS
OPJ_NOTES_MAX_BLOCKS = OPJ_NOTES_MAX_BLOCKS
OPJ_NOTE_SECTION_NAMES = OPJ_NOTE_SECTION_NAMES
OPJ_PARAMETERS_MAX_RECORDS = OPJ_PARAMETERS_MAX_RECORDS
OPJ_PARAMETERS_SCAN_WINDOW = OPJ_PARAMETERS_SCAN_WINDOW

__all__ = [
    "MAGIC_OPJ",
    "MAGIC_OPJU",
    "OPJ_HEADER_MARKER",
    "OPJ_NOTES_MAX_BLOCKS",
    "OPJ_NOTES_MAX_CHARS",
    "OPJ_NOTE_SECTION_NAMES",
    "OPJ_PARAMETERS_MAX_RECORDS",
    "OPJ_PARAMETERS_SCAN_WINDOW",
    "OpjAnnotationRecord",
    "OpjAttachmentRecord",
    "OpjColumnMetadata",
    "OpjCurveRecord",
    "OpjDataSection",
    "OpjFunctionMetadata",
    "OpjLayerRecord",
    "OpjMatrixMetadata",
    "OpjMatrixSheetMetadata",
    "OpjNoteMetadata",
    "OpjNoteSection",
    "OpjObjectBoundary",
    "OpjParameter",
    "OpjProjectNode",
    "OpjSignature",
    "OpjTreeNode",
    "OpjTreeOwnership",
    "OpjWalkElement",
    "OpjWindowMetadata",
    "OpjWorksheetMetadata",
    "is_opj_signature",
    "iter_opj_data_sections",
    "parse_opj_attachments",
    "parse_opj_boundaries",
    "parse_opj_function_metadata",
    "parse_opj_function_payload",
    "parse_opj_matrix_metadata",
    "parse_opj_note_metadata",
    "parse_opj_note_sections",
    "parse_opj_parameters",
    "parse_opj_project_nodes",
    "parse_opj_signature",
    "parse_opj_tree_nodes",
    "parse_opj_tree_ownership_links",
    "parse_opj_tree_references",
    "parse_opj_window_metadata",
    "parse_opj_worksheet_metadata",
    "recover_excel_sheets_from_opj_sections",
    "recover_matrix_metadata_from_opj_sections",
    "recover_opj_note_sections",
    "recover_parser_function_records",
    "recover_worksheet_metadata_from_opj_sections",
    "walk_opj_file",
]
