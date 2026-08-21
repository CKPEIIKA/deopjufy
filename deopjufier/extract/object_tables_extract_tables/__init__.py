from deopjufier.extract import object_tables_extract_filters as _object_tables_extract_filters
from deopjufier.extract import object_tables_match as _object_tables_match
from deopjufier.extract.object_tables_extract_tables._core import book_rows_for_object
from deopjufier.extract.object_tables_extract_tables._public import (
    extract_books,
    extract_excel,
    extract_matrices,
)

__all__: list[str] = [
    "book_rows_for_object",
    "extract_books",
    "extract_excel",
    "extract_matrices",
]

for _name in _object_tables_extract_filters.__all__:
    if _name not in __all__:
        __all__.append(_name)
    globals()[_name] = getattr(_object_tables_extract_filters, _name)

for _name in _object_tables_match.__all__:
    if _name not in __all__:
        __all__.append(_name)
    if _name not in globals():
        globals()[_name] = getattr(_object_tables_match, _name)

del _object_tables_extract_filters
del _object_tables_match
