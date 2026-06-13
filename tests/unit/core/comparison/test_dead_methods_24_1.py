"""Tests for story 24-1: DEAD-01/02/03 — unused private methods removed from comparators."""

import pytest


@pytest.mark.unit
class TestDeadMethodsRemoved:
    """Structural tests: dead private methods must not exist in comparator classes."""

    def test_procedure_comparator_no_normalize_parameters(self):
        """DEAD-01: _normalize_parameters removed from ProcedureComparator."""
        from core.comparison.procedure_comparator import ProcedureComparator

        assert "_normalize_parameters" not in ProcedureComparator.__dict__

    def test_package_comparator_no_normalize_package_code(self):
        """DEAD-02: _normalize_package_code removed from PackageComparator."""
        from core.comparison.package_comparator import PackageComparator

        assert "_normalize_package_code" not in PackageComparator.__dict__

    def test_object_comparator_no_normalize_identifier(self):
        """DEAD-03: _normalize_identifier removed from ObjectComparator."""
        from core.comparison.comparator import ObjectComparator

        assert "_normalize_identifier" not in ObjectComparator.__dict__


@pytest.mark.unit
class TestInlineImportsRemoved:
    """Structural tests: inline import logging removed from production code."""

    def test_events_no_inline_import_logging(self):
        """DEAD-05: events.py uses module-level _logger, not inline import."""
        import inspect

        from api.events import EventEmitter

        source = inspect.getsource(EventEmitter._handle_listener_error)
        assert "import logging" not in source

    def test_events_no_inline_import_time(self):
        """Bonus: events.py _get_timestamp uses module-level import time."""
        import inspect

        from api.events import EventEmitter

        source = inspect.getsource(EventEmitter._get_timestamp)
        assert "import time" not in source
