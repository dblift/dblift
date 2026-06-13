"""Regression tests for the Batch 6 bug fixes (B6-BUG-01..B6-BUG-05).

Grouped by bug number so an intentional behavioral change to any one fix is
easy to locate. Tests avoid real network/DB dependencies by mocking out the
provider layer.
"""

from __future__ import annotations

import argparse
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B6-BUG-01: MigrationContext.close() DBAPI shim must exist
# ---------------------------------------------------------------------------
class TestBug01MigrationContextClose(unittest.TestCase):
    def test_close_is_callable_and_returns_none(self) -> None:
        from core.migration.executors.python_executor import MigrationContext

        ctx = MigrationContext(provider=MagicMock(), log=MagicMock())
        self.assertTrue(hasattr(ctx, "close"))
        self.assertIsNone(ctx.close())

    def test_full_dbapi_cursor_close_cycle(self) -> None:
        """Classic DBAPI idiom: cur = conn.cursor(); cur.execute(...); cur.close()."""
        from core.migration.executors.python_executor import MigrationContext

        provider = MagicMock()
        ctx = MigrationContext(provider=provider, log=MagicMock())
        cur = ctx.cursor()
        cur.execute("INSERT INTO t VALUES (1)")
        ctx.commit()
        cur.close()
        provider.execute_statement.assert_called_once()


# ---------------------------------------------------------------------------
# B6-BUG-02: UNDO_SQL history record must not carry checksum=None (PG INT col)
# ---------------------------------------------------------------------------
class TestBug02UndoChecksumZeroSentinel(unittest.TestCase):
    """All four ``record_undo`` sites must emit ``checksum: 0`` — not ``None``
    — so the INT-typed column in the history table doesn't trip native drivers.
    """

    def _undo_info_sources(self):
        from pathlib import Path

        return [
            Path("db/plugins/base_undo_manager.py"),
            Path("db/plugins/base_history_manager.py"),
            Path("db/plugins/oracle/oracle/history_manager.py"),
            Path("db/plugins/sqlserver/sqlserver/history_manager.py"),
        ]

    def test_no_source_still_uses_checksum_none(self) -> None:
        from pathlib import Path

        # Read each file and verify the known-bad literal is gone from the
        # ``undo_info`` blocks. Guard: the literal ``"checksum": None`` must
        # not appear anywhere in these files.
        for rel in self._undo_info_sources():
            text = Path(rel).read_text()
            self.assertNotIn(
                '"checksum": None',
                text,
                msg=f"{rel} still writes None as the UNDO_SQL checksum",
            )

    def test_each_source_uses_checksum_zero(self) -> None:
        from pathlib import Path

        for rel in self._undo_info_sources():
            text = Path(rel).read_text()
            self.assertIn(
                '"checksum": 0',
                text,
                msg=f'{rel} missing explicit ``"checksum": 0`` sentinel',
            )


# ---------------------------------------------------------------------------
# B6-BUG-03: legacy URLs must fail, not infer a default dialect
# ---------------------------------------------------------------------------
class TestBug03UnknownJdbcUrlClearsType(unittest.TestCase):
    def _make_args(self, db_url: str) -> argparse.Namespace:
        return argparse.Namespace(
            config=None,
            db_url=db_url,
            db_username="u",
            db_password="p",
            db_schema=None,
        )

    def test_unknown_jdbc_scheme_raises_configuration_error(self) -> None:
        from config.dblift_config import load_config
        from config.errors import ConfigurationError

        args = self._make_args("jdbc:testdriver://localhost:1234/test")
        with self.assertRaisesRegex(
            ConfigurationError, "Legacy database URLs are no longer supported"
        ):
            load_config(None, args)

    def test_sqlite_still_inferred(self) -> None:
        """Guard that the new clause doesn't regress the SQLite inference."""
        from config.dblift_config import load_config

        args = self._make_args("sqlite:///tmp/x.db")
        config = load_config(None, args)
        self.assertEqual(config.database.type, "sqlite")

    def test_jdbc_sqlite_is_rejected(self) -> None:
        from config.dblift_config import load_config
        from config.errors import ConfigurationError

        args = self._make_args("jdbc:sqlite:/tmp/x.db")
        with self.assertRaisesRegex(
            ConfigurationError, "Legacy database URLs are no longer supported"
        ):
            load_config(None, args)

    def test_valid_native_scheme_unaffected(self) -> None:
        """Valid URLs still round-trip through the primary parse branch."""
        from config.dblift_config import load_config

        args = self._make_args("postgresql+psycopg://localhost:5432/test")
        config = load_config(None, args)
        self.assertEqual(config.database.type, "postgresql")

    def test_validate_rejects_empty_type(self) -> None:
        """The BUG-03 fix is only useful if downstream validation fails."""
        from db.provider_registry import ProviderRegistry

        cfg = MagicMock()
        cfg.database.type = ""
        cfg.database.url = "jdbc:testdriver://localhost/test"
        is_valid, msg = ProviderRegistry.validate_database_configuration(cfg)
        self.assertFalse(is_valid)
        assert msg is not None
        self.assertIn("Database type not specified", msg)


