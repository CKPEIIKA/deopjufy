"""Block carving helpers for embedded binary resources."""

from deopjufier import blocks

__all__ = [name for name in blocks.__all__]

for _name in __all__:
    globals()[_name] = getattr(blocks, _name)

del blocks
