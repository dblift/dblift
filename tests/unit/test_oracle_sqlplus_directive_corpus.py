"""Structural guard: every ``SqlplusDirective`` example must round-trip.

Batch 11 ``BUG-02..05`` was a directive-handling family of bugs:
SQL*Plus directives (``SET``, ``DEFINE``, ``PROMPT``, ``WHENEVER
SQLERROR``…) are *line*-terminated, but the Oracle tokenizer only
ends a statement on ``;`` or ``/``. Any directive without a trailing
``;`` silently merged with the next DDL, which either dropped the
user's real statement (when ``is_sqlplus_command`` matched the merged
text) or pushed an invalid blob to the execution provider.

The runtime fix added :func:`terminate_sqlplus_directives` to append
``;`` to every directive line. That kept the regex / tokenizer paths
in sync only as long as both sides remembered to use the same
directive corpus — which is exactly the kind of drift PR-E warned
about.

The structural fix is :data:`SQLPLUS_DIRECTIVES` — a single tuple
that both ``is_sqlplus_command`` and the corpus this test walks are
derived from. For each entry we assert:

1. each ``examples`` entry matches the directive's own pattern,
2. each example, when fed through ``terminate_sqlplus_directives``
   followed by ``CREATE TABLE t (id NUMBER);`` on a separate line,
   produces a script in which the trailing CREATE TABLE survives —
   i.e. the directive is recognised, terminated, and stripped before
   the SQL statement.

Adding a directive without an example is a hard error here: the test
asserts every entry in ``SQLPLUS_DIRECTIVES`` has at least one
example so the corpus stays in lockstep with the registry.
"""

from __future__ import annotations

import unittest
import warnings

from dblift.core.sql_parser.base_tokenizer import TokenizerWarning
from dblift.db.plugins.oracle.parser._sqlplus import SQLPLUS_DIRECTIVES, is_sqlplus_command
from dblift.db.plugins.oracle.parser.sqlplus_context import terminate_sqlplus_directives


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


class TestSqlplusDirectiveTerminationCorpus(unittest.TestCase):
    """Every example must let the trailing ``CREATE TABLE`` survive splitting.

    This is the end-to-end guarantee. If any directive is missing or its
    pattern drifts, the merge corruption from BUG-02..05 reappears here:
    the CREATE TABLE either disappears (because the merged text matched
    a directive) or is mangled (because it now starts with the directive
    text).
    """

    def _split(self, sql: str) -> list[str]:
        from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
        from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer

        tokens = OracleTokenizer(sql).tokenize()
        return [s for s in OracleStatementParser(tokens).split_statements() if s.strip()]

    def test_directive_followed_by_ddl_survives_split(self) -> None:
        for d in SQLPLUS_DIRECTIVES:
            for example in d.examples:
                with self.subTest(name=d.name, example=example):
                    raw = f"{example}\nCREATE TABLE t_{d.name.lower()} (id NUMBER);\n"
                    terminated = terminate_sqlplus_directives(raw)
                    # The directive line must have gained a `;`. Trailing
                    # whitespace is rstripped before the `;` is inserted, so
                    # compare against the rstripped example.
                    expected = f"{example.rstrip()};"
                    self.assertIn(
                        expected,
                        terminated,
                        f"{d.name}: terminate_sqlplus_directives did not append `;` "
                        f"to {example!r}; merged script:\n{terminated}",
                    )
                    stmts = self._split(terminated)
                    self.assertTrue(
                        any(f"t_{d.name.lower()}" in s for s in stmts),
                        f"{d.name}: trailing CREATE TABLE was lost after directive "
                        f"{example!r}; statements after split:\n{stmts}",
                    )

    def test_at_script_directives_do_not_emit_tokenizer_warning(self) -> None:
        raw = "@ /tmp/other_script.sql\n@@ relative_script.sql\nCREATE TABLE t_at (id NUMBER);\n"
        terminated = terminate_sqlplus_directives(raw)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", TokenizerWarning)
            stmts = self._split(terminated)

        assert not [w for w in caught if issubclass(w.category, TokenizerWarning)]
        assert len(stmts) == 1
        assert "CREATE TABLE t_at" in stmts[0]

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

    def _split(self, sql: str) -> list[str]:
        from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
        from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer

        tokens = OracleTokenizer(sql).tokenize()
        return [s for s in OracleStatementParser(tokens).split_statements() if s.strip()]

    def test_create_database_link_connect_to_line_not_terminated(self) -> None:
        raw = (
            "CREATE DATABASE LINK mylink\n"
            "CONNECT TO remote_user IDENTIFIED BY remote_pass\n"
            "USING '(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=remotehost)(PORT=1521))"
            "(CONNECT_DATA=(SERVICE_NAME=remotedb)))';\n"
        )
        terminated = terminate_sqlplus_directives(raw)
        self.assertNotIn("remote_pass;", terminated)
        self.assertEqual(terminated, raw)

        stmts = self._split(terminated)
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
        terminated = terminate_sqlplus_directives(raw)
        self.assertEqual(terminated, raw)

        stmts = self._split(terminated)
        matching = [s for s in stmts if "CREATE DATABASE LINK" in s]
        self.assertEqual(len(matching), 1, f"expected one statement, got: {stmts}")
        self.assertIn("CONNECT TO remote_user IDENTIFIED BY remote_pass", matching[0])
        self.assertIn("USING '(DESCRIPTION=", matching[0])

    def test_genuine_sqlplus_connect_command_still_terminated(self) -> None:
        """Regression guard: real SQL*Plus ``CONNECT user/pass@db`` directives
        (no ``TO``) must still get their trailing ``;`` inserted.
        """
        raw = "CONNECT app_user/app_pass@orcl\nSELECT 1 FROM dual;\n"
        self.assertIn("CONNECT app_user/app_pass@orcl;", terminate_sqlplus_directives(raw))


if __name__ == "__main__":
    unittest.main()
