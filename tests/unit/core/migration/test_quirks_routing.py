"""Verify dialect branches in engine + undo generators route through quirks."""

import pytest

from dblift.db.provider_registry import ProviderRegistry

pytestmark = [pytest.mark.unit]


class TestUndoDropIfExistsRoutedThroughQuirks:
    """Undo _generate_drop_statement IF EXISTS routes through quirks."""

    @pytest.mark.parametrize(
        "dialect, expect_if_exists",
        [
            ("postgresql", True),
            ("mysql", True),
            ("sqlite", True),
            ("sqlserver", True),
            ("oracle", False),
            ("db2", False),
        ],
    )
    def test_extractors_mixin_if_exists(self, dialect, expect_if_exists):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        emitter = UndoStatementEmitter(dialect=dialect)
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        if expect_if_exists:
            assert "IF EXISTS" in sql
        else:
            assert "IF EXISTS" not in sql

    @pytest.mark.parametrize(
        "dialect, expect_cascade",
        [
            ("postgresql", True),
            ("mysql", False),
            ("oracle", False),
            ("db2", False),
        ],
    )
    def test_extractors_mixin_cascade(self, dialect, expect_cascade):
        """CASCADE on TABLE drops is driven by drop_table_default_cascade quirks."""
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        emitter = UndoStatementEmitter(dialect=dialect)
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        if expect_cascade:
            assert "CASCADE" in sql
        else:
            assert "CASCADE" not in sql


class TestNoHardcodedDialectStringsInDropGeneration:
    """No hardcoded dialect string checks remain in undo drop generation."""

    def test_extractors_no_hardcoded_dialect_check(self):
        import inspect

        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            _UndoExtractorsMixin,
        )

        src = inspect.getsource(_UndoExtractorsMixin._generate_drop_statement)
        assert '"postgresql"' not in src
        assert '"mysql"' not in src
        # Cascade must route through quirks, not a dialect frozenset membership.
        assert "CASCADE_DROP_DIALECTS" not in src
        assert "drop_table_default_cascade" in src
