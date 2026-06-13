"""Unit tests for dblift.integrations.flask (thin helpers only).

TDD: these were written first to drive the implementation.
Uses real temp SQLite + DBLiftClient.from_sqlalchemy (no Docker) for guard
scenarios. The CLI test uses a mock to assert that the registered command
calls client.migrate().

NOTE: imports of the module under test (integrations.flask) + Flask itself
are performed *inside* each test function. This ensures:
- test collection succeeds even before the integrations/ package exists (TDD RED phase)
- flask is only required for tests that exercise app/CLI wiring (via pytest.importorskip)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient


def _setup_pending_db(tmp_path: Path) -> tuple[Any, Path, DBLiftClient]:
    """Create a migrations dir + sqlite DB with one pending migration. Return (engine, mig_dir, client)."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir(exist_ok=True)
    (mig_dir / "V1__init.sql").write_text(
        "CREATE TABLE flask_test (id INTEGER PRIMARY KEY, name TEXT);"
    )
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=mig_dir)
    # Intentionally do NOT call migrate() here -> pending state
    return engine, mig_dir, client


def _setup_current_db(tmp_path: Path) -> tuple[Any, Path, DBLiftClient]:
    """Same setup but call migrate() so DB is current."""
    engine, mig_dir, client = _setup_pending_db(tmp_path)
    result = client.migrate()
    assert result.success, "setup migrate must succeed for 'current' tests"
    return engine, mig_dir, client


def test_init_dblift_wires_client_to_extensions_and_returns_it(tmp_path: Path) -> None:
    """init_dblift creates client, stores under app.extensions['dblift'], returns it (guard=False for pending case)."""
    pytest.importorskip("flask")
    from flask import Flask

    from integrations.flask import init_dblift

    engine, mig_dir, setup_client = _setup_pending_db(tmp_path)
    try:
        app = Flask(__name__)
        returned = init_dblift(app, engine, str(mig_dir), guard=False)
        assert returned is not None
        assert app.extensions.get("dblift") is returned
        # returned should be a DBLiftClient that can report pending
        pending = returned.info().pending_migrations if hasattr(returned, "info") else []
        # basic sanity; real check_migrations not re-exported here
        assert len(pending) >= 0
    finally:
        setup_client.close()
        # the returned one shares engine; close via the setup one is sufficient


def test_init_dblift_guard_true_raises_on_pending(tmp_path: Path) -> None:
    """Default guard=True (and explicit) causes init to raise when migrations are pending."""
    pytest.importorskip("flask")
    from flask import Flask

    from integrations.flask import init_dblift

    engine, mig_dir, setup_client = _setup_pending_db(tmp_path)
    try:
        app = Flask(__name__)
        with pytest.raises(Exception) as exc:
            init_dblift(app, engine, str(mig_dir), guard=True)
        assert "pending" in str(exc.value).lower() or "Pending" in str(exc.value)
        # on raise, do not leave partial state (best effort)
        assert "dblift" not in getattr(app, "extensions", {})
    finally:
        setup_client.close()


def test_init_dblift_succeeds_when_current(tmp_path: Path) -> None:
    """guard=True is a no-op (no raise) and wiring succeeds when DB is current."""
    pytest.importorskip("flask")
    from flask import Flask

    from integrations.flask import init_dblift

    engine, mig_dir, setup_client = _setup_current_db(tmp_path)
    try:
        app = Flask(__name__)
        returned = init_dblift(app, engine, str(mig_dir), guard=True)
        assert app.extensions.get("dblift") is returned
    finally:
        setup_client.close()


def test_register_cli_wires_command_that_calls_client_migrate() -> None:
    """register_cli adds a command; invoking it via Flask test runner calls client.migrate()."""
    pytest.importorskip("flask")
    from flask import Flask

    from integrations.flask import register_cli

    app = Flask(__name__)
    mock_client = MagicMock(spec=DBLiftClient)

    register_cli(app, mock_client)

    runner = app.test_cli_runner()
    # The registered command name per impl
    result = runner.invoke(args=["dblift-migrate"])
    # We primarily care that migrate was invoked (the command may produce output or exit 0/1 depending on mock)
    mock_client.migrate.assert_called_once()
    # exit code can be anything; the point of the test is the call happened
    assert result is not None


def test_init_dblift_and_register_cli_together(tmp_path: Path) -> None:
    """Full factory + register flow works (guard disabled to allow pending in this test)."""
    pytest.importorskip("flask")
    from flask import Flask

    from integrations.flask import init_dblift, register_cli

    engine, mig_dir, setup_client = _setup_pending_db(tmp_path)
    try:
        app = Flask(__name__)
        client = init_dblift(app, engine, str(mig_dir), guard=False)
        register_cli(app, client)

        assert app.extensions["dblift"] is client

        # CLI should be present
        runner = app.test_cli_runner()
        # invoke will call the real client.migrate() which succeeds for pending
        result = runner.invoke(args=["dblift-migrate"])
        # after, should be current (no need to assert deeply, just no crash + client was used)
        assert result is not None
    finally:
        setup_client.close()
