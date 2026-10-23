# Snowflake — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | Snowflake SQL scripts sent through the Python connector; SnowSQL and other client-side preprocessing were not measured. |
| Native verification | Snowflake 10.38.100 with `snowflake-connector-python` 5.0.0 on 2026-10-20. Three bounded serial campaigns attempted 39, 113 and 20 fixed SQL sources: 172 attempts and 171 distinct recorded query IDs. All three final statuses were incomplete for a client/unattributed failure or non-grammar errors; the individual attributed observations below remain usable. Query-history text and query IDs matched the 19 prior statements of the third session byte for byte. |
| Splitter implementation | A Snowflake-owned `LexicalSpec` drives the common tokenizer and `LexicalEngine` for execution and parser split views. `SnowflakeStatementParser` remains in the source tree but is disconnected from every default execution, analysis and extraction path. Statement facts are read by the shared sqlglot reader (section 13). This document describes the candidate implementation, not a published release. |
| Vendor references | Snowflake [string constants](https://docs.snowflake.com/en/sql-reference/data-types-text), [identifier requirements](https://docs.snowflake.com/en/sql-reference/identifiers-syntax), [SQL variables](https://docs.snowflake.com/en/sql-reference/session-variables), [transaction `BEGIN`](https://docs.snowflake.com/en/sql-reference/sql/begin), [Scripting blocks](https://docs.snowflake.com/en/sql-reference/snowflake-scripting/begin), [anonymous `WITH … CALL`](https://docs.snowflake.com/en/sql-reference/sql/call-with), and [EXPLAIN](https://docs.snowflake.com/en/sql-reference/sql/explain). Native results below are narrower than the general vendor descriptions. |
| Evidence limits | The campaigns used the connector, not a command-line client. An input without a query ID is unattributed; it does not prove that no bytes reached the server. Stored `CREATE PROCEDURE` and `CREATE FUNCTION` body grammar is unqualified because both quoted and unquoted `EXPLAIN` controls failed before body compilation: first with no current schema, then with missing schema access. |
| Cost | Actual total credits and monetary cost are unknown. One session's query history reported **0.000187000 cloud-services credits for 19 rows only**; it excluded the final warehouse-state query and the other sessions, and it is not warehouse-compute billing. The account-usage metering query was denied. A post-run warehouse-state observation was `STARTED`, so an idle auto-suspend tail is also possible. |

The specification governs splitting, not SQL validity. A query-ID-attributed syntax error establishes how Snowflake treated the submitted source on this version; it does not mean the splitter should silently remove the offending character. The refusals below are conservative qualification boundaries. They do not claim that every similar construct is impossible in Snowflake.

## 1. String literals

| Form | Opens | Closes | Escape and measured boundary |
| --- | --- | --- | --- |
| Single-quoted | `'` | `'` | `''` and backslash escapes. `SELECT 'it''s;ok'` and `SELECT 'it\\'s;ok'` both returned `it's;ok`; `SELECT 'a\\b;c'` returned a string with a backspace before `;c`, not literal backslash-`b`. A newline and comment-looking text inside a quoted string stayed inside it. |
| Dollar-quoted | `$$` | matching `$$` | `SELECT $$a;b$$` returned `a;b`; the semicolon did not end the literal. Only the fixed double-dollar delimiter is qualified. |

`SELECT 1 AS a$$b` succeeded: `$$` inside an unquoted identifier is **not** a string opener. `SELECT $tag$` received attributed syntax error `1003/42000`, while `SELECT $tag` reached semantic error `2211/02000` for an undefined session variable. The spec must preserve the simple `$name` variable form and must not recognize PostgreSQL-style tagged dollar strings. A conservative refusal for a candidate `$tag$` opener is a splitter policy; the exact server observation is limited to the tested source. [Snowflake documents `$$` string constants](https://docs.snowflake.com/en/sql-reference/data-types-text) and [session variables](https://docs.snowflake.com/en/sql-reference/session-variables).

## 2. Identifiers

| Form | Delimiter or alphabet | Measured boundary |
| --- | --- | --- |
| Double-quoted | `"…"`, with `""` for an embedded quote | `SELECT 1 AS "a;b"`, `SELECT 1 AS "a""b;c"` and a quoted name containing a newline succeeded; an internal semicolon is not a statement terminator. |
| Unquoted | Sampled `_`, letters, digits and `$` | `_a`, `a_1`, `a$b` and `a$$b` succeeded. The exact unquoted candidates `é`, `aé` and `a©b` were rejected with attributed `1003/42000`. These samples do not define the full server alphabet. The spec leaves `non_ascii_names` false, but the shared tokenizer still applies Python `isalpha`/`isalnum`; it does not enforce an ASCII-only name grammar. |

See Snowflake's [identifier requirements](https://docs.snowflake.com/en/sql-reference/identifiers-syntax) for SQL-level naming rules. The splitter keeps quoted text and unclaimed characters verbatim; it does not manufacture an identifier from an invalid candidate.

## 3. Comments and blanks

| Form | Boundary | Native observation |
| --- | --- | --- |
| `--` | LF or CR, or end of input | `SELECT 1 -- comment` followed by LF or CR and then `+ 2` returned `3` in each case. A trailing `--` comment with no newline returned `1`. |
| `//` | LF, CR or CRLF, or end of input | The first `//` LF source returned `3`; the later CR and CRLF sources with `+ 2` after the line break also returned `3`. A single `/` remained division (`SELECT 8 / 2`). |
| `/* … */` | First following `*/`; no nesting | `SELECT 1 /* outer /* inner */ + 2` returned `3`, and `SELECT 1 /* outer /* inner */` returned `1`. A genuinely unclosed `SELECT 1 /* unclosed` received attributed `1003/42000` near end of input; the splitter refuses it before any partial split. |

The first-close rule is about the tested block-comment tokenization, not arbitrary nested source. A comment-only `-- comment-only` sent directly through the connector received a query ID and server `900/42601` (“Empty SQL statement”); the script splitter emits no statement record for comments alone, as required by the common splitter contract.

The positional blank matrix submitted each of 32 fixed code points at the leading, between-token and trailing positions of a scalar `SELECT`, for **96 server-attributed positions**. U+0020 SPACE, U+0009 TAB, U+000A LF, U+000D CR and U+2002 EN SPACE were accepted at all three positions. The other **27** sampled code points were rejected with attributed `1003/42000` at all three positions: U+000B, U+000C, U+0085, U+00A0, U+1680, U+2000, U+2001, U+2003–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+200B, U+FEFF, U+180E and U+001C–U+001F. The splitter recognizes the accepted five as blanks and **preserves** the other sampled characters in source sent to Snowflake; it neither trims nor normalizes them into whitespace. The lone U+0020 input had an unattributed connector failure, and the other lone-code-point inputs were not run. No lone-blank rule is claimed from the server.

## 4. Terminators

`;` ends a statement outside strings, quoted identifiers and comments. The terminator is recorded separately from the statement text by the common engine. The submitted `SELECT (1; 2)` received attributed syntax error `1003/42000`; this says nothing by itself about how a script should be cut at a semicolon inside parentheses. The splitter must keep its existing execution-text and source-span contract, including statements without a final semicolon, and refuse ambiguous procedural forms rather than emit a plausible partial cut.

## 5. Blocks and routines

`BEGIN`, `BEGIN WORK` and `BEGIN TRANSACTION` each succeeded as transaction heads and were followed by successful `ROLLBACK`. The splitter recognizes these as separate transaction statements, then the execution policy refuses them before any statement reaches the provider. A scalar anonymous `BEGIN LET x INTEGER := 1; RETURN x; END;` block also returned `1` natively, but the splitter deliberately refuses unquoted scripting blocks: their internal semicolons are not yet qualified for safe script splitting. That refusal is a policy boundary, **not** a claim that Snowflake cannot run the block. Snowflake documents both [transaction `BEGIN`](https://docs.snowflake.com/en/sql-reference/sql/begin) and [Scripting `BEGIN … END`](https://docs.snowflake.com/en/sql-reference/snowflake-scripting/begin).

Two exact inline anonymous procedure statements of the form `WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS <quoted body> CALL p()` returned `1`: one body was `$$BEGIN RETURN 1; END;$$`, the other was `'BEGIN RETURN 1; END;'`. Their paired `EXPLAIN USING TEXT` statements returned plans. The exact unquoted form `AS BEGIN RETURN 1; END; CALL p()` and its paired `EXPLAIN` were attributed `1003/42000` syntax rejections at `;`. The splitter may keep the measured quoted bodies whole and refuse the tested unquoted body, without generalizing that rejection to all procedural SQL. [Snowflake's `WITH … CALL` reference](https://docs.snowflake.com/en/sql-reference/sql/call-with) identifies this as an anonymous, non-stored procedure. These results **do not qualify stored `CREATE` routine bodies**. Both quoted and unquoted stored-routine `EXPLAIN` controls failed on schema context or access, before their body grammar could be distinguished; [EXPLAIN compiles without executing](https://docs.snowflake.com/en/sql-reference/sql/explain).

The splitter refuses recognized `CREATE [OR REPLACE] [SECURE|TEMP|TEMPORARY] PROCEDURE/FUNCTION … AS BEGIN/DECLARE` heads before a body can be cut into partial statements. Other stored-routine forms have no native grammar claim from these campaigns.

## 6. Client directives

The connector-submitted `!source never-opened.sql` had an attributed server syntax rejection `1003/42000`; `SELECT 1 != 2` remains ordinary SQL. There was no SnowSQL-client measurement, so the result does not establish how a client would preprocess `!`. The splitter refuses line-leading `!` commands with `UnsupportedMetaCommandError` rather than treating them as SQL or silently dropping them. This is a declared splitter policy, not a statement about measured SnowSQL behavior.

## 7. Raw blocks

None is recognized by this specification. Quoted routine bodies are handled as string literals (§1), not as a separate raw-block mode. Inputs that require an unqualified raw data protocol are refused rather than guessed.

## 8. Transaction markers

The `BEGIN` variants in §5 open a transaction; `ROLLBACK` closes it in the measured session. The splitter refuses script-level `BEGIN`, `START TRANSACTION`, `COMMIT` and `ROLLBACK` before execution, including a complete envelope, because dblift owns the migration transaction. Snowflake [documents `START TRANSACTION` as a `BEGIN` synonym](https://docs.snowflake.com/en/sql-reference/sql/begin); that alias was not separately native-probed in these campaigns. Transactional execution policy is separate from lexical splitting, and this specification does not infer a new “must run outside a transaction” flag.

## 9. Engine subclass

No dialect-specific scanning loop is needed for this contract. The Snowflake-owned `LexicalSpec` supplies comment openers, fixed-dollar quoting, measured blanks, directive refusal and conservative procedural guards to the common lexical engine. A small plugin parser binds the existing SQLGlot analysis path to those lexical records. The legacy `SnowflakeStatementParser` class remains in source, but no default split, execution, analysis or extraction path constructs or calls it. Statement facts are read from the same SQLGlot analysis path; §13 describes what the reader publishes.

## 10. Conformance examples

These are splitter conformance rows, not a claim that all combinations were sent as complete scripts to Snowflake. Native support is the exact scalar source described in §§1–6; the combined-script and refusal expectations are verified by the compiled conformance suite. In this table `␍` represents CR as defined by the shared table format.

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `SELECT 1; SELECT $$a;b$$;` | `SELECT 1` · `SELECT $$a;b$$` |
| 2 | `SELECT 'it''s;ok'; SELECT 2;` | `SELECT 'it''s;ok'` · `SELECT 2` |
| 3 | `SELECT 'it\\'s;ok'; SELECT 2;` | `SELECT 'it\\'s;ok'` · `SELECT 2` |
| 4 | `SELECT 1 AS "a""b;c"; SELECT 2;` | `SELECT 1 AS "a""b;c"` · `SELECT 2` |
| 5 | `SELECT 1 AS a$$b; SELECT 2;` | `SELECT 1 AS a$$b` · `SELECT 2` |
| 6 | `SELECT 1 // comment\n + 2;` | `SELECT 1 // comment\n + 2` |
| 7 | `SELECT 1 -- comment␍ + 2;` | `SELECT 1 -- comment␍ + 2` |
| 8 | `SELECT 1 // comment␍\n + 2;` | `SELECT 1 // comment␍\n + 2` |
| 9 | `SELECT 1 /* outer /* inner */ + 2;` | `SELECT 1 /* outer /* inner */ + 2` |
| 10 | `SELECT 1 /* unclosed` | `UnsafeStatementSplitError` |
| 11 | `-- comment-only` | `(empty)` |
| 12 | `SELECT\u20021;` | `SELECT\u20021` (EN SPACE retained between tokens) |
| 13 | `SELECT\u00a01;` | `SELECT\u00a01` (NBSP retained for server rejection) |
| 14 | `SELECT $tag;` | `SELECT $tag` (variable token preserved; an undefined variable may fail semantically) |
| 15 | `SELECT $tag$` | `UnsafeStatementSplitError` (unsupported tagged-dollar candidate; exact server source got syntax error) |
| 16 | `BEGIN TRANSACTION; ROLLBACK;` | `BEGIN TRANSACTION` · `ROLLBACK` |
| 17 | `BEGIN LET x INTEGER := 1; RETURN x; END;` | `UnsafeStatementSplitError` (splitter policy, despite native block success) |
| 18 | `WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS $$BEGIN RETURN 1; END;$$ CALL p();` | `WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS $$BEGIN RETURN 1; END;$$ CALL p()` |
| 19 | `WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS 'BEGIN RETURN 1; END;' CALL p();` | `WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS 'BEGIN RETURN 1; END;' CALL p()` |
| 20 | `WITH p AS PROCEDURE () RETURNS INT LANGUAGE SQL AS BEGIN RETURN 1; END; CALL p()` | `UnsafeStatementSplitError` (tested unquoted form rejected; no partial cut) |
| 21 | `!source never-opened.sql` | `UnsupportedMetaCommandError` (declared policy; only server handling was measured) |
| 22 | `SELECT 1 != 2;` | `SELECT 1 != 2` |

Native source mapping for these rows: the first 39-attempt slice supplied the fixed-dollar, quote, identifier-`$$`, `//` LF, block first-close, transaction, `!` and `!=` scalar controls (rows 1–6, 9, 16–17 and 21–22). The 113-attempt slice supplied the true unclosed block, the 96 positional blank matrix and the server-attributed comment-only result (rows 10–13). The 20-attempt slice supplied the distinguishing CR/CRLF comment controls, `$tag$`/`$tag` pair and inline `WITH … CALL`/`EXPLAIN` controls (rows 7–8, 14–15 and 18–20). Combined scripts, error policy and record projection are conformance targets, not separate native script executions.

## 11. Not handled

| Construct | Splitter action | Reason and evidence boundary |
| --- | --- | --- |
| Unquoted scripting blocks and unquoted routine bodies | Refuse before a partial split | A scalar anonymous block ran on Snowflake, while the one tested unquoted inline procedure source was rejected. The splitter does not implement the full procedural grammar. |
| Recognized stored `CREATE [OR REPLACE] [SECURE|TEMP|TEMPORARY] PROCEDURE/FUNCTION … AS BEGIN/DECLARE` heads | Refuse the **whole script before a partial cut** | Every non-executing stored-routine control was stopped by missing schema context/access; no body acceptance or rejection was measured. This is a qualification policy, not a claim that Snowflake cannot create either routine. Other forms remain unqualified and require separate review. |
| `$tag$` as a string delimiter | Refuse candidate opener; keep `$name` variables | The exact tagged candidate was a syntax error and the simple variable reached semantic resolution. Only `$$` is a qualified string delimiter. |
| Client-side `!` commands | Refuse by name and location | A connector request proved only server rejection, not client preprocessing. |
| Lone blank-only source | No server claim | One U+0020-only attempt failed without a query ID; the other lone candidates were not run. The common splitter's empty-statement rule remains the policy for recognized blanks. |

## 12. Current implementation

The Snowflake plugin owns the spec and the common lexical engine supplies records to `StatementSplitter` and parser views. Tests prove that making the retained legacy parser's constructor and `split` fail does not affect those paths. The legacy class remains in source until its planned removal after the 5.0 alpha is published. The shared conformance rows, split/record controls, and observed Unicode/quote/comment cases guard this specification.

## 13. Statement facts

Snowflake plugin: `statement_facts_class` is the shared reader, so object extraction, script analysis, the DML helpers and execution-time object tracking read facts; `HybridParser("snowflake")` and `SqlGlotParser("snowflake")` are refused like the other activated dialects. Statements are read by the shared sqlglot reader (`read_statement_facts(sql, dialect="snowflake")` in
`dblift/core/sql_parser/sqlglot_statement_facts.py`) after the lexical splitter above. This section
describes the reader. **Only the identifier folding below was observed on Snowflake DDL**: the earlier
10.38.100 campaigns measured splitting and refusals only, so every other reading is a structural
contract of the parser, not a claim about what the engine accepts or does.

| Form | Reading |
| --- | --- |
| `CREATE`/`ALTER`/`DROP` `TABLE`, `VIEW`, `SEQUENCE`, `FUNCTION`, `PROCEDURE`, `DATABASE`; `CREATE`/`DROP INDEX` | the object, an unquoted name in upper case and a quoted one as written; function and procedure bodies are not read; a function or procedure name carries no argument signature |
| `CREATE`/`DROP SCHEMA s`, `db.s` | `SCHEMA s`, scoped to `db`; a three-part name, or `SCHEMA` with a qualifier the parser discards, is opaque |
| `CREATE`/`DROP MATERIALIZED VIEW` | `MATERIALIZED_VIEW`, with the tables it reads; the `LOG ON` form is opaque |
| `CREATE … CLONE src` | `src` is referenced with the type of the object it copies |
| `INSERT`, `UPDATE`, `DELETE` | the target is altered, other tables are referenced, plus target, predicate, assigned columns and events; a target the reader cannot name is opaque |
| `TRUNCATE [TABLE] [IF EXISTS] t` | the table, altered (a data-changing statement, like the other readers); a list of tables, `CASCADE` and `TRUNCATE MATERIALIZED VIEW` are opaque |
| `MERGE INTO t USING … ON … WHEN …` | the target is altered, the sources are referenced, plus target, assigned columns and the `INSERT`, `UPDATE` and `DELETE` events of its actions; a `MERGE` with no readable action, or whose target is named like one of its CTEs, is unread; the CTE names are not sources. Not measured: whether Snowflake accepts a `WITH` before `MERGE` |
| `COMMENT [IF EXISTS] ON TABLE\|VIEW\|MATERIALIZED VIEW\|SEQUENCE\|COLUMN … IS '…'` | the object altered (`COLUMN` names its table); every other kind of `COMMENT ON` is opaque |
| `SELECT`, `WITH … SELECT` | the tables read are referenced |

Opaque (a diagnostic, no object or only a head-proven name, never a guess): `CREATE`/`DROP` of `STAGE`, `FILE FORMAT`,
`TAG`, `WAREHOUSE`, `ROLE`, `USER` and other kinds the object model has no type for; `CREATE LOCAL TEMP TABLE`;
`CREATE TRIGGER`; a name computed at run time (`IDENTIFIER(...)`, a `$variable`, a string path); a keyword
where a name belongs (`ALTER TABLE ADD COLUMN x`, `DROP TABLE IF`); a name continued by a `{…}` template brace; an unquoted name holding a non-ASCII letter; `ALTER … RENAME TO` and
`SWAP WITH` (they name a second object); a relation with four or more name parts; a `CTE` whose body writes;
a `@stage` reference; `COPY`, `INSERT ALL`, `GRANT`/`REVOKE`, `USE`, `SHOW`, `DESCRIBE`,
`UNDROP`, `COMMENT ON` of any other kind and every statement sqlglot cannot parse. A name kept on an opaque statement is checked
against the source tokens of the statement head; it is never read from the body.

Identifier case, measured on Snowflake 10.38.100 with `QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE` (the default):
`CREATE SCHEMA DBLIFT_QA.D2_QA_20261021_A8F3D2` and `CREATE SCHEMA DBLIFT_QA."d2_qa_20261021_a8f3d2"` made two
schemas, catalogued as `D2_QA_20261021_A8F3D2` and `d2_qa_20261021_a8f3d2`; the materialized views `LOG` and `"log"`
were two views; `CREATE`/`DROP SCHEMA`, `CREATE`/`DROP MATERIALIZED VIEW` and `CREATE`/`DROP TABLE` were accepted with
those forms (query IDs `01c7e32f-3204-c9bb-0008-38020027f07a`, `01c7e32f-3204-ccd2-0008-380200281012`,
`01c7e32f-3204-cd96-0008-380200282006`, `01c7e32f-3204-cd96-0008-38020028200a`). The reader therefore folds an unquoted
name to upper case and keeps a quoted name exact, so `CREATE SCHEMA app` and `CREATE SCHEMA "app"` name different
objects. Names are compared as stored only under that default: the reader does not read the session parameter. Only an
unquoted ASCII name is folded. An unquoted name with a non-ASCII letter is left unread, because the engine rejected the
unquoted candidates `é`, `aé` and `a©b` (section 2, `1003/42000`) and other non-ASCII letters are unmeasured; a quoted
name is read exactly, whatever it holds.

Known gaps, recorded rather than closed:

- A quoted name holding a dot, a three-part name and a two-part name with a dotted part collapse to the same
  schema string: `CREATE TABLE "a.b"."c"`, `CREATE TABLE a.b.c` and `CREATE TABLE "a"."b"."c"` all read as table
  `c` in schema `a.b` (modulo the case fold). The schema is one string, a design shared with the PostgreSQL and
  Redshift readers.
- `ALTER TABLE … ADD CONSTRAINT … REFERENCES o (id)` names the altered table only; the referenced table `o` is not
  reported (a `CREATE TABLE` reports it). The mapping is shared with the other readers.
- An unterminated quote reports an error and no object; the splitter normally refuses such a script first.
- `UPDATE t a SET … WHERE a.y = 1` names the bare table `t` as its target while the predicate keeps the alias `a`.
- A `DROP` whose object kind or name is unread is reported by lint as `drop-unread-object` (review), except for kinds
  whose vendor documentation says they remove a definition and not rows (listed in the lint rule), and, when the name is unread, always when
  the statement holds `CASCADE` or `FORCE` (a named `DROP ... CASCADE` is unchanged). The kinds the vendors leave unclear (for example `SUBSCRIPTION`, `BUFFERPOOL`,
  `CERTIFICATE`, `SECRET`) stay a review.
- Native acceptance and effect of the other DDL forms are unmeasured, as are
  `DYNAMIC` and `EXTERNAL` tables (read as `TABLE`) and `SELECT … INTO` (the target is read as referenced, not created).
