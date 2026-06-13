"""PR-G9 coverage push for ``core.migration.executor.execution_engine``.

Targets the residual uncovered branches after PR-F4:

* ``_parse_sql_statements`` returning ``None`` triggers an early-return from
  ``execute_migration`` (line 141).
* ``_ensure_autocommit_for_policy`` short-circuits for non-transactional
  providers (line 220).
* ``_probe_dialect_key`` Enum normalisation + empty-string return None
  (lines 376 and 379).
* ``_execute_statements`` DBMS_OUTPUT enable failure (lines 438-439).
* ``_execute_statements`` TypeError when sql_execution_service returns a
  non-int for the "not query" branch (line 534).
* ``_execute_statements`` ``read_dbms_output`` exception swallow (lines 554-555).
* ``_handle_statement_failure`` ``add_migration`` failure swallow (lines 621-622).
* ``_commit_and_verify`` qualified-name validation break (line 772).
* ``_commit_and_verify`` outer-block exception swallow (lines 810-811).
"""

import unittest
from enum import Enum
from unittest.mock import MagicMock, patch

from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration

# ---------------------------------------------------------------------------
# Helpers (mirroring test_execution_engine_extended.py for consistency)
# ---------------------------------------------------------------------------


def _make_engine(dialect="postgresql", with_history=False, with_config=True):
    """Build a minimal ExecutionEngine suitable for unit tests."""
    from db.provider_interfaces import TransactionalProvider

    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    provider.supports_transactions.return_value = True
    provider.supports_transactional_ddl.return_value = True
    provider.connection = MagicMock()
    provider.connection.getAutoCommit.return_value = False
    provider.connection.isClosed.return_value = False
    provider.canonical_dialect_key = ""

    sql_analyzer = MagicMock()
    sql_analyzer.dialect = dialect

    log = MagicMock()

    config = None
    if with_config:
        config = MagicMock()
        config.database.type.value = dialect
        config.database.url = f"{dialect}://host:5432/db"

    history_manager = MagicMock() if with_history else None

    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=sql_analyzer,
        log=log,
        config=config,
        history_manager=history_manager,
    )
    return engine


def _make_sql_migration(content="SELECT 1;", name="V1__test.sql", statements=None):
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.SQL
    m.content = content
    m.script_name = name
    m.version = "1"
    m.description = "test"
    m.checksum = 12345
    m.type = MagicMock()
    m.type.value = "SQL"
    m.type.name = "VERSIONED"
    m.parse_sql_statements.return_value = statements if statements is not None else ["SELECT 1"]
    return m


# ---------------------------------------------------------------------------
# execute_migration early-return when _parse_sql_statements returns None
# ---------------------------------------------------------------------------


