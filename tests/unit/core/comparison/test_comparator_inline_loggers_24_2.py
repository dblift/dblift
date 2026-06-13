"""Tests for DEAD-11: no inline import logging in comparator compare_*() methods (story 24-2).

Verifies that the 13 comparator classes no longer have inline
`import logging` + `logger = logging.getLogger(...)` inside their
compare methods. The module-level logger is sufficient.
"""

import inspect

import pytest

from core.comparison.database_link_comparator import DatabaseLinkComparator
from core.comparison.event_comparator import EventComparator
from core.comparison.extension_comparator import ExtensionComparator
from core.comparison.foreign_data_wrapper_comparator import ForeignDataWrapperComparator
from core.comparison.foreign_server_comparator import ForeignServerComparator
from core.comparison.function_comparator import FunctionComparator
from core.comparison.linked_server_comparator import LinkedServerComparator
from core.comparison.package_comparator import PackageComparator
from core.comparison.procedure_comparator import ProcedureComparator
from core.comparison.sequence_comparator import SequenceComparator
from core.comparison.synonym_comparator import SynonymComparator
from core.comparison.trigger_comparator import TriggerComparator
from core.comparison.user_defined_type_comparator import UserDefinedTypeComparator

pytestmark = [pytest.mark.unit]

_COMPARATORS = [
    (DatabaseLinkComparator, "compare_database_links"),
    (EventComparator, "compare_events"),
    (ExtensionComparator, "compare_extensions"),
    (ForeignDataWrapperComparator, "compare_foreign_data_wrappers"),
    (ForeignServerComparator, "compare_foreign_servers"),
    (FunctionComparator, "compare_functions"),
    (LinkedServerComparator, "compare_linked_servers"),
    (PackageComparator, "compare_packages"),
    (ProcedureComparator, "compare_procedures"),
    (SequenceComparator, "compare_sequences"),
    (SynonymComparator, "compare_synonyms"),
    (TriggerComparator, "compare_triggers"),
    (UserDefinedTypeComparator, "compare_user_defined_types"),
]


class TestNoInlineImportLoggingInCompareMethods:
    """AC#2 — 13 comparators must not have inline import logging."""

    @pytest.mark.parametrize(
        "cls, method_name",
        _COMPARATORS,
        ids=[cls.__name__ for cls, _ in _COMPARATORS],
    )
    def test_no_inline_import_logging(self, cls, method_name):
        """The compare method body must not contain 'import logging'."""
        method = getattr(cls, method_name)
        source = inspect.getsource(method)
        # Skip the def line and docstring — check method body for inline import
        lines = source.split("\n")
        body_lines = [line.strip() for line in lines if line.strip()]
        assert not any(
            line == "import logging" for line in body_lines
        ), f"{cls.__name__}.{method_name} still contains inline 'import logging'"

    @pytest.mark.parametrize(
        "cls, method_name",
        _COMPARATORS,
        ids=[cls.__name__ for cls, _ in _COMPARATORS],
    )
    def test_no_inline_getlogger(self, cls, method_name):
        """The compare method body must not contain 'logging.getLogger'."""
        method = getattr(cls, method_name)
        source = inspect.getsource(method)
        # Count occurrences in the method body (excluding the def line)
        lines = source.split("\n")[1:]  # skip def line
        body = "\n".join(lines)
        assert (
            "logging.getLogger" not in body
        ), f"{cls.__name__}.{method_name} still contains inline 'logging.getLogger'"
