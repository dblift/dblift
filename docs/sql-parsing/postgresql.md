# PostgreSQL family — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | PostgreSQL 12+; AlloyDB, Aurora PostgreSQL, Citus, CockroachDB, Neon, Supabase, TimescaleDB, YugabyteDB (all inherit this spec unchanged, see §13) |
| Code facts taken from | OSS `develop` `61b1d83f`; the pieces without code and the statement records at OSS `develop` `48051ff` (2026-10-19); the kept-character rows (30d to 30i) rest on the change that makes the PostgreSQL family send a statement holding a character the engine does not read as blank |
| Vendor references, fetched 2026-10-10 | *PostgreSQL 18 documentation*, §4.1.1 Identifiers, §4.1.2.1–4.1.2.5 Constants, §4.1.5 Comments; *psql* reference, "Meta-Commands" and `\;` |
| Live verification | psql against PostgreSQL 15 and 16, 2026-10-10 (rows 16, 21, 25); psql 16.14 and psycopg 3.3.5 against PostgreSQL 16.14, and ysqlsh, cockroach sql and psycopg 3 against YugabyteDB 2026.1.2.0 and CockroachDB v24.3.18, 2026-10-19, and psql and psycopg 3.3.5 against Redshift Serverless 1.0.477953, 2026-10-20 (rows 30j to 30p: every character above U+007F continues and begins a name on PostgreSQL 16.14, CockroachDB v24.3.18, YugabyteDB 2026.1.2.0 and Redshift, measured 2026-10-19 with psql 16.14, ysqlsh, cockroach sql and psycopg 3.3.5; rows 30d to 30f: U+00A0, U+3000 and U+001C are rejected with SQLSTATE 42601 everywhere, U+0020 and U+0009 are accepted; rows 30d to 30i hold on Redshift too; a Unicode space at the end of a statement, before its terminator, is accepted there, see section 13) |
| Engine subclass | none; tagged strings use the shared lexical primitive (§9) |

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
| Regular | letter or `_` | end of `[A-Za-z0-9_$]` and of every character above U+007F | — | §4.1.1: "Subsequent characters in an identifier or key word can be letters, underscores, digits (0-9), or dollar signs ($)". The server's scanner also reads every non-ASCII character as a letter: `U+00A0`, `U+0085`, `U+2003`, `U+2028`, `U+3000`, `U+20AC` and the rest continue a name, and begin one, on PostgreSQL 16.14, CockroachDB v24.3.18, YugabyteDB 2026.1.2.0 and Redshift (measured 2026-10-19, rows 30j to 30o). `CREATE TABLE t (x INT); CREATE TABLE t\u00a0 (x INT);` creates two tables, the second named `74c2a0` in hex. U+001C is not a name character. |

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
| `COPY … FROM STDIN` data | the statement head is `COPY`, the header contains the two top-level words `FROM STDIN` (unquoted, parenthesis depth 0), and the header's `;` has been read | the first line consisting **exactly** of `\.` (psql `copy.c` compares the whole line against `\.\n` or `\.\r\n`; COPY reference: "a line containing just backslash-period (\.)"); a line with leading blanks before `\.` is data | the header, its `;`, and the data lines form **one** `Statement` with `kind="copy_stdin"`; the `\.` line is the block's terminator and, like every terminator, is consumed and not part of the text. The row payload starts after the header line, excluding ASCII spaces, tabs, line comments or block comments after `;` on that line, and retains every data byte, including the final LF or CRLF. The statement text still preserves the original header line. Any other text after the header semicolon is refused. Analysis sees the COPY header as one opaque constituent. Execution streams the data through the driver's COPY API. `COPY … TO STDOUT` is rejected by execution. |

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

