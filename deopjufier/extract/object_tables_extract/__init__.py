"""Object-table extraction entrypoints."""

from __future__ import annotations

from deopjufier.extract import object_tables_extract_main as _object_tables_extract_main
from deopjufier.extract.object_tables_extract_filters import _filter_meaningful_recovered_rows

__all__: list[str] = [name for name in _object_tables_extract_main.__all__]

for _name in _object_tables_extract_main.__all__:
    globals()[_name] = getattr(_object_tables_extract_main, _name)

if _filter_meaningful_recovered_rows.__name__ not in __all__:
    __all__.append(_filter_meaningful_recovered_rows.__name__)

del _name
del _object_tables_extract_main
