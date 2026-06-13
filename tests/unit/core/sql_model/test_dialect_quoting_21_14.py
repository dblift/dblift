"""Tests for DialectEnum.quote_identifier (story 21-14 — phase 1 dispatch).

AC#1 — Covers every branch of the dispatch dict.
AC#2 — Validates delegation from the three refactored _quote_identifier methods.
AC#3 — Non-regression for existing DiffSqlGenerator quoting expectations.
"""

import pytest

from core.sql_model.dialect import DialectEnum

pytestmark = [pytest.mark.unit]


class TestDialectEnumQuoteIdentifier:
    """AC#1 — quote_identifier dispatch, one test per branch."""

    @pytest.mark.parametrize(
        "dialect, identifier, expected",
        [
            # mysql → backtick
            ("mysql", "users", "`users`"),
            ("MySQL", "my_table", "`my_table`"),
            # sqlserver → square brackets
            ("sqlserver", "users", "[users]"),
            ("SQLSERVER", "my_table", "[my_table]"),
            # postgresql → double-quote (ANSI default)
            ("postgresql", "users", '"users"'),
            # oracle → double-quote (ANSI default)
            ("oracle", "MY_COL", '"MY_COL"'),
            # db2 → double-quote (ANSI default)
            ("db2", "T1", '"T1"'),
            # sqlite → double-quote (ANSI default)
            ("sqlite", "data", '"data"'),
            # cosmosdb → no quoting (NoSQL — JSON keys, not SQL identifiers).
            # Story 26-5: CosmosdbQuirks sets ``quote_open=""``/``quote_close=""``
            # so ``Dialect.quote_identifier`` and ``base.format_identifier``
            # both pass identifiers through unchanged. Aligns with the
            # SQL DDL emitter which already produced unquoted output.
            ("cosmosdb", "Container", "Container"),
            # unknown string → double-quote (ANSI default)
            ("unknown_db", "x", '"x"'),
            # None → double-quote (ANSI default)
            (None, "col", '"col"'),
            # empty string → double-quote (ANSI default)
            ("", "col", '"col"'),
        ],
    )
    def test_quote_identifier_parametric(self, dialect, identifier, expected):
        """Every dialect branch produces the correct quoting character."""
        result = DialectEnum.quote_identifier(dialect, identifier)
        assert result == expected, (
            f"quote_identifier({dialect!r}, {identifier!r}) → {result!r}, " f"expected {expected!r}"
        )

    def test_quote_identifier_is_static(self):
        """quote_identifier is a @staticmethod (callable without instance)."""
        # Must not raise even when called on the class directly
        result = DialectEnum.quote_identifier("postgresql", "id")
        assert result == '"id"'

    def test_identifiers_with_spaces(self):
        """Identifiers containing spaces are wrapped correctly."""
        assert DialectEnum.quote_identifier("mysql", "my table") == "`my table`"
        assert DialectEnum.quote_identifier("sqlserver", "my table") == "[my table]"
        assert DialectEnum.quote_identifier("postgresql", "my table") == '"my table"'


class TestQuoteIdentifierDelegation:
    """AC#2 — The three refactored _quote_identifier methods now delegate here."""

    def test_diff_sql_generator_delegates(self):
        """DiffSqlGenerator._quote_identifier delegates via DiffSqlStatementBuilder to DialectEnum."""
        import inspect

        from core.sql_generator.diff_sql_generator import DiffSqlStatementBuilder

        src = inspect.getsource(DiffSqlStatementBuilder.quote_identifier)
        assert (
            "DialectEnum.quote_identifier" in src
        ), "DiffSqlStatementBuilder.quote_identifier must delegate to DialectEnum"

    def test_base_converter_delegates(self):
        """BaseConverter._quote_identifier delegates to DialectEnum."""
        import inspect

        from core.sql_generator.diff_converters.base_converter import BaseConverter

        src = inspect.getsource(BaseConverter._quote_identifier)
        assert (
            "DialectEnum.quote_identifier" in src
        ), "BaseConverter._quote_identifier must delegate to DialectEnum"

    def test_undo_script_generator_delegates(self):
        """UndoScriptGenerator._quote_identifier delegates to DialectEnum."""
        import inspect

        from core.migration.scripting.undo_script_generator import UndoScriptGenerator

        src = inspect.getsource(UndoScriptGenerator._quote_identifier)
        assert (
            "DialectEnum.quote_identifier" in src
        ), "UndoScriptGenerator._quote_identifier must delegate to DialectEnum"


class TestDiffSqlGeneratorQuoteRegressions:
    """AC#3 — Non-regression: existing DiffSqlGenerator quoting expectations."""

    def test_postgresql_double_quote(self):
        from core.sql_generator.diff_sql_generator import DiffSqlGenerator

        gen = DiffSqlGenerator(dialect="postgresql")
        assert gen._quote_identifier("users") == '"users"'

    def test_mysql_backtick(self):
        from core.sql_generator.diff_sql_generator import DiffSqlGenerator

        gen = DiffSqlGenerator(dialect="mysql")
        assert gen._quote_identifier("users") == "`users`"

    def test_oracle_double_quote(self):
        from core.sql_generator.diff_sql_generator import DiffSqlGenerator

        gen = DiffSqlGenerator(dialect="oracle")
        assert gen._quote_identifier("users") == '"users"'

    def test_sqlserver_brackets(self):
        from core.sql_generator.diff_sql_generator import DiffSqlGenerator

        gen = DiffSqlGenerator(dialect="sqlserver")
        assert gen._quote_identifier("users") == "[users]"

    def test_cosmosdb_no_quote(self):
        # Story 26-5: CosmosDB is NoSQL — quirks set empty quote chars.
        from core.sql_generator.diff_sql_generator import DiffSqlGenerator

        gen = DiffSqlGenerator(dialect="cosmosdb")
        assert gen._quote_identifier("users") == "users"

    def test_unknown_dialect_returns_double_quote(self):
        """Unknown dialect now returns double-quote (ANSI standard fallback)."""
        from core.sql_generator.diff_sql_generator import DiffSqlGenerator

        gen = DiffSqlGenerator(dialect="postgresql")
        gen.dialect = "unknown_dialect"
        # Before story 21-14: returned bare identifier.
        # After story 21-14: returns double-quoted (ANSI standard).
        result = gen._quote_identifier("users")
        assert result == '"users"'
