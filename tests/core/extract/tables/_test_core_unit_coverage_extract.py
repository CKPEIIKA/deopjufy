"""Compatibility shim for legacy oversized test module path."""

# This file is intentionally small and keeps backward references stable.

# The coverage test modules are split for readability.

from tests.core.extract.objects.books._test_core_unit_coverage_extract_books import *  # noqa: F403
from tests.core.extract.objects.functions._test_core_unit_coverage_extract_functions import *  # noqa: F403
from tests.core.extract.objects.graphs._test_core_unit_coverage_extract_graphs import *  # noqa: F403
from tests.core.extract.objects.io._test_core_unit_coverage_extract_io import *  # noqa: F403
from tests.core.extract.objects.notes._test_core_unit_coverage_extract_notes import *  # noqa: F403
from tests.core.extract.tables._test_core_unit_coverage_extract_tables import *  # noqa: F403
from tests.core.extract.tables._test_core_unit_coverage_extract_tables_books import *  # noqa: F403
