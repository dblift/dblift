"""Per-call placeholders must reach Python migration scripts.

``client.migrate(placeholders=...)`` and ``client.undo(placeholders=...)`` feed
the shared placeholder service that the SQL path substitutes from.  A Python
script reads the same values through ``context.placeholders``, so both paths
must agree on the effective set: config-time values, per-call values winning
over them, and the ``dblift_*`` system placeholders.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from api import DBLiftClient
from config import DbliftConfig

V1_PY = """\
def migrate(context):
    context.execute("CREATE TABLE observed (phase TEXT, value TEXT)")
    value = context.placeholders.get("status_value", "default_status")
    context.execute("INSERT INTO observed VALUES ('migrate', '%s')" % value)
"""

U1_PY = """\
def migrate(context):
    value = context.placeholders.get("status_value", "default_status")
    context.execute("INSERT INTO observed VALUES ('undo', '%s')" % value)
"""

V1_SYSTEM_PY = """\
def migrate(context):
    context.execute("CREATE TABLE observed (phase TEXT, value TEXT)")
    keys = ",".join(sorted(context.placeholders))
    context.execute("INSERT INTO observed VALUES ('keys', '%s')" % keys)
"""


def _setup(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return engine, migrations


def _observed(engine, phase: str) -> str:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT value FROM observed WHERE phase = ?", (phase,)
        ).fetchall()
    assert len(rows) == 1, f"expected one '{phase}' row, got {rows!r}"
    return str(rows[0][0])


def _overlay(migrations: Path, placeholders: dict) -> DbliftConfig:
    return DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "url": "sqlite:///ignored.db"},
            "migrations": {"directory": str(migrations)},
            "placeholders": placeholders,
        }
    )


def test_migrate_per_call_placeholder_reaches_python_script(tmp_path):
    engine, migrations = _setup(tmp_path)
    (migrations / "V1__observe.py").write_text(V1_PY)

    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        assert client.migrate(placeholders={"status_value": "api_status"}).success
        assert _observed(engine, "migrate") == "api_status"
    finally:
        client.close()


def test_undo_per_call_placeholder_reaches_python_undo_script(tmp_path):
    engine, migrations = _setup(tmp_path)
    (migrations / "V1__observe.py").write_text(V1_PY)
    (migrations / "U1__observe_undo.py").write_text(U1_PY)

    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        assert client.migrate().success
        undo_result = client.undo(placeholders={"status_value": "undo_status"})
        assert undo_result.success, undo_result
        assert _observed(engine, "undo") == "undo_status"
    finally:
        client.close()


def test_per_call_placeholder_overrides_config_placeholder(tmp_path):
    engine, migrations = _setup(tmp_path)
    (migrations / "V1__observe.py").write_text(V1_PY)

    client = DBLiftClient.from_sqlalchemy(
        engine,
        migrations_dir=migrations,
        config=_overlay(migrations, {"status_value": "config_status"}),
    )
    try:
        assert client.migrate(placeholders={"status_value": "api_status"}).success
        assert _observed(engine, "migrate") == "api_status"
    finally:
        client.close()


def test_config_placeholder_used_when_no_per_call_value(tmp_path):
    engine, migrations = _setup(tmp_path)
    (migrations / "V1__observe.py").write_text(V1_PY)

    client = DBLiftClient.from_sqlalchemy(
        engine,
        migrations_dir=migrations,
        config=_overlay(migrations, {"status_value": "config_status"}),
    )
    try:
        assert client.migrate().success
        assert _observed(engine, "migrate") == "config_status"
    finally:
        client.close()


def test_python_context_placeholders_match_the_sql_path_set(tmp_path):
    engine, migrations = _setup(tmp_path)
    (migrations / "V1__observe.py").write_text(V1_SYSTEM_PY)

    client = DBLiftClient.from_sqlalchemy(
        engine,
        migrations_dir=migrations,
        config=_overlay(migrations, {"config_only": "c"}),
    )
    try:
        assert client.migrate(placeholders={"per_call": "p"}).success
        keys = _observed(engine, "keys").split(",")
        # Same mapping the SQL path substitutes from.
        assert keys == sorted(client.executor.placeholder_service.placeholders)
        assert {"config_only", "per_call"} <= set(keys)
        assert {"dblift_schema", "dblift_username", "dblift_date"} <= set(keys)
    finally:
        client.close()
