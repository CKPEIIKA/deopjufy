"""Object extraction facade."""

from deopjufier.extract.objects_extractors import *
from deopjufier.extract.objects_list_raw import *

__all__ = [name for name in globals() if not name.startswith("__")]
