# Db2 for LUW — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | Db2 for Linux, UNIX and Windows scripts written for the command line processor (CLP) and run through the `ibm_db` driver. Measured: Db2 12.1.5.0 (CLP and server) with `ibm_db` 3.3.0; the rules are extrapolated to 11.1-11.5 where the V11.5 manuals agree and are unmeasured there |
| Code facts taken from | OSS `develop` `fdf0563` (2026-10-17), the splitter before this change; §12 describes the code of this change |
| Vendor references, fetched 2026-10-10 | *IBM Db2 V11.5 Command Reference* (PDF `db2_commands_115.pdf`, chapter 1 "Command line processor (CLP)": "Command line processor options", "Statement Termination Character Options", "Read from Input File Option"); *IBM Db2 V11.5 SQL Reference* (PDF `db2_sql_reference_115.pdf`: "Characters", "Constants", "SQL comments" p. 740, "CREATE MODULE" p. 1276). Both from the IBM support page "Db2 Version 11.5 for Linux, UNIX, and Windows English manuals". |
| Live verification | `db2 -tsvf script.sql` (the CLP of `DB2 v12.1.5.0`, `s2605181111`) run as the instance owner against `DB2/LINUXX8664 12.1.5.0`, database `TESTDB`, autocommit on; `-s` stops at the first error, as dblift does. Every "measured 2026-10-11" below is that pair. Where the V11.5 manual and the measurement disagree the cell follows the measurement and says so. |
| Second ground truth | the `ibm_db` 3.3.0 driver dblift executes through: what it does with a `;` inside the text of one statement decides the rules marked "driver" (§4, §11, rows 12, 42) |
| Engine subclass | none: the CLP rules are data of the shared lexical tokenizer (§9) |

Db2 is also the one dialect whose **schema extraction stays hand-written**
(sqlglot has no Db2 dialect); that is the extractor's concern and does not
affect this specification.

The central decision of this specification is that **the CLP reads lines, not
SQL**. A statement ends at a line whose last non-blank characters are the
active terminator, and nothing else is looked at: a `;` at the end of a line
that sits inside a string, a block comment or a quoted identifier ends the
statement there, and the server then rejects both halves (measured, rows 18,
18a). The splitter does the same, which makes it safe by construction: a cut
inside a lexeme leaves an unterminated string, comment or identifier in the
first half, and the server refuses it. Three things protect what actually runs
and are the only places the scanner reads SQL: a routine's `BEGIN … END` body
is kept whole under the `;` terminator (§5), a `;` in the middle of a
statement is refused (§4), and the CLP commands that change what runs are
refused (§6).

## 1. String literals

| Form | Opens | Closes | Escape inside | Vendor rule |
| --- | --- | --- | --- | --- |
| String | `'` | `'` | `''` | "Constants": "A sequence of characters that starts and ends with a string delimiter, which is an apostrophe ('). … Two consecutive string delimiters are used to represent one string delimiter within the character string. Two consecutive string delimiters that are not contained within a string represent the empty string." No backslash escapes (measured: `INSERT INTO a VALUES ('\')` stores one backslash). |
| Prefixed | `X'`, `GX'`, `UX'`, `G'`, `N'`, `U&'`, `BX'` | `'` | `''` | lexically a plain string after an identifier |

**The CLP does not read strings when it looks for the terminator.** A `;`
inside a string ends the statement only when it is the last non-blank
character of its line: `INSERT INTO a VALUES ('x;y')` runs and stores `x;y`;
`INSERT INTO a VALUES ('x;` then `y');` is cut after `'x`, and both halves fail
with SQL0010N (measured 2026-10-11, db2 CLP 12.1.5.0, Db2 12.1.5.0; row 18).
Under a custom terminator the same holds for the custom character (`'x@` then
`y')@`). A `--#SET TERMINATOR` line inside a string is honoured by the CLP,
stays in the statement text and cuts it there (§4).

**dblift does not copy that cut.** A statement whose line ends with the
terminator inside a string or a quoted identifier is refused with
`UnsafeStatementSplitError` naming the line (rows 18, 18a): the CLP would send
the two broken halves, the server rejects them, and a refusal says so before
anything runs. The old splitter read the literal as one statement and ran it;
the CLP rejects that script (measured), so nothing that runs under the CLP is
refused here, and the refusal is the safe side of a script that was never
valid under `db2 -tvf`.

**The CLP rewrites a literal that spans lines.** Each line break inside a
statement becomes a blank: `INSERT INTO a VALUES ('x` newline `y');` stores
`x y` (measured, also with CRLF line ends, also `-- ` inside the literal). The
splitter keeps the text as written, so dblift stores `x` newline `y`; this is a
deliberate difference (§11).

## 2. Identifiers

| Form | Opens | Closes | Escape inside |
| --- | --- | --- | --- |
| Delimited | `"` | `"` | `""` |
| Ordinary | letter | end of `[A-Za-z0-9_$#@]` | — ("Characters": "Letters also include three code points reserved as alphabetic extenders for national languages (#, @, and $ in the United States)." so they are letters wherever an ordinary identifier allows one) |

`CREATE TABLE "a;b" (id INT);` runs (the `;` is not the last character of its
line); `CREATE TABLE "a;` newline `b" (id INT);` is cut after `"a` and fails
(SQL0010N) like a string (measured). `@` is never a terminator unless
declared: `MY@TBL` is an identifier (measured, row 4), and `"my@tbl"` stays one
under `@` unless a line ends in it (measured: `"a@` newline `b"` is cut).

## 3. Comments

| Form | Opens | Closes | Nests | Vendor rule |
| --- | --- | --- | --- | --- |
| Line | `--` | end of line | — | "SQL comments" |
| Block | `/*` | the matching `*/` | **yes, on the server** | "SQL comments": "Bracketed comments are introduced by /\* and end with \*/." The manual does not say whether they nest. Measured 2026-10-11, db2 CLP 12.1.5.0, Db2 12.1.5.0: `CREATE TABLE a (id INT /* a /* b */ c */)` and `CREATE TABLE a (/* a /* b */ */ id INT)` both run, so the server nests. The CLP reads no block comments at all (below); the `ibm_db` driver does not nest, which the provider works around by sending the text without comments when the two readings differ. |
| CLP directive | `--#SET TERMINATOR x` | end of line | — | the one comment form with meaning (§4) |
| CLP comment block | `(=` at the start of a line … a line ending in `=)` | — | — | Command Reference: "Input file lines that begin with (= are treated as the beginning of a comment block. Lines that end with =) mark the end of a comment block. … Comments may be nested, and can be used nested in statements. The command termination character (;) cannot be used after =)." **Measured: the CLP skips the block silently**, statements inside it included (`CREATE TABLE b (id INT);` between `(=` and `=)` is never run, rc 0; an unterminated `(=` swallows the rest of the script, DB21007E); `(=` in the middle of a line is statement text and the server rejects it. The splitter **refuses** a line that starts with `(=` (§6, row 29) |

