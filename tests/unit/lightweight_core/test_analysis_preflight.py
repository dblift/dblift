"""Required journal analysis must be ready before any migration write."""

from unittest.mock import Mock

import pytest

from dblift.core.exceptions import ParserNotAvailableError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.db.base_quirks import BaseQuirks
from dblift.db.dml_analysis import DmlMutation
from tests.unit.lightweight_core._support import run_python


def test_required_analysis_is_prepared_before_execution():
    provider = Mock()
    analyzer = Mock()
    analyzer.prepare_object_analysis.side_effect = ModuleNotFoundError("sqlglot")
    journal = Mock(
        spec=["record_statement_start", "record_statement_complete", "record_object_changes"]
    )
    service = SqlExecutionService(provider, analyzer, journal=journal)

    with pytest.raises(ModuleNotFoundError, match="sqlglot"):
        service.prepare_analysis()

    analyzer.prepare_object_analysis.assert_called_once_with()
    provider.execute_statement.assert_not_called()
    provider.execute_query.assert_not_called()
    journal.record_statement_start.assert_not_called()


def test_direct_statement_call_prepares_before_provider_or_journal():
    provider = Mock()
    provider.execute_statement.return_value = 1
    analyzer = Mock()
    analyzer.prepare_object_analysis.side_effect = ModuleNotFoundError("sqlglot")
    journal = Mock(
        spec=["record_statement_start", "record_statement_complete", "record_object_changes"]
    )
    service = SqlExecutionService(provider, analyzer, journal=journal)

    with pytest.raises(ModuleNotFoundError, match="sqlglot"):
        service.execute_statement("CREATE TABLE t (id INTEGER)")

    provider.execute_statement.assert_not_called()
    provider.execute_query.assert_not_called()
    journal.record_statement_start.assert_not_called()


def test_preparation_retries_after_failure_and_then_caches_success():
    analyzer = Mock()
    analyzer.prepare_object_analysis.side_effect = [ModuleNotFoundError("sqlglot"), None]
    journal = Mock(spec=["record_object_changes"])
    service = SqlExecutionService(Mock(), analyzer, journal=journal)

    with pytest.raises(ModuleNotFoundError, match="sqlglot"):
        service.prepare_analysis()
    service.prepare_analysis()
    service.prepare_analysis()
    assert analyzer.prepare_object_analysis.call_count == 2


def test_parser_preparation_exposes_missing_dependency_without_exception_cycle():
    dependency_error = ModuleNotFoundError("No module named 'driver_parser'", name="driver_parser")
    factory = Mock()
    factory.get_parser.side_effect = ParserNotAvailableError("parser unavailable")
    factory.get_parser.side_effect.__cause__ = dependency_error
    analyzer = SqlAnalyzer("sqlite", parser_factory=factory)

    with pytest.raises(ModuleNotFoundError) as raised:
        analyzer.prepare_object_analysis()

    assert raised.value is dependency_error
    assert raised.value.name == "driver_parser"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_parser_preparation_preserves_ordinary_unavailable_error():
    unavailable = ParserNotAvailableError("unsupported parser")
    factory = Mock()
    factory.get_parser.side_effect = unavailable
    analyzer = SqlAnalyzer("sqlite", parser_factory=factory)

    with pytest.raises(ParserNotAvailableError) as raised:
        analyzer.prepare_object_analysis()

    assert raised.value is unavailable


def test_opaque_factory_and_instance_dml_override_do_not_require_sqlglot(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def block_sqlglot(name, *args, **kwargs):
        if name.split(".")[0] == "sqlglot":
            raise ModuleNotFoundError("contract blocked: sqlglot", name="sqlglot")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_sqlglot)
    factory = object()  # No preparation protocol; the injected factory is opaque.
    analyzer = SqlAnalyzer("sqlite", parser_factory=factory)
    quirks = BaseQuirks()
    quirks.analyze_dml = lambda statement: None
    service = SqlExecutionService(
        Mock(), analyzer, journal=Mock(spec=["record_object_changes"]), quirks=quirks
    )

    service.prepare_analysis()
    assert analyzer.parser_factory is factory


def test_inherited_dml_requires_sqlglot_even_with_opaque_parser(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def block_sqlglot(name, *args, **kwargs):
        if name.split(".")[0] == "sqlglot":
            raise ModuleNotFoundError("contract blocked: sqlglot", name="sqlglot")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_sqlglot)
    service = SqlExecutionService(
        Mock(),
        SqlAnalyzer("sqlite", parser_factory=object()),
        journal=Mock(spec=["record_object_changes"]),
        quirks=BaseQuirks(),
    )
    with pytest.raises(ModuleNotFoundError, match="sqlglot"):
        service.prepare_analysis()


