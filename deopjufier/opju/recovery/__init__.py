"""Parser-owned OPJU recovery helpers.

This module is kept as a package so ``deopjufier.opju.recovery`` remains a
stable import target while allowing future OPJU recovery submodules to live under
an explicit package boundary.
"""

from __future__ import annotations

from .. import recovery_helpers as _recovery_helpers
from ..recovery_helpers_tokens import (
    _build_worksheet_name_candidate_lookup,
    _expand_adjacent_alpha1_sheet_targets_from_selection,
    _infer_parser_backed_worksheet_names,
)
from ..recovery_helpers_windows import (
    _iter_family_worksheet_tokens_from_payload,
    _match_family_table_to_worksheet_names,
)
from ..recovery_main import (
    descriptor_table_metadata,
    recover_matrix_rows_from_opju,
    recover_worksheet_metadata_from_opju,
    recover_worksheet_rows_from_opju,
)

__all__: list[str] = [
    "descriptor_table_metadata",
    "recover_matrix_rows_from_opju",
    "recover_worksheet_metadata_from_opju",
    "recover_worksheet_rows_from_opju",
]
for _name in _recovery_helpers.__all__:
    if _name in globals():
        continue
    globals()[_name] = getattr(_recovery_helpers, _name)
    __all__.append(_name)

__all__.sort()

del _name
del _build_worksheet_name_candidate_lookup
del _expand_adjacent_alpha1_sheet_targets_from_selection
del _infer_parser_backed_worksheet_names
del _iter_family_worksheet_tokens_from_payload
del _match_family_table_to_worksheet_names
del _recovery_helpers
