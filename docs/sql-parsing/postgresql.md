# PostgreSQL family — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | PostgreSQL 12+; AlloyDB, Aurora PostgreSQL, Citus, CockroachDB, Neon, Supabase, TimescaleDB, YugabyteDB (all inherit this spec unchanged, see §13) |
| Code facts taken from | OSS `develop` `61b1d83f` |
| Vendor references, fetched 2026-10-10 | *PostgreSQL 18 documentation*, §4.1.1 Identifiers, §4.1.2.1–4.1.2.5 Constants, §4.1.5 Comments; *psql* reference, "Meta-Commands" and `\;` |
| Live verification | psql against PostgreSQL 15 and 16, 2026-10-10 (rows 16, 21, 25) |
| Engine subclass | dollar-quote tags |

## 1. String literals

| Form | Opens | Closes | Escape inside | Vendor rule |
| --- | --- | --- | --- | --- |
| String | `'` | `'` | `''` only | §4.1.2.1: "To include a single-quote character within a string constant, write two adjacent single quotes". Backslash is literal (`standard_conforming_strings=on`, the default since 9.1, §4.1.2.2). |
| Escape string | `E'` / `e'` | `'` | `''` and `\x` (any `\` consumes the next character) | §4.1.2.2: "An escape string constant is specified by writing the letter E (upper or lower case) just before the opening single quote … a single quote can be included in an escape string by writing `\'`, in addition to the normal way of `''`". The `E` must not be preceded by an identifier character, `$`, `'` or `"`. |
| Unicode escape string | `U&'` | `'` | `''`; backslash escapes are code points, not quote escapes | §4.1.2.3. Lexically a plain string preceded by `U&`. |
| Bit / hex string | `B'`, `X'` | `'` | none | §4.1.2.5. Lexically a plain string. |
| Dollar-quoted | `$tag$` where *tag* is empty or follows the rules of an unquoted identifier | the identical `$tag$` | **none**: "no characters inside a dollar-quoted string are ever escaped" | §4.1.2.4. "The tag, if any, of a dollar-quoted string follows the same rules as an unquoted identifier, except that it cannot contain a dollar sign. Tags are case sensitive". An unquoted identifier begins with a letter or `_` (§4.1.1), so **`$1` is never a tag**: `$` followed by a digit is a positional parameter (§4.1.2.7). "A dollar-quoted string that follows a keyword or identifier must be separated from it by whitespace; otherwise the dollar quoting delimiter would be taken as part of the preceding identifier." |

Two string constants separated only by whitespace containing a newline are
one constant (§4.1.2.1); lexically they are two literals and the splitter
need not join them.

## 2. Identifiers

| Form | Opens | Closes | Escape inside | Vendor rule |
| --- | --- | --- | --- | --- |
| Quoted | `"` | `"` | `""` | §4.1.1 |
| Unicode quoted | `U&"` | `"` | `""` | §4.1.1; lexically `U&` then a quoted identifier |
| Regular | letter or `_` | end of `[A-Za-z0-9_$]` | — | §4.1.1: "Subsequent characters in an identifier or key word can be letters, underscores, digits (0-9), or dollar signs ($)" |

## 3. Comments

| Form | Opens | Closes | Nests | Vendor rule |
| --- | --- | --- | --- | --- |
| Line | `--` | end of line | — | §4.1.5 |
| Block | `/*` | the matching `*/` | **yes** | §4.1.5: "These block comments nest, as specified in the SQL standard but unlike C" |

No comment form carries directives. An unterminated block comment is an
error (the engine rejects it; so does the splitter). Verified 2026-10-10 against PostgreSQL 16.14 with the row 21 script.

## 4. Terminators

| Terminator | Rule |
| --- | --- |
| `;` | ends a statement when **parenthesis depth is 0** and no block (§5) is open. psql applies the same parenthesis rule, which is what allows `CREATE RULE … DO ALSO (stmt; stmt);`. The `;` is consumed and recorded on the `Statement`. An unclosed parenthesis at end of input does not split: the remainder is one statement, as psql sends its buffer at end of input. |
| `\;` | psql: "simply causes a semicolon to be added to the query buffer without any further processing", so the statements before and after it "are effectively combined and sent to the server in one request". The splitter replaces `\;` by `;` and does **not** end the statement; the `Statement` records `multi=True`. Verified 2026-10-10 against PostgreSQL 15 with psql. |
| `\g` | a psql meta-command (§6): rejected. |

A bare `;` (empty statement) is dropped, not returned.

## 5. Blocks

Procedure and function bodies are string literals (dollar-quoted or
single-quoted), so no depth tracking is needed for them. One construct has
an unquoted body:

| Opener | Condition | Closer |
| --- | --- | --- |
| `BEGIN ATOMIC` | the two keywords adjacent (comments allowed between), at parenthesis depth 0, in a statement whose head is `CREATE [OR REPLACE] { FUNCTION \| PROCEDURE }` (psql's lexer tracks `BEGIN`/`CASE`/`END` depth only inside such statements, `psqlscan_is_create_routine`) | the `END` that returns to depth 0; `CASE … END` inside the body is counted so its `END` does not close the block |

`BEGIN` alone, `BEGIN TRANSACTION`, `BEGIN WORK`, `BEGIN ISOLATION LEVEL …`
are transaction statements and open nothing. `DO` blocks and `CREATE
FUNCTION … LANGUAGE plpgsql` bodies are dollar-quoted strings.

## 6. Client directives

psql: "Anything you enter in psql that begins with an unquoted backslash is a
psql meta-command that is processed by psql itself. … Parsing for arguments
stops at the end of the line, or when another unquoted backslash is found.
… the arguments of a meta-command cannot continue beyond the end of the line."

| Directive | Splitter action |
| --- | --- |
| `\restrict <key>`, `\unrestrict <key>` (emitted by `pg_dump` 17.6+/18) | **drop and record** as `kind="directive"` |
| `\copy …` | **reject**: the client-side variant of COPY; the server-side `COPY … FROM STDIN` (§7) is the supported equivalent |
| `\connect`, `\c`, `\set`, `\i`, `\ir`, `\include`, `\echo`, `\g`, `\gx`, `\gexec`, `\gset`, `\if` … `\endif`, `\o`, `\q`, `\!`, `\timing`, and every other meta-command | **reject** with `UnsupportedMetaCommandError` naming the command and line |
| `:var`, `:'var'`, `:"var"` (psql variable interpolation) | passed through to the server (they are legal SQL casts or syntax errors there); a placeholder service is the supported equivalent |

A meta-command is recognised at **any** unquoted `\` outside strings,
identifiers, comments and dollar quotes, not only at line start: psql's
lexer (`psqlscan.l`) returns a backslash token wherever it meets one in SQL
state, and the reference says "SQL and psql commands can be freely mixed on a
line". The documented idioms `SELECT count(*) FROM t \gset n` and
`SELECT 1 \gx` are therefore rejected by name, not sent to the server. The
exceptions are `\;` (§4) and `\:`.

## 7. Raw blocks

| Block | Opens | Closes | Rule |
| --- | --- | --- | --- |
| `COPY … FROM STDIN` data | the statement head is `COPY`, the header contains the two top-level words `FROM STDIN` (unquoted, parenthesis depth 0), and the header's `;` has been read | the first line consisting **exactly** of `\.` (psql `copy.c` compares the whole line against `\.\n` or `\.\r\n`; COPY reference: "a line containing just backslash-period (\.)"); a line with leading blanks before `\.` is data | the header, its `;`, and the data lines form **one** `Statement` with `kind="copy_stdin"`; the `\.` line is the block's terminator and, like every terminator, is consumed and not part of the text. Execution streams the data through the driver's COPY API. `COPY … TO STDOUT` is rejected by execution. |

Dollar-quoted bodies are opaque by §1.

## 8. Transaction markers

| Pattern (first keywords after comments) | Status |
| --- | --- |
| `CREATE [UNIQUE] INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `REINDEX … CONCURRENTLY` | current code, verified by `test_postgresql_non_transactional.py` |
| `VACUUM`, `REINDEX DATABASE|SCHEMA|SYSTEM`, `CLUSTER` (bare form) | current code |
| `CREATE|DROP DATABASE`, `CREATE|DROP TABLESPACE`, `ALTER SYSTEM` | current code |
| `CREATE SUBSCRIPTION` ("When creating a replication slot (the default behavior), CREATE SUBSCRIPTION cannot be executed inside a transaction block."), `DISCARD ALL` ("DISCARD ALL cannot be executed inside a transaction block."), `ALTER DATABASE … SET TABLESPACE` ("This form of the command cannot be executed inside a transaction block.") | **to add**, cited |
| `DROP SUBSCRIPTION` (with a slot) | **to add, verify live** |
| `ALTER TYPE … ADD VALUE` | not a marker: allowed in a transaction since PostgreSQL 12 (the new value is unusable until commit, which is execution's concern) |

## 9. Engine subclass

Dollar-quote tag matching: the closer repeats the opener's tag, which a fixed
pair table cannot express. Shared with DuckDB and Redshift.

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `CREATE TABLE t(a int); INSERT INTO t VALUES (1);` | `CREATE TABLE t(a int)` · `INSERT INTO t VALUES (1)` (terminators consumed) |
| 2 | `CREATE FUNCTION f() RETURNS int LANGUAGE plpgsql AS $$ BEGIN RETURN 1; END; $$; SELECT f();` | `CREATE FUNCTION f() RETURNS int LANGUAGE plpgsql AS $$ BEGIN RETURN 1; END; $$` · `SELECT f()` |
| 3 | `CREATE FUNCTION g() RETURNS text AS $body$ SELECT $$x;y$$ $body$ LANGUAGE sql; SELECT 1;` | `CREATE FUNCTION g() RETURNS text AS $body$ SELECT $$x;y$$ $body$ LANGUAGE sql` · `SELECT 1` (the inner untagged dollar quote does not close the tagged one) |
| 4 | `SELECT E'it\'s; fine'; SELECT 2;` | `SELECT E'it\'s; fine'` · `SELECT 2` |
| 5 | `SELECT 'a\'; SELECT 2;` | `SELECT 'a\'` · `SELECT 2` (plain string: the backslash is literal) |
| 6 | `PREPARE q(int) AS SELECT $1; EXECUTE q(1); SELECT 3;` | `PREPARE q(int) AS SELECT $1` · `EXECUTE q(1)` · `SELECT 3` (**three**: the positional parameter is not a tag) |
| 7 | `/* a /* b */ ; */ SELECT 1;` | `SELECT 1` |
| 8 | `CREATE RULE r AS ON INSERT TO t DO ALSO (INSERT INTO u VALUES (1); INSERT INTO v VALUES (2)); SELECT 1;` | `CREATE RULE r AS ON INSERT TO t DO ALSO (INSERT INTO u VALUES (1); INSERT INTO v VALUES (2))` · `SELECT 1` (**two**: the semicolon inside parentheses does not split) |
| 9 | `CREATE FUNCTION h() RETURNS int BEGIN ATOMIC SELECT CASE WHEN true THEN 1 END; SELECT 2; END; SELECT 9;` | `CREATE FUNCTION h() RETURNS int BEGIN ATOMIC SELECT CASE WHEN true THEN 1 END; SELECT 2; END` · `SELECT 9` |
| 10 | `BEGIN; INSERT INTO t VALUES (1); COMMIT;` | `BEGIN` · `INSERT INTO t VALUES (1)` · `COMMIT` |
| 11 | `COPY t (a) FROM STDIN;\n1\n2\n\.\nSELECT count(*) FROM t;` | `COPY t (a) FROM STDIN;\n1\n2` (one copy_stdin statement: the header and its two data lines; the backslash-period terminator line consumed) · `SELECT count(*) FROM t` |
| 12 | `COPY t TO STDOUT; SELECT 1;` | `COPY t TO STDOUT` · `SELECT 1` (execution later refuses the first) |
| 13 | `\restrict abc\nSELECT 1;\n\unrestrict abc\n` | directive record · `SELECT 1` · directive record |
| 14 | `\connect other\nSELECT 1;` | `UnsupportedMetaCommandError` (line 1, `\connect`) |
| 15 | `SELECT 1; \set x 1` | `UnsupportedMetaCommandError` (line 1, `\set`) |
| 15a | `SELECT count(*) FROM t \gset n` | `UnsupportedMetaCommandError` (line 1, `\gset`) |
| 15b | `COPY t (a) FROM STDIN;\n1\n  \.\n\.\nSELECT 1;` | `COPY t (a) FROM STDIN;\n1\n  \.` (one copy_stdin statement whose data is the two lines 1 and, with its leading blanks, backslash-period; the exact backslash-period line consumed) · `SELECT 1` |
| 16 | `SELECT 1 \; SELECT 2; SELECT 3;` | `SELECT 1 ; SELECT 2` with multi=True · `SELECT 3` |
| 17 | `SELECT "a;b" FROM t; SELECT 2;` | `SELECT "a;b" FROM t` · `SELECT 2` |
| 18 | `SELECT U&'d\0061t;a'; SELECT 2;` | `SELECT U&'d\0061t;a'` · `SELECT 2` |
| 19 | `SELECT 1;\n;\n;` | `SELECT 1` only |
| 20 | `SELECT 1 -- trailing\n` | `SELECT 1 -- trailing` (no terminator; last statement returned) |
| 21 | `/*DELIMITER //*/ SELECT 1;` | `UnsafeStatementSplitError` (the `/*` inside the comment opens a nested comment that never closes; psql 16: `ERROR: unterminated /* comment`) |
| 22 | `SELECT 'abc; SELECT 2;` | `UnsafeStatementSplitError` (unterminated string, line 1 column 8) |
| 23 | `SELECT $$abc; SELECT 2;` | `UnsafeStatementSplitError` (unterminated dollar-quoted string, line 1 column 8) |
| 24 | `SELECT "a;b FROM t;` | `UnsafeStatementSplitError` (unterminated quoted identifier) |
| 25 | `SELECT (1; SELECT 2;` | `SELECT (1; SELECT 2;` (one statement, the text unchanged: psql sends the buffer at end of input at any parenthesis depth; the server rejects it, verified 2026-10-10 on PostgreSQL 15: syntax error at or near ";") |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| `standard_conforming_strings = off` | plain strings are read without backslash escapes | a server setting the splitter cannot see; off has not been the default since 9.1 |
| psql variables and conditionals (`\if`) | rejected | a client preprocessor, not SQL |
| `\copy` | rejected | its client-side file access has no server equivalent in the migration model; `COPY FROM STDIN` is supported |
| Single-line mode (`-S`) | not modelled | psql option, not a property of the script |

## 12. Implementation

Code: `dblift/db/plugins/postgresql/parser/postgresql_tokenizer.py`,
`postgresql_statement_parser.py` and `postgresql_regex_parser.py`. The
splitter returns `Statement` records (`dblift/core/sql_parser/statement.py`):
text without its terminator, line, terminator, and kind. The conformance
table in section 10 is compiled into
`tests/unit/core/sql_parser/test_postgresql_spec_conformance.py`.

Unterminated lexemes (comment, string, quoted identifier, dollar quote) and
unsupported meta-commands are refusals, not input to a fallback.

The string projection `split_statements()` keeps the trailing `;`; the
`Statement.text` excludes it.

## 13. Family members

| Plugin | Override of this spec | Evidence |
| --- | --- | --- |
| AlloyDB, Aurora PostgreSQL, Citus, Neon, Supabase, TimescaleDB | none | `make_pg_compatible_plugin` with no parser override |
| YugabyteDB | none | `yugabytedb/plugin.py:31-39` records a live check that block comments nest |
| CockroachDB | none | `cockroachdb/quirks.py:24-32` records a live check that block comments nest |
| Redshift | a separate Redshift specification (not in this repository) | string escapes and comment nesting differ or are unverified |
