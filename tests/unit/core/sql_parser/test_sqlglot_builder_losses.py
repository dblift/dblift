"""SQL-file models retain metadata already present in sqlglot's AST."""

import pytest

from dblift.core.sql_model.base import ConstraintType
from dblift.core.sql_parser import SqlParserFactory
from tests.support.legacy_sqlserver_parsers import legacy_sqlserver_hybrid

pytestmark = pytest.mark.unit
DIALECTS = ("oracle", "sqlserver")


def _model_parser(dialect):
    return (
        legacy_sqlserver_hybrid()
        if dialect == "sqlserver"
        else SqlParserFactory(dialect).get_parser()
    )


@pytest.mark.parametrize(
    "dialect, definition, stored",
    [
        ("sqlserver", "f AS (a + 1) PERSISTED", True),
        ("sqlserver", "f AS (a + 1)", False),
    ],
)
def test_generated_column_keeps_expression_and_storage(dialect, definition, stored):
    result = _model_parser(dialect).parse_sql(
        f"CREATE TABLE t (id INT PRIMARY KEY, a INT, {definition})"
    )
    assert result.success
    column = result.tables[0].columns[2]
    assert column.is_computed is True
    assert column.computed_expression == "(a + 1)"
    assert column.computed_stored is stored


@pytest.mark.parametrize("dialect", DIALECTS)
def test_plain_column_is_not_computed(dialect):
    result = _model_parser(dialect).parse_sql("CREATE TABLE t (a INT)")
    column = result.tables[0].columns[0]
    assert column.is_computed is False
    assert column.computed_expression is None
    assert column.computed_stored is False


@pytest.mark.parametrize("dialect", DIALECTS)
def test_plain_index_key_is_not_an_expression(dialect):
    result = _model_parser(dialect).parse_sql("CREATE INDEX ix ON t (a)")
    assert result.indexes[0].columns == ["a"]
    assert result.indexes[0].expression_flags == [False]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "keys, directions",
    [
        ("a DESC, id ASC", ["DESC", "ASC"]),
        ("a, id", []),
        ("a ASC, id ASC", ["ASC", "ASC"]),
        ("a DESC, id", ["DESC", ""]),
        ("a, id DESC", ["", "DESC"]),
        ("a, id ASC", ["", "ASC"]),
    ],
)
def test_index_keeps_key_sort_directions(dialect, keys, directions):
    result = _model_parser(dialect).parse_sql(f"CREATE INDEX ix ON t ({keys})")
    assert result.indexes[0].sort_directions == directions


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize(
    "actions, on_delete, on_update",
    [
        ("ON DELETE CASCADE ON UPDATE SET NULL", "CASCADE", "SET NULL"),
        ("ON UPDATE CASCADE ON DELETE NO ACTION", "NO ACTION", "CASCADE"),
    ],
)
def test_foreign_key_keeps_referential_actions(dialect, inline, actions, on_delete, on_update):
    definition = (
        f"pid INT REFERENCES p(id) {actions}"
        if inline
        else f"pid INT, CONSTRAINT fk FOREIGN KEY (pid) REFERENCES p(id) {actions}"
    )
    result = _model_parser(dialect).parse_sql(f"CREATE TABLE t ({definition})")
    fk = next(
        c for c in result.tables[0].constraints if c.constraint_type == ConstraintType.FOREIGN_KEY
    )
    assert fk.on_delete == on_delete
    assert fk.on_update == on_update


@pytest.mark.parametrize("dialect", DIALECTS)
def test_foreign_key_without_actions_keeps_none(dialect):
    result = _model_parser(dialect).parse_sql(
        "CREATE TABLE t (pid INT, CONSTRAINT fk FOREIGN KEY (pid) REFERENCES p(id))"
    )
    fk = next(
        c for c in result.tables[0].constraints if c.constraint_type == ConstraintType.FOREIGN_KEY
    )
    assert fk.on_delete is None
    assert fk.on_update is None


@pytest.mark.parametrize("quote_left, quote_right", [("`", "`"), ('"', '"'), ("[", "]")])
@pytest.mark.parametrize("qualified", [False, True])
def test_trigger_header_accepts_quoted_identifiers(quote_left, quote_right, qualified):
    parser = legacy_sqlserver_hybrid()
    table = f"{quote_left}t{quote_right}"
    if qualified:
        table = f"{quote_left}s{quote_right}.{table}"
    match = parser._parse_trigger_header(
        f"CREATE TRIGGER {quote_left}s{quote_right}.{quote_left}trg{quote_right} "
        f"BEFORE INSERT ON {table} FOR EACH ROW SET NEW.a = 3"
    )
    assert match is not None
    header = parser._parse_trigger_match(match, default_schema=None)
    assert header.name == "trg"
    assert header.schema == "s"
    assert header.table_name == "t"