def test_complete_injected_parser_and_instance_dml_quirk_execute_without_sqlglot(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def block_sqlglot(name, *args, **kwargs):
        if name.split(".")[0] == "sqlglot":
            raise ModuleNotFoundError("contract blocked: sqlglot", name="sqlglot")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_sqlglot)

    class ExternalFactory:
        def get_parser(self):
            return self

        def extract_objects(self, statement, schema):
            return [{"object_name": "t", "object_type": "TABLE", "schema": schema}]

    provider = Mock()
    provider.execute_statement.return_value = 1
    journal = Mock(
        spec=["record_statement_start", "record_statement_complete", "record_object_changes"]
    )
    analyzer = SqlAnalyzer("sqlite", parser_factory=ExternalFactory())
    quirks = BaseQuirks()
    quirks.analyze_dml = lambda statement: DmlMutation("t", {"INSERT"}, [])
    service = SqlExecutionService(provider, analyzer, journal=journal, quirks=quirks)

    service.execute_statement("CREATE TABLE t (id INTEGER)", stmt_index=0)
    service.execute_statement("INSERT INTO t (id) VALUES (1)", stmt_index=1)

    assert provider.execute_statement.call_count == 2
    assert journal.record_statement_start.call_count == 2
    assert journal.record_statement_complete.call_count == 2
    assert journal.record_object_changes.call_count == 2
    assert [
        call.args[2][0]["object_name"] for call in journal.record_object_changes.call_args_list
    ] == ["t", "t"]


@pytest.mark.parametrize(
    "migrate_call",
    [
        "client.migrate()",
        "MigrateCommand(client.executor._make_command_context()).execute(migrations)",
    ],
)
def test_standard_client_missing_sqlglot_does_not_create_history_or_user_table(
    tmp_path, migrate_call
):
    result = run_python(
        f"""
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog
from dblift.core.migration.commands.migrate_command import MigrateCommand

db_path = Path('app.db')
migrations = Path('migrations')
migrations.mkdir()
(migrations / 'V1__create_t.sql').write_text('CREATE TABLE t (id INTEGER PRIMARY KEY);')
with sqlite3.connect(db_path) as observer:
    before = list(observer.execute("SELECT name FROM sqlite_master WHERE type='table'"))
engine = create_engine(f'sqlite:///{{db_path}}')
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog())
try:
    try:
        {migrate_call}
    except ModuleNotFoundError as exc:
        assert exc.name == 'sqlglot'
    else:
        raise AssertionError('missing required analysis did not fail')
finally:
    client.close()
    engine.dispose()
with sqlite3.connect(db_path) as observer:
    after = list(observer.execute("SELECT name FROM sqlite_master WHERE type='table'"))
assert after == before, (before, after)
""",
        blocked=("sqlglot",),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_validate_and_clean_without_sql_callbacks_do_not_require_analysis(tmp_path):
    result = run_python(
        """
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

migrations = Path('migrations')
migrations.mkdir()
engine = create_engine('sqlite:///app.db')
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog()) as client:
    assert client.validate().success
    assert client.clean(clean_enabled=True).success
engine.dispose()
""",
        blocked=("sqlglot",),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("callback", "command"),
    [
        ("beforeValidate__check.sql", "client.validate()"),
        ("beforeClean__check.sql", "client.clean(clean_enabled=True)"),
    ],
)
def test_sql_callback_preparation_precedes_command_writes(tmp_path, callback, command):
    result = run_python(
        f"""
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

migrations = Path('migrations')
migrations.mkdir()
(migrations / {callback!r}).write_text('CREATE TABLE callback_written (id INTEGER);')
db_path = Path('app.db')
with sqlite3.connect(db_path) as observer:
    before = list(observer.execute("SELECT name FROM sqlite_master WHERE type='table'"))
engine = create_engine(f'sqlite:///{{db_path}}')
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog())
try:
    try:
        {command}
    except ModuleNotFoundError as exc:
        assert exc.name == 'sqlglot'
    else:
        raise AssertionError('SQL callback dependency did not fail')
finally:
    client.close()
    engine.dispose()
with sqlite3.connect(db_path) as observer:
    after = list(observer.execute("SELECT name FROM sqlite_master WHERE type='table'"))
assert after == before, (before, after)
""",
        blocked=("sqlglot",),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_undo_missing_analysis_does_not_run_error_callback_or_change_database(tmp_path):
    seed = run_python(
        """
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

migrations = Path('migrations')
migrations.mkdir()
(migrations / 'V1__create_t.sql').write_text('CREATE TABLE t (id INTEGER);')
(migrations / 'U1__create_t.sql').write_text('DROP TABLE t;')
engine = create_engine('sqlite:///app.db')
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog()) as client:
    assert client.migrate().success
engine.dispose()
""",
        cwd=tmp_path,
    )
    assert seed.returncode == 0, seed.stderr
    failed = run_python(
        """
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

migrations = Path('migrations')
(migrations / 'afterUndoError__side_effect.sql').write_text('CREATE TABLE callback_written (id INTEGER);')
with sqlite3.connect('app.db') as observer:
    before = list(observer.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
engine = create_engine('sqlite:///app.db')
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog())
try:
    try:
        client.undo()
    except ModuleNotFoundError as exc:
        assert exc.name == 'sqlglot'
    else:
        raise AssertionError('undo dependency did not fail')
finally:
    client.close()
    engine.dispose()
with sqlite3.connect('app.db') as observer:
    after = list(observer.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
assert after == before, (before, after)
""",
        blocked=("sqlglot",),
        cwd=tmp_path,
    )
    assert failed.returncode == 0, failed.stderr