class TestExecuteMigrationParseFailureEarlyReturn(unittest.TestCase):
    """Covers line 141: ``if statements is None: return`` after parse failure."""

    def test_parse_failure_short_circuits(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        result = MagicMock()

        with patch("core.licensing._guard._refresh_state"):
            with patch.object(engine, "_parse_sql_statements", return_value=None) as mock_parse:
                with patch.object(engine, "_classify_execution_statements") as mock_classify:
                    engine.execute_migration(migration, result)

        mock_parse.assert_called_once()
        # Execution must not progress past the None check.
        mock_classify.assert_not_called()
        # No begin / commit / rollback either.
        engine.provider.begin_transaction.assert_not_called()
        engine.provider.commit_transaction.assert_not_called()


# ---------------------------------------------------------------------------
# _ensure_autocommit_for_policy short-circuit for non-transactional provider
# ---------------------------------------------------------------------------


class TestEnsureAutocommitNonTransactional(unittest.TestCase):
    """Covers line 220: early return when the provider is not
    a ``TransactionalProvider``."""

    def test_non_transactional_provider_skips_entirely(self):
        engine = _make_engine()
        # Replace provider with a plain MagicMock (no JdbcProvider spec → not a
        # TransactionalProvider). The method must return immediately without
        # touching rollback / setAutoCommit.
        engine.provider = MagicMock()
        engine.provider.rollback_transaction = MagicMock()
        migration = _make_sql_migration()

        engine._ensure_autocommit_for_policy(migration)

        engine.provider.rollback_transaction.assert_not_called()


# ---------------------------------------------------------------------------
# _probe_dialect_key Enum normalisation + empty-string return-None
# ---------------------------------------------------------------------------


class _FakeDialectEnum(Enum):
    """Concrete Enum so ``isinstance(raw, Enum)`` is True (line 375)."""

    POSTGRES = "postgresql"
    MSSQL_ALIAS = "mssql"


class TestProbeDialectKeyNormalize(unittest.TestCase):
    """Covers the legacy-fallback ``_normalize`` helper (lines 376 + 379)."""

    def test_enum_value_normalised_via_registry(self):
        # Provider has no canonical_dialect_key set, sql_analyzer.dialect is
        # an Enum instance — exercises line 376 (``raw = raw.value``).
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = _FakeDialectEnum.POSTGRES
        # provider.dialect attribute also unset to make sure the first match wins.
        assert engine._probe_dialect_key() == "postgresql"

    def test_enum_with_mssql_alias_canonicalised(self):
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = _FakeDialectEnum.MSSQL_ALIAS
        # MSSQL_ALIAS.value == "mssql" → registry → "sqlserver"
        assert engine._probe_dialect_key() == "sqlserver"

    def test_empty_string_input_normalises_to_none(self):
        # Force every signal to an empty string so ``_normalize`` exercises
        # the line-379 ``if not s: return None`` branch for each candidate.
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = ""  # empty string → _normalize returns None
        engine.provider.dialect = ""
        assert engine._probe_dialect_key() is None

    def test_whitespace_only_string_input_returns_none(self):
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = "   "
        engine.provider.dialect = "   "
        assert engine._probe_dialect_key() is None

    def test_canonical_dialect_key_whitespace_falls_through(self):
        # Cover the line-388 ``if isinstance(key, str) and key.strip(): ...``
        # decision: a whitespace-only key should NOT short-circuit; the
        # fallback cascade should run.
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = "   "
        engine.sql_analyzer.dialect = "oracle"
        assert engine._probe_dialect_key() == "oracle"

    def test_provider_dialect_used_when_all_else_missing(self):
        # ``sql_analyzer.dialect`` and ``config`` empty/None; provider.dialect
        # provides the only signal. Exercises the final ``return _normalize(...)``.
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = None
        engine.provider.dialect = "mssql"  # alias → canonicalises to sqlserver
        assert engine._probe_dialect_key() == "sqlserver"


# ---------------------------------------------------------------------------
# _parse_sql_statements: mssql alias normalisation (preserves
# behaviour: only "sqlserver" canonical name triggers the rewrite).
# ---------------------------------------------------------------------------


class TestParseSqlStatementsMssqlAlias(unittest.TestCase):
    """Covers the ``if canonical == 'sqlserver'`` branch in _parse_sql_statements."""

    def test_mssql_config_type_value_rewrites_to_sqlserver(self):
        engine = _make_engine()
        engine.config.database.type.value = "mssql"
        migration = _make_sql_migration(content="SELECT 1;")
        result = MagicMock()

        # Capture the dialect that ``parse_sql_statements`` is invoked with.
        engine._parse_sql_statements(migration, result)

        kwargs = migration.parse_sql_statements.call_args.kwargs
        # The canonical name "sqlserver" should reach the parser despite the
        # config saying "mssql".
        assert kwargs["dialect"] == "sqlserver"

    def test_postgres_alias_passes_through_unchanged(self):
        # Sanity check: the alias normalisation is gated on "sqlserver" only.
        # "postgres" must NOT be rewritten to "postgresql" (per the inline
        # OCP-todo comment in the production code).
        engine = _make_engine()
        engine.config.database.type.value = "postgres"
        migration = _make_sql_migration(content="SELECT 1;")
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        kwargs = migration.parse_sql_statements.call_args.kwargs
        assert kwargs["dialect"] == "postgres"


# ---------------------------------------------------------------------------
# _execute_statements: DBMS_OUTPUT enable failure (lines 438-439)
# ---------------------------------------------------------------------------


class TestDbmsOutputEnableFailure(unittest.TestCase):
    """Covers lines 438-439: enable_dbms_output raises → log warning, continue."""

    def test_enable_failure_logs_warning_and_continues(self):
        engine = _make_engine(dialect="oracle")
        migration = _make_sql_migration()
        result = MagicMock()

        # Force the Oracle SQL*Plus path with serveroutput=True so DBMS_OUTPUT
        # is attempted. The provider.connection exists per _make_engine.
        ctx = MagicMock()
        ctx.wants_session_output = True
        engine._current_sqlplus_ctx = ctx

        # Make the import target raise; OracleQuirks.enable_session_output
        # lazy-imports this symbol, so the patch path is the same.
        with patch(
            "db.plugins.oracle.oracle.dbms_output.enable_dbms_output",
            side_effect=RuntimeError("dbms_output broken"),
        ):
            with patch.object(engine, "_transaction_liveness_probe_sql", return_value="SELECT 1"):
                # Use an empty statements list so the per-statement loop is a no-op.
                ok = engine._execute_statements([], migration, result, 0.0)

        assert ok is True
        engine.log.warning.assert_called()
        warning_msgs = [str(c) for c in engine.log.warning.call_args_list]
        assert any("Could not enable session output capture" in m for m in warning_msgs)


# ---------------------------------------------------------------------------
# _execute_statements: read_dbms_output post-statement failure (lines 554-555)
# ---------------------------------------------------------------------------


class TestDbmsOutputReadFailure(unittest.TestCase):
    """Covers lines 554-555: read_dbms_output raises → log warning, continue."""

    def test_read_failure_logs_warning(self):
        engine = _make_engine(dialect="oracle")
        migration = _make_sql_migration()
        result = MagicMock()

        ctx = MagicMock()
        ctx.wants_session_output = True
        engine._current_sqlplus_ctx = ctx

        # provider.execute_statement returns 0 rows affected (DDL-ish).
        engine.provider.execute_statement.return_value = 0
        # Pre-check probe path: prepareStatement raises AttributeError so we
        # fall back to provider.execute_query (which is harmless).
        engine.provider.connection.prepareStatement.side_effect = AttributeError

        with patch("db.plugins.oracle.oracle.dbms_output.enable_dbms_output"):
            with patch(
                "db.plugins.oracle.oracle.dbms_output.read_dbms_output",
                side_effect=RuntimeError("read failed"),
            ):
                with patch.object(
                    engine, "_transaction_liveness_probe_sql", return_value="SELECT 1"
                ):
                    ok = engine._execute_statements(
                        ["CREATE TABLE t (id INT)"], migration, result, 0.0
                    )

        assert ok is True
        warning_msgs = [str(c) for c in engine.log.warning.call_args_list]
        assert any("Could not read session output" in m for m in warning_msgs)


# ---------------------------------------------------------------------------
# _execute_statements: TypeError when sql_execution_service returns wrong type
# (line 534)
# ---------------------------------------------------------------------------


class TestSqlExecutionServiceTypeError(unittest.TestCase):
    """Covers line 534: non-int returned for the not-a-query branch raises
    TypeError, which the engine routes through _handle_statement_failure."""

    def test_non_int_rows_affected_raises_typeerror(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        result = MagicMock()

        svc = MagicMock()
        # is_query=False but result_data is a string instead of an int.
        svc.execute_statement.return_value = (False, "not-an-int")
        engine.sql_execution_service = svc

        # Make the pre-check provider path harmless.
        engine.provider.connection.prepareStatement.side_effect = AttributeError

        with patch.object(engine, "_transaction_liveness_probe_sql", return_value="SELECT 1"):
            ok = engine._execute_statements(["UPDATE t SET x = 1"], migration, result, 0.0)

        # Statement-level failure → engine returns False.
        assert ok is False
        result.set_error.assert_called()
        # The TypeError message should reach the user via set_error.
        err_text = " ".join(str(c) for c in result.set_error.call_args_list)
        assert "rows affected" in err_text or "str" in err_text


# ---------------------------------------------------------------------------
# _handle_statement_failure: add_migration raises → log warning (lines 621-622)
# ---------------------------------------------------------------------------


class TestHandleStatementFailureAddMigrationException(unittest.TestCase):
    def test_add_migration_failure_is_swallowed_and_logged(self):
        engine = _make_engine(with_history=False)
        migration = _make_sql_migration()
        # result.add_migration raises — engine should swallow and log.
        result = MagicMock()
        result.add_migration.side_effect = RuntimeError("boom")

        engine._handle_statement_failure(migration, RuntimeError("stmt err"), 0, 12, result)

        warning_msgs = [str(c) for c in engine.log.warning.call_args_list]
        assert any("Could not add failed migration" in m for m in warning_msgs)


# ---------------------------------------------------------------------------
# _commit_and_verify: invalid qualified name → break verification (line 772)
# ---------------------------------------------------------------------------


class TestCommitAndVerifyInvalidQualifiedName(unittest.TestCase):
    """Line 772 is defense-in-depth — the regex's ``\\w+`` capture already
    excludes everything but ``[A-Za-z0-9_]``, so the ``re.match`` guard at
    line 769 can never actually trigger on real input. We force the guard
    to fail explicitly to cover the ``break`` line."""

    def test_validation_guard_break_skips_verification(self):
        engine = _make_engine()
        engine.sql_analyzer.dialect = "postgresql"
        migration = _make_sql_migration()
        statements = ['CREATE TABLE "public"."t" (id INT)']

        # Force the OWASP defense-in-depth guard to fail. The regex match
        # itself extracts only \w+ groups so this is otherwise unreachable.
        with patch(
            "core.migration.executor.execution_engine.re.match",
            return_value=None,
        ):
            engine._commit_and_verify(migration, statements, 100)

        engine.provider.commit_transaction.assert_called_once()
        engine.provider.execute_query.assert_not_called()

    def test_inner_verification_isclosed_exception_logged_inner_block(self):
        # Inner ``try/except Exception as verify_e`` (line 805-808): a probe
        # failure inside the verification body is swallowed at the inner
        # level, not by the outer block (lines 810-811).
        engine = _make_engine()
        engine.sql_analyzer.dialect = "postgresql"
        migration = _make_sql_migration()

        engine.provider.connection.isClosed.side_effect = RuntimeError(
            "connection state probe failed"
        )
        statements = ["CREATE TABLE public.t (id INT)"]

        engine._commit_and_verify(migration, statements, 100)

        engine.provider.commit_transaction.assert_called_once()
        debug_msgs = [str(c) for c in engine.log.debug.call_args_list]
        assert any("Post-commit verification query failed" in m for m in debug_msgs)


# ---------------------------------------------------------------------------
# _commit_and_verify: outer post-commit verification block raises (lines 810-811)
# ---------------------------------------------------------------------------


class TestCommitAndVerifyOuterExceptionSwallowed(unittest.TestCase):
    def test_outer_post_commit_block_exception_logged_debug(self):
        engine = _make_engine()
        engine.sql_analyzer.dialect = "postgresql"
        migration = _make_sql_migration()

        # Inject a non-string statement so ``sql_stmt.upper()`` (line 759)
        # raises an AttributeError BEFORE entering the inner try block.
        # That bubbles up to the outer except at lines 810-811. The string
        # representation of ``statements`` must contain "CREATE TABLE" so
        # the outer guard at line 757 passes; we place the bad item first
        # so the loop hits ``sql_stmt.upper()`` on it.
        bad_statement = MagicMock()
        bad_statement.upper.side_effect = AttributeError("not a string")
        statements = [bad_statement, "CREATE TABLE public.t (id INT)"]

        engine._commit_and_verify(migration, statements, 100)

        engine.provider.commit_transaction.assert_called_once()
        debug_msgs = [str(c) for c in engine.log.debug.call_args_list]
        assert any("Could not perform post-commit state verification" in m for m in debug_msgs)
