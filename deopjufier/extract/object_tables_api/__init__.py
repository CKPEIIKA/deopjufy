"""Tabular object extractors for worksheet-like Origin payloads."""

from deopjufier.extract import object_tables as _object_tables

__all__ = [name for name in _object_tables.__all__]

for _name in __all__:
    globals()[_name] = getattr(_object_tables, _name)

del _name
del _object_tables
