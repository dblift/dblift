"""Preparatory MySQL-family facts must not discard potentially executable SQL."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject, SqlglotStatementFactsReader
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks

# Openers whose text runs on some supported servers and not on others, or that no supported
# server reads at all, so the reader cannot say what the statement does.
_UNRESOLVED_OPENERS = [
    "/*!50700",
    "/*!50701",
    "/*!80000",
    "/*!99999",
    "/*!100500",
    "/*!999999",
    "/*!5000",
    "/*!5",
    "/*M!",
    "/*M!50000",
    "/*M!100500",
    "/*M!999999",
]
# Openers whose text runs on every supported server (see the measurements below).
_GUARANTEED_OPENERS = [
    "/*!",
    "/*!00000",
    "/*!32312",
    "/*!40101",
    "/*!50000",
    "/*!50001",
    "/*!50699",
]

_STATEMENT_TEMPLATES = [
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
]


@pytest.mark.parametrize("opener", _UNRESOLVED_OPENERS)
@pytest.mark.parametrize("sql", _STATEMENT_TEMPLATES)
def test_mysql_executable_comments_do_not_expose_partial_facts(opener, sql):
    facts = SqlglotStatementFactsReader("mysql").read(sql.format(comment=opener))

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


# Each statement with the text of its executable comments kept, and the same statement as the
# server reads it (the comment markers removed, the content kept).
_SERVER_VIEWS = [
    ("{comment} DELETE FROM items */", "DELETE FROM items"),
    ("UPDATE items SET a=1 {comment} , b=2 */ WHERE id=3", "UPDATE items SET a=1 , b=2 WHERE id=3"),
    (
        "INSERT INTO items (a) VALUES (1) {comment} ON DUPLICATE KEY UPDATE a=2 */",
        "INSERT INTO items (a) VALUES (1) ON DUPLICATE KEY UPDATE a=2",
    ),
    ("DELETE FROM items {comment} WHERE id=3 */", "DELETE FROM items WHERE id=3"),
    ("CREATE TABLE items (a INT {comment} , b INT */)", "CREATE TABLE items (a INT , b INT )"),
    (
        "ALTER TABLE items ADD a INT {comment} , ADD b INT */",
        "ALTER TABLE items ADD a INT , ADD b INT",
    ),
    ("DROP TABLE items {comment} , logs */", "DROP TABLE items , logs"),
    (
        "SELECT * FROM items {comment} JOIN logs USING (id) */",
        "SELECT * FROM items JOIN logs USING (id)",
    ),
    ("SELECT 'literal' {comment} + 2 */", "SELECT 'literal' + 2"),
    ("SELECT 1 # ignored\n{comment} + 2 */", "SELECT 1 # ignored\n + 2"),
]


@pytest.mark.parametrize("opener", _GUARANTEED_OPENERS)
@pytest.mark.parametrize(("sql", "as_the_server_reads_it"), _SERVER_VIEWS)
def test_mysql_executable_comment_that_runs_everywhere_is_read_as_the_server_reads_it(
    opener, sql, as_the_server_reads_it
):
    """Measured 2026-10-24 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8 (``SET @a = 1`` inside the
    comment, then ``SELECT @a``): ``/*! … */``, ``/*!00000 … */``, ``/*!01000 … */``,
    ``/*!32312 … */`` and every ``/*!NNNNN … */`` from 50000 to 50699 tried (see the boundary
    test) ran on all three. The reader therefore reads the statement without the markers."""
    facts = SqlglotStatementFactsReader("mysql").read(sql.format(comment=opener))
    plain = SqlglotStatementFactsReader("mysql").read(as_the_server_reads_it)

    assert not facts.opaque
    assert facts == plain


def test_mysql_executable_comment_boundary_is_the_lowest_version_a_server_stops_running():
    """Bisected 2026-10-24 (``SET @a = NULL``; ``/*!NNNNN SET @a = 1 */``; ``SELECT @a``):
    MariaDB 11.8.8 sets ``@a`` for 50000, 50100, 50300, 50500, 50600, 50601, 50606, 50612,
    50625, 50650, 50660, 50670, 50690 and 50699, and leaves it NULL for 50700, 50701 and 80000.
    MySQL 8.0.46 and 8.4.11 set it for every one of those and stop above their own version
    (99999 leaves it NULL). The floor is therefore 50700, MariaDB's."""
    reader = SqlglotStatementFactsReader("mysql")

    assert not reader.read("/*!50699 DELETE FROM items */").opaque
    assert reader.read("/*!50700 DELETE FROM items */").opaque


