"""Ordinary client construction is silent and execution-only; full analysis is opt-in."""

import inspect

import pytest

from dblift.api import DBLiftClient, _client_factory
from dblift.api.async_client import AsyncDBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.executor.migration_executor import MigrationExecutor
from tests.unit.lightweight_core._support import run_python

ENTRY_POINTS = [
    _client_factory.client_from_config,
    _client_factory.client_from_config_file,
    _client_factory.client_from_sqlalchemy,
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


def _migrate_with(tmp_path, build):
    migrations = _migrations(tmp_path)
    with build(migrations) as client:
        assert client.migrate().success


@pytest.mark.parametrize("argument", ["log_level", "log_format"])
def test_ctor_logging_argument_turns_logging_on(tmp_path, capfd, argument):
    from sqlalchemy import create_engine

    from dblift.core.logger import NullLog

    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    try:
        seed = DBLiftClient.from_sqlalchemy(
            engine, migrations_dir=_migrations(tmp_path), logger=NullLog()
        )
        value = {"log_level": "info", "log_format": "text"}[argument]
        client = DBLiftClient(
            seed.provider, seed.config.migrations.directory, config=seed.config, **{argument: value}
        )
        with client:
            assert client.migrate().success
    finally:
        engine.dispose()
    assert capfd.readouterr().err != ""


@pytest.mark.parametrize("argument", ["log_level", "log_format"])
def test_from_sqlalchemy_logging_argument_turns_logging_on(tmp_path, capfd, argument):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    value = {"log_level": "debug", "log_format": "text"}[argument]
    try:
        _migrate_with(
            tmp_path,
            lambda m: DBLiftClient.from_sqlalchemy(engine, migrations_dir=m, **{argument: value}),
        )
    finally:
        engine.dispose()
    assert capfd.readouterr().err != ""


@pytest.mark.parametrize("key", ["log_level", "log_format"])
def test_config_logging_setting_turns_logging_on(tmp_path, capfd, key):
    config = _config(tmp_path)
    setattr(config, key, {"log_level": "info", "log_format": "text"}[key])
    _migrate_with(tmp_path, lambda m: DBLiftClient.from_config(config, migrations_dir=m))
    assert capfd.readouterr().err != ""


def test_config_logging_level_section_turns_logging_on(tmp_path, capfd):
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite"), "schema": "main"},
            "logging": {"level": "debug"},
        }
    )
    _migrate_with(tmp_path, lambda m: DBLiftClient.from_config(config, migrations_dir=m))
    assert capfd.readouterr().err != ""


def test_explicit_logger_is_used(tmp_path):
    class Recorder(NullLog):
        def __init__(self):
            self.messages = []

        def info(self, message, *args, **kwargs):
            self.messages.append(message)

    recorder = Recorder()
    _migrate_with(
        tmp_path,
        lambda m: DBLiftClient.from_config(_config(tmp_path), migrations_dir=m, logger=recorder),
    )
    assert recorder.messages


def _spy_side_effects(monkeypatch):
    """Record every side effect that must not happen before the sqlglot check."""
    import sys

    from dblift.api import client as client_module
    from dblift.db.provider_registry import ProviderRegistry

    calls = []
    monkeypatch.setitem(sys.modules, "sqlglot", None)  # import sqlglot -> ImportError
    for owner, name in (
        (ProviderRegistry, "create_provider"),
        (client_module, "load_feature_extensions"),
        (MigrationExecutor, "_make_command_context"),
    ):
        original = getattr(owner, name)

        def spy(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, name, spy)
    return calls


def test_client_from_config_checks_sqlglot_before_building_a_provider(tmp_path, monkeypatch):
    calls = _spy_side_effects(monkeypatch)
    with pytest.raises(ModuleNotFoundError, match=r"dblift\[analysis\]"):
        _client_factory.client_from_config(_config(tmp_path), analysis_mode="full")
    assert calls == []


def test_client_from_config_file_checks_sqlglot_before_reading_the_file(tmp_path, monkeypatch):
    from dblift.config.config_builder import ConfigBuilder

    calls = _spy_side_effects(monkeypatch)
    monkeypatch.setattr(ConfigBuilder, "build", lambda *a, **k: calls.append("build"))
    with pytest.raises(ModuleNotFoundError, match=r"dblift\[analysis\]"):
        _client_factory.client_from_config_file(str(tmp_path / "x.yml"), analysis_mode="full")
    assert calls == []


def test_constructor_checks_sqlglot_before_loading_features(tmp_path, monkeypatch):
    seed = DBLiftClient.from_config(_config(tmp_path), migrations_dir=_migrations(tmp_path))
    calls = _spy_side_effects(monkeypatch)
    with pytest.raises(ModuleNotFoundError, match=r"dblift\[analysis\]"):
        DBLiftClient(
            seed.provider,
            seed.config.migrations.directory,
            config=seed.config,
            analysis_mode="full",
        )
    assert calls == []
    seed.close()


def test_executor_checks_sqlglot_before_building_components(tmp_path, monkeypatch):
    from dblift.core.migration.sql import statement_reader as sql_analyzer

    seed = DBLiftClient.from_config(_config(tmp_path), migrations_dir=_migrations(tmp_path))
    built = []
    original = sql_analyzer.StatementReader.__init__

    def spy(self, *args, **kwargs):
        built.append(1)
        original(self, *args, **kwargs)

    monkeypatch.setattr(sql_analyzer.StatementReader, "__init__", spy)
    import sys

    monkeypatch.setitem(sys.modules, "sqlglot", None)
    with pytest.raises(ModuleNotFoundError, match=r"dblift\[analysis\]"):
        MigrationExecutor(seed.provider, seed.config, NullLog(), analysis_mode="full")
    assert built == []
    seed.close()


@pytest.mark.parametrize(("configured", "expected"), [("error", "ERROR"), ("debug", "DEBUG")])
def test_config_logging_level_is_honoured(tmp_path, configured, expected):
    from dblift.core.logger import LogLevel

    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite"), "schema": "main"},
            "logging": {"level": configured},
        }
    )
    with DBLiftClient.from_config(config, migrations_dir=_migrations(tmp_path)) as client:
        assert client.logger.level == LogLevel[expected]
