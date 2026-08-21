"""Object-table extraction API entrypoint.

The entrypoint stays compact and re-exports helpers split into two implementation
modules: filter helpers and extraction implementations.
"""

from __future__ import annotations

from deopjufier.extract import object_tables_extract_filters as _object_tables_extract_filters
from deopjufier.extract import object_tables_extract_tables as _object_tables_extract_tables

__all__: list[str] = []

for _name in _object_tables_extract_filters.__all__:
    __all__.append(_name)
    globals()[_name] = getattr(_object_tables_extract_filters, _name)

for _name in _object_tables_extract_tables.__all__:
    if _name not in __all__:
        __all__.append(_name)
    globals()[_name] = getattr(_object_tables_extract_tables, _name)

del _name
del _object_tables_extract_filters
del _object_tables_extract_tables