Dollar-quote tag matching uses the shared tokenizer's tagged-string primitive:
the closer repeats the opener's tag. A specification enables it as data; no
PostgreSQL engine subclass is needed. Redshift uses the same implementation;
DuckDB retains its existing scanner until it is migrated.

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
| 11 | `COPY t (a) FROM STDIN;\n1\n2\n\.\nSELECT count(*) FROM t;` | `COPY t (a) FROM STDIN;\n1\n2\n` **exact text** (one copy_stdin statement: the header and its two data lines; the backslash-period terminator line consumed) · `SELECT count(*) FROM t;` |
| 11a | `COPY t (a) FROM STDIN;\n1\n\n\.\nSELECT 1;` | `COPY t (a) FROM STDIN;\n1\n\n` **exact text** (the second data row is empty and remains in the COPY payload) · `SELECT 1;` |
| 11b | `COPY t (a) FROM STDIN; -- header\n1\n\n\.\nSELECT 1;` | `COPY t (a) FROM STDIN; -- header\n1\n\n` **exact text** (the statement preserves the header line; the COPY payload excludes the comment and retains the final empty row) · `SELECT 1;` |
| 11c | `COPY t (a) FROM STDIN; DROP TABLE t;\n1\n\.` | `UnsafeStatementSplitError` (executable text after the COPY header semicolon must not be discarded) |
| 11d | `COPY t (a) FROM STDIN; /* header */\n1\n\n\.\nSELECT 1;` | `COPY t (a) FROM STDIN; /* header */\n1\n\n` **exact text** (psql accepts a block comment on the header line; the COPY payload starts with the next line) · `SELECT 1;` |
| 11e | `COPY t (a) FROM STDIN; \n1\n\.` | `UnsafeStatementSplitError` (U+00A0 after the semicolon is not psql header whitespace and must not be discarded) |
| 12 | `COPY t TO STDOUT; SELECT 1;` | `COPY t TO STDOUT` · `SELECT 1` (execution later refuses the first) |
| 13 | `\restrict abc\nSELECT 1;\n\unrestrict abc\n` | directive record · `SELECT 1` · directive record |
| 14 | `\connect other\nSELECT 1;` | `UnsupportedMetaCommandError` (line 1, `\connect`) |
| 15 | `SELECT 1; \set x 1` | `UnsupportedMetaCommandError` (line 1, `\set`) |
| 15a | `SELECT count(*) FROM t \gset n` | `UnsupportedMetaCommandError` (line 1, `\gset`) |
| 15b | `COPY t (a) FROM STDIN;\n1\n  \.\n\.\nSELECT 1;` | `COPY t (a) FROM STDIN;\n1\n  \.\n` **exact text** (one copy_stdin statement whose data is the two lines 1 and, with its leading blanks, backslash-period; the exact backslash-period line consumed) · `SELECT 1;` |
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
| 26 | `CREATE TABLE t(begin int); SELECT begin atomic FROM t; SELECT 2;` | `CREATE TABLE t(begin int)` · `SELECT begin atomic FROM t` · `SELECT 2` (ordinary identifiers do not open a routine body; psql executes three statements) |
| 27 | `SELECT E'a\'--b'; DROP TABLE visible;` | `SELECT E'a\'--b'` · `DROP TABLE visible` (comment masking for analysis uses these same literal boundaries and keeps the following statement) |
| 28 | `SELECT 0 \; CREATE FUNCTION f() RETURNS int LANGUAGE SQL BEGIN ATOMIC SELECT 1; END; SELECT 2;` | `SELECT 0 ; CREATE FUNCTION f() RETURNS int LANGUAGE SQL BEGIN ATOMIC SELECT 1; END` with multi=True · `SELECT 2` (the combined query starts a fresh routine head after its escaped semicolon; analysis has three constituents) |
| 29 | `CREATE TABLE stdin(copy int); SELECT copy FROM stdin; SELECT 2;` | `CREATE TABLE stdin(copy int)` · `SELECT copy FROM stdin` · `SELECT 2` (a column named COPY never opens a data header) |
| 30 | `DROP TABLE t\xa0` | `DROP TABLE t\xa0` **exact text** (no terminator: the last statement keeps a trailing no-break space; psql 16 sends it and the server reads it as part of the name, measured 2026-10-17; CockroachDB and YugabyteDB the same, measured) |
| 30a | `DROP TABLE t\u3000;\nSELECT 1;` | `DROP TABLE t\u3000;` · `SELECT 1;` **exact text** (an ideographic space before the terminator is a name character on PostgreSQL, CockroachDB and YugabyteDB, measured 2026-10-17: the text keeps it) |
| 30b | `SELECT 1\x0c` | `SELECT 1` **exact text** (a form feed is a blank for the server, CockroachDB and YugabyteDB included) |
| 30c | `SELECT 1\x0b` | `SELECT 1\x0b` **exact text** (rejected by the engine, kept: a vertical tab is a syntax error on PostgreSQL, CockroachDB and YugabyteDB, so the statement fails as it does under psql) |
| 30d | `SELECT 1;\n\xa0;\nSELECT 2;` | `SELECT 1` · `\xa0` · `SELECT 2` (a piece made only of a no-break space is a statement and is sent; psql and the drivers send it and the server answers a syntax error near the character, so a migration fails as a client run does; measured 2026-10-19 with psql 16.14, ysqlsh, cockroach sql and psycopg 3 against PostgreSQL 16.14, CockroachDB v24.3.18 and YugabyteDB 2026.1.2.0: each rejects the piece with SQLSTATE 42601) |
| 30e | `SELECT 1;\n　;\nSELECT 2;` | `SELECT 1` · `\u3000` · `SELECT 2` (a piece made only of an ideographic space is a statement and is sent; the server answers a syntax error near the character; measured 2026-10-19 with psql 16.14, ysqlsh, cockroach sql and psycopg 3 against PostgreSQL 16.14, CockroachDB v24.3.18 and YugabyteDB 2026.1.2.0: each rejects the piece with SQLSTATE 42601) |
| 30f | `SELECT 1;\n\x1c;\nSELECT 2;` | `SELECT 1` · `\x1c` · `SELECT 2` (a piece made only of a control character is a statement and is sent; the server answers a syntax error near the character; a form feed alone is a blank and is accepted; measured 2026-10-19 with psql 16.14, ysqlsh, cockroach sql and psycopg 3 against PostgreSQL 16.14, CockroachDB v24.3.18 and YugabyteDB 2026.1.2.0: each rejects the piece with SQLSTATE 42601) |
| 30g | `SELECT 1;\n\xa0\nSELECT 2;` | `SELECT 1` · `\xa0\nSELECT 2` (a kept character at the head of a statement is part of it, not skipped, and the statement starts on the line that holds it; measured 2026-10-19 with psql 16.14 against PostgreSQL 16.14: the statement is rejected with SQLSTATE 42601; CockroachDB and YugabyteDB were measured only on a piece made of the character alone, rows 30d to 30f) |
| 30h | `\xa0SELECT 1;` | `\xa0SELECT 1` (the leading no-break space is sent with the statement, which the engine rejects; measured 2026-10-19 with psql 16.14 against PostgreSQL 16.14; CockroachDB and YugabyteDB were measured only on the lone-piece case, rows 30d to 30f) |
| 30i | `SELECT 1;\xa0` | `SELECT 1` · `\xa0` (a kept character after the last terminator is a piece of its own and is sent, and the engine rejects it; measured 2026-10-19 with psql 16.14 against PostgreSQL 16.14; CockroachDB and YugabyteDB were measured only on the lone-piece case, rows 30d to 30f) |
| 30j | `SELECT 1 AS a\xa0$x$;\nSELECT 2 AS $x$;` | `UnsafeStatementSplitError` (the no-break space continues the name, so a\xa0$x$ is one alias and no dollar quote opens there; the second statement's $x$ is the unterminated one, as for a$x$; measured 2026-10-19 with psql 16.14, ysqlsh, cockroach sql and psycopg 3 against PostgreSQL 16.14, CockroachDB v24.3.18 and YugabyteDB 2026.1.2.0, and with psycopg 3 against Redshift: the first statement runs, the second is rejected as an unterminated dollar-quoted string; U+2003, U+3000, U+0085 and U+2028 give the same) |
| 30k | `SELECT 1 AS a\u2003E'\';\nSELECT 2;` | `SELECT 1 AS a\u2003E'\'` · `SELECT 2` (an E after a name that holds an em space is part of the name, not an escape prefix, so the string is plain and its backslash is literal: two statements; measured 2026-10-19 with psql 16.14, ysqlsh and cockroach sql: SELECT 2 runs; if the E were a prefix the string would be unterminated) |
| 30l | `CREATE TABLE t\u3000$$ (x INT);\nSELECT 1;` | `CREATE TABLE t\u3000$$ (x INT)` · `SELECT 1` (t\u3000$$ is one table name; measured 2026-10-19 on PostgreSQL 16.14, CockroachDB v24.3.18 and YugabyteDB 2026.1.2.0: creating t and then t followed by an ideographic space makes two tables, the second named 74e38080 in hex) |
| 30m | `SELECT 1 AS \x85$x$;\nSELECT 2 AS $x$;` | `UnsafeStatementSplitError` (a name may also begin with the character: \x85$x$ is one alias; measured 2026-10-19 with psql 16.14, ysqlsh, cockroach sql and psycopg 3 against the three engines and Redshift: the second statement is rejected as unterminated) |
| 30n | `SELECT 1 AS a\u20ac$x$;\nSELECT 2 AS $x$;` | `UnsafeStatementSplitError` (a character that is no blank at all, here the euro sign, is a name character too, as is U+2014 and U+1F600: every character above U+007F continues a name on these engines; U+1680, U+2000, U+200A, U+200B, U+2029, U+202F, U+205F, U+FEFF and U+00E9 were measured the same way; measured 2026-10-19 on the three engines and Redshift as in row 30j) |
| 30o | `SELECT 1 AS a\x1c$x$;\nSELECT 2 AS $x$;` | `SELECT 1 AS a\x1c$x$;\nSELECT 2 AS $x$` (U+001C is an ASCII control character, not a name character, so $x$ opens a dollar quote after it and the script is one statement that the engine rejects at the control character; measured 2026-10-19 with psql 16.14, ysqlsh and cockroach sql: one syntax error near the character, no second statement) |
| 30p | `COPY t (a) FROM STDIN\xa0;\n1\n\.` | `UnsupportedMetaCommandError` (STDIN followed by a no-break space is one name, not the keyword, so the statement is no COPY header and the backslash-period line is a psql command that dblift does not run; measured 2026-10-19 with psql 16.14 against PostgreSQL 16.14: syntax error near the name, then invalid command backslash-period) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| `standard_conforming_strings = off` | plain strings are read without backslash escapes | a server setting the splitter cannot see; off has not been the default since 9.1 |
| psql variables and conditionals (`\if`) | rejected | a client preprocessor, not SQL |
| `\copy` | rejected | its client-side file access has no server equivalent in the migration model; `COPY FROM STDIN` is supported |
| Single-line mode (`-S`) | not modelled | psql option, not a property of the script |

## 12. Implementation

Code: the shared `dblift/core/sql_parser/lexical_engine.py`,
`lexical_tokenizer.py` and `lexical_statement_parser.py`, driven by
`dblift/db/plugins/postgresql/parser/lexical_spec.py`. The former dialect
tokenizer and statement parser are removed. Execution resolves the specification
from the plugin; `postgresql_regex_parser.py` projects the same shared engine
for analysis and extraction. Comment masking uses the same token scan. The
splitter returns `Statement` records (`dblift/core/sql_parser/statement.py`):
text without its terminator, line, terminator, kind, and scanner-derived analysis constituents. COPY text retains the exact row payload and line endings. The conformance
table in section 10 is compiled into
`tests/unit/core/sql_parser/test_postgresql_spec_conformance.py`.

Unterminated lexemes (comment, string, quoted identifier, dollar quote) and
unsupported meta-commands are refusals, not input to a fallback.

The shared engine checks COPY terminators at their source position without
copying the remainder of the script for each block; repeated COPY units have
bounded source-slicing cost.

The string projection `split_statements()` keeps the trailing `;`; the
`Statement.text` excludes it.

## 13. Family members

| Plugin | Override of this spec | Evidence |
| --- | --- | --- |
| AlloyDB, Aurora PostgreSQL, Citus, Neon, Supabase, TimescaleDB | none | `make_pg_compatible_plugin` with no parser override |
| YugabyteDB | none | `yugabytedb/plugin.py:31-39` records a live check that block comments nest |
| CockroachDB | none | `cockroachdb/quirks.py:24-32` records a live check that block comments nest |
| Redshift | plugin spec derives from PostgreSQL with nonnested block comments, backslash escapes in plain strings and the form feed among its blanks | measured 2026-10-20 on Redshift Serverless 1.0.477953 (reports `PostgreSQL 8.0.2`) with psycopg 3.3.5 (autocommit, simple protocol) and psql: space, tab, line feed, carriage return and form feed are blanks alone, before, after and between tokens; the vertical tab, C0 controls U+0001 and U+001C to U+001F and DEL are rejected with SQLSTATE 42601 everywhere; the no-break space, U+0085, U+1680, U+2000 to U+200B, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF are rejected with 42601 alone, before a statement, between tokens and as a piece of its own (rows 30d to 30f and 30h are measured; 30g and 30i follow from the lone-piece and leading shapes, not measured in their own form). Unlike PostgreSQL 16, Redshift accepts these Unicode spaces at the end of a statement (`SELECT 1\xa0` and `SELECT 1\xa0;` run). dblift sends them and does not trim them, so there is no difference to correct |