@pytest.mark.parametrize(
    ("sql", "operation", "objects"),
    [
        (
            "CREATE TABLE /*!32312 IF NOT EXISTS*/ items (id INT)",
            "CREATE",
            (NamedObject("items", SqlObjectType.TABLE, "created"),),
        ),
        (
            "/*!50001 CREATE TABLE items (id INT) */",
            "CREATE",
            (NamedObject("items", SqlObjectType.TABLE, "created"),),
        ),
        (
            "/*!50001 CREATE ALGORITHM=UNDEFINED */ "
            "/*!50013 DEFINER=`root`@`%` SQL SECURITY DEFINER */ "
            "/*!50001 VIEW report AS select 1 AS x */",
            "CREATE",
            (NamedObject("report", SqlObjectType.VIEW, "created"),),
        ),
        ("/*!40101 SET NAMES utf8mb4 */", "SET", ()),
    ],
)
def test_mysql_dump_statements_are_read_as_the_servers_ran_them(sql, operation, objects):
    """Measured 2026-10-24 on MySQL 8.0.46, 8.4.11 and MariaDB 11.8.8, the statements run as
    written: the first creates table ``f670_a`` (the second run only notes that it exists),
    the second table ``f670_b``, the third the view ``f670_v`` (the three comments make one
    ``CREATE ALGORITHM=UNDEFINED DEFINER=… SQL SECURITY DEFINER VIEW … AS select 1 AS x``),
    the fourth leaves ``@@character_set_client`` at utf8mb4 after ``SET NAMES latin1`` and
    creates nothing. The ``f670`` objects were dropped afterwards."""
    facts = SqlglotStatementFactsReader("mysql").read(sql)

    assert facts.operation == operation
    assert facts.objects == objects
    assert facts.error is None


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE items SET a=1 /*!50001 , b=2 */ /*!50700 , c=3 */",
        "/*!50700 DELETE FROM items */ /*!50001 */",
        "/*!50001 DELETE FROM items */ /*M!100000 */",
        "/*!50001 DELETE FROM items */ /*!50001 */ /*!999999 */",
    ],
)
def test_mysql_one_unresolved_executable_comment_leaves_the_whole_statement_opaque(sql):
    facts = SqlglotStatementFactsReader("mysql").read(sql)

    assert facts.opaque
    assert facts.operation == "UNKNOWN"
    assert facts.objects == ()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 /*!50001 , /* c */ 2 */ AS a FROM items",
        "DELETE FROM items /*!50001 WHERE id=3",
    ],
)
def test_mysql_executable_comment_the_reader_cannot_scan_stays_opaque(sql):
    """Measured 2026-10-24 for ``SELECT 1 /*! , /* c */ 2 */ AS y``: MySQL 8.4.11 returns the
    row, MySQL 8.0.46 and MariaDB 11.8.8 fail with error 1064, so a comment opened inside an
    executable comment has no single reading. An executable comment with no ``*/`` is not read
    either."""
    facts = SqlglotStatementFactsReader("mysql").read(sql)

    assert facts.opaque
    assert facts.objects == ()


def test_mysql_executable_comment_removal_does_not_touch_a_marker_inside_a_literal():
    facts = SqlglotStatementFactsReader("mysql").read(
        "SELECT '/*!99999 x */', `/*!99999 y */` FROM /*! items */"
    )

    assert not facts.opaque
    assert facts.objects == (NamedObject("items", SqlObjectType.TABLE, "referenced"),)


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
def test_mysql_quote_in_control_character_comment_does_not_hide_a_marker_that_runs(separator):
    facts = SqlglotStatementFactsReader("mysql").read(
        f"UPDATE items SET a=1 --{separator}'\n/*!50000 , b=2 */"
    )

    assert not facts.opaque
    assert facts.target == "items"
    assert facts.affected_columns == ("a", "b")
    assert facts.events == frozenset({"UPDATE"})


@pytest.mark.parametrize("separator", _LINE_COMMENT_SEPARATORS, ids=repr)
@pytest.mark.parametrize("marker", ["/*!50700", "/*M!50000"])
def test_mysql_quote_in_control_character_comment_does_not_hide_active_marker(separator, marker):
    facts = SqlglotStatementFactsReader("mysql").read(
        f"UPDATE items SET a=1 --{separator}'\n{marker} , b=2 */"
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
    assert facts.target == ("ITEMS" if dialect == "oracle" else "items")  # Oracle folds
    assert facts.affected_columns == ("a",)
    assert facts.events == frozenset({"UPDATE"})


@pytest.mark.parametrize("quirks", [MysqlQuirks, MariadbQuirks])
def test_mysql_family_statement_facts_hooks_are_active(quirks):
    assert quirks().supports_statement_facts
    assert issubclass(quirks().statement_facts_class, SqlglotStatementFactsReader)
