# Amazon Redshift — lexical specification for statement splitting

Where Redshift reads a script differently from PostgreSQL ([postgresql.md](postgresql.md)); every other
rule is the PostgreSQL one.

## Status

| Item | Value |
| --- | --- |
| Covers | scripts sent to Redshift as text, one statement at a time |
| Live verification | psycopg 3.3.5 (autocommit, simple protocol) against Redshift Serverless 1.0.485645 (`version()` reports `PostgreSQL 8.0.2`), 2026-10-20. Every row of section 10 and every entry of section 2 was sent to the engine alone; the engine was read-only for them (temporary tables and rolled-back transactions only). The first runs were made on the same cluster before its build was read; the last campaign repeated all of them on 1.0.485645 with the same answers. The blank rows of postgresql.md section 13 were measured on 1.0.477953 |

## 2. Differences from the PostgreSQL specification

| Fact | PostgreSQL | Redshift (measured) |
| --- | --- | --- |
| Block comments | nest | nest: `/* a /* b */ c */ SELECT 1` runs and `/* a /* b */ SELECT 1` is rejected as an unterminated comment |
| Backslash in `'…'` | literal (`standard_conforming_strings`) | escapes the next character: `'a\'b'` is `a'b`, `'a\\'` is `a\`, `'a\nb'` holds a line feed, `'a\'` is unterminated; `SHOW standard_conforming_strings` is an unknown parameter |
| `E'…'` | escape string | not a prefix: `E` is read as a type name (`type "e" does not exist`) before an ordinary backslash-escaping string |
| `"…"` | doubled quote only | doubled quote only: `"a\"b"` is a syntax error, `"a""b"` is `a"b` |
| `$$…$$`, `$tag$…$tag$` | accepted anywhere | accepted anywhere, outside `CREATE FUNCTION` too (`SELECT $$a;b$$`); `a$x$` is a name |
| `COPY … FROM STDIN` | data block up to `\.` | a syntax error at `STDIN`: no data block |
| `BEGIN ATOMIC` function body | accepted | a syntax error at `BEGIN` |
| Unquoted and quoted names | fold to lower case | fold to lower case unless `enable_case_sensitive_identifier` is on (off by default): `"AbC"` is `abc`, `"TMPA"` finds `TmpA`; only ASCII letters fold (`Éa`) |
| `[name]` | array subscript | not a quote: the brackets around a name are dropped (`CREATE TEMP TABLE [t]` creates `t`, `["a""b"]` creates `a"b`); a space or a semicolon inside is a syntax error |
| Unicode spaces | continue a name | continue a name, at the end of a statement too: `DELETE FROM t<U+00A0>;` names a relation `t<U+00A0>` |

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| R1 | `/* a /* b */ c */ SELECT 1;` | `SELECT 1` (the engine returns 1; the leading comment is not part of the statement) |
| R2 | `/* a /* b */ SELECT 1;` | `UnsafeStatementSplitError` (42601, unterminated /* comment) |
| R3 | `SELECT 1 /* a /* b */ c */; SELECT 2;` | `SELECT 1 /* a /* b */ c */` · `SELECT 2` |
| R4 | `SELECT /* /* */ 1;` | `UnsafeStatementSplitError` (42601, unterminated /* comment) |
| R5 | `SELECT 1; /* a /* b */ c */ SELECT 2;` | `SELECT 1` · `SELECT 2` |
| R6 | `SELECT 1; /* a /* b */ SELECT 2;` | `UnsafeStatementSplitError` (42601, unterminated /* comment) |
| R7 | `SELECT 1 /* x` | `UnsafeStatementSplitError` (42601, unterminated /* comment) |
| R8 | `SELECT 1; -- x` | `SELECT 1` |
| R9 | `SELECT 1; /* x */` | `SELECT 1` |
| R10 | `/* only */` | `(empty)` |
| R11 | `SELECT 'a\'b;c'; SELECT 2;` | `SELECT 'a\'b;c'` · `SELECT 2` |
| R12 | `SELECT 'a\\\\'; SELECT 2;` | `SELECT 'a\\\\'` · `SELECT 2` (two backslashes in the script: one escaped backslash) |
| R13 | `SELECT 'a\'; SELECT 2;` | `UnsafeStatementSplitError` (42601, unterminated quoted string) |
| R14 | `SELECT E'a\'b;c'; SELECT 2;` | `SELECT E'a\'b;c'` · `SELECT 2` |
| R15 | `SELECT 'a\\\\\\'b;c'; SELECT 2;` | `SELECT 'a\\\\\\'b;c'` · `SELECT 2` (three backslashes in the script: an escaped backslash, then an escaped quote) |
| R16 | `SELECT 'it''s;'; SELECT 2;` | `SELECT 'it''s;'` · `SELECT 2` |
| R17 | `SELECT $$a;b$$; SELECT 2;` | `SELECT $$a;b$$` · `SELECT 2` |
| R18 | `SELECT $tag$a;b$tag$; SELECT 2;` | `SELECT $tag$a;b$tag$` · `SELECT 2` |
| R19 | `SELECT $$a; SELECT 2;` | `UnsafeStatementSplitError` (42601, unterminated dollar-quoted string) |
| R20 | `SELECT 1 AS "a""b;"; SELECT 2;` | `SELECT 1 AS "a""b;"` · `SELECT 2` |
| R21 | `SELECT 1 AS "a\"b"; SELECT 2;` | `UnsafeStatementSplitError` (42601, a backslash does not escape the quote of a name) |
| R22 | `SELECT 1 AS a$x$; SELECT 2;` | `SELECT 1 AS a$x$` · `SELECT 2` |
| R23 | `COPY t FROM STDIN;\n1\nSELECT 2;` | `COPY t FROM STDIN` · `1\nSELECT 2` (42601 at STDIN: no data block) |
| R24 | `CREATE FUNCTION f() RETURNS int BEGIN ATOMIC SELECT 1; SELECT 2; END; SELECT 3;` | `CREATE FUNCTION f() RETURNS int BEGIN ATOMIC SELECT 1` · `SELECT 2` · `END` · `SELECT 3` (42601 at BEGIN) |
| R25 | `SELECT 1;; SELECT 2;` | `SELECT 1` · `SELECT 2` |
| R26 | `SELECT 1 AS a\u00a0; SELECT 2;` | `SELECT 1 AS a\u00a0` · `SELECT 2` (the alias is a followed by U+00A0) |
| R27 | `SELECT 1 AS [a;b]; SELECT 2;` | `SELECT 1 AS [a` · `b]` · `SELECT 2` (42601 at the semicolon: a bracket is not a quote) |
| R28 | `/*DELIMITER //*/ SELECT 1;` | `UnsafeStatementSplitError` (42601, unterminated /* comment: the `/*` inside the comment opens a nested one) |
| R29 | `COPY t (a) FROM STDIN;\n1\n\\.\nSELECT 1;` | `UnsupportedMetaCommandError` (42601 at STDIN: no data block, so the `\.` line is a command no client here runs) |
| R30 | `SELECT 1;\n/* a /* b */ c */;\nSELECT 2;` | `SELECT 1` · `SELECT 2` (the middle piece is a comment) |

## 12. Statement facts

Redshift statements are read by `SqlglotStatementFactsReader("redshift")` (sqlglot's `redshift` grammar)
after the shared lexical splitter above; `HybridParser("redshift")` and `SqlGlotParser("redshift")`
are refused like the other activated dialects, and the `regex` parser type still splits and masks.
The Redshift-specific readings are `_redshift_facts` in `dblift/core/sql_parser/sqlglot_statement_facts.py`;
materialized views and bare DML targets share PostgreSQL's branches. `undo_reverses_statement_facts`
stays false: undo asks for review.

| Form | Reading | Measured on Redshift Serverless 1.0.485645 (2026-10-20) |
| --- | --- | --- |
| `CREATE`/`ALTER`/`DROP` `TABLE`, `VIEW` (also `WITH NO SCHEMA BINDING`), `PROCEDURE`, `FUNCTION`, `EXTERNAL TABLE`; `DISTKEY`, `SORTKEY`, `DISTSTYLE`, `ENCODE`, `BACKUP` | the object, as written; function and procedure bodies are not read | each was run in a rolled-back transaction or on a temporary table |
| `CREATE`/`DROP MATERIALIZED VIEW` | `MATERIALIZED_VIEW`, with the tables it reads | `DROP MATERIALIZED VIEW IF EXISTS` runs; `CREATE` needs a source table (0A000 otherwise); `COMMENT ON MATERIALIZED VIEW` and `ALTER VIEW` are syntax errors |
| `SELECT … INTO [TEMP[ORARY]] [TABLE] t` (also after a set operation or a CTE) | `t` is created, the tables the query reads are referenced | the table exists afterwards; `INTO UNLOGGED` is a syntax error |
| `COPY t [(cols)] FROM 's3://…' …` | `t` is altered by an `INSERT`; the source and the options are not read | loads into `t`; `COPY … TO` answers 0A000 and `COPY … FROM STDIN` is a syntax error |
| `TRUNCATE [TABLE] t` | `t` is altered | one table only: a list, `ONLY`, `CASCADE`, `RESTART IDENTITY` and `RESTRICT` are syntax errors |
| `COMMENT ON TABLE`/`COLUMN`/`VIEW` | the commented relation is altered (a column names its table) | run; `COMMENT ON INDEX`/`SEQUENCE`/`TRIGGER` answer 0A000, other targets are unread |
| `CREATE`/`DROP SCHEMA s` | the schema | a two-part name is `database.schema` (3D000 "producer database"); schema elements, `QUOTA` and `AUTHORIZATION` are not read |
| `MERGE INTO t USING …` | `t` is altered, the sources and actions are unread | the target takes no alias; `WITH … MERGE` is a syntax error; the single-`WHEN` form answers 0A000 |
| `WITH … UPDATE`/`DELETE`/`SELECT`, `INSERT INTO t WITH … SELECT` | as PostgreSQL's: a flat CTE is read, a recursive or shadowing one is unread | `WITH … INSERT` and data-changing CTEs are syntax errors |
| `UPDATE t [AS] a SET … FROM u`, `DELETE FROM t USING u`, `DELETE t` | `t` is altered (alias removed), `u` is referenced | run; `UPDATE ONLY`/`DELETE FROM ONLY` answer 0A000, `DELETE FROM t AS a` is a syntax error |
| `[name]` in a DDL head or as a DML target | unread (diagnostic) | the brackets are dropped; the text between them is not always the name (`["a""b"]` is `a"b`) |

Read as unread (a diagnostic, no object) rather than guessed: `CREATE EXTERNAL SCHEMA`, `CREATE EXTERNAL FUNCTION`,
`CREATE LIBRARY`, `CREATE USER`, `CREATE GROUP`, `CREATE MODEL`, `UNLOAD`, `CALL`, `USE`, `GRANT`/`REVOKE` targets, a schema
name with a database part, a bracketed name, a `COPY` whose source is not one string literal, and
`ALTER TABLE … APPEND FROM` (its target is named, its source is not). Redshift parses but refuses
`CREATE INDEX`, `CREATE SEQUENCE`, `DROP TYPE` and `COMMENT ON INDEX` (0A000 or XX000), and rejects
`CREATE TRIGGER`, `CREATE TYPE … AS ENUM` and `CREATE EXTENSION` (42601): the reader still names what such
a statement would create, because it never runs.

The corpus `tests/support/facts_corpus/redshift.jsonl` and the ledger `redshift.review.json` (every difference
against the former extraction, explained) are the evidence, and `gated.json` gates the family.
