"""Names the statement facts keep exactly as the engine does, one place per fact."""

import pytest

from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit


def _objects(dialect, sql):
    facts = ProviderRegistry.get_quirks(dialect).statement_facts(sql)
    return [(o.type.value, o.name, o.schema) for o in facts.affected_objects]


def test_an_oracle_name_may_hold_dollar_and_hash():
    assert _objects("oracle", "CREATE TABLE a$b#c (id NUMBER)") == [("TABLE", "A$B#C", None)]


def test_an_oracle_private_temporary_table_is_named():
    sql = "CREATE PRIVATE TEMPORARY TABLE ORA$PTT_T (id NUMBER) ON COMMIT DROP DEFINITION"
    assert _objects("oracle", sql) == [("TABLE", "ORA$PTT_T", None)]


def test_a_db2_index_takes_the_schema_it_is_created_in():
    assert _objects("db2", "CREATE INDEX s.i ON s.t (c)") == [("INDEX", "I", "S")]


@pytest.mark.parametrize(
    ("dialect", "sql", "expected"),
    [
        ("postgresql", 'CREATE TABLE "MixedCase" (id int)', "MixedCase"),
        ("redshift", 'CREATE TABLE "MixedCase" (id int)', "MixedCase"),
        ("db2", 'CREATE TABLE "MixedCase" (id int)', "MixedCase"),
        ("oracle", 'CREATE TABLE "MixedCase" (id int)', "MixedCase"),
        ("snowflake", 'CREATE TABLE "MixedCase" (id int)', "MixedCase"),
        ("sqlserver", "CREATE TABLE [MixedCase] (id int)", "MixedCase"),
        ("mysql", "CREATE TABLE `MixedCase` (id int)", "MixedCase"),
        ("mariadb", "CREATE TABLE `MixedCase` (id int)", "MixedCase"),
        ("postgresql", 'CREATE VIEW "MyView" AS SELECT 1', "MyView"),
        ("postgresql", 'DROP TABLE "Old"', "Old"),
    ],
)
def test_a_quoted_name_keeps_its_case(dialect, sql, expected):
    assert [name for _, name, _ in _objects(dialect, sql)] == [expected]


def test_reading_statement_facts_without_sqlglot_names_the_extra(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "sqlglot", None)
    monkeypatch.delitem(
        sys.modules, "dblift.core.sql_parser.sqlglot_statement_facts", raising=False
    )

    with pytest.raises(ModuleNotFoundError, match=r"pip install dblift\[analysis\]") as raised:
        ProviderRegistry.get_quirks("postgresql").statement_facts("SELECT 1")

    assert raised.value.name == "sqlglot"
