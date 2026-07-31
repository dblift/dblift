"""Story 26-9: Verify dialect branches in engine + undo generators route through quirks."""

import pytest

from db.provider_registry import ProviderRegistry

pytestmark = [pytest.mark.unit]


class TestSelectSupportsLimit:
    """AC#1: select_supports_limit quirks property drives post-commit verification."""

    @pytest.mark.parametrize(
        "dialect, expected",
        [
            ("postgresql", True),
            ("mysql", True),
            ("sqlite", True),
            ("oracle", False),
            # A live db2 12.01.0500 server, probed via
            # tests/integration/capabilities/test_engine_capabilities.py
            # ::test_row_limit_clauses_match_the_engine (CI run 30346957093,
            # cmodiano/dblift), accepted a bare trailing ``SELECT ... LIMIT 2``
            # -- contradicting the ``select_supports_limit = False`` this
            # dialect declared. Db2 still renders ``FETCH FIRST n ROWS ONLY``
            # as its preferred row_limit_style; it merely ALSO tolerates a
            # bare LIMIT, so the coarser "may I append LIMIT at all for an
            # optional probe" question is True here even though the declared
            # rendering style is not "limit".
            ("db2", True),
            ("sqlserver", False),
        ],
    )
    def test_select_supports_limit_per_dialect(self, dialect, expected):
        quirks = ProviderRegistry.get_quirks(dialect)
        assert quirks.select_supports_limit is expected


class TestUndoDropIfExistsRoutedThroughQuirks:
    """AC#2: Undo _generate_drop_statement IF EXISTS routes through quirks."""

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
        from core.migration.scripting.undo_script_generator._extractors import (
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
        from core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        emitter = UndoStatementEmitter(dialect=dialect)
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        if expect_cascade:
            assert "CASCADE" in sql
        else:
            assert "CASCADE" not in sql


class TestNoHardcodedDialectStringsInDropGeneration:
    """AC#3: No hardcoded dialect string checks remain in undo drop generation."""

    def test_extractors_no_hardcoded_dialect_check(self):
        import inspect

        from core.migration.scripting.undo_script_generator._extractors import (
            _UndoExtractorsMixin,
        )

        src = inspect.getsource(_UndoExtractorsMixin._generate_drop_statement)
        assert '"postgresql"' not in src
        assert '"mysql"' not in src
        # Cascade must route through quirks, not a dialect frozenset membership.
        assert "CASCADE_DROP_DIALECTS" not in src
        assert "drop_table_default_cascade" in src
