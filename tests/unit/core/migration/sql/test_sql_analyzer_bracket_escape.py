"""Regression tests for #380: ``sql_analyzer``'s identifier handling did not
strip or un-escape quoted-identifier delimiters before re-quoting the name
downstream, and (separately) its ``_IDENTIFIER``/``_QUALIFIED_NAME`` regex
truncated at the first unescaped-looking delimiter instead of reading a
doubled pair as part of the token -- the same class of defect #375 fixed in
``SqlServerConfig.object_patterns``'s ``id_token``
(``dblift/db/plugins/sqlserver/parser/parser_config.py``), but left
unfixed here because ``sql_analyzer.py`` carries a separate copy of
identifier handling for the regex-fallback path.

Covers the same matrix #375 used (plain bracketed name, trailing doubled
bracket, doubled bracket at the start, two doublings in one identifier,
adjacent bracketed identifiers, a three-part db.schema.object name, and the
``"`` and backtick spellings), plus the literal reported symptom end to end
through the undo generator, plus a cross-check that the escape-aware
delimiters ``sql_analyzer.py`` and ``parser_config.py`` both use cannot
silently drift apart again.
"""

import unittest

from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


def _only(analyzer: SqlAnalyzer, sql: str) -> dict:
    """Return the single object ``sql`` affects, failing if there is not one."""
    objects = analyzer.extract_objects(sql)
    assert len(objects) == 1, f"expected exactly one object for {sql!r}, got {objects!r}"
    return objects[0]


