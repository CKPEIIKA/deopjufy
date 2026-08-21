"""Extractors for origin object-style content and inventories."""

from deopjufier.extract import objects as _objects

__all__ = [name for name in _objects.__all__]

for _name in __all__:
    globals()[_name] = getattr(_objects, _name)

del _name
del _objects
