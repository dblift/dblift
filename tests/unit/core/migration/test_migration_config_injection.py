"""Unit tests for Migration config injection (Story 10-20).

Validates that Migration.__init__ accepts config= and that
parse_sql_statements() uses self.config as dialect fallback
when no dialect is provided explicitly.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.migration.migration import Migration


@pytest.mark.unit
class TestMigrationConfigInjection:
    """Tests for config injection path in Migration (AC#3 story 10-20)."""

    def _make_config(self, db_type: str = "postgresql") -> MagicMock:
        config = MagicMock()
        config.database.type = db_type
        return config

    def test_migration_stores_injected_config(self):
        """Migration.__init__ stores config in self.config."""
        mock_config = self._make_config()
        migration = Migration(
            script_name="V001__test.sql",
            content="SELECT 1;",
            config=mock_config,
        )
        assert migration.config is mock_config

    def test_migration_config_none_by_default(self):
        """config defaults to None when not provided."""
        migration = Migration(
            script_name="V001__test.sql",
            content="SELECT 1;",
        )
        assert migration.config is None

    def test_parse_sql_statements_uses_config_dialect_when_no_explicit_dialect(self):
        """parse_sql_statements() uses self.config.database.type as dialect fallback."""
        mock_config = self._make_config("postgresql")
        migration = Migration(
            script_name="V001__test.sql",
            content="SELECT 1;",
            config=mock_config,
        )

        # SqlAnalyzer is imported inline inside parse_sql_statements — patch at source module
        with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as mock_analyzer_class:
            mock_analyzer = MagicMock()
            mock_analyzer.split_statements.return_value = ["SELECT 1"]
            mock_analyzer_class.return_value = mock_analyzer

            result = migration.parse_sql_statements()  # no dialect= argument

        # SqlAnalyzer was called with the dialect from config
        mock_analyzer_class.assert_called()
        # The last call with dialect kwarg should use "postgresql"
        calls_with_dialect = [
            c
            for c in mock_analyzer_class.call_args_list
            if c[1].get("dialect") == "postgresql" or (c[0] and c[0][0] == "postgresql")
        ]
        assert calls_with_dialect, (
            f"Expected SqlAnalyzer to be called with dialect='postgresql'. "
            f"Calls: {mock_analyzer_class.call_args_list}"
        )
        assert result == ["SELECT 1"]

    def test_parse_sql_statements_explicit_dialect_takes_precedence_over_config(self):
        """Explicit dialect= overrides self.config when both are present."""
        mock_config = self._make_config("sqlserver")
        migration = Migration(
            script_name="V001__test.sql",
            content="SELECT 1;",
            config=mock_config,
        )

        with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as mock_analyzer_class:
            mock_analyzer = MagicMock()
            mock_analyzer.split_statements.return_value = ["SELECT 1"]
            mock_analyzer_class.return_value = mock_analyzer

            result = migration.parse_sql_statements(dialect="oracle")

        calls_with_oracle = [
            c
            for c in mock_analyzer_class.call_args_list
            if c[1].get("dialect") == "oracle" or (c[0] and c[0][0] == "oracle")
        ]
        assert calls_with_oracle, (
            f"Expected SqlAnalyzer to be called with dialect='oracle'. "
            f"Calls: {mock_analyzer_class.call_args_list}"
        )

    def test_parse_sql_statements_with_config_none_falls_back_to_env_or_warning(self):
        """When config=None and no dialect, falls through to env/warning path."""
        migration = Migration(
            script_name="V001__test.sql",
            content="SELECT 1;",
            config=None,
        )

        mock_logger = MagicMock()
        migration.logger = mock_logger

        with patch.dict("os.environ", {}, clear=True):
            with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as mock_analyzer_class:
                mock_analyzer = MagicMock()
                mock_analyzer.split_statements.return_value = ["SELECT 1"]
                mock_analyzer_class.return_value = mock_analyzer

                result = migration.parse_sql_statements()

        # A warning should have been issued about missing dialect
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any(
            "dialect" in c.lower() for c in warning_calls
        ), f"Expected warning about missing dialect, got: {warning_calls}"

    def test_no_dialect_path_passes_registry_default_not_hidden_literal(self):
        """The config=None/no-dialect path must pass an explicit registry-derived
        dialect to SqlAnalyzer (ADR-26 E5).

        Previously SqlAnalyzer had a hidden ``dialect="oracle"`` default and this
        path called ``SqlAnalyzer(logger=...)`` with no dialect. The dialect is
        now required, so the caller resolves a registry default and passes it.
        """
        from db.provider_registry import ProviderRegistry

        migration = Migration(
            script_name="V001__test.sql",
            content="SELECT 1;",
            config=None,
        )
        mock_logger = MagicMock()
        migration.logger = mock_logger

        with patch.dict("os.environ", {}, clear=True):
            with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as mock_analyzer_class:
                mock_analyzer = MagicMock()
                mock_analyzer.split_statements.return_value = ["SELECT 1"]
                mock_analyzer_class.return_value = mock_analyzer

                migration.parse_sql_statements()

        # SqlAnalyzer must be constructed with an explicit dialect that resolves
        # to a real registered native dialect — never an implicit default.
        passed_dialects = []
        for c in mock_analyzer_class.call_args_list:
            if c.args:
                passed_dialects.append(c.args[0])
            if "dialect" in c.kwargs:
                passed_dialects.append(c.kwargs["dialect"])
        assert passed_dialects, "SqlAnalyzer must be called with an explicit dialect"
        for d in passed_dialects:
            assert ProviderRegistry.canonical_dialect_name(d) == d
            assert ProviderRegistry.is_native_dialect(d)
