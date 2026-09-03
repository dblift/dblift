"""Structural guard: every dialect tokenizer must claim every character.

Batch 11 ``BUG-01`` was a silent-drop bug: ``MySQLTokenizer`` inherited the
base fallthrough that quietly consumed any unrecognized character, so
``@stmt_count`` lost its ``@`` and ``SET @stmt_count = 0`` was lexed as
``SET stmt_count = 0``. The targeted fix added an ``@``-aware override on
the MySQL tokenizer; this test makes the *class* of bug noisy.

Strategy:

1. ``BaseTokenizer._handle_unknown_char`` now emits a ``TokenizerWarning``
   instead of silently consuming.
2. This test escalates that warning to an error and runs each dialect's
   tokenizer against a representative SQL corpus that exercises the
   characters historically dropped (``@``, ``${...}``, ``[brackets]``,
   ``DELIMITER``-introduced fences, etc.).
3. Any future tokenizer regression that lets a character fall through
   trips ``warnings.catch_warnings(..., simplefilter("error", ...))`` and
   the test fails with the offending dialect / character / line / col in
   the assertion message.

The corpus is intentionally small but each entry is a real shape we have
seen in production migrations — adding cases here is cheap and the test is
fast.
"""

from __future__ import annotations

import unittest
import warnings

from dblift.core.sql_parser.base_tokenizer import TokenizerWarning


class TestTokenizerNoSilentDrop(unittest.TestCase):
    """Run each dialect tokenizer over a corpus, assert no silent drops.

    A silent drop would historically be a no-op: the bad character was
    consumed and ``None`` returned. Now it raises ``TokenizerWarning``,
    which we turn into ``TokenizerError`` (an exception) for the test.
    """

    def _assert_no_drops(self, tokenizer_cls, corpus: list[str]) -> None:
        for sql in corpus:
            with self.subTest(dialect=tokenizer_cls.dialect_name, sql=sql[:60]):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", TokenizerWarning)
                    tokenizer_cls(sql).tokenize()

    def test_mysql_tokenizer_claims_user_variables(self) -> None:
        from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer

        self._assert_no_drops(
            MySQLTokenizer,
            [
                "SET @stmt_count = 0;",
                "SELECT @@global.read_only;",
                "INSERT INTO logs (n) VALUES (@x + 1, @y);",
                "SELECT @v := COUNT(*) FROM t;",
                "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SET @x = 1; END$$\nDELIMITER ;",
                "SELECT `quoted_id`, c1 FROM t WHERE c1 = 'O\\'Reilly';",
                "/*!50001 CREATE VIEW v AS SELECT 1 */;",
                "INSERT INTO t (a) VALUES (1); -- trailing comment\n",
                "INSERT INTO t (a) VALUES (1); # hash comment\n",
            ],
        )

    def test_oracle_tokenizer_claims_double_quotes_and_q_quotes(self) -> None:
        from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer

        self._assert_no_drops(
            OracleTokenizer,
            [
                'CREATE TABLE "MyTable" (id NUMBER);',
                "SELECT q'[O'Reilly]' FROM dual;",
                "BEGIN DBMS_OUTPUT.PUT_LINE('hi'); END;\n/\n",
                "DECLARE v NUMBER := 1; BEGIN NULL; END;\n/",
                'INSERT INTO t ("Col") VALUES (1);',
                "SELECT 1 || 2 FROM dual;",
            ],
        )

    def test_postgresql_tokenizer_claims_dollar_quotes_and_quoted_idents(self) -> None:
        from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer

        self._assert_no_drops(
            PostgreSQLTokenizer,
            [
                'CREATE TABLE "Quoted" (id INT);',
                "CREATE FUNCTION f() RETURNS void AS $$ BEGIN RAISE NOTICE 'hi'; END; $$ LANGUAGE plpgsql;",
                "CREATE FUNCTION g() RETURNS int AS $body$ SELECT 1 $body$ LANGUAGE sql;",
                "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING;",
                "SELECT a || b FROM t;",
            ],
        )

    def test_sqlserver_tokenizer_claims_brackets_and_at_signs(self) -> None:
        from dblift.db.plugins.sqlserver.parser.sqlserver_tokenizer import SQLServerTokenizer

        self._assert_no_drops(
            SQLServerTokenizer,
            [
                "SELECT [Order Date] FROM [dbo].[Orders];",
                "DECLARE @id INT = 1;\nSELECT @@ROWCOUNT;",
                "EXEC sp_executesql N'SELECT 1';\nGO\n",
                "INSERT INTO t (a) VALUES (1);",
                "CREATE PROCEDURE dbo.p @x INT AS BEGIN SELECT @x; END",
            ],
        )

    def test_warning_carries_dialect_char_line_col(self) -> None:
        """Sanity-check the diagnostic shape for new regressions."""
        from dblift.core.sql_parser.base_tokenizer import BaseTokenizer

        sql = "SELECT 1\nWHERE x \x00 1;"  # NUL is genuinely outside any rule
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", TokenizerWarning)
            BaseTokenizer(sql).tokenize()
        msgs = [str(w.message) for w in caught]
        self.assertTrue(
            any("\\x00" in m or "'\\x00'" in m for m in msgs),
            f"expected NUL char in TokenizerWarning, got {msgs!r}",
        )
        self.assertTrue(any("line 2" in m for m in msgs))


if __name__ == "__main__":
    unittest.main()
