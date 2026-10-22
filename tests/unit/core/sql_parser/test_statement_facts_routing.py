"""Statement facts are read by the plugin that owns the statement, not by a dialect name."""

import ast
import pathlib
from unittest.mock import MagicMock

import pytest

import dblift
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_parser.statement_facts import StatementFacts
from dblift.db.dml_analysis import (
    analyze_dml,
    dml_where_predicate,
    is_full_table_dml,
    statement_dml_table,
    updates_restore_key,
)
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

UPDATE = "UPDATE zz SET a = 1 WHERE id = 1;"
DELETE = "DELETE FROM zz WHERE id = 1;"

ProviderRegistry.discover_plugins()
SQL_PLUGINS = sorted(
    p.name
    for p in ProviderRegistry.list_plugins()
    if ProviderRegistry.get_quirks(p.name).supports_sql_migrations
)
DERIVATIVES = ["cockroachdb", "mariadb", "db2"]


def reader_named(label, *, predicate="from_reader = 1"):
    class Reader:
        def __init__(self, dialect, spec=None):
            self.dialect = dialect

        def read(self, sql):
            return StatementFacts(
                "UPDATE",
                "DML",
                target=label,
                target_sql=label,
                predicate=predicate,
                events=frozenset({"UPDATE"}),
                affected_columns=("a",),
            )

    return Reader


def own_reader(monkeypatch, plugin, label="from_reader", **kwargs):
    quirks = ProviderRegistry.get_quirks(plugin)
    monkeypatch.setattr(type(quirks), "statement_facts_class", reader_named(label, **kwargs))
    return quirks


@pytest.mark.parametrize("plugin", SQL_PLUGINS)
def test_quirks_dml_entry_points_reach_the_plugin_reader(monkeypatch, plugin):
    quirks = own_reader(monkeypatch, plugin)

    assert quirks.analyze_dml(UPDATE).table == "from_reader"
    # the reader reports no predicate, so the reader says full-table where the text says not
    quirks = own_reader(monkeypatch, plugin, predicate=None)
    assert quirks.is_full_table_dml(DELETE) is True


@pytest.mark.parametrize("plugin", DERIVATIVES)
def test_every_dml_function_reaches_the_reader_through_quirks(monkeypatch, plugin):
    quirks = own_reader(monkeypatch, plugin)

    assert analyze_dml(UPDATE, quirks=quirks).table == "from_reader"
    assert dml_where_predicate(UPDATE, quirks=quirks) == "from_reader = 1"
    assert statement_dml_table(UPDATE, quirks=quirks) == "from_reader"
    assert updates_restore_key(UPDATE, ("a",), quirks=quirks) is True
    assert quirks.dml_where_predicate(UPDATE) == "from_reader = 1"
    assert quirks.statement_dml_table(UPDATE) == "from_reader"
    quirks = own_reader(monkeypatch, plugin, predicate=None)
    assert is_full_table_dml(DELETE, quirks=quirks) is True


@pytest.mark.parametrize("child", ["cockroachdb", "mariadb"])
def test_opted_out_plugin_gets_no_parent_facts(monkeypatch, child):
    child_quirks = ProviderRegistry.get_quirks(child)
    parent_quirks = ProviderRegistry.get_quirks(child_quirks.sqlglot_dialect)
    assert type(parent_quirks) is not type(child_quirks)
    parent_reader = reader_named("parent_reader", predicate=None)
    monkeypatch.setattr(type(parent_quirks), "statement_facts_class", parent_reader)
    monkeypatch.setattr(type(child_quirks), "statement_facts_class", None)

    assert not child_quirks.supports_statement_facts
    assert child_quirks.analyze_dml(UPDATE).table == "zz"
    assert child_quirks.is_full_table_dml(DELETE) is False
    assert statement_dml_table(UPDATE, quirks=child_quirks) == "zz"
    assert dml_where_predicate(DELETE, quirks=child_quirks) == "id = 1"


def test_execution_tracking_records_no_parent_target_after_opt_out(monkeypatch):
    child = ProviderRegistry.get_quirks("cockroachdb")
    parent = ProviderRegistry.get_quirks("postgres")
    monkeypatch.setattr(type(parent), "statement_facts_class", reader_named("parent_reader"))
    monkeypatch.setattr(type(child), "statement_facts_class", None)
    assert type(parent) is not type(child)
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, SqlAnalyzer("cockroachdb"), journal=journal, quirks=child
    )

    service.execute_statement(UPDATE)

    objects = journal.record_object_changes.call_args.args[2]
    assert [obj["object_name"] for obj in objects] == ["zz"]


