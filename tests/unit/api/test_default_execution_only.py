"""Ordinary client construction is silent and execution-only; full analysis is opt-in."""

import inspect

import pytest

from dblift.api import DBLiftClient
from dblift.api.async_client import AsyncDBLiftClient
from dblift.config import DbliftConfig
from dblift.core.migration.executor.migration_executor import MigrationExecutor
from tests.unit.lightweight_core._support import run_python

ENTRY_POINTS = [
    DBLiftClient.__init__,
    DBLiftClient.from_config,
    DBLiftClient.from_config_file,
    DBLiftClient.from_sqlalchemy,
    AsyncDBLiftClient.from_config,
    AsyncDBLiftClient.from_config_file,
    AsyncDBLiftClient.from_sqlalchemy,
    MigrationExecutor.__init__,
]


@pytest.mark.parametrize("fn", ENTRY_POINTS, ids=lambda f: f.__qualname__)
def test_analysis_mode_defaults_to_execution(fn):
    assert inspect.signature(fn).parameters["analysis_mode"].default == "execution"


def _config(tmp_path):
    return DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite"), "schema": "main"}}
    )


def _migrations(tmp_path):
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "V1__create.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    return migrations


def test_default_clients_are_execution_mode_and_silent(tmp_path, capfd):
    from sqlalchemy import create_engine

    migrations = _migrations(tmp_path)
    config_file = tmp_path / "dblift.yml"
    config_file.write_text(
        f"database:\n  type: sqlite\n  path: {tmp_path / 'file.db'}\n  schema: main\n"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'engine.db'}")
    try:
        clients = [
            DBLiftClient.from_config(_config(tmp_path), migrations_dir=migrations),
            DBLiftClient.from_config_file(str(config_file), migrations_dir=migrations),
            DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations),
        ]
        for client in clients:
            with client:
                assert client.analysis_mode == "execution"
                assert client.executor.analysis_mode == "execution"
                assert client.migrate().success
                assert client.validate().success
    finally:
        engine.dispose()
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_default_client_never_imports_analysis_packages(tmp_path):
    result = run_python(
        """
import warnings
warnings.simplefilter('error')
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient

root = Path('.')
migrations = root / 'sql'
migrations.mkdir()
(migrations / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
engine = create_engine('sqlite:///:memory:')
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations) as client:
    assert client.analysis_mode == 'execution'
    assert client.migrate().success
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_explicit_full_keeps_analysis(tmp_path):
    migrations = _migrations(tmp_path)
    with DBLiftClient.from_config(
        _config(tmp_path), migrations_dir=migrations, analysis_mode="full"
    ) as client:
        assert client.analysis_mode == "full"
        pending = next(m for m in client.info().migrations if m.script == "V1__create.sql")
        assert pending.analysis.get("status") != "disabled"


def test_explicit_full_without_sqlglot_fails_before_connection_or_callback(tmp_path):
    result = run_python(
        """
from pathlib import Path
from sqlalchemy import create_engine, event
from dblift.api import DBLiftClient

root = Path('.')
migrations = root / 'sql'
migrations.mkdir()
marker = root / 'callback-ran'
(migrations / 'beforeMigrate__spy.py').write_text(
    "from pathlib import Path\\n"
    "def migrate(context):\\n"
    f"    Path({str(marker)!r}).write_text('ran')\\n"
)
(migrations / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
engine = create_engine('sqlite:///:memory:')
connects = []
event.listen(engine, 'connect', lambda *a: connects.append(1))

def build():
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, analysis_mode='full')

try:
    client = build()
    client.migrate()
except ImportError as exc:
    assert 'dblift[analysis]' in str(exc), str(exc)
else:
    raise AssertionError('explicit full without sqlglot must fail')
assert not marker.exists(), 'callback ran'
assert not connects, 'connection opened'
""",
        blocked=("sqlglot",),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