What the CLP does with comments (measured 2026-10-11, db2 CLP 12.1.5.0, Db2 12.1.5.0):

- a line whose first non-blank characters are `--` is skipped, wherever it is outside a string: before a statement and inside one (`CREATE TABLE a (` newline `-- c;` newline `id INT);` runs); it never ends a statement (`-- a;`) and it is not part of the text sent to the server for a table or a view, whereas a routine keeps it (the stored text of a procedure holds its `-- line comment` lines). The splitter does not send leading comment lines and keeps those inside a statement: the server ignores them either way, and the only visible difference is a stored view text (§11). Inside a string the CLP reads such a line as text and cuts the statement there when it ends in the terminator (row 51); the splitter reads it as a comment line there, the same known difference as in §12;
- a `--` comment that follows code is part of the line and is sent: `CREATE TABLE a (id INT) -- c;` ends the statement at the `;` and sends `CREATE TABLE a (id INT) -- c` (row 20); a comment after the terminator spoils it: `CREATE TABLE a (id INT); -- c` has not ended (§4, row 13; the splitter ends the statement there, extension);
- a block comment is statement text: `/* c */ CREATE TABLE a (id INT);` sends the comment (the stored text of `/* hdr */` + `CREATE PROCEDURE` begins with the comment), a line `/* x;` inside a statement ends it, and a `/* … */` followed by the terminator and nothing else is a statement of its own that the server rejects (SQL0198N, blank statement; row 27);
- **a `;` at the end of a line inside a block comment cuts there**: `/*` newline `DROP TABLE old;` newline `*/` newline `CREATE TABLE n (id INT);` is cut after `old`, the first half is an unclosed comment and the second begins with a stray `*/`, both rejected (SQL0104N, return code 4; measured, `h_commented_out_sql`); the same comment with the `;` in the middle of its line runs. **dblift does not cut there** (extension, row 47): a comment is never executed, the previous splitter kept it whole, commented-out SQL is the commonest place a `;` ends a line inside one, and the CLP's answer to it is a message about a token `*/`;
- a `*/` without an opener, and an unterminated `/*`, are text for the CLP; the server rejects the statement (SQL0104N). The splitter refuses an unterminated `/*`, naming its line.

## 4. Terminators

Command Reference, "Statement Termination Character Options (-t and -tdx or
-tdxx)": "The -t option tells the command line processor to use a semicolon
(;) as the statement termination character, and disables the backslash (\)
line continuation character." "To define termination characters 1 or 2
characters in length, use -td followed by the chosen character or
characters. For example, -td%% sets %% as the statement termination
characters. Alternatively, use the --#SET TERMINATOR directive in an input
file to set the statement termination characters." "The termination
character or characters cannot be used to concatenate multiple statements
from the command line, since checks for a termination symbol are performed
on only the last one or two non-blank characters of each input line."

