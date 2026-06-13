"""Tests structurels — vérification absence loggers module-level morts (Story 16-6).

Vérifie que les loggers module-level morts ont été supprimés dans index_extractor,
view_comparator, et comparator (migré vers self.log en story 19-5).

Note (Story 16-9) : le test AC#3 (test_module_comparator_no_module_level_logger) a été
retiré car le fichier core/comparison/module_comparator.py a été supprimé en entier.
Les tests structurels de cette suppression sont dans test_comparator_module_cleanup.py.
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestModuleLevelLoggers:
    """AC#1-2, AC#4 : vérification structurelle des loggers module-level.

    AC#3 (module_comparator) retiré en story 16-9 — voir test_comparator_module_cleanup.py.
    """

    def test_index_extractor_no_module_level_logger(self):
        """AC#1 : index_extractor n'a plus de logger module-level."""
        import core.introspection.extractors.index_extractor as mod

        assert "logger" not in vars(mod), "module-level logger should have been removed"

    def test_index_extractor_no_import_logging_module_level(self):
        """AC#1 : import logging n'est plus au module-level."""
        import core.introspection.extractors.index_extractor as mod

        assert "logging" not in vars(mod), "module-level logging import should have been removed"

    def test_view_comparator_has_module_level_logger(self):
        """view_comparator requires a module-level logger (used in compare_views).

        Story 16-6 originally planned removal, but the logger is used — keeping it.
        """
        import core.comparison.view_comparator as mod

        assert "logger" in vars(mod), "view_comparator needs module-level logger for compare_views"

    def test_comparator_no_module_level_logger(self):
        """Story 19-5: comparator.py migrated to self.log (NullLog pattern).

        Module-level logger has been removed.
        """
        import core.comparison.comparator as mod

        assert "logger" not in vars(
            mod
        ), "comparator module-level logger must be removed (story 19-5)"

    def test_index_extractor_missing_vendor_queries_returns_empty(self):
        """No module-level logger is used when vendor queries are unavailable."""
        from core.introspection.extractors.index_extractor import IndexExtractor

        extractor = IndexExtractor.__new__(IndexExtractor)
        extractor.log = MagicMock()
        extractor.metadata = MagicMock()  # non-None so ensure_metadata guard passes
        extractor.vendor_queries = None
        extractor.ensure_metadata = MagicMock()  # no-op
        extractor.track_error = MagicMock()

        result = extractor.get_indexes("myschema", "mytable")

        assert result == []
        extractor.log.warning.assert_not_called()

    def test_view_comparator_compare_views_returns_none_when_no_diff(self):
        """AC#6 : compare_views fonctionne correctement (nominal, pas de diff)."""
        from core.comparison.view_comparator import ViewComparator
        from core.sql_model.view import View

        comparator = ViewComparator()
        expected = View(name="v1", query="SELECT 1")
        actual = View(name="v1", query="SELECT 1")

        result = comparator.compare_views(expected, actual)

        assert result is None
