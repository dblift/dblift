"""Structural guard: every ``SqlplusDirective`` example must round-trip.

Batch 11 ``BUG-02..05`` was a directive-handling family of bugs:
SQL*Plus directives (``SET``, ``DEFINE``, ``PROMPT``, ``WHENEVER
SQLERROR``…) are *line*-terminated, but the Oracle tokenizer only
ends a statement on ``;`` or ``/``. Any directive without a trailing
``;`` silently merged with the next DDL, which either dropped the
user's real statement (when ``is_sqlplus_command`` matched the merged
text) or pushed an invalid blob to the execution provider.

The first fix appended ``;`` to every directive line in a pre-pass; the
splitter now reads directives itself (see below).

The structural fix is :data:`SQLPLUS_DIRECTIVES` — a single tuple
that both ``is_sqlplus_command`` and the corpus this test walks are
derived from. For each entry we assert:

1. each ``examples`` entry matches the directive's own pattern,
2. each example, followed by ``CREATE TABLE t (id NUMBER);`` on a separate
   line, is recorded, refused or ends the script, and never swallows the
   CREATE TABLE.

Adding a directive without an example is a hard error here: the test
asserts every entry in ``SQLPLUS_DIRECTIVES`` has at least one
example so the corpus stays in lockstep with the registry.

The splitter no longer pre-processes the text: it reads a directive line as a
``DIRECTIVE`` token and records, rewrites or refuses it
(docs/sql-parsing/oracle.md section 6). The end-to-end checks below therefore
run the corpus through the splitter and expect, per directive, the action
``classify_directive`` names; the regex-path functions (``is_sqlplus_command``)
are still checked against the registry.
"""

from __future__ import annotations

import unittest
import warnings

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.sql_parser.base_tokenizer import TokenizerWarning
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser._directives import DirectiveAction, classify_directive
from dblift.db.plugins.oracle.parser._sqlplus import SQLPLUS_DIRECTIVES, is_sqlplus_command
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


class TestSqlplusDirectiveRegistry(unittest.TestCase):
    def test_every_directive_has_at_least_one_example(self) -> None:
        for d in SQLPLUS_DIRECTIVES:
            with self.subTest(name=d.name):
                self.assertTrue(
                    d.examples,
                    f"SqlplusDirective {d.name!r} has no examples — corpus would silently skip it",
                )

    def test_example_matches_owning_pattern(self) -> None:
        for d in SQLPLUS_DIRECTIVES:
            for example in d.examples:
                with self.subTest(name=d.name, example=example):
                    self.assertTrue(
                        d.pattern.match(example.upper()),
                        f"{d.name}: example {example!r} does not match its own pattern",
                    )

    def test_directive_names_are_unique(self) -> None:
        names = [d.name for d in SQLPLUS_DIRECTIVES]
        self.assertEqual(
            len(names),
            len(set(names)),
            f"Duplicate directive names in registry: {names}",
        )


def _split(sql: str) -> list[str]:
    from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser

    tokens = OracleTokenizer(sql).tokenize()
    return [s for s in OracleStatementParser(tokens, source=sql).split_statements() if s.strip()]