| Rule | Measured 2026-10-11, db2 CLP 12.1.5.0, Db2 12.1.5.0 |
| --- | --- |
| Default terminator | Without `-t` and without a directive the terminator is the end of the line (`CREATE TABLE a (` is a statement); the splitter always starts with `;`, the `-t` reading. There is **no dblift setting that plays the part of `-td`**: the only way to change the terminator is the directive in the script (a configuration key `terminator`, which the first draft of this specification assumed, does not exist). |
| Where a statement ends | at a line whose **last non-blank characters** are the active terminator (1 or 2 characters). Blank means space and tab; a carriage return is a line end only before a line feed (`;` + CR + LF ends the statement, a lone CR is a non-blank character and `;` + CR at the end of the script has not ended it); a no-break space or a form feed after the `;` is not blank (the statement goes on and fails, SQL0007N). The terminator can stand alone on a line, and a line holding only the terminator with nothing pending is no statement (`;;` on one line sends `X;`, which the server accepts; a bare `;` line sends nothing). |
| Mid-line terminator | text, not a terminator: `CREATE TABLE a (id INT); CREATE TABLE b (id INT);` is **one** statement with a `;` in the middle. The CLP sends it and the server rejects it (SQL0104N). The `ibm_db` driver does not reject it: it runs the text up to the first `;` that is outside strings, quoted identifiers, comments and routine bodies and drops the rest, with no error (measured through dblift's provider, `Db2Provider.execute_statement`: `INSERT … ('h1'); INSERT … ('h2')` stores `h1` only, `…; garbage garbage` stores the first row and reports success; a multi-line `CREATE METHOD … BEGIN ATOMIC … END` and a compound statement run whole). **The splitter refuses such a statement** (`UnsafeStatementSplitError`, rows 12, 42): code after a `;` that is not inside a string, a quoted identifier, a comment or a routine body, on the same line. **This is a tightening**: the previous splitter cut at the mid-line `;` and ran both halves; the CLP rejects the script, dblift now follows its statement boundaries and refuses what it cannot run the same way, with the line named; the fix is to put each statement on its own line. Trailing `;` characters are fine, and so are comments after the `;` (next row). A declared terminator keeps the rule for `;` too (`SELECT 1; SELECT 2@` is refused). |
| After the terminator | a comment on the same line spoils it for the CLP: `CREATE TABLE t (id INT); -- trailing` has not ended, the CLP joins the next line and the server rejects the `;` (row 13, measured with `-tvf` and `-tsvf`; a block comment after the `;` does the same). **The splitter ends the statement at the `;` and drops the comment** (extension, row 13: a `--` comment or a closed `/* */` after a `;` is trivia, nothing executable is lost, and `stmt; -- why` is the commonest Db2 comment style). The form the CLP runs has the comment on its own line. Under a declared terminator the CLP rule stands (a comment after `@` joins the next line). A comment before the terminator is fine: `CREATE TABLE a (id INT) -- c ;` ends at the `;` and sends the comment (row 21). |
| A terminator at the end of a line inside a lexeme | the CLP cuts there whatever the line holds: inside a string or a quoted identifier (rows 18, 18a: both halves rejected, SQL0010N) and inside a block comment (row 47, SQL0104N on the stray `*/`). **The splitter does not cut inside a block comment** (extension) and **refuses inside a string or a quoted identifier** (`UnsafeStatementSplitError`, line named), inside a routine body too: the body is kept whole, but a line end inside a string is not read as the end of the line. A block comment that is never closed is refused, with the line it opened on, because the statements inside it would be dropped. |
| Last statement without a terminator | the CLP does **not** run it: `DB21007E End of file reached while reading the command.`, return code 2, and the statement is lost (a trailing `/* bye */` line after the last terminator draws the same warning but loses nothing). **The splitter returns it** (row 17): dropping it silently is the failure mode, and a one-statement migration without `;` is the commonest script there is. Comment-only lines (`--` or block comments) after its last code are not part of it (the same as a comment after a terminator, row 13). |
| `--#SET TERMINATOR x` | a line whose first non-blank characters are `--#SET`, one or more **blanks** (a tab makes it an ordinary comment), `TERMINATOR`, one or more blanks and the value, then optional blanks or tabs. **Upper case only** (`--#set terminator @` and `--#SET terminator @` are comments). The value is **one or two** non-blank characters, any of them (`@`, `@;`, `%%`, `'`, `"`, `/`, `\`, `-`, `*`, `$`, `\|`, `0`, `e`, `--`, `;;`, `)` all measured; `)` as terminator ended a statement at a line holding only `)`). A value of three characters or more, a blank inside the value, a comment after the value, no value, or no blank before the value is an error, DB21109E reason 1 (value), 2 (none) or 3 (blank), return code 8; the CLP then goes on **with the old terminator**. The splitter refuses a malformed directive (row 23). |
| Where a directive is honoured | on any line that starts with it, wherever the CLP is. Between statements: it takes effect. **In the middle of a statement**, outside a string, a quoted identifier and a comment: the line is consumed and the statement goes on (row 24; `dir_mid_statement`). **Inside a string literal**: the line is *not* consumed, it stays in the statement text and, because it now ends with the new terminator, cuts the statement there: `INSERT INTO a VALUES ('x` newline `--#SET TERMINATOR @` newline `y')` sends `INSERT INTO a VALUES ('x --#SET TERMINATOR @` and `y')`, both rejected, SQL0010N, return code 4 (measured, `dir_in_string`, `f_dir_directive_in_string_valid`, `h_dir_in_string_text`). **Inside a block comment**: the terminator switches and the line stays in the text (measured, `h_dir_in_block_comment_text`: after `/*` newline `--#SET TERMINATOR #` newline `*/ RETURN 1@` the `@` ends nothing, SQL0103N on `1@`). After code on the same line it is not a directive. The splitter drops the directive line and records it (`kind="directive"`) between statements and in the middle of a statement outside lexemes, and **refuses it inside a string, a quoted identifier or a block comment** (`UnsafeStatementSplitError`, the directive's line; rows 48, 49): the CLP's reading there cuts or misreads the statement, and silence would mean the two clients disagree about where the next statement starts. |
| Scope | to the next directive or the end of the file; `--#SET TERMINATOR ;` returns to the default; the old terminator is then text (`;` at a line end under `@` ends nothing). |
| `-td` against the directive | the directive wins (`-td# -f` with `--#SET TERMINATOR @` ends statements at `@`; a script that starts with `#`-terminated lines uses `#` until the directive). |
| Other `--#SET` forms | `--#SET DELIMITER`, `--#SET MAXERRORS 1`, `--#SET AUTOCOMMIT OFF`, `--#COMMENT`, `--#TERMINATOR @` are comments for the CLP (measured: `MAXERRORS` did not stop the script at the second error). They are comments for the splitter. |
| CLP options | `-t` and `-td` only choose the terminator. `-v` echoes the statement. `-s` (and `UPDATE COMMAND OPTIONS USING S ON` in the script) stops at the first error; without it the CLP **goes on** after an error and reports return code 4 at the end. `+c` and `UPDATE COMMAND OPTIONS USING C OFF` delay the commit to `COMMIT` or to the end of the run (measured: nothing is lost, the end of the run commits). The return code is a bit set, not the last status: 1 no rows (a `SELECT` that returns nothing, SQL0100W on an `UPDATE`), 2 warning (SQL0605W, DB21007E), 4 error, 8 CLP error; they add up (5, 6, 10). A script was rejected when the code has bit 4 or 8. |

Because the terminator is end-of-line and declared, **`@` is never a
terminator unless declared**.

## 5. Blocks

The CLP tracks no blocks: with terminator `;`, a routine body whose statements
end in `;` at the end of a line is cut at each of them, and the pieces run
(measured: the body of a trigger, `UPDATE u SET a = 1;` on a line of its own, ran
as a statement of its own against `u` and reported SQL0100W). That is why Db2
scripts declare `@`. The same body written on **one line** needs nothing
(`CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END;` runs: only the
last character of the line counts, row 5). This specification keeps **one
extension**: the `BEGIN … END` body of a routine is kept whole, whatever the
terminator, and the statement ends at the first line after the body that ends
with the terminator. The CLP rejects the script written that way (row 5a); the
same script in the `--#SET TERMINATOR @` form runs (measured). A migration file that holds such a body is therefore not
runnable by `db2 -tvf` without a `--#SET TERMINATOR` line; dblift runs it either way.

| Opener | Condition | Closer |
| --- | --- | --- |
| `BEGIN`, `BEGIN ATOMIC`, `BEGIN NOT ATOMIC` | the statement head is `CREATE [OR REPLACE] { PROCEDURE \| FUNCTION \| TRIGGER \| METHOD }` or `ALTER MODULE …`, and the `BEGIN` is the first `BEGIN` at parenthesis depth 0 after the head, outside comments, strings and quoted identifiers; or the statement itself begins with `BEGIN` (a compound statement) | the `END` that returns to depth 0, optionally followed by a label |
| `CREATE [OR REPLACE] PACKAGE [BODY]` (the Oracle compatibility vector) | the body opens at the first `AS` or `IS` at parenthesis depth 0 (a package has no `BEGIN` of its own) | its own `END [name]`, counted like any other: a nested `BEGIN … END` pairs with itself (rows 45, 46) |
| nested `BEGIN`, `CASE` (statement and expression) | depth > 0 | its `END` (`END CASE` for the statement) |
| `IF`, `WHILE`, `FOR`, `LOOP`, `REPEAT` | not counted | `END IF`, `END WHILE`, `END FOR`, `END LOOP`, `END REPEAT` close nothing the scanner counted; a comment between `END` and the keyword does not change the pairing (measured: `END /* c */ IF;` runs) |
| `CREATE [OR REPLACE] MODULE m` | — | not a block. SQL Reference p. 1276, "CREATE MODULE", Syntax: `CREATE [OR REPLACE] MODULE module-name`, nothing else; objects are added with `ALTER MODULE m ADD PROCEDURE p() BEGIN … END`, which is a block. `CREATE MODULE m BEGIN END MODULE` does not exist (measured: SQL0104N, `Expected tokens may include: "PROCEDURE"`). |