def test_deprecated_dialect_keyword_routes_through_the_named_plugin(monkeypatch):
    own_reader(monkeypatch, "cockroachdb")

    with pytest.warns(DeprecationWarning, match="quirks="):
        assert statement_dml_table(UPDATE, dialect="cockroachdb") == "from_reader"
    with pytest.warns(DeprecationWarning, match="quirks="):
        assert dml_where_predicate(DELETE, sqlglot_dialect="postgres") == "id = 1"


def test_quirks_wins_over_a_deprecated_keyword(monkeypatch):
    quirks = own_reader(monkeypatch, "cockroachdb")

    with pytest.warns(DeprecationWarning, match="quirks="):
        mutation = analyze_dml(UPDATE, quirks=quirks, sqlglot_dialect="mysql")

    assert mutation.table == "from_reader"


FIVE = {
    "analyze_dml",
    "dml_where_predicate",
    "is_full_table_dml",
    "statement_dml_table",
    "updates_restore_key",
}


def routed_by_name(source):
    """Lines that call the five functions without ``quirks=`` (or with a dialect name),
    or look a plugin up by a sqlglot dialect name."""
    tree = ast.parse(source)
    aliases = {
        a.asname or a.name: a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
    }
    flagged = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        if isinstance(func, ast.Name):
            name = aliases.get(func.id, func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            name = func.attr if func.value.id in {"dml_analysis", "dml"} else None
        else:
            name = None
        if name in FIVE:
            keywords = {kw.arg for kw in call.keywords}
            if "quirks" not in keywords or keywords & {"sqlglot_dialect", "dialect"}:
                flagged.append(call.lineno)
            elif name == "statement_dml_table" and len(call.args) > 1:
                flagged.append(call.lineno)
        elif getattr(func, "attr", getattr(func, "id", "")) == "get_quirks":
            arg = call.args[0] if call.args else None
            if isinstance(arg, ast.Attribute) and arg.attr == "sqlglot_dialect":
                flagged.append(call.lineno)
    return flagged


def test_the_guard_flags_a_call_that_routes_by_name():
    assert routed_by_name("statement_dml_table(sql, dialect=name)") == [1]
    assert routed_by_name("analyze_dml(sql, sqlglot_dialect=name)") == [1]
    assert routed_by_name("analyze_dml(sql, quirks=q, sqlglot_dialect=name)") == [1]
    assert routed_by_name("statement_dml_table(sql, name, quirks=q)") == [1]
    assert routed_by_name("analyze_dml(sql, quirks=q)") == []
    assert routed_by_name("q.analyze_dml(sql)") == []
    assert routed_by_name("dml_analysis.analyze_dml(sql, sqlglot_dialect=n)") == [1]
    assert routed_by_name("from m import analyze_dml as a\na(sql)") == [2]
    assert routed_by_name("R.get_quirks(q.sqlglot_dialect).statement_facts(s)") == [1]
    assert routed_by_name("R.get_quirks(name)") == []


def test_no_src_caller_routes_facts_by_name():
    root = pathlib.Path(dblift.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path == root / "db" / "dml_analysis.py":
            continue
        for line in routed_by_name(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(root)}:{line}")
    assert offenders == []


def test_dml_analysis_looks_a_plugin_up_by_name_only_for_the_deprecated_keywords():
    root = pathlib.Path(dblift.__file__).parent
    tree = ast.parse((root / "db" / "dml_analysis.py").read_text(encoding="utf-8"))
    lookups = []
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get_quirks":
                lookups.append(func.name)
    assert lookups == ["_quirks_for"]


def test_undo_strategy_follows_the_quirks_flag(monkeypatch):
    from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
    from dblift.db.plugins.sqlite.quirks import SqliteQuirks

    migration = make_migration(script_name="V1__t.sql", content="CREATE TABLE t (id INT);")
    other = ProviderRegistry.get_quirks("duckdb")
    monkeypatch.setattr(type(other), "sqlglot_dialect", "sqlite")

    undo = UndoScriptGenerator("duckdb")._generate_undo_statements(migration)

    assert [s.requires_manual_review for s in undo] == [True]
    assert SqliteQuirks.undo_reverses_statement_facts is True
    sqlite_undo = UndoScriptGenerator("sqlite")._generate_undo_statements(migration)
    assert [s.sql for s in sqlite_undo] == ['DROP TABLE IF EXISTS "t";']


def test_deprecated_keyword_naming_no_plugin_keeps_the_sqlglot_grammar():
    bigquery = "UPDATE `s`.`t` SET a = 1 WHERE b = 2"
    with pytest.warns(DeprecationWarning):
        assert analyze_dml(bigquery, sqlglot_dialect="bigquery").table == "s.t"
    with pytest.warns(DeprecationWarning):
        assert dml_where_predicate(bigquery, sqlglot_dialect="spark") == "b = 2"
    with pytest.warns(DeprecationWarning):
        assert (
            statement_dml_table("WITH x AS (SELECT 1) UPDATE t SET a = 1", dialect="trino") == "t"
        )