class TestSqlplusDirectiveTerminationCorpus(unittest.TestCase):
    """Every example is classified, and the splitter does with it what the spec says.

    This is the end-to-end guarantee. If a directive is missing from the
    splitter's table the merge corruption from BUG-02..05 reappears here: the
    CREATE TABLE after it disappears or is mangled by the directive's text.
    """

    def test_every_example_is_a_directive_to_the_splitter(self) -> None:
        for d in SQLPLUS_DIRECTIVES:
            for example in d.examples:
                with self.subTest(name=d.name, example=example):
                    self.assertIsNotNone(
                        classify_directive(example),
                        f"{d.name}: the splitter does not recognise its own example {example!r}",
                    )

    def test_directive_followed_by_ddl_is_recorded_refused_or_ends_the_script(self) -> None:
        for d in SQLPLUS_DIRECTIVES:
            for example in d.examples:
                with self.subTest(name=d.name, example=example):
                    action = classify_directive(example).action
                    raw = f"{example}\nCREATE TABLE t_{d.name.lower()} (id NUMBER);\n"
                    if action is DirectiveAction.REJECT:
                        with self.assertRaises(UnsupportedMetaCommandError):
                            _split(raw)
                        continue
                    stmts = _split(raw)
                    survives = any(f"t_{d.name.lower()}" in s for s in stmts)
                    # EXIT / QUIT end the script: SQL*Plus never runs what follows.
                    self.assertEqual(survives, action is not DirectiveAction.EXIT, stmts)
                    # The directive's own text reaches execution only for the
                    # WHENEVER SQLERROR policy line.
                    for stmt in stmts:
                        if stmt.startswith("CREATE TABLE"):
                            continue
                        if action is DirectiveAction.EXEC:
                            # EXEC[UTE] is rewritten to a PL/SQL unit (spec section 6).
                            self.assertTrue(stmt.startswith("BEGIN "), stmts)
                            continue
                        self.assertFalse(d.filter_from_execution, stmts)
                        self.assertIn("WHENEVER SQLERROR", stmt)

    def test_at_script_directives_do_not_emit_tokenizer_warning(self) -> None:
        raw = "@ /tmp/other_script.sql\n@@ relative_script.sql\nCREATE TABLE t_at (id NUMBER);\n"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", TokenizerWarning)
            tokens = OracleTokenizer(raw).tokenize()

        assert not [w for w in caught if issubclass(w.category, TokenizerWarning)]
        assert [t.type for t in tokens[:2]] == [TokenType.DIRECTIVE, TokenType.DIRECTIVE]
        with self.assertRaises(UnsupportedMetaCommandError):
            _split(raw)

    def test_filtered_directives_match_is_sqlplus_command(self) -> None:
        for d in SQLPLUS_DIRECTIVES:
            if not d.filter_from_execution:
                continue
            for example in d.examples:
                with self.subTest(name=d.name, example=example):
                    self.assertTrue(
                        is_sqlplus_command(example),
                        f"{d.name}: is_sqlplus_command rejected own example {example!r}",
                    )

    def test_passthrough_directives_not_filtered(self) -> None:
        """``WHENEVER SQLERROR …`` must NOT be filtered (executor handles it)."""
        for d in SQLPLUS_DIRECTIVES:
            if d.filter_from_execution:
                continue
            for example in d.examples:
                with self.subTest(name=d.name, example=example):
                    self.assertFalse(
                        is_sqlplus_command(example),
                        f"{d.name}: is_sqlplus_command would drop pass-through "
                        f"directive {example!r} before reaching executor",
                    )


class TestConnectDirectiveExcludesDatabaseLinkSyntax(unittest.TestCase):
    """``CONNECT TO user IDENTIFIED BY password`` is Oracle DDL syntax (part
    of ``CREATE DATABASE LINK``), not the SQL*Plus ``CONNECT`` client
    command — SQL*Plus ``CONNECT`` is always ``CONNECT
    [user][/password][@identifier]`` and never uses ``TO``. Before the fix,
    the ``CONNECT`` directive's pattern matched this DDL continuation line
    too broadly and appended a spurious ``;``, splitting a multi-line
    ``CREATE DATABASE LINK ... USING '...'`` statement in two and creating a
    database link with no connect descriptor. This is the same class of
    false-positive already documented above for ``SET``/``WHENEVER``/
    ``START`` — the negative-example case the corpus module docstring calls
    out as exactly what this file exists to guard against.
    """

    def test_create_database_link_connect_to_line_not_terminated(self) -> None:
        raw = (
            "CREATE DATABASE LINK mylink\n"
            "CONNECT TO remote_user IDENTIFIED BY remote_pass\n"
            "USING '(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=remotehost)(PORT=1521))"
            "(CONNECT_DATA=(SERVICE_NAME=remotedb)))';\n"
        )
        stmts = _split(raw)
        matching = [s for s in stmts if "CREATE DATABASE LINK" in s]
        self.assertEqual(len(matching), 1, f"expected one statement, got: {stmts}")
        self.assertIn("CONNECT TO remote_user IDENTIFIED BY remote_pass", matching[0])
        self.assertIn("USING '(DESCRIPTION=", matching[0])

    def test_create_database_link_single_line_still_works(self) -> None:
        """Regression guard: the already-working single-line form must stay intact."""
        raw = (
            "CREATE DATABASE LINK mylink CONNECT TO remote_user IDENTIFIED BY remote_pass "
            "USING '(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=remotehost)(PORT=1521))"
            "(CONNECT_DATA=(SERVICE_NAME=remotedb)))';\n"
        )
        stmts = _split(raw)
        matching = [s for s in stmts if "CREATE DATABASE LINK" in s]
        self.assertEqual(len(matching), 1, f"expected one statement, got: {stmts}")
        self.assertIn("CONNECT TO remote_user IDENTIFIED BY remote_pass", matching[0])
        self.assertIn("USING '(DESCRIPTION=", matching[0])

    def test_genuine_sqlplus_connect_command_is_refused(self) -> None:
        """Regression guard: real SQL*Plus ``CONNECT user/pass@db`` directives
        (no ``TO``) are still recognised, and refused: a migration has no
        second connection to open (spec section 6).
        """
        raw = "CONNECT app_user/app_pass@orcl\nSELECT 1 FROM dual;\n"
        with self.assertRaises(UnsupportedMetaCommandError):
            _split(raw)


if __name__ == "__main__":
    unittest.main()
