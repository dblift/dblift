"""Tests structurels pour logging comparator/table_comparator.

Updated by story 19-5: module-level logger replaced by self.log (NullLog pattern).
Original story 18-5 assertions are now inverted — logger must NOT exist module-level.
"""

import inspect

import pytest

import core.comparison.comparator as comparator_mod
import core.comparison.table_comparator as table_comparator_mod


@pytest.mark.unit
class TestComparatorLogging18_5:

    def test_comparator_no_module_level_logger(self):
        """Story 19-5: comparator.py must NOT have module-level logger (migrated to self.log)."""
        assert "logger" not in vars(
            comparator_mod
        ), "Module-level 'logger' found — must be removed (story 19-5 AC#1)"

    def test_comparator_uses_self_log(self):
        """Story 19-5: comparator.py must use self.log.* calls."""
        source = inspect.getsource(comparator_mod)
        count = source.count("self.log.")
        assert count >= 15, f"self.log.* must appear >= 15 times, found {count}"

    def test_table_comparator_no_module_level_logger(self):
        """Story 19-5: table_comparator.py must NOT have module-level logger."""
        assert "logger" not in vars(
            table_comparator_mod
        ), "Module-level 'logger' found — must be removed (story 19-5 AC#2)"

    def test_table_comparator_no_inline_import_logging(self):
        """No indented 'import logging' in table_comparator.py."""
        source = inspect.getsource(table_comparator_mod)
        lines = source.splitlines()
        inline_imports = [
            line
            for line in lines
            if line.startswith((" ", "\t")) and line.strip() == "import logging"
        ]
        assert (
            inline_imports == []
        ), f"Found {len(inline_imports)} inline 'import logging' in table_comparator.py"

    def test_table_comparator_no_inline_logger_assignment(self):
        """No indented 'logger = logging.getLogger' in table_comparator.py."""
        source = inspect.getsource(table_comparator_mod)
        lines = source.splitlines()
        inline_assignments = [
            line
            for line in lines
            if line.startswith((" ", "\t")) and "logger = logging.getLogger" in line
        ]
        assert (
            inline_assignments == []
        ), f"Found {len(inline_assignments)} inline 'logger = logging.getLogger' in table_comparator.py"

    def test_table_comparator_uses_self_log(self):
        """Story 19-5: table_comparator.py must use self.log.* calls (all 24 logger.* replaced)."""
        source = inspect.getsource(table_comparator_mod)
        count = source.count("self.log.")
        assert (
            count >= 20
        ), f"self.log.* must appear >= 20 times in table_comparator.py, found {count}"
