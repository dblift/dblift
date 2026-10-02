"""SQL-file models retain metadata already present in sqlglot's AST."""

import pytest

from dblift.core.sql_model.base import ConstraintType
from dblift.core.sql_parser import SqlParserFactory

pytestmark = pytest.mark.unit
DIALECTS = ("mysql", "mariadb", "postgresql", "sqlserver")


@pytest.mark.parametrize(
    "dialect, definition, stored",
    [
        ("mysql", "f INT AS (a + 1) STORED", True),
        ("mariadb", "f INT AS (a + 1) STORED", True),
        ("mysql", "f INT AS (a + 1) VIRTUAL", False),
        ("mysql", "f INT AS (a + 1)", False),
        ("postgresql", "f INT GENERATED ALWAYS AS (a + 1) STORED", True),
        ("sqlserver", "f AS (a + 1) PERSISTED", True),
        ("sqlserver", "f AS (a + 1)", False),
    ],
)
def test_generated_column_keeps_expression_and_storage(dialect, definition, stored):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(f"CREATE TABLE t (id INT PRIMARY KEY, a INT, {definition})")
    )
    assert result.success
    column = result.tables[0].columns[2]
    assert column.is_computed is True
    assert column.computed_expression == "(a + 1)"
    assert column.computed_stored is stored


@pytest.mark.parametrize("dialect", DIALECTS)
def test_plain_column_is_not_computed(dialect):
    result = SqlParserFactory(dialect).get_parser().parse_sql("CREATE TABLE t (a INT)")
    column = result.tables[0].columns[0]
    assert column.is_computed is False
    assert column.computed_expression is None
    assert column.computed_stored is False


@pytest.mark.parametrize(
    "dialect, key, expression",
    [
        ("mysql", "(a + 1)", "(a + 1)"),
        ("mariadb", "(a + 1)", "(a + 1)"),
        ("postgresql", "(lower(x))", "(LOWER(x))"),
        ("postgresql", "(lower(t.x))", "(LOWER(t.x))"),
        ("mysql", "(a + 1.5)", "(a + 1.5)"),
    ],
)
def test_functional_index_marks_expression_and_preserves_sql(dialect, key, expression):
    result = SqlParserFactory(dialect).get_parser().parse_sql(f"CREATE INDEX ix ON t ({key}, id)")
    assert result.success
    index = result.indexes[0]
    assert index.expression_flags == [True, False]
    assert index.columns == [expression, "id"]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_plain_index_key_is_not_an_expression(dialect):
    result = SqlParserFactory(dialect).get_parser().parse_sql("CREATE INDEX ix ON t (a)")
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
    result = SqlParserFactory(dialect).get_parser().parse_sql(f"CREATE INDEX ix ON t ({keys})")
    assert result.indexes[0].sort_directions == directions


@pytest.mark.parametrize("method", ["btree", "gin", "hash"])
def test_postgresql_index_without_explicit_direction_keeps_empty_sort_directions(method):
    result = (
        SqlParserFactory("postgresql")
        .get_parser()
        .parse_sql(f"CREATE INDEX ix ON t USING {method} (a)")
    )
    assert len(result.indexes) == 1
    assert result.indexes[0].sort_directions == []


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
    result = SqlParserFactory(dialect).get_parser().parse_sql(f"CREATE TABLE t ({definition})")
    fk = next(
        c for c in result.tables[0].constraints if c.constraint_type == ConstraintType.FOREIGN_KEY
    )
    assert fk.on_delete == on_delete
    assert fk.on_update == on_update


@pytest.mark.parametrize("dialect", DIALECTS)
def test_foreign_key_without_actions_keeps_none(dialect):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql("CREATE TABLE t (pid INT, CONSTRAINT fk FOREIGN KEY (pid) REFERENCES p(id))")
    )
    fk = next(
        c for c in result.tables[0].constraints if c.constraint_type == ConstraintType.FOREIGN_KEY
    )
    assert fk.on_delete is None
    assert fk.on_update is None


@pytest.mark.parametrize(
    "dialect, table, body",
    [
        ("mysql", "t", "SET NEW.a = 3"),
        ("mysql", "`t`", "SET NEW.a = 3"),
        ("mariadb", "t", "SET NEW.a = 3"),
        ("mariadb", "`t`", "SET NEW.a = 3"),
        ("postgresql", "t", "EXECUTE FUNCTION audit()"),
        ("postgresql", '"t"', "EXECUTE FUNCTION audit()"),
    ],
)
def test_trigger_on_unqualified_table_is_preserved(dialect, table, body):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(f"CREATE TRIGGER trg BEFORE INSERT ON {table} FOR EACH ROW {body};")
    )
    assert len(result.triggers) == 1
    trigger = result.triggers[0]
    assert trigger.name == "trg"
    assert trigger.table_name == "t"
    assert trigger.timing == "BEFORE"
    assert trigger.events == ["INSERT"]
    assert trigger.definition == body


@pytest.mark.parametrize("dialect", ["mysql", "mariadb", "postgresql"])
def test_trigger_on_qualified_table_still_parses(dialect):
    body = "EXECUTE FUNCTION audit()" if dialect == "postgresql" else "SET NEW.a = 3"
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(f"CREATE TRIGGER s.trg BEFORE INSERT ON s.t FOR EACH ROW {body};")
    )
    assert len(result.triggers) == 1
    assert result.triggers[0].name == "trg"
    assert result.triggers[0].schema == "s"
    assert result.triggers[0].table_name == "t"


@pytest.mark.parametrize("quote_left, quote_right", [("`", "`"), ('"', '"'), ("[", "]")])
@pytest.mark.parametrize("qualified", [False, True])
def test_trigger_header_accepts_quoted_identifiers(quote_left, quote_right, qualified):
    parser = SqlParserFactory("mysql").get_parser()
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


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_trigger_keeps_entire_compound_body(dialect):
    body = "BEGIN SET NEW.a = 3; SET NEW.id = 1; END"
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(
            f"CREATE TRIGGER trg BEFORE INSERT ON s.t FOR EACH ROW {body};\n"
            "CREATE TABLE following (id INT);"
        )
    )
    assert result.triggers[0].definition == body
    assert result.tables[0].name == "following"


def test_postgresql_trigger_body_keeps_semicolon_in_argument():
    result = (
        SqlParserFactory("postgresql")
        .get_parser()
        .parse_sql(
            "CREATE TRIGGER trg BEFORE INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION audit('a;b');"
        )
    )
    assert result.triggers[0].definition == "EXECUTE FUNCTION audit('a;b')"
