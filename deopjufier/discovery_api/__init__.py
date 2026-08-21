"""Heuristic object discovery helpers for OPJ and OPJU binary inputs."""

from deopjufier import discovery

__all__ = [name for name in discovery.__all__]

for _name in __all__:
    globals()[_name] = getattr(discovery, _name)

del discovery
