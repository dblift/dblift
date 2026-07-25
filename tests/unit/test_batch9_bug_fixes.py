"""Regression tests for the Batch 9 bug fixes (B9-BUG-01 / NOTE-01 / NOTE-02).

Grouped by bug number so an intentional behavioral change to any one fix is
easy to locate. Mirrors the conventions of ``test_batch8_bug_fixes.py``.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B9-BUG-01: CosmosDB ``_execute_delete`` must substitute ``?`` placeholders
# ---------------------------------------------------------------------------
class TestBug01CosmosDbParamSubstitution(unittest.TestCase):
    """CosmosDB SQL has no ``?`` placeholders, so positional params must be
    inlined as quoted/typed literals before a query is sent. Repair no
    longer composes SQL for Cosmos at all (the history manager deletes via
    the SDK), but ``execute_query`` still takes positional params from
    callers such as ``info`` and introspection, so the substitution
    contract stays pinned here."""

    def _make_executor(self):
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        executor = CosmosDbQueryExecutor.__new__(CosmosDbQueryExecutor)
        executor.log = MagicMock()
        executor.connection_manager = MagicMock()
        executor.container_client = None
        return executor

    # ---- _substitute_params helper ----------------------------------------
    def test_substitute_params_replaces_single_placeholder(self) -> None:
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        out = CosmosDbQueryExecutor._substitute_params(
            "script = ? AND success = false", ["V1__foo.py"]
        )
        self.assertEqual(out, "script = 'V1__foo.py' AND success = false")

    def test_substitute_params_escapes_single_quotes(self) -> None:
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        out = CosmosDbQueryExecutor._substitute_params("name = ?", ["O'Brien"])
        self.assertEqual(out, "name = 'O''Brien'")

    def test_substitute_params_renders_bool_none_number_verbatim(self) -> None:
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        out = CosmosDbQueryExecutor._substitute_params(
            "a = ? AND b = ? AND c = ? AND d = ?", [True, False, None, 42]
        )
        self.assertEqual(out, "a = true AND b = false AND c = null AND d = 42")

    def test_substitute_params_mismatch_raises(self) -> None:
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        with self.assertRaises(ValueError) as ctx:
            CosmosDbQueryExecutor._substitute_params("a = ? AND b = ?", ["x"])
        self.assertIn("Parameter count mismatch", str(ctx.exception))

    def test_substitute_params_no_placeholder_returns_unchanged(self) -> None:
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        out = CosmosDbQueryExecutor._substitute_params("a = 'x'", [])
        self.assertEqual(out, "a = 'x'")


# ---------------------------------------------------------------------------
# B9-NOTE-01: MigrationContext must reject dict-style access with a pointer
# ---------------------------------------------------------------------------
class TestNote01MigrationContextNotSubscriptable(unittest.TestCase):
    def test_dict_style_access_raises_actionable_typeerror(self) -> None:
        from core.migration.executors.python_executor import MigrationContext

        ctx = MigrationContext(provider=MagicMock(), log=MagicMock(), dry_run=False)
        with self.assertRaises(TypeError) as err:
            _ = ctx["account_endpoint"]
        msg = str(err.exception)
        # The key that was tried is echoed so users can grep their script.
        self.assertIn("account_endpoint", msg)
        # And the message points at the new API.
        self.assertIn("context.client", msg)
        self.assertIn("context.database", msg)

    def test_new_api_attributes_still_work(self) -> None:
        """Sanity: __getitem__ doesn't shadow the typed attribute accessors."""
        from core.migration.executors.python_executor import MigrationContext

        provider = MagicMock()
        provider.connection_manager.database = "DB_PROXY"
        provider.connection_manager.client = "COSMOS_CLIENT"
        ctx = MigrationContext(provider=provider, log=MagicMock(), dry_run=True)
        self.assertEqual(ctx.database, "DB_PROXY")
        self.assertEqual(ctx.client, "COSMOS_CLIENT")
        self.assertTrue(ctx.dry_run)


# ---------------------------------------------------------------------------
# B9-NOTE-02: validate-config warns when database credentials are missing
# ---------------------------------------------------------------------------
class TestNote02ValidateConfigCredentialWarning(unittest.TestCase):
    def _run_validate(self, db_type, username, password):
        from cli import db_utils

        urls = {
            "postgres": "postgresql+psycopg://localhost/testdb",
            "mysql": "mysql+pymysql://localhost/testdb",
            "sqlite": "sqlite:///test.db",
            "cosmosdb": "cosmosdb://localhost/testdb",
            "dummy": "dummy://localhost/testdb",
        }
        database = SimpleNamespace(
            type=db_type,
            url=urls[db_type],
            username=username,
            password=password,
        )
        config = SimpleNamespace(database=database)
        args = SimpleNamespace(config=None, db_url=database.url)

        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("cli.db_utils.load_config", return_value=config),
            patch("cli.db_utils.ProviderRegistry") as reg,
        ):
            reg.validate_database_configuration.return_value = (True, None)
            # Pass get_quirks through to the real registry so credentialless
            # detection works correctly; only validate_database_configuration is mocked.
            from db.provider_registry import ProviderRegistry as _RealReg

            reg.get_quirks.side_effect = _RealReg.get_quirks
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = db_utils.validate_config(args)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_warns_when_postgres_username_and_password_missing(self) -> None:
        rc, out, err = self._run_validate("postgres", "", "")
        self.assertEqual(rc, 0)
        self.assertIn("valid", out)
        self.assertIn("Warning", err)
        self.assertIn("username and password", err)
        self.assertIn("check-connection", err)

    def test_warns_when_only_password_missing(self) -> None:
        _, _, err = self._run_validate("mysql", "appuser", "")
        self.assertIn("Warning", err)
        self.assertIn("password", err)
        self.assertNotIn("username and", err)

    def test_no_warning_when_credentials_present(self) -> None:
        _, _, err = self._run_validate("postgres", "appuser", "s3cret")
        self.assertNotIn("Warning", err)

    def test_no_warning_for_sqlite(self) -> None:
        _, _, err = self._run_validate("sqlite", "", "")
        self.assertNotIn("Warning", err)

    def test_no_warning_for_cosmosdb(self) -> None:
        _, _, err = self._run_validate("cosmosdb", "", "")
        self.assertNotIn("Warning", err)

    def test_no_warning_for_dummy(self) -> None:
        _, _, err = self._run_validate("dummy", "", "")
        self.assertNotIn("Warning", err)


if __name__ == "__main__":
    unittest.main()