Packages need `DB2_COMPATIBILITY_VECTOR=ORA`. Measured 2026-10-11 on a database created with it (db2 CLP 12.1.5.0): under `;` the CLP cuts a package at each line that ends in `;` exactly as it cuts a procedure, and under `@` it sends the whole package; the reference container then refused to compile one (SQL1646N, the fenced user ID cannot reach the instance's `sqllib`), so no run of a whole package is claimed, only where the CLP cuts it.

A routine without a `BEGIN` (`CREATE FUNCTION f() RETURNS INT RETURN 1;`) is an
ordinary statement ending at the terminator, also when it spans lines or holds
a `CASE … END` expression (row 40). A routine whose body is not closed before
the end of the script is refused (row 36). The words `BEGIN`, `END`, `CASE` in
a string, a quoted identifier or a comment count for nothing. A labelled
top-level compound (`lbl: BEGIN`) is not recognised and is not valid on the
server either (measured: SQL0104N, it needs `BEGIN ATOMIC`).

## 6. Client directives

| Directive | Splitter action |
| --- | --- |
| `--#SET TERMINATOR x` | handled (§4) |
| `CONNECT TO db [USER u USING p]`, `CONNECT`, `UPDATE COMMAND OPTIONS …`, `CHANGE ISOLATION …`, `ECHO …`, `!cmd`, `?`, `QUIT` (as the last statement see the next row), and the utility and administration commands in the CLP's own `?` listing (`ATTACH`, `BACKUP`, `BIND`, `CATALOG`, `DESCRIBE`, `EXPORT`, `FORCE APPLICATION`, `GET …`, `IMPORT`, `LIST …`, `LOAD`, `REORG`, `REORGCHK`, `RESTORE`, `ROLLFORWARD`, `RUNSTATS`, `SET CLIENT`, `START …`, `STOP …`, `UPDATE DB CFG`, …; the full set is `FIRST_WORDS` and `FIRST_PHRASES` in the Db2 specification module) | **reject** with `UnsupportedMetaCommandError`. The CLP runs every one of them silently, with a return code that does not say so: `QUIT;` ends the run with return code 0 and drops everything after it, `ECHO` without a terminator swallows the next statement, `!echo hi;` runs a shell command, `UPDATE COMMAND OPTIONS USING S ON` changes what the rest of the script does, `CONNECT TO` resets the current schema, `(=` hides statements (rows 14, 28-31). A command word is a command **only as the first word of a statement**, with no comment before it on its line: `CREATE TABLE a (` newline `connect INT);` is a column (row 32); `/* c */ ECHO hello;` is sent to the server as SQL and rejected (row 33). Case does not matter (`connect to` is the command). A word that also starts an SQL statement is a command only with its second (third) word: `UPDATE t SET a = 1`, `SET CURRENT SCHEMA s` and `CREATE TABLE` are SQL (row 35). `CREATE DATABASE`, `CREATE DB`, `DROP DATABASE` and `DROP DB` are CLP commands too, and are **not** refused: measured through the driver on the live server, each is rejected with SQL0104N (`CREATE DATABASE nosuchdb`: unexpected token `DATABASE` following `CREATE`; `DROP DATABASE`, `DROP DB`, `CREATE DB` the same), so nothing silent happens, and `CREATE DATABASE LINK` (Oracle syntax) is rejected the same way. |
| `CONNECT RESET`, `TERMINATE`, `QUIT` | **dropped and recorded** (`kind="directive"`) when nothing but directives follows, because CLP scripts end with them (rows 15, 28a: a final `QUIT;` ends the run with return code 0, an unterminated `QUIT` on the last line draws DB21007E and is harmless, measured); **rejected** earlier in the script (`QUIT` drops the rest of the script, row 28; `CONNECT RESET` leaves the connection without a schema: the next statement fails with SQL1024N; `TERMINATE` reconnects to the default schema). Only the bare command is one: alone on its line, ended by the terminator or by the end of the script, with a comment after it at most. The CLP joins lines, so `QUIT` followed by a statement, `QUIT;;` or `QUIT foo` are refused. |
| `GET DIAGNOSTICS …` | SQL; passes through although `GET` also starts CLP commands (`GET DB CFG`): the splitter reads the first two words |
| `COMMIT`, `COMMIT WORK`, `ROLLBACK` | SQL; pass through (measured: `COMMIT WORK` and `ROLLBACK` are accepted as statements) |

## 7. Raw blocks

None. `EXEC SQL … END-EXEC` is embedded-SQL syntax from host programs: the CLP
sends it to the server, which rejects it (measured: SQL0104N, `EXEC SQL
INCLUDE SQLCA`), so the splitter has no special case for it and a script that
holds one fails at the server as it does for the CLP. (The first draft of this
specification said the splitter rejects it; the old code's gate that treated
a script containing `EXEC SQL` differently is gone with the rest of the gates.)

## 8. Transaction markers

None. Db2 DDL is transactional (`supports_transactional_ddl = True`). The CLP
runs with autocommit on by default and commits each statement; dblift's
provider commits each statement the same way.

## 9. Engine subclass

None. The CLP's rules are data of the shared lexical tokenizer: the active terminator and the end-of-line rule, the `--#SET TERMINATOR` directive and its value pattern, the comment line and comment block markers, the command prefixes, words and phrases, the epilogue commands and the §5 routine-body rule (the create and alter verbs, the routine kinds, the package openers, the body and depth words and the END qualifiers) are fields of the Db2 specification, and the core carries no Db2 word or message of its own.

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `CREATE TABLE t (id INT);\nINSERT INTO t VALUES (1);` | `CREATE TABLE t (id INT)` · `INSERT INTO t VALUES (1)` |
| 2 | `--#SET TERMINATOR @\nCREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END@\n--#SET TERMINATOR ;\nCALL p();` | directive · `CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END` · directive · `CALL p()` |
| 3 | `--#SET TERMINATOR @\nCREATE TABLE "my@tbl" (id INT)@\nSELECT 1 FROM sysibm.sysdummy1@` | directive · `CREATE TABLE "my@tbl" (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` |
| 4 | `CREATE TABLE MY@TBL (id INT);\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE MY@TBL (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` (the at sign is an identifier character) |
| 5 | `CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END;\nCALL p();` | `CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END` · `CALL p()` (measured: the CLP runs this as written, the ; inside is not at the end of the line) |
| 5a | `CREATE PROCEDURE p()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND;\nCALL p();` | `CREATE PROCEDURE p()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND` · `CALL p()` (extension, §5: measured, the CLP cuts the body at each ; line and rejects it) |
| 6 | `CREATE PROCEDURE p() BEGIN IF 1 = 1 THEN SET x = 1; END /* c */ IF; END P1;\nCALL p();` | `CREATE PROCEDURE p() BEGIN IF 1 = 1 THEN SET x = 1; END /* c */ IF; END P1` · `CALL p()` (the END IF with a comment between its words closes nothing; the label after END is consumed) |
| 7 | `CREATE FUNCTION f() RETURNS INT RETURN 1;\nCREATE TRIGGER tr AFTER INSERT ON t FOR EACH ROW BEGIN ATOMIC UPDATE u SET a = 1; END;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE FUNCTION f() RETURNS INT RETURN 1` · `CREATE TRIGGER tr AFTER INSERT ON t FOR EACH ROW BEGIN ATOMIC UPDATE u SET a = 1; END` · `SELECT 1 FROM sysibm.sysdummy1` |
| 8 | `BEGIN ATOMIC\n  DECLARE v INT;\n  SET v = 1;\nEND;\nSELECT 1 FROM sysibm.sysdummy1;` | `BEGIN ATOMIC\n  DECLARE v INT;\n  SET v = 1;\nEND` (the compound statement, extension §5) · `SELECT 1 FROM sysibm.sysdummy1` |
| 8a | `--#SET TERMINATOR @\nBEGIN ATOMIC\n  DECLARE v INT;\n  SET v = 1;\nEND@\nSELECT 1 FROM sysibm.sysdummy1@` | directive · `BEGIN ATOMIC\n  DECLARE v INT;\n  SET v = 1;\nEND` · `SELECT 1 FROM sysibm.sysdummy1` (measured: the CLP runs this as written) |
| 9 | `BEGIN\n  DECLARE v INT;\n  SET v = CASE WHEN 1 = 1 THEN 1 END;\nEND;\nSELECT 2 FROM sysibm.sysdummy1;` | `BEGIN\n  DECLARE v INT;\n  SET v = CASE WHEN 1 = 1 THEN 1 END;\nEND` · `SELECT 2 FROM sysibm.sysdummy1` |
| 10 | `CREATE TABLE "a;b" (id INT);\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE "a;b" (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` |
| 11 | `/* a /* b */ ; */ CREATE TABLE t (id INT);\nSELECT 1 FROM sysibm.sysdummy1;` | `/* a /* b */ ; */ CREATE TABLE t (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` (measured: the CLP sends the comment with the statement and the server nests it; the ; inside is not a cut) |
| 12 | `SELECT 1 FROM sysibm.sysdummy1; SELECT 2 FROM sysibm.sysdummy1;` | `UnsafeStatementSplitError` (a `;` in the middle: the CLP sends the line as one statement and the server rejects it, SQL0104N; tightening, the previous splitter ran both halves) |
| 13 | `CREATE TABLE t (id INT); -- trailing\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE t (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` (extension: measured, the CLP does not end the statement at a semicolon followed by a comment and the server rejects it; the comment is dropped) |
| 13a | `--#SET TERMINATOR %%\nCREATE TABLE t (id INT)%%\nSELECT 1 FROM sysibm.sysdummy1%%` | directive · `CREATE TABLE t (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` (two-character terminator) |
| 14 | `CONNECT TO sample;\nCREATE TABLE t (id INT);\nCONNECT RESET;` | `UnsupportedMetaCommandError` (line 1, `CONNECT TO`) |
| 15 | `CREATE TABLE t (id INT);\nCOMMIT;\nCONNECT RESET;\nTERMINATE;` | `CREATE TABLE t (id INT)` · `COMMIT` · two directive records |
| 16 | `INSERT INTO t VALUES (X'3B3B');\nSELECT 1 FROM sysibm.sysdummy1;` | `INSERT INTO t VALUES (X'3B3B')` · `SELECT 1 FROM sysibm.sysdummy1` |
| 17 | `CREATE TABLE t (id INT);\nINSERT INTO t VALUES (1)` | `CREATE TABLE t (id INT)` · `INSERT INTO t VALUES (1)` (extension: the CLP reports DB21007E and does not run the last statement) |
| 18 | `INSERT INTO t VALUES ('a;\nb');` | `UnsafeStatementSplitError` (line 1; measured: the CLP cuts at the ; that ends its line, inside the string, and both halves are rejected, SQL0010N; dblift refuses instead of sending the halves) |
| 18a | `CREATE TABLE "a;\nb" (id INT);` | `UnsafeStatementSplitError` (line 1; the same inside a quoted identifier) |
| 19 | `-- a;\nCREATE TABLE t (id INT);` | `CREATE TABLE t (id INT)` (a comment line is skipped and ends nothing) |
| 20 | `CREATE TABLE t (id INT) -- c;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE t (id INT) -- c` · `SELECT 1 FROM sysibm.sysdummy1` (measured: a comment that follows code is sent, and a ; at its end is the terminator) |
| 21 | `CREATE TABLE t (id INT) -- c ;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE t (id INT) -- c` · `SELECT 1 FROM sysibm.sysdummy1` |
| 22 | `--#set terminator @\nCREATE TABLE t (id INT)@\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE t (id INT)@\nSELECT 1 FROM sysibm.sysdummy1` (measured: the directive is upper case only; this one is a comment, so the semicolon stays the terminator) |
| 22a | `--#SET  TERMINATOR  @\nCREATE TABLE t (id INT)@\nSELECT 1 FROM sysibm.sysdummy1@` | directive · `CREATE TABLE t (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` (several blanks between the words and before the value are fine) |
| 23 | `--#SET TERMINATOR abc\nCREATE TABLE t (id INT);` | `UnsafeStatementSplitError` (line 1; measured: DB21109E reason 1, return code 8, the CLP goes on with `;`) |
| 24 | `CREATE TABLE t (\n--#SET TERMINATOR @\nid INT)@\nSELECT 1 FROM sysibm.sysdummy1@` | directive · `CREATE TABLE t (\nid INT)` · `SELECT 1 FROM sysibm.sysdummy1` (measured: a directive in the middle of a statement is consumed) |
| 25 | `CREATE TABLE t (id INT);;\n;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE t (id INT);` · `SELECT 1 FROM sysibm.sysdummy1` (two semicolons send the statement with the first one, a line of one semicolon sends nothing) |
| 26 | `--#SET TERMINATOR @\nCREATE TABLE t (id INT);@\nSELECT 1 FROM sysibm.sysdummy1@` | directive · `CREATE TABLE t (id INT);` · `SELECT 1 FROM sysibm.sysdummy1` (a semicolon right before the custom terminator is last in the text: fine) |
| 27 | `CREATE TABLE t (id INT);\n/* c */;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TABLE t (id INT)` · `SELECT 1 FROM sysibm.sysdummy1` (extension: the CLP sends the comment alone and the server rejects it, SQL0198N) |
| 28 | `CREATE TABLE t (id INT);\nQUIT;\nCREATE TABLE u (id INT);` | `UnsupportedMetaCommandError` (line 2, `QUIT`: the CLP stops here without an error and `u` is never created) |
| 28a | `CREATE TABLE t (id INT);\nQUIT;` | `CREATE TABLE t (id INT)` · directive record (a final quit is harmless, like a final connect reset) |
| 29 | `CREATE TABLE t (id INT);\n(=\nCREATE TABLE u (id INT);\n=)\nCREATE TABLE v (id INT);` | `UnsupportedMetaCommandError` (line 2, `(=`: the CLP skips the block and `u` is never created) |
| 30 | `UPDATE COMMAND OPTIONS USING S ON;\nCREATE TABLE t (id INT);` | `UnsupportedMetaCommandError` (line 1; the CLP honours it and stops at the next error) |
| 31 | `CREATE TABLE t (id INT);\nREORG TABLE t;` | `UnsupportedMetaCommandError` (line 2, `REORG`: a CLP command, not SQL) |
| 32 | `CREATE TABLE t (\nconnect INT);` | `CREATE TABLE t (\nconnect INT)` (a command word in the middle of a statement is a column) |
| 33 | `/* c */ ECHO hello;` | `/* c */ ECHO hello` (a comment before the word makes it SQL text; measured: SQL0104N from the server) |
| 34 | `connect to sample;` | `UnsupportedMetaCommandError` (line 1; measured: the CLP reads any case) |
| 35 | `UPDATE t SET a = 1;\nSET CURRENT SCHEMA s;\nCOMMIT WORK;` | `UPDATE t SET a = 1` · `SET CURRENT SCHEMA s` · `COMMIT WORK` (SQL that shares a first word with a CLP command) |
| 36 | `CREATE PROCEDURE p()\nBEGIN\n  SET x = 1;\n` | `UnsafeStatementSplitError` (line 1; the body is not closed) |
| 37 | `CREATE PROCEDURE p()\nBEGIN\n  DECLARE i INT DEFAULT 0;\n  WHILE i < 3 DO\n    SET i = i + 1;\n  END WHILE;\n  IF i = 3 THEN\n    SET i = 0;\n  END IF;\n  CASE i WHEN 0 THEN SET i = 1; ELSE SET i = 2; END CASE;\n  SET i = CASE WHEN i = 1 THEN 1 ELSE 2 END;\nEND;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE PROCEDURE p()\nBEGIN\n  DECLARE i INT DEFAULT 0;\n  WHILE i < 3 DO\n    SET i = i + 1;\n  END WHILE;\n  IF i = 3 THEN\n    SET i = 0;\n  END IF;\n  CASE i WHEN 0 THEN SET i = 1; ELSE SET i = 2; END CASE;\n  SET i = CASE WHEN i = 1 THEN 1 ELSE 2 END;\nEND` · `SELECT 1 FROM sysibm.sysdummy1` |
| 38 | `CREATE TABLE t (a INT);\nCREATE TABLE u (a INT);\nCREATE TRIGGER tr AFTER INSERT ON t\nFOR EACH ROW\nBEGIN ATOMIC\n  UPDATE u SET a = 1;\n  UPDATE u SET a = 2;\nEND;` | `CREATE TABLE t (a INT)` · `CREATE TABLE u (a INT)` · `CREATE TRIGGER tr AFTER INSERT ON t\nFOR EACH ROW\nBEGIN ATOMIC\n  UPDATE u SET a = 1;\n  UPDATE u SET a = 2;\nEND` (measured: the CLP cuts the body and runs UPDATE u SET a = 2 as a statement) |
| 39 | `CREATE MODULE m;\nALTER MODULE m ADD PROCEDURE p()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND;\nALTER MODULE m PUBLISH PROCEDURE q();` | `CREATE MODULE m` · `ALTER MODULE m ADD PROCEDURE p()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND` · `ALTER MODULE m PUBLISH PROCEDURE q()` |
| 40 | `CREATE FUNCTION f() RETURNS INT\nRETURN CASE WHEN 1 = 1 THEN 1 END;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE FUNCTION f() RETURNS INT\nRETURN CASE WHEN 1 = 1 THEN 1 END` · `SELECT 1 FROM sysibm.sysdummy1` (no BEGIN: an ordinary statement) |
| 41 | `CREATE PROCEDURE p()\nBEGIN\n  INSERT INTO t VALUES ('END;');\n  INSERT INTO t VALUES ('BEGIN');\nEND;` | `CREATE PROCEDURE p()\nBEGIN\n  INSERT INTO t VALUES ('END;');\n  INSERT INTO t VALUES ('BEGIN');\nEND` (the words in strings count for nothing) |
| 42 | `CREATE PROCEDURE p() BEGIN END; SELECT 1 FROM sysibm.sysdummy1;` | `UnsafeStatementSplitError` (a `;` after the body, then code on the same line) |
| 43 | `SELECT 1 FROM sysibm.sysdummy1 WHERE 1 != 2;\nSELECT 2 FROM sysibm.sysdummy1;` | `SELECT 1 FROM sysibm.sysdummy1 WHERE 1 != 2` · `SELECT 2 FROM sysibm.sysdummy1` (! inside a statement is not the shell escape) |
| 44 | `CREATE TABLE t (c VARCHAR(20));\nINSERT INTO t VALUES ('x\ny');` | `CREATE TABLE t (c VARCHAR(20))` · `INSERT INTO t VALUES ('x\ny')` (the text is sent as written; measured: the CLP replaces the line break with a blank and stores x y, §1) |
| 45 | `CREATE OR REPLACE PACKAGE pk1 AS\nPROCEDURE proc1(x INT);\nEND pk1;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE OR REPLACE PACKAGE pk1 AS\nPROCEDURE proc1(x INT);\nEND pk1` · `SELECT 1 FROM sysibm.sysdummy1` (extension, §5: measured, the CLP cuts the package after the first semicolon line) |
| 46 | `CREATE OR REPLACE PACKAGE BODY pk1 AS\nPROCEDURE proc1(x INT) IS\nBEGIN\n  INSERT INTO t VALUES (x);\nEND proc1;\nPROCEDURE proc2(y INT) IS\nBEGIN\n  INSERT INTO t VALUES (y);\nEND proc2;\nEND pk1;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE OR REPLACE PACKAGE BODY pk1 AS\nPROCEDURE proc1(x INT) IS\nBEGIN\n  INSERT INTO t VALUES (x);\nEND proc1;\nPROCEDURE proc2(y INT) IS\nBEGIN\n  INSERT INTO t VALUES (y);\nEND proc2;\nEND pk1` · `SELECT 1 FROM sysibm.sysdummy1` (the first END belongs to the first procedure, the package closes at the last) |
| 47 | `/*\nDROP TABLE old;\n*/\nCREATE TABLE t (id INT);` | `/*\nDROP TABLE old;\n*/\nCREATE TABLE t (id INT)` (extension: measured, the CLP cuts after the word old and rejects both halves; a comment is never cut) |
| 48 | `INSERT INTO t VALUES ('x\n--#SET TERMINATOR @\ny')@` | `UnsafeStatementSplitError` (line 2; measured: the CLP keeps the directive line in the text and cuts the statement there) |
| 49 | `/*\n--#SET TERMINATOR @\n*/ SELECT 1 FROM sysibm.sysdummy1@` | `UnsafeStatementSplitError` (line 2; measured: the CLP switches the terminator inside the comment) |
| 50 | `CREATE TYPE pt AS (x INT) MODE DB2SQL;\nALTER TYPE pt ADD METHOD m() RETURNS INT LANGUAGE SQL;\nCREATE METHOD m() FOR pt\nBEGIN ATOMIC\n  DECLARE v INT;\n  RETURN v;\nEND;\nSELECT 1 FROM sysibm.sysdummy1;` | `CREATE TYPE pt AS (x INT) MODE DB2SQL` · `ALTER TYPE pt ADD METHOD m() RETURNS INT LANGUAGE SQL` · `CREATE METHOD m() FOR pt\nBEGIN ATOMIC\n  DECLARE v INT;\n  RETURN v;\nEND` · `SELECT 1 FROM sysibm.sysdummy1` (extension, §5; measured through the driver: the server accepts the body whole) |
| 51 | `VALUES 'x\n-- y;\nz';\nVALUES 2;` | `UnsafeStatementSplitError` (line 2; measured: inside a string the CLP reads the comment-like line as text, cuts the statement at its semicolon and the server rejects both halves; known gap: the splitter reads the line as a comment line and runs the statement whole) |
| 52 | `VALUES 'p\n(= q\n';\nVALUES 2;` | `VALUES 'p\n(= q\n'` · `VALUES 2` (measured: inside a string the CLP sends the line as string text and returns it; known gap: the splitter refuses the line as a CLP comment block) |
| 53 | `VALUES 1;\x0d\x0d\nVALUES 2;` | `VALUES 1` · `VALUES 2` (measured: a run of carriage returns before the line feed ends the line for the CLP, both statements run; known gap: the splitter drops one carriage return only and refuses the semicolon as one in the middle of a line) |
| 54 | `--#SET TERMINATOR \u00e9\u00e9\nVALUES 1\u00e9\u00e9\nVALUES 2;` | `UnsafeStatementSplitError` (line 1; measured with a UTF-8 file: the CLP counts the terminator in bytes, rejects a value of three or more bytes with DB21109E reason 1 and keeps the semicolon, so it never sends VALUES 1 alone; known gap: the splitter counts characters and accepts the directive) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| `--#SET` options other than `TERMINATOR` (`DELIMITER`, `MAXERRORS`, `AUTOCOMMIT`) | comments | measured: the CLP ignores them |
| `(=` … `=)` CLP comment blocks | rejected (row 29) | the CLP skips them without an error, statements inside included |
| A last statement without a terminator | **run** (row 17) | extension: the CLP does not run it (DB21007E, return code 2). |
| A routine body under `;` whose lines end in `;` | **kept whole** (rows 5a, 8, 9, 37-39, 41, 45, 46) | extension: the CLP cuts it and the pieces run as statements. |
| A comment-only segment before a terminator (`/* c */;`) | dropped, no statement (row 27) | the CLP sends it and the server rejects it, SQL0198N. |
| A leading UTF-8 byte order mark | dropped, as the migration loader does | the CLP sends it and the first statement fails (measured: SQL0104N on the first statement, the byte order mark glued to CREATE). |
| A line break inside a string literal or a quoted identifier | sent as written | the CLP replaces it with a blank (§1): `'x` newline `y'` is stored as `x y` there and as `x` newline `y` by dblift. |
| Lines of a routine or a view that are comments | sent as written | the CLP drops whole-line comments from a table's or a view's text and keeps them in a routine's; the stored view text differs by those lines only |
| A `;` in the middle of a statement, code after it | rejected (rows 12, 42) | the CLP sends it and the server rejects it; the driver drops the text after it silently (tightening: the previous splitter cut there) |
| A comment after a `;` on its line | the statement ends at the `;`, the comment is dropped (row 13) | extension: the CLP does not end the statement there and the server rejects the joined text. |
| A `;` at the end of a line inside a block comment | no cut (row 47) | extension: the CLP cuts and rejects both halves. |
| A terminator at the end of a line inside a string or a quoted identifier, a directive inside a string, a quoted identifier or a block comment | rejected (rows 18, 18a, 48, 49) | the CLP cuts or switches there and the server rejects the result |
| `CONNECT RESET`, `TERMINATE` and `QUIT` before the end of the script | rejected | they drop the connection's schema or the rest of the script |
| Whether the server accepts a whole package | not claimed | the reference container could not compile one (SQL1646N); rows 45 and 46 claim only where the package is cut |
| The line-continuation backslash | text | measured: `-t` disables it, and without `-t` a `\` at the end of a line is sent as an invalid character (SQL0007N) in a file run; there is nothing to continue |
| A no-break space or a form feed after the terminator | not blank | measured: the statement goes on and fails (SQL0104N, SQL0007N) |

## 12. Current implementation

Code: the client's rules are data. `dblift/db/plugins/db2/parser/lexical_spec.py` holds `DB2_RULES` (the starting terminator, the blanks, the `--#SET TERMINATOR` directive with its value pattern and the wording of its refusal, the comment line and comment block markers, the word alphabet, the command prefixes, words and phrases, the SQL phrases that share a command's first word, the epilogue commands and the pattern of their line, and the driver name the stray-semicolon refusal names), `DB2_ROUTINES` (the §5 rule: the create and alter verbs, the routine kinds, the package kind and its openers, the body word, the depth words, the closer and its qualifiers, the word that skips `OR REPLACE`) and `DB2_SPEC`, which holds them (client name `CLP`, nested block comments, the double-quote identifier, a leading byte order mark dropped, masking left on the Db2 tokenizer). The shared tokenizer reads a script by those rules in three stages through three core modules: `terminator_lines.py` (the line pass: each line is classified from its raw text and the active terminator alone, as a directive, a comment line, a comment block, a blank or code, and every consumed terminator is blanked so the lexemes are read from the text the CLP sends), the lexeme loop of `lexical_tokenizer.py` (the shared string, identifier and nested block comment readers; the block comment reader records the nesting depth at the end of each line that lies inside a comment) and `terminator_script.py` with `routine_body.py` (what the CLP remembers between lines: it builds the records with their source bounds and raises the refusals in the order the script meets them; `routine_body.py` is the §5 tracker). `Db2Quirks.lexical_spec()` returns the specification, so execution does not construct a regex parser; `db2_regex_parser.py` is a thin delegate (`split()` returns `Statement` records, `split_statements()` their execution text, `split_for_extraction()` the constituent view without directive records). The earlier scanner module is removed.

Every row of section 10 is a passing test except rows 51 to 54, which are known gaps listed in `KNOWN_GAPS` of the conformance test; each fails strictly, so a fix must remove its entry.

Masking and extraction: literal masking, object extraction and comment stripping still read the text with the Db2 nesting-comment tokenizer (`redaction_reads_engine` is false and the parser keeps its splitter specification under a name object extraction does not read). The two readings differ: the engine takes a quoted identifier or a comment left open to the end of the script, so a literal after it stays visible. Measured on 46 017 generated execution strings (2026-10-17): the engine's reading would mask 882 of them differently, 108 of them with fewer literals masked. `strict_tokenizer` changes nothing: the reader has no unknown characters. The splitter writes no log record; the analyzer's per-statement debug records are as before. Building an analyzer still logs, once, the debug record of the regex parser it builds for classification (measured: one record on construction and none on the first split, where the earlier scanner also logged one on the first split).

Refusals: client commands, a `(=` line, a `!` or `?` command and a `CONNECT RESET`, `TERMINATE` or `QUIT` before the last SQL statement are `UnsupportedMetaCommandError`; a stray semicolon, a terminator at the end of a line inside a string or quoted identifier, a terminator that is also half of a comment delimiter, a directive inside a string, quoted identifier or comment, a malformed directive, an epilogue command that is not alone on its line, a block comment left open and a routine body left open are `UnsafeStatementSplitError`, each naming its line and, where the CLP is the reference, the client as `CLP`. A NUL byte is text: Db2 has no rule for it, and an unterminated string or quoted identifier at the end of the script is returned as the last statement. Order of refusals: the script is read in order and the first refusal met is raised: a directive inside a lexeme, a malformed directive, a `(=` line, an overlapping terminator and a terminator inside a string are raised at their line; a client command and a stray semicolon are raised when their statement ends, the command first; at the end of the script a block comment left open is raised before a routine body left open, then the last statement is checked, and only then is an epilogue command before the last SQL statement refused.

Cost: splitting is linear in the length of the script and is a count-bounded test (`test_db2_splitting_cost.py`), not a clock. On the reference machine a 3 MiB script of one `INSERT` per line took 1.70 s and a 20.4 MB peak before the move and takes 1.96 s and a 226 MB peak after it (the token list is kept); the median corpus script (77 bytes) takes about 44 microseconds before and about 50 after, and the same script repeated to 100 KB takes 0.059 s and 1.3 MB before, 0.059 s and 7.6 MB after (timings repeat to within about 3% on the reference machine).

Current implementation gaps, kept as the earlier scanner had them (the CLP and dblift differ; each is a known difference and none changes a script that is not listed):

- Inside a string, a line that starts with `--` is read as a comment line and cannot end the statement; the CLP reads it as text (row 51).
- Inside a string or a comment, a line that starts with `(=` is refused; the CLP sends it as text (row 52).
- A run of carriage returns before a line feed is not a line end: only one is dropped (row 53).
- A directive value of one or two characters is accepted whatever its length in bytes; the CLP counts bytes and rejects three or more (row 54).
- Form feed, vertical tab, no-break space and line separator at either end of a statement are dropped from the text dblift sends; the CLP sends them and the server rejects the statement.
- A terminator followed by a lone carriage return at the end of the script, `VALUES 1;` and a carriage return, is returned as the last statement with its semicolon and no terminator; the CLP runs nothing (DB21007E).
- A vertical tab, form feed or no-break space right after a directive's value makes the directive malformed; the CLP takes the blank as part of the terminator and reads on.
- `CREATE OR` followed by any word and a routine kind is read as a routine head, so `CREATE OR ALTER PROCEDURE` is kept whole; the CLP cuts it at each semicolon line and the server rejects the statement.
- A routine with a declaration section before `BEGIN` (`CREATE OR REPLACE FUNCTION f RETURN NUMBER IS`, declarations, `BEGIN`) and a labelled compound statement (`lbl: BEGIN … END lbl;`) under the `;` terminator are cut at their semicolon lines, where the CLP cuts them; the server rejects both on a default database, the first needing the Oracle compatibility vector.

Tests: `tests/unit/core/sql_parser/test_db2_spec_conformance.py` runs every row of section 10 through `SqlAnalyzer.split_statements`; `test_db2_line_pass.py`, `test_db2_lexical_reading.py`, `test_db2_terminator_script.py`, `test_db2_client_commands.py` and `test_db2_routine_body.py` cover the stages rule by rule against recorded output of the scanner they replaced, `test_db2_shared_lexical_path.py` holds the routing, `test_db2_splitting_cost.py` bounds the work, `tests/unit/db/plugins/db2/test_script.py` covers the splitter rule by rule, `test_extraction_keeps_statements.py` checks that extraction and execution agree on refusals, and `test_extraction_view_unchanged.py` holds masking and extraction to their recorded output.
