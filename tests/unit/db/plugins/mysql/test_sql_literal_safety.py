"""MySQL-generated SQL must keep caller strings as data under either escape mode."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.mysql.sqlalchemy_url import build_sqlalchemy_url


@pytest.mark.parametrize("owner", [MySqlProvider, MySqlSchemaOperations])
@pytest.mark.parametrize("value", ["quote'", "back\\slash'", "é漢", "x'; SELECT 123; -- ", ""])
def test_column_lookup_names_are_mode_independent_literals(owner, value):
    sql = owner.get_columns_query(None, value, value)
    literal = f"_utf8mb4 X'{value.encode('utf-8').hex()}'"
    assert f"TABLE_SCHEMA = {literal}" in sql
    assert f"TABLE_NAME = {literal}" in sql


@pytest.mark.parametrize(
    "value", ["quote'", "back\\slash'", "é漢", "x\\'; SET @escaped=1; -- ", ""]
)
def test_session_values_are_mode_independent_literals(value):
    config = SimpleNamespace(session_variables={"time_zone": value})
    sql = make_url(build_sqlalchemy_url(config)).query["init_command"]
    assert sql == f"SET SESSION time_zone=_utf8mb4 X'{value.encode('utf-8').hex()}'"


@pytest.mark.parametrize(
    "key", ["", "a=b, autocommit", "x; SELECT 1; --", "@@sql_mode", "a`b", "é", "1name"]
)
def test_session_variable_names_must_be_simple_identifiers(key):
    with pytest.raises(ValueError, match="session variable"):
        build_sqlalchemy_url(SimpleNamespace(session_variables={key: "1"}))


@pytest.mark.parametrize("value", ["1", "-1", "+1", "0.5", "1e3", " 28800 ", "28800\n"])
def test_numeric_session_values_keep_numeric_types(value):
    config = SimpleNamespace(session_variables={"wait_timeout": value})
    sql = make_url(build_sqlalchemy_url(config)).query["init_command"]
    assert sql == f"SET SESSION wait_timeout={value.strip()}"


@pytest.mark.parametrize("value", ["nan", "inf", "1_000"])
def test_python_float_syntax_is_not_inserted_as_sql(value):
    config = SimpleNamespace(session_variables={"wait_timeout": value})
    sql = make_url(build_sqlalchemy_url(config)).query["init_command"]
    assert sql == f"SET SESSION wait_timeout=_utf8mb4 X'{value.encode('utf-8').hex()}'"