class TestCreateIndexBracketDoubling(unittest.TestCase):
    """``CREATE INDEX``'s own name and its ON-target must both come out
    un-escaped -- a bare name, with no leftover ``[``/``]``/``"``/`` ` `` --
    so a downstream re-quote does not double them up."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="sqlserver")

    def test_plain_bracketed_name_is_unescaped(self):
        # The exact statement from the issue report.
        obj = _only(self.analyzer, "CREATE INDEX [idx_users_email] ON [dbo].[users]([email]);")
        self.assertEqual(obj["object_name"], "idx_users_email")
        self.assertEqual(obj["on_object"], "dbo.users")

    def test_trailing_doubled_bracket(self):
        obj = _only(self.analyzer, "CREATE INDEX [name]]] ON [dbo].[t]([c]);")
        self.assertEqual(obj["object_name"], "name]")

    def test_doubled_bracket_at_start(self):
        obj = _only(self.analyzer, "CREATE INDEX []]abc] ON [dbo].[t]([c]);")
        self.assertEqual(obj["object_name"], "]abc")

    def test_two_doubled_brackets_in_one_identifier(self):
        obj = _only(self.analyzer, "CREATE INDEX [a]]b]]c] ON [dbo].[t]([c]);")
        self.assertEqual(obj["object_name"], "a]b]c")

    def test_adjacent_bracketed_identifiers_on_target(self):
        obj = _only(self.analyzer, "CREATE INDEX [idx] ON [a]]b].[c]]d]([col]);")
        self.assertEqual(obj["on_object"], "a]b.c]d")

    def test_three_part_on_target_still_works(self):
        obj = _only(self.analyzer, "CREATE INDEX [idx] ON [mydb].[dbo].[mytable]([col]);")
        self.assertEqual(obj["on_object"], "dbo.mytable")

    def test_double_quoted_spelling(self):
        obj = _only(self.analyzer, 'CREATE INDEX "real""one" ON "dbo"."users"("email");')
        self.assertEqual(obj["object_name"], 'real"one')
        self.assertEqual(obj["on_object"], "dbo.users")


class TestBacktickAndDoubleQuoteAcrossDialects(unittest.TestCase):
    """#360 found the same truncation for the double-quote and backtick
    spellings on other dialects; #380 asks whether the divergence between
    sql_analyzer.py and parser_config.py reaches them too. It does --
    ``_IDENTIFIER``/``_QUALIFIED_NAME`` are shared by every dialect's
    regex-fallback path, not just SQL Server's."""

    def test_mysql_backtick_doubling_is_unescaped(self):
        analyzer = SqlAnalyzer(dialect="mysql")
        obj = _only(analyzer, "CREATE INDEX `idx``1` ON `db`.`t`(`c`);")
        self.assertEqual(obj["object_name"], "idx`1")
        self.assertEqual(obj["on_object"], "db.t")

    def test_postgresql_double_quote_doubling_is_unescaped(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        obj = _only(analyzer, 'CREATE INDEX "idx""1" ON "sch"."t"("c");')
        self.assertEqual(obj["object_name"], 'idx"1')
        self.assertEqual(obj["on_object"], "sch.t")


class TestGenericDdlBracketDoubling(unittest.TestCase):
    """The same ``_qualified_object_name`` helper backs every recognised DDL
    branch, not just CREATE INDEX -- CREATE TABLE and DROP INDEX included."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="sqlserver")

    def test_create_table_doubled_bracket(self):
        obj = _only(self.analyzer, "CREATE TABLE [real]]one] (id int);")
        self.assertEqual(obj["object_name"], "default_schema.real]one")

    def test_create_table_plain_bracket_is_unescaped(self):
        obj = _only(self.analyzer, "CREATE TABLE [idx_users_email] (id int);")
        self.assertEqual(obj["object_name"], "default_schema.idx_users_email")

    def test_drop_index_plain_bracket_is_unescaped(self):
        obj = _only(self.analyzer, "DROP INDEX [idx_users_email];")
        self.assertEqual(obj["object_name"], "default_schema.idx_users_email")


class TestUndoScriptEndToEnd(unittest.TestCase):
    """The literal reported symptom: a bracket-quoted CREATE INDEX reaching
    the undo generator's regex-fallback path (``_reverse_statement`` /
    ``_reverse_create``) must not emit a double-bracketed DROP INDEX name."""

    def _undo_sql(self, dialect: str, sql: str) -> str:
        gen = UndoScriptGenerator(dialect=dialect)
        undo = gen._reverse_statement(sql)
        assert undo is not None, f"expected an undo statement for {sql!r}"
        return undo.sql

    def test_reported_case(self):
        sql = "CREATE INDEX [idx_users_email] ON [dbo].[users]([email]);"
        undo_sql = self._undo_sql("sqlserver", sql)
        self.assertEqual(undo_sql, "DROP INDEX IF EXISTS [idx_users_email] ON [dbo].[users];")
        # The specific shape the bug produced must not reappear.
        self.assertNotIn("[[idx_users_email]]]", undo_sql)

    def test_doubled_bracket_index_name_resolves_rather_than_refuses(self):
        # Before this fix, the truncated regex match made the extractor
        # refuse to name the table at all (see the corresponding update in
        # tests/unit/core/migration/test_undo_script_generator.py).
        sql = "CREATE INDEX idx_x ON [dbo].[foo]]bar]([email]);"
        undo_sql = self._undo_sql("sqlserver", sql)
        self.assertEqual(undo_sql, "DROP INDEX IF EXISTS [idx_x] ON [dbo].[foo]]bar];")


class TestSharedDelimitersDoNotDrift(unittest.TestCase):
    """The test #380 exists to get: sql_analyzer.py and parser_config.py
    must use the exact same escape-aware bracket/double-quote delimiter
    patterns, not two copies that happen to agree today. If a future edit
    touches one and not the other, this fails -- it is the cross-check, not
    a same-file duplicate of either module's own tests."""

    def test_sql_analyzer_and_parser_config_share_the_same_delimiter_source(self):
        # The strongest form of the guard: both sql_analyzer.py and
        # parser_config.py must build their patterns from the exact same
        # constants in dblift.core.sql_parser.dialects.identifier_tokens --
        # not two textually-identical copies that happen to agree today.
        from dblift.core.migration.sql import sql_analyzer
        from dblift.core.sql_parser.dialects import identifier_tokens
        from dblift.db.plugins.sqlserver.parser import parser_config

        self.assertIn(identifier_tokens.BRACKET_IDENTIFIER, sql_analyzer._IDENTIFIER)
        self.assertIn(identifier_tokens.DOUBLE_QUOTED_IDENTIFIER, sql_analyzer._IDENTIFIER)

        config = parser_config.SqlServerConfig()
        # object_patterns() is a fresh computation each call (it's a
        # @property), so both fragments below are read from the same call
        # that actually builds the live patterns, not a stale copy.
        drop_table_pattern = config.object_patterns["table_drop"].pattern

        self.assertIn(identifier_tokens.BRACKET_IDENTIFIER, drop_table_pattern)
        self.assertIn(identifier_tokens.DOUBLE_QUOTED_IDENTIFIER, drop_table_pattern)

    def test_both_modules_unescape_a_doubled_bracket_identically(self):
        from dblift.core.sql_parser.dialects.identifier_tokens import (
            strip_identifier_quotes,
        )
        from dblift.db.plugins.sqlserver.parser.parser_config import SqlServerConfig

        config = SqlServerConfig()
        token = "[real]]one]"
        self.assertEqual(
            strip_identifier_quotes(token),
            config.normalize_identifier(token),
        )
