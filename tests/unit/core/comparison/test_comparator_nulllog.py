"""Tests vérifiant que ObjectComparator et TableComparator utilisent self.log (NullLog pattern)."""

import inspect
from unittest.mock import MagicMock

import pytest

from core.comparison.comparator import ObjectComparator
from core.comparison.table_comparator import TableComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.logger import NullLog


@pytest.mark.unit
class TestObjectComparatorNullLog:
    """Vérifie le pattern NullLog dans ObjectComparator."""

    def test_default_log_is_nulllog(self):
        """Sans log explicite, self.log doit être NullLog."""
        comparator = ObjectComparator(DataTypeNormalizer())
        assert isinstance(comparator.log, NullLog)

    def test_injected_log_is_used(self):
        """Avec un log injecté, self.log doit être ce logger."""
        mock_log = MagicMock()
        comparator = ObjectComparator(DataTypeNormalizer(), log=mock_log)
        assert comparator.log is mock_log

    def test_no_module_level_logger(self):
        """comparator.py ne doit pas avoir de logger = logging.getLogger(...)."""
        import core.comparison.comparator as mod

        assert not hasattr(
            mod, "logger"
        ), "Module-level 'logger' trouvé — doit être supprimé (AC#1)"

    def test_no_import_logging(self):
        """comparator.py ne doit pas importer logging au niveau module."""
        import core.comparison.comparator as mod

        src = inspect.getsource(mod)
        lines = [l.strip() for l in src.splitlines()]
        assert "import logging" not in lines, "'import logging' trouvé — doit être supprimé (AC#1)"


@pytest.mark.unit
class TestTableComparatorNullLog:
    """Vérifie le pattern NullLog dans TableComparator."""

    def test_default_log_is_nulllog(self):
        """Sans log explicite, self.log doit être NullLog."""
        comparator = TableComparator(DataTypeNormalizer())
        assert isinstance(comparator.log, NullLog)

    def test_injected_log_is_used(self):
        """Avec un log injecté, self.log doit être ce logger."""
        mock_log = MagicMock()
        comparator = TableComparator(DataTypeNormalizer(), log=mock_log)
        assert comparator.log is mock_log

    def test_no_module_level_logger(self):
        """table_comparator.py ne doit pas avoir de logger = logging.getLogger(...)."""
        import core.comparison.table_comparator as mod

        assert not hasattr(
            mod, "logger"
        ), "Module-level 'logger' trouvé — doit être supprimé (AC#2)"

    def test_no_import_logging(self):
        """table_comparator.py ne doit pas importer logging au niveau module."""
        import core.comparison.table_comparator as mod

        src = inspect.getsource(mod)
        lines = [l.strip() for l in src.splitlines()]
        assert "import logging" not in lines, "'import logging' trouvé — doit être supprimé (AC#2)"


@pytest.mark.unit
class TestObjectComparatorPropagatesLogToTableComparator:
    """Vérifie que ObjectComparator propage self.log à TableComparator."""

    def test_table_comparator_receives_log(self):
        """Le TableComparator créé via lazy init doit recevoir le même log."""
        mock_log = MagicMock()
        comparator = ObjectComparator(DataTypeNormalizer(), log=mock_log)
        tc = comparator.table_comparator  # déclenche __getattr__
        assert tc.log is mock_log

    def test_table_comparator_default_nulllog_when_no_log(self):
        """Sans log injecté, le TableComparator doit avoir NullLog."""
        comparator = ObjectComparator(DataTypeNormalizer())
        tc = comparator.table_comparator
        assert isinstance(tc.log, NullLog)

    def test_other_registry_comparators_do_not_receive_log(self):
        """Les autres comparators du registry ne reçoivent pas log (pas de paramètre log)."""
        mock_log = MagicMock()
        comparator = ObjectComparator(DataTypeNormalizer(), log=mock_log)
        # index_comparator is in the registry but does not accept log
        ic = comparator.index_comparator
        assert not hasattr(
            ic, "log"
        ), "index_comparator should not have self.log — only table_comparator does (AC#3)"
