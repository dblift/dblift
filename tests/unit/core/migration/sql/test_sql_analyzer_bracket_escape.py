"""Regression tests for #380: ``sql_analyzer``'s identifier handling did not
strip or un-escape quoted-identifier delimiters before re-quoting the name
downstream, and (separately) its ``_IDENTIFIER``/``_QUALIFIED_NAME`` regex
truncated at the first unescaped-looking delimiter instead of reading a
doubled pair as part of the token -- the same class of defect #375 fixed in
``SqlServerConfig.object_patterns``'s ``id_token``
(``dblift/db/plugins/sqlserver/parser/parser_config.py``), but left
unfixed here because ``sql_analyzer.py`` carries a separate copy of
identifier handling for the regex-fallback path.

The parser coverage retains the same matrix #375 used (plain bracketed name, trailing doubled
bracket, doubled bracket at the start, two doublings in one identifier,
adjacent bracketed identifiers, a three-part db.schema.object name, and the
``"`` and backtick spellings), plus a cross-check that the escape-aware
delimiters ``sql_analyzer.py`` and ``parser_config.py`` both use cannot
silently drift apart again.
"""

import unittest

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
        self.assertEqual(obj["object_name"], "dbo.idx_users_email")
        self.assertEqual(obj["on_object"], "dbo.users")

    def test_trailing_doubled_bracket(self):
        obj = _only(self.analyzer, "CREATE INDEX [name]]] ON [dbo].[t]([c]);")
        self.assertEqual(obj["object_name"], "dbo.name]")

    def test_doubled_bracket_at_start(self):
        obj = _only(self.analyzer, "CREATE INDEX []]abc] ON [dbo].[t]([c]);")
        self.assertEqual(obj["object_name"], "dbo.]abc")

    def test_two_doubled_brackets_in_one_identifier(self):
        obj = _only(self.analyzer, "CREATE INDEX [a]]b]]c] ON [dbo].[t]([c]);")
        self.assertEqual(obj["object_name"], "dbo.a]b]c")

    def test_adjacent_bracketed_identifiers_on_target(self):
        obj = _only(self.analyzer, "CREATE INDEX [idx] ON [a]]b].[c]]d]([col]);")
        self.assertEqual(obj["on_object"], "a]b.c]d")

    def test_three_part_on_target_still_works(self):
        obj = _only(self.analyzer, "CREATE INDEX [idx] ON [mydb].[dbo].[mytable]([col]);")
        self.assertEqual(obj["on_object"], "mydb.dbo.mytable")

    def test_double_quoted_spelling(self):
        obj = _only(self.analyzer, 'CREATE INDEX "real""one" ON "dbo"."users"("email");')
        self.assertEqual(obj["object_name"], 'dbo.real"one')
        self.assertEqual(obj["on_object"], "dbo.users")


class TestBacktickAndDoubleQuoteAcrossDialects(unittest.TestCase):
    """#360 found the same truncation for the double-quote and backtick
    spellings on other dialects; #380 asks whether the divergence between
    sql_analyzer.py and parser_config.py reaches them too. It does --
    ``_IDENTIFIER``/``_QUALIFIED_NAME`` are shared by every dialect's
    regex-fallback path, not just SQL Server's."""

    def test_postgresql_double_quote_doubling_is_unescaped(self):
        analyzer = SqlAnalyzer(dialect="postgresql")
        obj = _only(analyzer, 'CREATE INDEX "idx""1" ON "sch"."t"("c");')
        self.assertEqual(obj["object_name"], 'default_schema.idx"1')


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
        self.assertEqual(self.analyzer.extract_objects("DROP INDEX [idx_users_email];"), [])

    def test_escaped_bracket_in_index_target_is_unescaped(self):
        obj = _only(self.analyzer, "CREATE INDEX idx_x ON [dbo].[foo]]bar]([email]);")
        self.assertEqual(obj["object_name"], "dbo.idx_x")
        self.assertEqual(obj["on_object"], "dbo.foo]bar")

    def test_long_index_target_does_not_collapse_to_its_schema(self):
        for name in ("x" * 300, "y" * 1000):
            obj = _only(self.analyzer, f"CREATE INDEX [idx_test] ON [dbo].[{name}](col);")
            self.assertEqual(obj["on_object"], f"dbo.{name}")
