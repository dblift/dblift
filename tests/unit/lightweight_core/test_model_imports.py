"""Import boundaries and compatibility for public core re-exports."""

from tests.unit.lightweight_core._support import run_python


def test_execution_contract_does_not_load_concrete_schema_models():
    run = run_python(
        """
import sys
from dblift.core.migration.sql.execution_contracts import ExecutionSqlParser
assert ExecutionSqlParser.__module__ == 'dblift.core.migration.sql.execution_contracts'
for name in ('table', 'view', 'index', 'trigger', 'procedure', 'sequence'):
    assert f'dblift.core.sql_model.{name}' not in sys.modules, name
""",
        blocked=("rich", "jinja2", "sqlglot"),
    )
    assert run.returncode == 0, run.stderr


def test_core_reexports_are_deferred_and_keep_canonical_identity():
    run = run_python("""
import importlib
import pickle
import sys

core = importlib.import_module('dblift.core')
model = importlib.import_module('dblift.core.sql_model')
migration = importlib.import_module('dblift.core.migration')
parser = importlib.import_module('dblift.core.sql_parser')
assert 'dblift.core.sql_model.table' not in sys.modules
assert 'dblift.core.migration.migration' not in sys.modules
assert 'dblift.core.sql_parser.parser_factory' not in sys.modules
for facade, names in ((core, ('Table', 'SqlObjectType')),
                      (model, ('Table', 'SqlObjectType', 'quote_identifier')),
                      (migration, ('Migration', 'is_versioned')),
                      (parser, ('SqlParserFactory',))):
    assert set(names) <= set(facade.__all__)
    assert set(names) <= set(dir(facade))
    for name in names:
        value = getattr(facade, name)
        assert getattr(facade, name) is value
        assert pickle.loads(pickle.dumps(value)) is value
        assert value.__module__ != facade.__name__
    try:
        getattr(facade, 'UnknownExport')
    except AttributeError:
        pass
    else:
        raise AssertionError(f'{facade.__name__} accepted an unknown name')

from dblift.core import Table as CoreTable
from dblift.core.sql_model import Table as ModelTable
from dblift.core.sql_model.table import Table as DefinedTable
assert CoreTable is ModelTable is DefinedTable
assert CoreTable.__module__ == 'dblift.core.sql_model.table'
assert issubclass(type('ChildTable', (CoreTable,), {}), DefinedTable)
table = CoreTable('users', schema='public', dialect='postgresql')
restored = pickle.loads(pickle.dumps(table))
assert type(restored) is CoreTable
assert (restored.name, restored.schema, restored.dialect) == ('users', 'public', 'postgresql')
from dblift.core.migration import Migration
from dblift.core.migration.migration import Migration as DefinedMigration
assert Migration is DefinedMigration
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser.parser_factory import SqlParserFactory as DefinedFactory
assert SqlParserFactory is DefinedFactory
""")
    assert run.returncode == 0, run.stderr


def test_reexports_work_when_definition_imports_first_and_with_import_star():
    run = run_python("""
from dblift.core.sql_model.table import Table as DefinedTable
from dblift.core.migration.migration import Migration as DefinedMigration
from dblift.core.sql_parser.parser_factory import SqlParserFactory as DefinedFactory
from dblift.core.sql_model import *
from dblift.core.migration import *
from dblift.core.sql_parser import *
assert Table is DefinedTable
assert Migration is DefinedMigration
assert SqlParserFactory is DefinedFactory
""")
    assert run.returncode == 0, run.stderr


def test_simultaneous_reexport_access_keeps_identity():
    run = run_python("""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import dblift.core as core
import dblift.core.sql_model as model
barrier = Barrier(8)
def read_export(i):
    barrier.wait()
    return getattr(core if i % 2 else model, 'Table')
with ThreadPoolExecutor(max_workers=8) as pool:
    values = list(pool.map(read_export, range(8)))
from dblift.core.sql_model.table import Table as DefinedTable
assert all(value is DefinedTable for value in values)
""")
    assert run.returncode == 0, run.stderr