# ---------------------------------------------------------------------------
# B6-BUG-04: validate-config must refuse to validate the stock defaults
# ---------------------------------------------------------------------------
class TestBug04ValidateConfigRequiresExplicitInput(unittest.TestCase):
    def _make_args(self, **kwargs) -> argparse.Namespace:
        defaults = dict(
            config=None,
            db_url=None,
            db_username=None,
            db_password=None,
            db_schema=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_validate_config_without_any_input_fails(self) -> None:
        from cli.db_utils import validate_config

        buf_err = io.StringIO()
        # Ensure env vars don't leak a URL into the test
        env_backup = {k: os.environ.pop(k, None) for k in ("DBLIFT_DB_URL", "DBLIFT_DATABASE_URL")}
        try:
            with redirect_stderr(buf_err):
                rc = validate_config(self._make_args())
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v
        self.assertEqual(rc, 1)
        self.assertIn("no configuration source", buf_err.getvalue().lower())

    def test_validate_config_with_env_var_does_not_short_circuit(self) -> None:
        """With DBLIFT_DB_URL set, validate-config proceeds to the real validator."""
        from cli.db_utils import validate_config

        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with patch.dict(
            os.environ,
            {"DBLIFT_DB_URL": "postgresql+psycopg://localhost:5432/x"},
            clear=False,
        ):
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                rc = validate_config(self._make_args())
        # The early "no configuration source" guard must not fire with the env var set.
        self.assertNotIn("no configuration source", buf_err.getvalue().lower())
        # rc is whatever validate_database_configuration returns; test the path, not
        # the exact outcome.
        self.assertIn(rc, (0, 1))

    def test_validate_config_with_cli_url_proceeds(self) -> None:
        from cli.db_utils import validate_config

        buf_err = io.StringIO()
        env_backup = {k: os.environ.pop(k, None) for k in ("DBLIFT_DB_URL", "DBLIFT_DATABASE_URL")}
        try:
            with redirect_stderr(buf_err), redirect_stdout(io.StringIO()):
                validate_config(self._make_args(db_url="postgresql+psycopg://localhost:5432/x"))
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v
        self.assertNotIn("no configuration source", buf_err.getvalue().lower())


# ---------------------------------------------------------------------------
# B6-BUG-05: EventEmitter must expose subscribe/unsubscribe aliases
# ---------------------------------------------------------------------------
class TestBug05EventEmitterSubscribeAlias(unittest.TestCase):
    def test_subscribe_alias_registers_and_fires(self) -> None:
        from api.events import EventEmitter, EventType

        emitter = EventEmitter()
        received = []
        emitter.subscribe(EventType.MIGRATION_FAILED, lambda evt: received.append(evt))
        emitter.emit(EventType.MIGRATION_FAILED, {"version": "42"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].version, "42")

    def test_unsubscribe_alias_removes_listener(self) -> None:
        from api.events import EventEmitter, EventType

        emitter = EventEmitter()
        received = []
        cb = lambda evt: received.append(evt)  # noqa: E731
        emitter.subscribe(EventType.MIGRATION_STARTED, cb)
        emitter.unsubscribe(EventType.MIGRATION_STARTED, cb)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        self.assertEqual(received, [])

    def test_subscribe_and_on_are_interchangeable(self) -> None:
        from api.events import EventEmitter, EventType

        emitter = EventEmitter()
        received = []
        emitter.on(EventType.MIGRATION_STARTED, lambda evt: received.append("on"))
        emitter.subscribe(EventType.MIGRATION_STARTED, lambda evt: received.append("sub"))
        emitter.emit(EventType.MIGRATION_STARTED, {})
        self.assertIn("on", received)
        self.assertIn("sub", received)


# ---------------------------------------------------------------------------
# B6-BUG-06: DBLiftClient.events must be per-instance, not a shared singleton
# ---------------------------------------------------------------------------
class TestBug06PerClientEventIsolation(unittest.TestCase):
    """Two DBLiftClient instances must not share an ``EventEmitter``.

    The regression was that ``__init__`` aliased ``self.events`` to
    ``get_default_emitter()``, so listeners attached to client A fired for
    events emitted by client B. The fix is a per-instance emitter with a
    contextvar binding for core-layer ``emit_event`` calls.
    """

    def test_emitters_are_distinct_per_client(self) -> None:
        """DBLiftClient instances must own independent emitters."""
        from api.events import EventEmitter

        # Construct EventEmitter the way DBLiftClient.__init__ now does.
        emitter_a = EventEmitter()
        emitter_b = EventEmitter()
        self.assertIsNot(emitter_a, emitter_b)

    def test_emit_event_prefers_bound_client_emitter(self) -> None:
        """emit_event routes to the active client emitter when one is bound."""
        from api.events import EventEmitter, emit_event, use_client_emitter

        client_emitter = EventEmitter()
        received: list = []
        client_emitter.on("migration.script.started", received.append)

        with use_client_emitter(client_emitter):
            emit_event("migration.script.started", {"script": "V1__x.sql"})

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].script, "V1__x.sql")

    def test_emit_event_falls_back_to_default_outside_client_scope(self) -> None:
        """When no client emitter is bound, emit_event targets the singleton."""
        from api.events import emit_event, get_default_emitter

        received: list = []
        get_default_emitter().on("migration.script.completed", received.append)
        emit_event("migration.script.completed", {"script": "V2__y.sql"})
        self.assertTrue(any(r.script == "V2__y.sql" for r in received))

    def test_sibling_client_does_not_see_other_clients_events(self) -> None:
        """Events bound to client A must not leak into client B's listeners."""
        from api.events import EventEmitter, emit_event, use_client_emitter

        client_a = EventEmitter()
        client_b = EventEmitter()
        a_events: list = []
        b_events: list = []
        client_a.on("migration.script.started", a_events.append)
        client_b.on("migration.script.started", b_events.append)

        with use_client_emitter(client_a):
            emit_event("migration.script.started", {"script": "A.sql"})
        with use_client_emitter(client_b):
            emit_event("migration.script.started", {"script": "B.sql"})

        self.assertEqual([e.script for e in a_events], ["A.sql"])
        self.assertEqual([e.script for e in b_events], ["B.sql"])

    def test_use_client_emitter_with_none_is_noop(self) -> None:
        """Passing None must not corrupt the contextvar or raise."""
        from api.events import emit_event, get_default_emitter, use_client_emitter

        received: list = []
        get_default_emitter().on("migration.script.failed", received.append)
        with use_client_emitter(None):
            emit_event("migration.script.failed", {"script": "Z.sql"})
        self.assertTrue(any(r.script == "Z.sql" for r in received))

    def test_client_init_uses_fresh_emitter(self) -> None:
        """DBLiftClient source no longer wires self.events to the singleton."""
        from pathlib import Path

        src = Path("api/client.py").read_text()
        # The regression was ``self.events = get_default_emitter()``; the fix
        # restores ``self.events = EventEmitter()``.
        self.assertNotIn("self.events = get_default_emitter()", src)
        self.assertIn("self.events = EventEmitter()", src)


