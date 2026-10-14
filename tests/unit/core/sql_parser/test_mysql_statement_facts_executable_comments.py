"""Preparatory MySQL-family facts must not discard potentially executable SQL."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject, SqlglotStatementFactsReader
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks


@pytest.mark.parametrize("marker", ["/*!", "/*M!"])
@pytest.mark.parametrize("version", ["", "50000", "100500", "999999"])
@pytest.mark.parametrize(
    "sql",
    [
        "{comment} DELETE FROM items */",
        "UPDATE items SET a=1 {comment} , b=2 */ WHERE id=3",
        "INSERT INTO items (a) VALUES (1) {comment} ON DUPLICATE KEY UPDATE a=2 */",
        "DELETE FROM items {comment} WHERE id=3 */",
        "CREATE TABLE items (a INT {comment} , b INT */)",
        "ALTER TABLE items ADD a INT {comment} , ADD b INT */",
        "DROP TABLE items {comment} , logs */",
        "SELECT * FROM items {comment} JOIN logs USING (id) */",
        "SELECT 1 --x {comment} + 2 */",
        "SELECT 1 # ignored\n{comment} + 2 */",
        "SELECT 1 -- ignored\n{comment} + 2 */",
        "SELECT 'literal' {comment} + 2 */",
        "SELECT `a\\` FROM items {comment} JOIN logs USING (id) */",
    ],
)
def test_mysql_executable_comments_do_not_expose_partial_facts(marker, version, sql):
    facts = SqlglotStatementFactsReader("mysql").read(sql.format(comment=marker + version))

    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None
    assert facts.operation == "UNKNOWN"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.predicate is None
    assert facts.declared_columns == ()
    assert facts.declared_constraints == ()
    assert facts.affected_columns == ()
    assert facts.events is None


@pytest.mark.parametrize("marker", ["/*!", "/*M!"])
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT '{marker}50000 FROM logs */' FROM items",
        'SELECT "{marker}50000 FROM logs */" FROM items',
        "SELECT 'it''s {marker}50000 FROM logs */' FROM items",
        'SELECT "a""b {marker}50000 FROM logs */" FROM items',
        r"SELECT 'it\'s {marker}50000 FROM logs */' FROM items",
        r'SELECT "a\"b {marker}50000 FROM logs */" FROM items',
        "SELECT `{marker}50000 logs */` FROM items",
        "SELECT `a``{marker}50000 logs */` FROM items",
        "SELECT * FROM items /* ordinary {marker}50000 FROM logs */",
        "SELECT * FROM items -- {marker}50000 FROM logs */",
        "SELECT * FROM items --\t{marker}50000 FROM logs */",
        "SELECT * FROM items #{marker}50000 FROM logs */",
    ],
)
def test_mysql_markers_in_literals_identifiers_and_plain_comments_are_not_executable(marker, sql):
    facts = SqlglotStatementFactsReader("mysql").read(sql.format(marker=marker))

    assert not facts.opaque
    assert facts.operation == "SELECT"
    assert facts.kind == "QUERY"
    assert facts.objects == (NamedObject("items", SqlObjectType.TABLE, "referenced"),)


# LF ends the comment immediately; the remaining ASCII controls and space keep it open.
_LINE_COMMENT_SEPARATORS = [chr(code) for code in (*range(1, 10), *range(11, 33), 127)]


@pytest.mark.parametrize("separator", _LINE_COMMENT_SEPARATORS, ids=repr)
@pytest.mark.parametrize("marker", ["/*!", "/*M!"])
def test_mysql_control_character_comment_hides_inactive_marker(separator, marker):
    facts = SqlglotStatementFactsReader("mysql").read(
        f"UPDATE items SET a=1 --{separator}{marker}50000 , b=2 */"
    )

    assert not facts.opaque
    assert facts.target == "items"
    assert facts.affected_columns == ("a",)
    assert facts.events == frozenset({"UPDATE"})


@pytest.mark.parametrize("separator", _LINE_COMMENT_SEPARATORS, ids=repr)
@pytest.mark.parametrize("marker", ["/*!", "/*M!"])
def test_mysql_quote_in_control_character_comment_does_not_hide_active_marker(separator, marker):
    facts = SqlglotStatementFactsReader("mysql").read(
        f"UPDATE items SET a=1 --{separator}'\n{marker}50000 , b=2 */"
    )

    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None
    assert facts.operation == "UNKNOWN"
    assert facts.kind == "UNKNOWN"
    assert facts.objects == ()
    assert facts.target is None
    assert facts.affected_columns == ()
    assert facts.events is None


@pytest.mark.parametrize("dialect", ["sqlite", "postgres", "duckdb", "oracle", "tsql"])
@pytest.mark.parametrize("marker", ["/*!", "/*M!"])
def test_mysql_comment_guard_preserves_other_dialect_facts(dialect, marker):
    facts = SqlglotStatementFactsReader(dialect).read(
        f"UPDATE items SET a=1 {marker}50000 , b=2 */ WHERE id=3"
    )

    assert not facts.opaque
    assert facts.target == "items"
    assert facts.affected_columns == ("a",)
    assert facts.events == frozenset({"UPDATE"})


@pytest.mark.parametrize("quirks", [MysqlQuirks, MariadbQuirks])
def test_mysql_family_statement_facts_hooks_remain_inactive(quirks):
    assert not quirks().supports_statement_facts
