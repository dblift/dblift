# Oracle — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | Oracle Database 12c+ scripts written for SQL\*Plus / SQLcl |
| Code facts taken from | OSS `develop` `61b1d83f` |
| Vendor references, fetched 2026-10-10 | *SQL\*Plus User's Guide and Reference 19c*, ch. 4 "SQL\*Plus Basics": "Running SQL Commands", "Running PL/SQL Blocks", "Running SQL\*Plus Commands"; *SQL Language Reference 19c*, "Text Literals", "Comments" |
| Live verification | sqlplus 23.x on Oracle Free 23ai, 2026-10-10 (XE 21c runs in the maintainers' CI, not yet measured) |
| Engine subclass | alternative quoting `q'…'` |

The central decision of this specification is that **a PL/SQL unit ends at
`/`, not at an `END` found by counting**. SQL\*Plus: "Terminate PL/SQL
subprograms by entering a period (.) by itself on a new line. You can also
terminate and execute a PL/SQL subprogram by entering a slash (/) by itself
on a new line." and "A semicolon (;) is treated as part of the PL/SQL
subprogram and will not execute the command." Whether a statement is a
PL/SQL unit is decided from its first keywords (§5), so no `BEGIN`/`END`
depth tracking exists in this spec. Every depth-tracking defect in the
current parser (§12) disappears with it.

## 1. String literals

| Form | Opens | Closes | Escape inside | Vendor rule (Text Literals) |
| --- | --- | --- | --- | --- |
| String | `'` | `'` | `''` | "To represent one single quotation mark within a literal, enter two single quotation marks." |
| National string | `N'` / `n'` | `'` | `''` | lexically a plain string |
| Alternative quoting | `q'd` / `Q'd` / `nq'd` / `NQ'd`, where `d` is the *quote_delimiter* | `d'`, with `d` mapped: `[`→`]`, `{`→`}`, `<`→`>`, `(`→`)`; any other `d` closes with the same character | **none** | "quote_delimiter is any single- or multibyte character except space, tab, and return." "If the opening quote_delimiter is one of [, {, <, or (, then the closing quote_delimiter must be the corresponding ], }, >, or ). In all other cases, the opening and closing quote_delimiter must be the same character." A space, tab or newline after `q'` is an error. |

An unterminated literal is an error, never "read to end of file".

## 2. Identifiers

| Form | Opens | Closes | Escape inside |
| --- | --- | --- | --- |
| Quoted | `"` | `"` | none (a `"` cannot appear inside a quoted identifier) |
| Regular | letter | end of `[A-Za-z0-9_$#]` | — |

## 3. Comments

| Form | Opens | Closes | Nests | Vendor rule (Comments) |
| --- | --- | --- | --- | --- |
| Line | `--` | end of line | — | "Begin the comment with – (two hyphens). … End the comment with a line break." |
| Block | `/*` | the first `*/` | **no** | "Begin the comment with a slash and an asterisk (/\*). … End the comment with an asterisk and a slash (\*/)." The Oracle manual does not say so explicitly; Snowflake's SnowConvert documentation does, in comparing engines: `/*/` "can start a nesting inside the block comment, or finish the whole block … the comment behaves differently in Teradata and SQL Server than in Oracle and Snowflake", i.e. Oracle finishes the block. |
| Hint | `/*+` … `*/`, `--+` | as above | — | a comment to the splitter; kept in the statement text |

**Stray `*/` after `;`.** Oracle comments do not nest, so in
`/* a /* b */ DROP TABLE t; */` the `DROP` is outside the comment and the `;`
is not the last text on its line. Under the §4 rule that `;` is not a
terminator; the splitter rejects the line. SQL\*Plus itself keeps the text in
its buffer up to the next line ending in `;` and the server rejects the joined
text, so neither client runs the `DROP`. The OSS changelog records the
current code reproducing the buffer behaviour; the spec replaces it with the
explicit error. Measured: SQL\*Plus does not run the `DROP`; the server
rejects the `DROP TABLE t13; */` line and `T13` still exists afterwards
(sqlplus 23.x, Oracle Free 23ai, 2026-10-10: rc 1, ORA-03405, row 13).

## 4. Terminators

SQL\*Plus, "Running SQL Commands": a SQL command ends "with a semicolon (;)",
"with a slash (/) on a line by itself", or "with a blank line" (which ends
input without running).

| Terminator | Rule |
| --- | --- |
| `;` | ends a **SQL** statement (one that is not a PL/SQL unit, §5) at parenthesis depth 0 **when it is the last non-blank text on its line**. SQL\*Plus 5.3.4: "Do not put comments after statement terminators (period, semicolon or slash). … SQL\*Plus expects no text after a statement terminator and is unable to process the command." (ORA-00911). A `;` followed by more text on the same line is therefore not a terminator for SQL\*Plus; the splitter **rejects** it with an error naming the line, rather than silently running two statements the client would not, or one the client would reject. This subsumes the stray-`*/` rule below. Measured, the server error is ORA-03405 "End of query reached; no additional text should follow." for a trailing comment, a second statement and a directive after the `;` (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: rows 16a, 16b, 19, each rc 1, ORA-03405; the documented ORA-00911 was not what the server returned). |
| `/` | ends any statement, SQL or PL/SQL, **only when it is alone on its line** (SQL\*Plus accepts leading blanks per its reference; live verification measured only an unindented `/`). A `/` followed by other text is not a terminator and stays statement text: `/ 2; END;` inside a package body compiled VALID (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 5, rc 0, `PACKAGE BODY` VALID with its source lines 3-6 intact); `/ -- done` after a statement without `;` was sent to the server with the statement and rejected (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 25, rc 1, ORA-00922), and the splitter sends the same text, so the server rejects it for both. After a PL/SQL unit the `/` is **required**; after a SQL statement already ended by `;` a following `/` alone on its line is a SQL\*Plus re-execution of the buffer and is **rejected** with an error (it would run the statement twice; sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 22, "1 row created." twice, `T22` = 2 rows). |
| blank line | **not** a terminator: the splitter behaves as `SET SQLBLANKLINES ON`. A script that relies on a blank line to end a statement is listed under *Not handled*. (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: probe 40: with the default `SQLBLANKLINES OFF`, sqlplus reports SP2-0042 and creates nothing; with `SET SQLBLANKLINES ON` the table is created) |
| `.` alone on a line | ends a PL/SQL buffer without running it; **rejected**, because dropping the block silently would hide a statement the author wrote (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 26, rc 0, the buffered `BEGIN … END;` was discarded without running and the script continued, `T26` created) |

A SQL statement with no `;` but followed by `/` alone on a line is valid
SQL\*Plus and is one statement.

## 5. Blocks: what is a PL/SQL unit

A statement is a PL/SQL unit, and therefore ends only at `/`, when its first
tokens after comments match one of:

```
DECLARE
BEGIN
<<label>>  (then DECLARE or BEGIN)
CREATE [OR REPLACE] [EDITIONABLE | NONEDITIONABLE]
    { FUNCTION | PROCEDURE | PACKAGE [BODY] | TYPE [BODY] | TRIGGER | LIBRARY }
CREATE [OR REPLACE] [AND { COMPILE | RESOLVE }] [NOFORCE] JAVA { SOURCE | CLASS | RESOURCE }
CREATE [OR REPLACE] [IF NOT EXISTS] MLE MODULE          (23ai; to verify live)
```

SQL\*Plus 4.5.1, "Running PL/SQL Blocks": "Entering any of these commands
places you in PL/SQL mode"; the list as printed is CREATE FUNCTION, LIBRARY,
PACKAGE, PACKAGE BODY, PROCEDURE, TRIGGER, TYPE. `TYPE BODY`, `JAVA SOURCE`
and `MLE MODULE` are spec additions. `TYPE BODY` is verified (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 7, rc 0, "Type body created.", VALID). `JAVA SOURCE`: **to verify live**; Oracle Free has no JVM (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 24, rc 1, ORA-29538: Java not installed). `MLE MODULE`: **to verify live**; MLE is not enabled on Oracle Free, even with `CREATE MLE` granted (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 27, ORA-00439: feature not enabled: MLE). `CREATE MLE MODULE`
matters because its body is inline, unquoted and contains `;`: the 23ai SQL
Language Reference says "Do not encapsulate the character sequence within
quotes. The character sequence is delimited by the end of the DDL statement."
`CREATE TYPE t AS OBJECT (…)` has no body and still ends at `/`.
`CREATE VIEW v AS SELECT type FROM t;` and `SELECT begin FROM t;` are SQL
statements: the keyword is not at the statement head. SQL\*Plus "scans the
first few keywords of each new statement" and says "Do not put comments
within the first few keywords"; the spec's "first tokens after comments" is
more lenient than the client, deliberately.

Inside a PL/SQL unit nothing is counted: `;`, `BEGIN`, `END`, `CASE`,
`LOOP`, labels and nested blocks are text until the `/`.

## 6. Client directives

SQL\*Plus, "Running SQL\*Plus Commands": "You do not need to end a SQL\*Plus
command with a semicolon." "You can continue a long SQL\*Plus command by typing
a hyphen at the end of the line and pressing Return."

A directive is recognised only where a statement can begin (top of script,
after a statement-ending `;`, after a `/` line, after another directive),
with only blanks and block comments before it on the line. Block comments
before the directive on the same line are allowed (sqlplus 23.x, Oracle Free
23ai, 2026-10-10: `/* c */ PROMPT hi` printed `hi`). It runs to the end of
the line; a trailing `-` continues it on the next line (sqlplus 23.x, Oracle
Free 23ai, 2026-10-10: `REM a -` followed by `SELECT 2 ...;` swallowed the
`SELECT`, only the next statement ran). Its text is **never lexed as SQL**:
`REM don't` opens no literal. In the text of other directives a `--` ends the
directive and starts a comment, and a trailing `-` continues it, except inside
a single- or double-quoted span (`EXEC p('a -- b')`, `DEFINE x = 'a--b'`); an
unclosed quote on a line means neither a comment nor a continuation there. For
`PROMPT`, `REM` and `REMARK` the whole rest of the line is the text, `--` and
quotes included. A `--` in unquoted text of any other directive starts a
comment (kept from the previous rule; not measured).

Substitution variables apply on the `DEFINE` line itself: `DEFINE b = &a`
stores the value of `a` (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: `DEFINE a
= q`, `DEFINE b = &a`, `SELECT '&b'` gave `q`). A comment-only line before a
statement is not substituted: no prompt and the statement ran (sqlplus 23.x,
Oracle Free 23ai, 2026-10-10: `-- R&D` before a statement); a comment inside a
statement is.

| Directive | Splitter action |
| --- | --- |
| `SET` (all options except those below), `SHOW`, `SPOOL`, `PROMPT`, `REM`/`REMARK`, `COLUMN`/`COL`, `TTITLE`/`BTITLE`, `REPHEADER`/`REPFOOTER`, `BREAK`, `COMPUTE`, `CLEAR`, `TIMING`, `VARIABLE`, `PRINT`, `DESC`/`DESCRIBE`, `WHENEVER OSERROR` | **drop and record** (`kind="directive"`); `PROMPT` text is logged |
| `SET DEFINE {ON|OFF|char}`, `SET SCAN {ON|OFF}`, `DEFINE x = v`, `UNDEFINE x` | **record and apply positionally** to `&x`/`&&x` substitution in the statements that follow; a `.` ends a reference (`&x.suffix`). `SET SCAN` is obsolete in favour of `SET DEFINE` (SQL\*Plus reference) and acts as `SET DEFINE ON|OFF` |
| `SET SERVEROUTPUT ON|OFF` | record; execution enables `DBMS_OUTPUT` retrieval |
| `WHENEVER SQLERROR {EXIT … | CONTINUE …}` | record; execution applies the policy to the statements that follow. An unrecognised `WHENEVER SQLERROR` action is refused. |
| `EXEC[UTE] stmt[;]` | **rewrite** to the PL/SQL unit `BEGIN stmt; END;` after stripping one trailing `;` from `stmt`; never dropped. SQL\*Plus documents only "Executes a single PL/SQL statement"; EXEC runs the call (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 16, two EXEC lines → T16 has 2 rows); the `BEGIN stmt; END;` rewrite is the splitter's choice of equivalent, not a measured client behaviour |
| `EXIT` / `QUIT` | everything after it is **not executed**; the remainder is not recorded: the parser stops and logs a warning naming the count and the first ignored line (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 17, rc 0, `T17` empty: the `INSERT` after `EXIT` never ran). An exit status (`EXIT FAILURE`, `EXIT n`, `EXIT ROLLBACK`) is recorded with the directive and not modelled: the statements before it ran; migration status is dblift's (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: `EXIT FAILURE` exit code 1, `EXIT 3` exit code 3) |
| `@file`, `@@file`, `START file`, `HOST`, `!cmd`, `ACCEPT`, `PAUSE`, `CONNECT`, `CONN`, `DISCONNECT`, `PASSWORD`, `SET SQLTERMINATOR`, `SET BLOCKTERMINATOR`, `SET SQLBLANKLINES`, `SET SQLPREFIX`, `SET CMDSEP`, `SET ESCAPE`, `SET CONCAT` | **reject** with `UnsupportedMetaCommandError` naming the directive and line |
| `SET ESCAPE`, `SET CONCAT` (rows above) | they change how `&` and `.` are read (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: `SET DEFINE ON`, `DEFINE x = v`, `SET ESCAPE ON`, `SELECT '\&x' FROM dual` gave `&x`: the escape suppresses substitution) |
| a directive after a `;` on the **same** line | **reject**: SQL\*Plus sends the whole line to the server, which fails with ORA-03405 (§4; sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 19, rc 1, ORA-03405 "End of query reached; no additional text should follow."); the current code silently loses the following statement |

`CONNECT` is a directive only when not followed by `TO` (`CREATE DATABASE LINK
… CONNECT TO …` is SQL). Abbreviations SQL\*Plus accepts (`SET SERVEROUT`,
`SET TERM`, `SET FEED`) are recognised by the same prefix rule SQL\*Plus
uses: the documented minimum abbreviation of each option.

## 7. Raw blocks

| Block | Rule |
| --- | --- |
| `… WRAPPED` PL/SQL | no special handling: the body is a PL/SQL unit ending at `/`; a wrapped body never contains a line consisting of `/` alone |
| `CREATE JAVA SOURCE … AS …` | a PL/SQL unit by §5; the Java text is not lexed as SQL (`//` and `/* */` inside it are irrelevant because nothing but a `/` line can end it) |

## 8. Transaction markers

None. Oracle DDL commits implicitly; execution policy owns that knowledge.

## 9. Engine subclass

Alternative quoting: the closing delimiter is computed from the opening one,
including the four bracket pairs and the "same character" rule. Everything
else in this spec is data.

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `CREATE TABLE a (x NUMBER);\nCREATE TABLE b (y NUMBER);` | `CREATE TABLE a (x NUMBER)` · `CREATE TABLE b (y NUMBER)` |
| 2 | `CREATE TABLE a (x NUMBER)\n/\nCREATE TABLE b (y NUMBER);` | `CREATE TABLE a (x NUMBER)` · `CREATE TABLE b (y NUMBER)` (the slash ends a SQL statement that has no semicolon) |
| 3 | `CREATE OR REPLACE PROCEDURE p AS BEGIN IF 1=1 THEN NULL; END IF; END;\n/\nCREATE TABLE t (id NUMBER);` | `CREATE OR REPLACE PROCEDURE p AS BEGIN IF 1=1 THEN NULL; END IF; END;` (the PL/SQL unit; its terminator is the slash) · `CREATE TABLE t (id NUMBER)` |
| 4 | `BEGIN\n  OPEN c FOR SELECT 1 FROM dual;\n  NULL;\nEND;\n/\nSELECT 1 FROM dual;` | `BEGIN\n  OPEN c FOR SELECT 1 FROM dual;\n  NULL;\nEND;` · `SELECT 1 FROM dual` |
| 5 | `CREATE OR REPLACE PACKAGE BODY pk AS\n  PROCEDURE a IS BEGIN NULL; END;\n  FUNCTION f RETURN NUMBER IS BEGIN RETURN 4\n/ 2; END;\nBEGIN NULL;\nEND pk;\n/` | `CREATE OR REPLACE PACKAGE BODY pk AS\n  PROCEDURE a IS BEGIN NULL; END;\n  FUNCTION f RETURN NUMBER IS BEGIN RETURN 4\n/ 2; END;\nBEGIN NULL;\nEND pk;` (one unit: the line beginning with a slash and 2; END; is statement text, §4) |
| 6 | `CREATE TYPE t AS OBJECT (id NUMBER);\n/\nCREATE TABLE u (id NUMBER);` | `CREATE TYPE t AS OBJECT (id NUMBER);` (a PL/SQL unit, ended by the slash) · `CREATE TABLE u (id NUMBER)` |
| 7 | `CREATE TYPE BODY tb AS MEMBER FUNCTION m RETURN NUMBER IS BEGIN RETURN 1; END; END;\n/` | `CREATE TYPE BODY tb AS MEMBER FUNCTION m RETURN NUMBER IS BEGIN RETURN 1; END; END;` (one unit) |
| 8 | `CREATE VIEW v AS SELECT type, package FROM t;\nSELECT begin FROM t;` | `CREATE VIEW v AS SELECT type, package FROM t` · `SELECT begin FROM t` |
| 9 | `INSERT INTO t VALUES (q'[it's; fine]');\nINSERT INTO t VALUES (nq'{x;y}');\nSELECT 1 FROM dual;` | `INSERT INTO t VALUES (q'[it's; fine]')` · `INSERT INTO t VALUES (nq'{x;y}')` · `SELECT 1 FROM dual` |
| 10 | `INSERT INTO t VALUES (q'!a;b!');\nSELECT 1 FROM dual;` | `INSERT INTO t VALUES (q'!a;b!')` · `SELECT 1 FROM dual` |
| 11 | `INSERT INTO t VALUES (q' x ');` | `error` (whitespace quote delimiter) |
| 12 | `CREATE TABLE a (v VARCHAR2(20) DEFAULT '-- x');\nCREATE TABLE b (id NUMBER);` | `CREATE TABLE a (v VARCHAR2(20) DEFAULT '-- x')` · `CREATE TABLE b (id NUMBER)` |
| 13 | `/* outer /* inner */ DROP TABLE t; */\nSELECT 1 FROM dual;` | `error` at line 1: the semicolon is followed by text on the same line (§4); the DROP is never run, matching SQL\*Plus, which also never runs it |
| 14 | `PROMPT Creating customer's table\nCREATE TABLE a (x NUMBER);\nREM don't run twice\nCREATE TABLE b (y NUMBER);` | directive · `CREATE TABLE a (x NUMBER)` · directive · `CREATE TABLE b (y NUMBER)` |
| 15 | `SET DEFINE OFF\nINSERT INTO t VALUES ('a&b');\nSET DEFINE ON\nDEFINE s = x\nCREATE TABLE &s.1 (id NUMBER);` | directives recorded · `INSERT INTO t VALUES ('a&b')` (unchanged) · `CREATE TABLE x1 (id NUMBER)` |
| 16 | `EXEC dbms_output.put_line('hi');\nSELECT 1 FROM dual;` | `BEGIN dbms_output.put_line('hi'); END;` (PL/SQL unit; one trailing semicolon stripped before wrapping) · `SELECT 1 FROM dual` |
| 16a | `SELECT 1 FROM dual; -- note\nSELECT 2 FROM dual;` | `error` at line 1: text after the terminator (SQL\*Plus 5.3.4; sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 16a, rc 1, ORA-03405 "End of query reached; no additional text should follow.", nothing created) |
| 16b | `INSERT INTO t VALUES (1); INSERT INTO t VALUES (2);` | `error` at line 1: the semicolon is not the last text on its line (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 16b, rc 1, ORA-03405 "End of query reached; no additional text should follow."; `T16B` created, 0 rows) |
| 17 | `SELECT 1 FROM dual;\nEXIT\nSELECT 2 FROM dual;` | `SELECT 1 FROM dual` · directive record with warning "1 statement after EXIT ignored" |
| 18 | `@@setup.sql\nSELECT 1 FROM dual;` | `UnsupportedMetaCommandError` (line 1, `@@`) |
| 19 | `SELECT 1 FROM dual; PROMPT x\nSELECT 2 FROM dual;` | `UnsupportedMetaCommandError` (line 1, directive after `;` on the same line) |
| 20 | `CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\nCREATE TABLE t (id NUMBER);` | `error`: PL/SQL unit not terminated by a slash before end of input (SQL\*Plus would hang waiting for it) |
| 21 | `BEGIN\n  EXECUTE IMMEDIATE 'CREATE TABLE x (\n  id NUMBER)';\nEND;\n/` | `BEGIN\n  EXECUTE IMMEDIATE 'CREATE TABLE x (\n  id NUMBER)';\nEND;` (one unit: the line starting with id NUMBER is inside a literal, not a directive) |
| 22 | `CREATE TABLE t (id NUMBER);\n/\n` | `error`: the slash would re-execute the previous statement |
| 23 | `WHENEVER SQLERROR EXIT FAILURE\nCREATE TABLE t (id NUMBER);` | `WHENEVER SQLERROR EXIT FAILURE;` (a directive: recorded, and handed to execution, which applies the policy to the statements that follow) · `CREATE TABLE t (id NUMBER)` |
| 24 | `CREATE OR REPLACE AND COMPILE JAVA SOURCE NAMED "H" AS\npublic class H { int f() { return 1; } }\n/` | `CREATE OR REPLACE AND COMPILE JAVA SOURCE NAMED "H" AS\npublic class H { int f() { return 1; } }` (one unit) (Oracle Free: ORA-29538, unverifiable there) |
| 25 | `CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1);` | `CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1)` (the slash line is text, the semicolon ends it; the server rejects it, as it rejected it for SQL\*Plus) |
| 26 | `BEGIN\n  NULL;\nEND;\n.\nCREATE TABLE t26 (id NUMBER);` | `error`: a `.` alone discards the buffered unit in SQL\*Plus; the splitter rejects rather than silently dropping a block |
| 27 | `CREATE OR REPLACE MLE MODULE m27 LANGUAGE JAVASCRIPT AS\nexport function f() { return 1; }\n/` | **to verify live** (ORA-00439 on Oracle Free) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| Blank-line termination (`SQLBLANKLINES OFF`, the SQL\*Plus default) | blank lines are whitespace | ending a statement on a blank line never runs it in SQL\*Plus either; scripts that depend on it are interactive artefacts (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: probe 40, SP2-0042 and nothing created under the default) |
| `.` alone on a line | rejected (§4) | SQL\*Plus discards the buffered unit without running it (sqlplus 23.x, Oracle Free 23ai, 2026-10-10: row 26) |
| `SET SQLTERMINATOR`, `SET BLOCKTERMINATOR`, `SET CMDSEP` | rejected | they redefine the lexer at runtime; no migration tool supports them |
| `@`/`@@`/`START` includes | rejected | file inclusion is the migration framework's job |
| Interactive directives (`ACCEPT`, `PAUSE`, `CONNECT`, `HOST`) | rejected | no terminal, no second connection |
| A PL/SQL unit without `/` | error | SQL\*Plus does not run it either; the current code's depth-counting acceptance is what this spec removes |

## 12. Implementation

Code: `dblift/db/plugins/oracle/parser/` (`oracle_tokenizer.py`,
`oracle_statement_parser.py`, `_unit_heads.py`, `_directives.py`,
`oracle_parser.py`) and `quirks.py`. The regex path (`_statement_splitter.py`,
`_plsql_block.py`) remains behind `parse_sql` for object extraction only.

Facts established by reading and running the code; each is a row above or the
reason for a rule:

- A SQL statement ended only by `/` (row 2) is merged with the next statement
  in the regex path.
- `OPEN c FOR SELECT ...` or `SELECT ... FOR UPDATE` inside a block adds depth
  that never closes in the regex path; the `/` is then ignored (row 4).
- A column named `TYPE`, `PACKAGE`, `FUNCTION`, `PROCEDURE` or `TRIGGER` at
  parenthesis depth 0 in any `CREATE`, or a column named `begin`, switches
  the regex path's delimiter to `/` (row 8).
- The regex path does not know alternative quoting and cuts `q'[it's; fine]'`
  and `nq'{x;y}'` at the inner `;`; it scans `CREATE TYPE ... AS OBJECT` to end
  of file and splits `CREATE TYPE BODY` after its first member (row 7).
- `CREATE JAVA SOURCE` is cut at the first `;` (row 24).

Tests to re-point (about 470 functions): `tests/unit/core/sql_parser/oracle/*`,
`tests/unit/core/sql_parser/test_oracle_parser*.py`,
`tests/unit/test_tokenization_oracle*.py`,
`tests/unit/test_oracle_sqlplus_directive_*.py`,
`tests/unit/core/migration/executor/test_execution_engine_sqlplus.py`,
`tests/integration/parsers/test_oracle_parser.py` (live).