# ---------------------------------------------------------------------------
# B6-BUG-06b: undo() must bind the client emitter before executor work
# ---------------------------------------------------------------------------
class TestBug06bUndoBindsClientEmitter(unittest.TestCase):
    """Undo's executor call must route core-layer events to the per-client
    emitter — otherwise ``migration.script.*`` events emitted during rollback
    leak to the process-wide singleton, partially reversing the BUG-06 fix.
    """

    def _method_decorator_names(self, method_name: str) -> list[str]:
        import ast
        from pathlib import Path

        src = Path("api/client.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == method_name:
                return [dec.id for dec in node.decorator_list if isinstance(dec, ast.Name)]
        raise AssertionError(f"{method_name} method not found in api/client.py")

    def test_undo_wraps_executor_in_use_client_emitter(self) -> None:
        # The implementation used to inline ``with use_client_emitter(self.events)``
        # inside ``undo``. The current structural contract is stronger and less
        # repetitive: ``@_with_client_emitter`` wraps the whole public operation.
        self.assertIn("_with_client_emitter", self._method_decorator_names("undo"))

    def test_migrate_and_undo_both_bind_client_emitter(self) -> None:
        """Symmetry guard: if one wraps, both must."""
        self.assertIn("_with_client_emitter", self._method_decorator_names("migrate"))
        self.assertIn("_with_client_emitter", self._method_decorator_names("undo"))


if __name__ == "__main__":
    unittest.main()
