# SQL Server — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | SQL Server 2016+, Azure SQL Database (T-SQL) |
| Code facts taken from | `develop` `532665c` (the shared lexical engine change, branch `feature/sqlserver-lexical-engine`, is described by §12); the pieces without code and the statement records at OSS `develop` `48051ff` (2026-10-19) |
| Vendor references, fetched 2026-10-10 | *SQL Server documentation*: "SQL Server Utilities Statements — GO", "Slash Star (Block Comment)", "Comment (Transact-SQL)", "Constants (Transact-SQL)", "Database identifiers", "sqlcmd utility" |
| Live verification | Ground truth `sqlcmd -C -I -b -i script.sql` with the ODBC `sqlcmd` 18.6 (`/opt/mssql-tools18/bin/sqlcmd`). `-I` is required with the ODBC sqlcmd: "Sets the SET QUOTED_IDENTIFIER connection option to ON. The default setting is OFF.", and dblift's driver connection runs with it ON. Every "measured 2026-10-11" below is `sqlcmd 18.6.0002.1 Linux` against `SQL Server 2022 RTM-CU25 16.0.4255.1` (Developer, Linux). The same probes were run through go-sqlcmd 1.10.0 (the Go rewrite, Homebrew `sqlcmd`, `-C -I -b -i`) against the same server; where it differs, the cell says "ODBC sqlcmd: …; go-sqlcmd: …". The dblift rule: follow the ODBC sqlcmd, the reference client, and refuse in addition anything go-sqlcmd would run differently without failing. The one script the ODBC sqlcmd accepts and go-sqlcmd silently runs differently is `GO--c` after a batch that can take an alias (row 7b), which is refused; the scripts go-sqlcmd runs and the ODBC sqlcmd rejects are refused because the ODBC sqlcmd rejects them; where go-sqlcmd fails loudly on what the ODBC sqlcmd runs, dblift follows the ODBC sqlcmd. |
| Engine subclass | none |

The central decision of this specification is that **the unit the splitter
returns is the batch, not the `;`-terminated statement**. T-SQL variables,
temporary-object visibility rules and `CREATE PROCEDURE` placement are all
defined per batch; `sqlcmd` and SSMS send a batch as one request; and the
server accepts several statements in one request. Splitting a batch at `;`,
as the current code does, changes the meaning of valid scripts
(`DECLARE @x INT = 1; SELECT @x;` fails because `@x` is undeclared in the
second request). The extractor, not the splitter, divides a batch into
statements for reporting.

## 1. String literals

| Form | Opens | Closes | Escape inside | Note |
| --- | --- | --- | --- | --- |
| Character string | `'` | `'` | `''` | "Constants": "If a character string enclosed in single quotation marks contains an embedded quotation mark, represent the embedded single quotation mark with two single quotation marks." No backslash escapes. |
| Unicode string | `N'` | `'` | `''` | "'Michél' is a character constant while N'Michél' is a Unicode constant" |
| Binary | `0x…` | end of hex digits | none | "Binary constants have the prefix 0x and are a string of hexadecimal numbers. They aren't enclosed in quotation marks." |
| Money | `$12.50`, `£…` | end of digits | none | currency symbols are literal prefixes, not unknown characters |

`"…"` is **never** a string: "If the QUOTED_IDENTIFIER option has been set OFF
for a connection, character strings can also be enclosed in double quotation
marks, but the Microsoft OLE DB Driver for SQL Server and ODBC Driver for SQL
Server automatically use SET QUOTED_IDENTIFIER ON." A script that relies on
`OFF` is listed under *Not handled*.

## 2. Identifiers

| Form | Opens | Closes | Escape inside |
| --- | --- | --- | --- |
| Bracketed | `[` | `]` | `]]` |
| Quoted | `"` | `"` | `""` |
| Regular | letter, `_`, `@`, `#` | end of `[A-Za-z0-9_@#$]` | — |

"Database identifiers": regular identifiers "can only contain letters,
digits, and certain symbols (_, @, #, $), must start with a letter or one of
_, @, #"; "If the identifier itself contains a right bracket (]), escape it by
doubling it (]]). A left bracket ([) doesn't require escaping."; "If the
identifier itself contains a double quotation mark, escape it by doubling it
("")." So `@local`, `@@system`, `#temp` and `##global` are regular identifiers.
`$action`, `$IDENTITY` and `$PARTITION` are not (a regular identifier cannot
start with `$`); they are special tokens the identifier alphabet must
tolerate, and `$` is never an unknown character.

## 3. Comments

| Form | Opens | Closes | Nests |
| --- | --- | --- | --- |
| Line | `--` | end of line | — |
| Block | `/*` | `*/` | **the server: yes. sqlcmd: no.** |

"Slash Star (Block Comment)": "Nested comments are supported. If the /\*
character pattern occurs anywhere within an existing comment, it is treated
as the start of a nested comment and, therefore, requires a closing \*/
comment mark. If the closing comment mark does not exist, an error is
generated." That is the server's rule. No comment form carries directives.

The server and the client disagree about where a block comment ends, and the
client decides where a batch ends, so the splitter reads as the client does:

- **The server nests** (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `/* a /* b */\nCREATE TABLE t06 (id INT)\nGO` → `Msg 113 … Missing end comment mark '*/'`, exit 1; `/* a /* b */ */\nCREATE TABLE t06 (id INT)\nGO` creates `t06`; `/* a /* b */ CREATE TABLE t06z (id INT) */\nCREATE TABLE t06 (id INT)\nGO` creates `t06` only).
- **sqlcmd's lexer, which looks for `GO` and the commands of §6, ends a block comment at the first `*/`** (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `/* a /* b */ GO */\nCREATE TABLE t06 (id INT)\nGO` → `Sqlcmd: Error: Syntax error at line 1 near command 'GO' in file …`, exit 1, nothing ran: the client read the `GO` after the first `*/` as a command and the `*/` after it as text; `/* a\nGO\n/* b */\nGO\n*/ CREATE TABLE t06 (id INT)\nGO` → the `GO` of line 4 cut the script and the server rejected the first half, `Msg 113 … Line 4`, exit 1).
- A `GO` alone on a line inside a block comment is text, not a separator (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `/* a\nGO\n*/\nCREATE TABLE t06 (id INT)\nGO` creates `t06`).
- `--` inside a block comment and `/*` inside a line comment do nothing (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `/* a -- b */ CREATE TABLE ta (id INT)\nGO` creates `ta`; `-- /*\nGO\nCREATE TABLE ta (id INT)\nGO` cuts at the `GO`). An apostrophe inside a comment opens nothing (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `/* it's */` and `-- it's` before a `GO`). `/*` and `--` inside a string literal are text (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `INSERT INTO ta VALUES ('/*')\nGO\nCREATE TABLE tb (id INT)\nGO` creates `tb`).
- An unterminated block comment swallows every later `GO`: the rest of the script is one batch and the server rejects it (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `CREATE TABLE ta (id INT)\n/* x\nGO\nCREATE TABLE tb (id INT)\nGO` → `Msg 113 … Line 6`, exit 1, nothing created).

The two readers can disagree only into an error. The server's comment ends at the
matching `*/`, never before the client's, so the client never reads as comment what
the server reads as code. The reverse can happen: a `GO` the client cuts at inside a
comment the server still holds open leaves that comment unclosed in the first half,
which the server rejects (`Msg 113`); the commented-out text never runs.

go-sqlcmd 1.10.0 reads comments the same way except that a `GO` after a `*/` on the same line is text for it (`/* a /* b */ GO */` runs there and creates the table, where the ODBC sqlcmd refuses it).

The splitter therefore ends a block comment at the first `*/`, passes the batch
text through verbatim, and leaves nesting to the server. The one place it reads nesting is the decision whether a batch is a statement at all: a batch the server reads as nothing but closed comments (`/* a /* b */ */`, `/* a */`) is not one, and a batch the server reads as an unclosed comment (`/* a /* b */`) is, so it is sent and fails as the server does (`Msg 113`; rows 6d to 6g). A script whose nesting
makes the two readers disagree is rejected by sqlcmd and gets the same verdict
here: row 6 is refused by the splitter, row 6c is cut where sqlcmd cuts and the
server rejects the first half.

## 4. Terminators

| Terminator | Rule |
| --- | --- |
| `GO` | **Batch separator.** A line whose first token is `GO` (leading blanks and tabs allowed, any case) followed on the same line only by blanks, an optional count (`GO 3`) and an optional `--` comment. `GO` is not sent to the server. It is recognised only outside strings, bracketed identifiers, quoted identifiers and block comments: a `GO` alone on a line inside any of them is text (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `'a\nGO\nb'`, `[a\nGO\nb]`, `"a\nGO\nb"` each leave one batch and the object exists; the same for `N'…'` and for a double-quoted string under `SET QUOTED_IDENTIFIER OFF`). A CRLF line end, a UTF-8 byte order mark at the start of the file, a tab between `GO` and the count (ODBC sqlcmd only: go-sqlcmd sends `GO\t2` to the server), and a last line without a newline (`GO -- c` at end of file) are all accepted (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1). **Only a `--` comment may follow**: `GO /* c */`, `GO /* c` and `GO // c` are client errors (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `Sqlcmd: Error: Syntax error at line 2 near command 'GO' in file …`, exit 1, the pending batch did not run, earlier batches did), as are `GO foo`, `GO 5x`, `GO -1`, `GO +2`, `GO 2 3` and `GO ;`; the splitter refuses each with `UnsafeStatementSplitError` naming the line. **`--` directly after `GO` (`GO--c`) is refused too**, for another reason: the ODBC sqlcmd takes it for a separator, go-sqlcmd sends `GO` to the server as text, so a batch that can take an alias absorbs `GO` and the next statement joins it (row 7b). **`GO;` with no blank is different**: sqlcmd does not take it for a command, the line goes to the server as text (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `CREATE TABLE t14 (id INT)\nGO;\nINSERT INTO t14 VALUES (1)` → `Msg 102 … Incorrect syntax near 'GO'`, exit 1; `SELECT 1\nGO;` runs and returns a column named `GO`). The splitter refuses `GO;` anyway, because the author meant a separator (row 14). **The first token of a line decides, and so does the character after it** (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1): after the word `go`, a blank, the end of the line, `-`, `=`, `(`, `[`, `'` or `/` make the line a command, or a client error where it is not a valid one (`go INT`, `go = 1`, `go(1)`, `go[1]`, `go'x'`, `go/*c*/`, `go-1` and `go ;` are `Sqlcmd: Error: Syntax error … near command 'go'`; `GO--c` is a command); after `.`, `,`, `;`, `+`, `)`, `*`, `:`, `|`, `<`, `@` or a letter the line goes to the server as text (`go.id`, `go,` and `go@x` run, `go+1`, `go)`, `go*2`, `go:x`, `go|1`, `go<1` and `GOO` fail as SQL with `Msg 102`; `GOTO` is a label statement). The splitter reads the same follower set; its one deliberate exception is `GO;`, refused (row 14). `GO` after the first token (`SELECT 1 AS go`, `SELECT 1 GO`, `SELECT go INT FROM t`, `[go]`) is an identifier. sqlcmd takes a `GO` that follows **exactly one** block comment on its line as a command and one that follows two as text (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `/* c */ GO` separates, `/* a */ /* b */ GO` → `Msg 102 … near 'GO'`); the splitter refuses a `GO` that follows a comment on its line rather than model that (row 23). |
| where go-sqlcmd differs | go-sqlcmd 1.10.0 (same probes, same server). It **agrees** with the ODBC sqlcmd on `GO /* c */`, `GO foo`, `GO ;`, `GO;` (text for the server, `Msg 102`), `GO -1`, a column named `go`, `exit`, `quit` or `ed` at a line start (client error), the first-`*/` comment rule when no `GO` follows the `*/` on its line (rows 6b, 6c), and `$(var)` (substituted in text, strings and `[…]`, not in comments; the environment counts). It **differs**: `GO--c`, `GO\t2`, `GO 0` and a `GO` after a comment on its line (`/* c */ GO`, `b */ GO` after a multi-line comment) are not accepted as commands (`GO--c`, `GO\t2` and `/* c */ GO` reach the server as text, `Msg 102`; `GO 0` is `Sqlcmd: Error: Syntax error`); `GO 5x`, `GO +2` and `GO 2 3` are accepted; `/* a /* b */ GO */` runs and creates the table (ODBC: client error); `[$(nope)]` with an undefined variable prints `'nope' scripting variable not defined.` **and runs**, creating a table literally named `$(nope)`; `RESET now` is accepted (the text ignored), `reset = 1` and `go/*c*/` are SQL; `:perftrace` and `:serverlist` are not commands (`Msg 102`). Of these, the ones go-sqlcmd runs and the ODBC sqlcmd rejects (`/* a /* b */ GO */`, `GO 2 3`, `GO +2`, `go/*c*/`, `reset = 1`, `RESET now`, `[$(nope)]`) are refused by dblift because the ODBC sqlcmd rejects them; the ones the ODBC sqlcmd runs and go-sqlcmd rejects loudly (`GO\t2`, `GO 0`) dblift follows the ODBC sqlcmd on, and records as known differences. `GO--c` is the third kind: go-sqlcmd fails loudly only when the batch cannot take an alias (`SELECT 1 AS a INTO ta`, `Msg 102`) and runs silently when it can: `DECLARE @v INT = 5`, `SELECT * FROM tr3`, `GO--end`, `INSERT INTO tr3 VALUES (@v)` exits 0 (the objects it leaves were checked, the rows were not counted), whereas the ODBC sqlcmd cuts it and fails with `Msg 137` (measured 2026-10-11, go-sqlcmd 1.10.0, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1). dblift refuses it (row 7b). |
| `GO n` | The batch is sent *n* times (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `GO 3` → three rows; `GO 002` → two; `GO\t2` and `GO 2 -- c` accepted; `GO 0` → the batch does not run). `split_statements` returns the batch *n* times, because execution sends what it receives; the `Statement` record is one entry with `repeat=n` (`GO 0`: no string is returned). sqlcmd puts no small limit on the count (`GO 99999999999` repeated the batch until the probe was killed after 30 s; the count actually executed is unknown). `split_statements` materialises one string per repetition, so the splitter refuses a count above 1 000 000 (about 8 MB of references; a count of 10⁹ would exhaust memory before anything ran): a bound of its own, not a sqlcmd rule, pinned by row 30. `GO 0` is logged, not dropped silently. go-sqlcmd: `GO 0` is a client syntax error, `GO\t2` is text. |
| `;` | **Not a splitter terminator.** It stays in the batch text and the server reads it (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `CREATE TABLE ta (id INT);;\nINSERT INTO ta VALUES (1);\n;\nGO` runs; a bare `;` is harmless). A batch of nothing but `;`, blanks and comments is not a statement. |

Vendor rules ("SQL Server Utilities Statements — GO"): "GO is not a
Transact-SQL statement; it is a command recognized by the sqlcmd and osql
utilities and SQL Server Management Studio Code editor." "The current batch
of statements is composed of all statements entered since the last GO, or
since the start of the ad hoc session or script if this is the first GO." "A
Transact-SQL statement cannot occupy the same line as a GO command. However,
the line can contain comments." "GO [count] … The batch preceding GO will
execute the specified number of times." "The scope of local (user-defined)
variables is limited to a batch, and cannot be referenced after a GO
command." "The SQL Server utilities never send a GO command to the server."
The page's "the line can contain comments" is narrower in sqlcmd 18.6: `--`
only (measured above).

A script without `GO` is one batch, and a last batch without a trailing `GO`
runs (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `CREATE TABLE t02 (id INT);\nGO\nGO\nINSERT INTO t02 VALUES (1);` creates the table and the row; `GO` as the last characters of the file, with no newline, runs the final batch: that the `GO` separated is not distinguishable from the end of the file flushing it, `row02` shows the flush happens anyway).

## 5. Blocks

None needed. Because `;` does not split, `BEGIN … END`, `BEGIN TRY … END
CATCH`, `CASE … END`, `BEGIN TRANSACTION` and procedure bodies without
`BEGIN` cannot be cut. The whole category of block-depth defects in the
current parser (see §12) disappears with the batch decision.

One consequence is the server's, not the splitter's: `CREATE PROCEDURE`,
`CREATE VIEW`, `CREATE FUNCTION`, `CREATE TRIGGER`, `CREATE SCHEMA` and
`CREATE OR ALTER PROCEDURE` must be the first statement of their batch
(measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: each after `CREATE TABLE ta (id INT)` → `Msg 111 … must be the first statement in a query batch.`, exit 1, nothing created; the same after `USE probe` and after `SELECT 1;`; comments before it are fine). The splitter does not move a `GO` for the author (row 27).

## 6. Client directives

| Directive | Client | Splitter action |
| --- | --- | --- |
| every sqlcmd command: `:setvar`, `:r`, `:connect`, `:on error`, `:exit`, `:quit`, `:list`, `:listvar`, `:error`, `:out`, `:perftrace`, `:help`, `:serverlist`, `:xml`, `:reset`, `:ed`, `:!!`, and the osql-compatible colon-less forms `RESET`, `ED`, `!!`, `QUIT`, `EXIT` | sqlcmd | **reject** with `UnsupportedMetaCommandError` naming the directive and line. Microsoft: "All sqlcmd commands, except GO, must start with a colon (:) … To maintain backward compatibility with existing osql scripts, some commands work without the colon"; "sqlcmd recognizes commands only if they appear at the start of a line." sqlcmd honours every one of them (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `:setvar t dbo` then `CREATE TABLE $(t).tsv (id INT)` creates `tsv`; `:r file` runs the file, `GO` inside it included; `:on error ignore` continues after an error; `:connect`, `:listvar`, `:list`, `:error`, `:out`, `:perftrace`, `:reset`, `RESET` run; `!!echo hi` and `:!!echo hi` run a shell command; `:exit`, `:quit`, `EXIT`, `exit` and `QUIT` end the script with exit code 0 and discard a pending batch; `EXIT(SELECT 42)` exits with code 42; `:xml` and `:serverlist` print "currently unavailable in the Linux version" and end the script). |
| where a directive is recognised | sqlcmd | At the first token of a line, leading blanks allowed, any case, **even in the middle of a statement** (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `CREATE TABLE ta (id INT,\n:setvar a b\n x INT)\nGO` creates `ta`: sqlcmd consumed the line and the statement went on; the splitter refuses it, row 22). **Not** inside a string literal or a comment (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `INSERT INTO ta VALUES ('x\n:setvar a b\ny')` stores the three lines; `/*\n:setvar a b\n*/\nCREATE TABLE ta (id INT)\nGO` creates `ta`; the same for `EXIT` and `:r` alone on a line inside a string) and **not** after other text on the line (`SELECT 1 AS a INTO ta :setvar x y` → `Msg 102 … near ':'`). An unknown `:foo` is SQL text sent to the server (`Msg 102 … Incorrect syntax near ':'`), and the splitter passes it through (row 21). |
| the colon-less words `RESET`, `ED`, `QUIT`, `EXIT` | sqlcmd | A command when it is the first token of a line and followed as `GO` is above (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1, each probed alone in `CREATE TABLE ta (\n  <word> INT\n)\nGO`): `exit`, `quit`, `reset` and `ed` are each `Sqlcmd: Error: Syntax error … near command '<word>'`; so are `EXIT foo`, `QUIT now`, `RESET now`, `<word> = 1` and `<word>(1)` for `quit`, `reset` and `ed`. `<word>.id`, `<word>,` and `<word>;` are text for the server: `SELECT 1\nquit;` returns a column named `quit`, `ed.id` and `quit.id` as qualified aliases run, `exit.id` fails as SQL (`exit` is a reserved word, `Msg 156`). The splitter refuses a line whose first token is one of the four words followed by a command follower (`UnsupportedMetaCommandError`) and passes the others through. go-sqlcmd: the same for `exit`, `quit` and `ed`; `RESET now` is accepted (text ignored) and `reset = 1` is SQL. |
| `$(name)` variable reference | sqlcmd, go-sqlcmd | **reject** with `UnsupportedMetaCommandError` outside comments, unless a placeholder service substitutes it before splitting. sqlcmd substitutes it in plain text, in strings and in identifiers, and fails when it is undefined (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `CREATE TABLE $(nope) (id INT)` and `INSERT INTO ta VALUES ('$(x)')` and `CREATE TABLE [$(nope)] (id INT)` → `'nope' scripting variable not defined.`, exit 1); a variable can be set by `:setvar`, by the environment (`CREATE TABLE [$(HOME)] (id INT)` created `/home/mssql`) or by sqlcmd itself. It does **not** substitute inside `--` or `/* */` comments (`-- $(zz)` and `/* $(zz) */` before a statement are no error), and `$ (x)` is text. sqlcmd documents the ambiguity: its `-x` option "Causes sqlcmd to ignore scripting variables. This parameter is useful when a script contains many INSERT statements that might contain strings that have the same format as regular variables, such as $(<variable_name>)." (with `-x` the string `'$(x)'` is stored as is, measured). |
| `USE db` | server statement | pass through (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `USE tempdb\nGO\nCREATE TABLE tu (id INT)\nGO\nSELECT DB_NAME()` runs in `tempdb`: the context persists across `GO`) |
| `PRINT`, `RAISERROR` | server statements | pass through |

A directive is recognised only at the first token of a line, outside strings
and comments.

A command word after a comment on its line (`/* c */ EXIT`, `/* c */ :setvar a b`) is refused: sqlcmd takes it as a command (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1, `-i`: after `/* c */ :setvar a b` the next statement ran without error, and `/* c */ EXIT` was not sent to the server as text).

Any `$(` outside a comment is refused with `UnsupportedMetaCommandError` naming the text and line, strings and `[…]` included: sqlcmd reads `$(x-y)` as a variable reference (`'x-y' scripting variable not defined.`) and fails on `$()`, `$(1x)`, `$(a.b)`, `$(x y)`, `$(` and `$(x` (measured 2026-10-11, `sqlcmd -C -I -b -i file`, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1, each as `SELECT 1 AS a, '<text>' AS b` + `GO`: exit 1, e.g. `$(a.b)` gives `Sqlcmd: Error: Syntax error at line 1 near command '.' in file …`). `$ (x)` with a blank is text.

A command word followed by a character other than a blank, the end of the line, `- = ( [ ' /` goes to the server as text (measured 2026-10-11 with the ODBC sqlcmd 18.6, SQL Server 2022 RTM-CU25, `-i`: `exit+1`, `exit)` and `exit|1` give Msg 156; `quit*2`, `reset<1` and `ed@x` give Msg 102; `GO` has the same follower set, §4).

## 7. Raw blocks

None.

## 8. Transaction markers

Statements the splitter flags as *not transactional*; execution runs them in
autocommit. The flag is set from the first keywords of a statement after
comments; a batch is flagged as a whole when ANY of its statements is one of these
(the batch is divided into statements to find out, with scanner-derived analysis constituents: `CREATE TABLE a (id INT);\nCREATE FULLTEXT INDEX …` with no `GO` is flagged) and reported. The division follows `;`: a statement SQL Server refuses in a transaction must start a `;`-terminated statement or its own batch; otherwise the server reports the error (Msg 226, 574 or 3021) and the batch rolls back. Every pattern below is a statement SQL Server
refuses inside a user transaction (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `BEGIN TRANSACTION; <statement>; COMMIT;`), exit 1, nothing created:

| Pattern (first keywords) | Measured error | Flagged |
| --- | --- | --- |
| `CREATE FULLTEXT CATALOG`, `CREATE FULLTEXT INDEX`, `DROP FULLTEXT INDEX`, `DROP FULLTEXT CATALOG` | `Msg 574 … statement cannot be used inside a user transaction.` | yes |
| `ALTER FULLTEXT CATALOG`, `ALTER FULLTEXT INDEX` | `Msg 574 … ALTER FULLTEXT CATALOG statement cannot be used inside a user transaction.` (the image has no Full-Text Search, `SERVERPROPERTY('IsFullTextInstalled')` is 0; the statements fail with 574 before anything else) | yes |
| `CREATE DATABASE`, `ALTER DATABASE` (`SET`, `MODIFY FILE`, `SCOPED CONFIGURATION` alike) | `Msg 226 … statement not allowed within multi-statement transaction.` | yes |
| `DROP DATABASE` | `Msg 574 … DROP DATABASE statement cannot be used inside a user transaction.` | yes |
| `BACKUP DATABASE`, `BACKUP LOG`, `RESTORE DATABASE`, `RESTORE LOG`, `RESTORE VERIFYONLY` | `Msg 3021 … Cannot perform a backup or restore operation within a transaction.` | yes |
| `RECONFIGURE` (also `WITH OVERRIDE`) | `Msg 574 … CONFIG statement cannot be used inside a user transaction.` | yes |
| `KILL` (a session id, `STATS JOB n`, a unit-of-work GUID, `QUERY NOTIFICATION SUBSCRIPTION`) | `Msg 6115 …` (measured with `-i`, `BEGIN TRANSACTION; <statement>; ROLLBACK;`) | yes |
| `ALTER SERVER CONFIGURATION`, `ALTER SERVER AUDIT` | `Msg 574 …` (`SET PROCESS AFFINITY CPU = AUTO`, `WITH (STATE = OFF)`) | yes |
| `DROP FULLTEXT STOPLIST`, `DROP SEARCH PROPERTY LIST` | `Msg 574 …` | yes |

Accepted inside a user transaction, so **not** flagged (same measurement, exit 0): `RESTORE HEADERONLY`, `RESTORE FILELISTONLY`, `RESTORE LABELONLY`, `BACKUP MASTER KEY`, `CREATE DATABASE SCOPED CREDENTIAL`, `ALTER DATABASE SCOPED CREDENTIAL`, `DROP DATABASE SCOPED CREDENTIAL`, `CREATE DATABASE ENCRYPTION KEY`, `CREATE DATABASE AUDIT SPECIFICATION`. The `ALTER` and `DROP` forms of `DATABASE ENCRYPTION KEY` and `DATABASE AUDIT SPECIFICATION`, `BACKUP CERTIFICATE` and `BACKUP SERVICE MASTER KEY` were not measured and are treated as transactional. `RESTORE REWINDONLY` is a tape command (Msg 3216 on a disk device) and was not classified. `ALTER FULLTEXT STOPLIST` answered Msg 7609 here (no Full-Text Search installed), which says nothing about transactions, and is not flagged.

## 9. Engine subclass

None. Every rule above is expressible as data: quote pairs, identifier
alphabet, non-nested block comments (for the client), a line-anchored batch
separator with an optional count and comment, command and variable words. The
sqlcmd rules are the data of `BatchScriptRules` and `DivisionRules` in
`SQLSERVER_SPEC`, read by the shared tokenizer and engine.

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `SELECT 1\nGO\n` | `SELECT 1` |
| 2 | `CREATE TABLE t (id INT);\nGO\nGO\nSELECT 1;\n` | `CREATE TABLE t (id INT);` · `SELECT 1;` (empty batch dropped) |
| 3 | `DECLARE @x INT = 1;\nSELECT @x;\nGO` | one batch: `DECLARE @x INT = 1;\nSELECT @x;` |
| 4 | `CREATE PROCEDURE p AS\nSELECT 1;\nSELECT 2;\nGO\nEXEC p;` | `CREATE PROCEDURE p AS\nSELECT 1;\nSELECT 2;` · `EXEC p;` |
| 5 | `SELECT 'GO\n' AS s\nGO` | `SELECT 'GO\n' AS s` |
| 5a | `SELECT 'a\nGO\nb' AS s\nGO` | `SELECT 'a\nGO\nb' AS s` (a GO alone on a line inside a string is text) |
| 5b | `CREATE TABLE [a\nGO\nb] (id INT)\nGO` | `CREATE TABLE [a\nGO\nb] (id INT)` (the same inside a bracketed identifier) |
| 5c | `SELECT 'a'␍GO` | `UnsafeStatementSplitError` (a lone CR in code is not a GO line break) |
| 5d | `SELECT [x]␍GO` | `UnsafeStatementSplitError` (the same after a bracketed identifier) |
| 5e | `SELECT 'a␍GO';\nGO` | `SELECT 'a␍GO';` (a CR and GO inside a string are text) |
| 5f | `SELECT [x␍GO];\nGO` | `SELECT [x␍GO];` (the same inside a bracketed identifier) |
| 6 | `/* a /* b */ GO */\nSELECT 1\nGO` | `error` (measured: sqlcmd ends the comment at the first `*/`; `GO */` is text after `GO`: client syntax error, exit 1; go-sqlcmd runs it and creates the table; §3) |
| 6a | `SELECT /* a /* b */ */ 1\nGO` | `SELECT /* a /* b */ */ 1` (no GO involved: the nested comment is the server's, the text is passed through) |
| 6b | `SELECT 1 /* a\nGO\n*/\nGO` | `SELECT 1 /* a\nGO\n*/` (a GO alone on a line inside a block comment is text) |
| 6c | `SELECT 1 /* a\nGO\n/* b */\nGO\n*/` | `SELECT 1 /* a\nGO\n/* b */` · `*/` (the client cuts at the GO of line 4 because the comment it opened at line 1 ended at the first star-slash; the server then rejects the first half, Msg 113) |
| 6d | `SELECT 1\nGO\n/* a /* b */\nGO\nSELECT 2\nGO\n` | `SELECT 1` · `/* a /* b */` · `SELECT 2` (measured 2026-10-19, sqlcmd 18.6.0002.1, SQL Server 2022 RTM-CU25 16.0.4255.1: the second GO is a separator, because sqlcmd ends the comment at the first star-slash; the fragment is sent as its own batch and the server nests, so it is not a closed comment: Msg 113 Missing end comment mark, through sqlcmd and pymssql alike; SELECT 2 then runs. A batch is a statement when the server does not read it as comment only) |
| 6e | `/* a /* b */ */` | `(empty)` (measured 2026-10-19, sqlcmd 18.6.0002.1, SQL Server 2022 RTM-CU25 16.0.4255.1: the server nests, the comment is closed, the batch is accepted and does nothing; no record, though the client reading leaves a stray star-slash after the first one) |
| 6f | `/* a */` | `(empty)` (measured 2026-10-19, sqlcmd 18.6.0002.1, SQL Server 2022 RTM-CU25 16.0.4255.1: accepted, a comment only) |
| 6g | `/* a /* b */ SELECT 1` | `/* a /* b */ SELECT 1` (measured 2026-10-19, sqlcmd 18.6.0002.1, SQL Server 2022 RTM-CU25 16.0.4255.1: the server reads all of it as one open comment, Msg 113; the batch is kept whole and sent, so it fails as the server does) |
| 6h | `/* a /* b */ */ /* c` | `error` (the comment opened last is never closed, in either reading: the splitter refuses the script as it refuses any unterminated block comment; the server answers `Msg 113`) |
| 6i | `/* a /* b */ 'x */ y'` | `/* a /* b */ 'x */ y'` (the client reads a comment and then the string, which is code; the server reads a nested comment through the first star-slash after the b and then an unclosed quotation mark; not measured itself: it follows from the measured nesting rule (row 6d), under which the server reads the star-slash inside the quotes as the end of the nested comment and the quotation mark that follows is left unclosed; expected Msg 105 unclosed quotation mark) |
| 6j | `/*/**/'*/'` | `/*/**/'*/'` (the same: not measured itself: it follows from the measured nesting rule (row 6d), under which the server reads the star-slash inside the quotes as the end of the nested comment and the quotation mark that follows is left unclosed; expected Msg 105 unclosed quotation mark) |
| 7 | `SELECT [go] FROM t\ngo -- end\n` | `SELECT [go] FROM t` |
| 7a | `SELECT 1\nGO /* c */\nSELECT 2` | `error` (measured: only a `--` comment may follow `GO`; `Sqlcmd: Error: Syntax error … near command 'GO'`, exit 1) |
| 7b | `SELECT 1\nGO--c\nSELECT 2` | `error` at line 2 (ODBC sqlcmd: `GO--c` is a separator, both batches run; go-sqlcmd: `GO` goes to the server as text, which a batch ending in an expression takes as an alias, so `SELECT * FROM t\nGO--end\nSELECT 2` runs as one batch with exit 0 (measured 2026-10-11); the splitter refuses `--` directly after `GO`: "GO must be followed by a blank, a count or end of line; `--` directly after GO is read differently by sqlcmd clients") |
| 8 | `INSERT INTO t VALUES (1)\nGO 3\n` | `INSERT INTO t VALUES (1)` · `INSERT INTO t VALUES (1)` · `INSERT INTO t VALUES (1)` (measured: GO 3 runs the batch three times; the Statement record is one entry with repeat=3) |
| 8a | `INSERT INTO t VALUES (1)\nGO 0\nSELECT 2` | `SELECT 2` (measured: GO 0 runs the batch zero times) |
| 8b | `SELECT 1\nGO 5x\nSELECT 2` | `error` (measured: `Sqlcmd: Error: Syntax error … near command 'GO'`, exit 1) |
| 9 | `SELECT N'it''s'\nGO` | `SELECT N'it''s'` |
| 10 | `MERGE t USING s ON 1=1 WHEN MATCHED THEN DELETE OUTPUT $action;\nGO` | `MERGE t USING s ON 1=1 WHEN MATCHED THEN DELETE OUTPUT $action;` (one batch; the $action token is not an error) |
| 11 | `:setvar schema dbo\nGO` | `UnsupportedMetaCommandError` (line 1, `:setvar`; sqlcmd honours it, the splitter refuses by design) |
| 12 | `GOTO label\nGO` | `GOTO label` |
| 12a | `SELECT\n    go.id\nFROM t AS go\nGO` | `SELECT\n    go.id\nFROM t AS go` (a qualified alias: go. is text for sqlcmd, measured) |
| 12b | `SELECT\n    go,\n    2 AS b\nFROM t\nGO` | `SELECT\n    go,\n    2 AS b\nFROM t` (go, is text for sqlcmd, measured) |
| 13 | `SELECT 1 GO` | `SELECT 1 GO` (one batch; the server accepts it as SELECT 1 AS GO, exactly as it does for sqlcmd) |
| 14 | `SELECT 1\nGO;` | `error` at line 2 (measured: neither sqlcmd nor go-sqlcmd takes `GO;` for a command; the line goes to the server, which mostly rejects it with `Msg 102` but runs `SELECT 1\nGO;` as `SELECT 1 AS GO`; the splitter refuses `GO;` anyway) |
| 15 | `SELECT 1 AS go;\nSELECT 2;\nGO` | `SELECT 1 AS go;\nSELECT 2;` (one batch) |
| 16 | `SELECT go INT FROM t;\nSELECT 2;\nGO` | `SELECT go INT FROM t;\nSELECT 2;` (one batch) |
| 17 | `EXIT\nSELECT 1\nGO` | `UnsupportedMetaCommandError` (line 1, `EXIT`: an osql-compatible sqlcmd command; sqlcmd stops there, exit 0, and discards what follows) |
| 18 | `:r include.sql\nGO` | `UnsupportedMetaCommandError` (line 1, `:r`; sqlcmd runs the file) |
| 19 | `SELECT * FROM $(table)\nGO` | `UnsupportedMetaCommandError` (line 1, `$(table)`; sqlcmd substitutes it or fails) |
| 19a | `SELECT 1 -- $(x)\nGO` | `SELECT 1 -- $(x)` (measured: sqlcmd does not substitute inside a comment) |
| 19b | `SELECT '$(x)' AS s\nGO` | `UnsupportedMetaCommandError` (line 1, `$(x)`; measured: sqlcmd substitutes inside a string literal) |
| 20 | `SELECT 'a\n:setvar x y\nb' AS s\nGO` | `SELECT 'a\n:setvar x y\nb' AS s` (a directive line inside a string is text) |
| 20a | `SELECT 1 /*\n:setvar x y\n*/\nGO` | `SELECT 1 /*\n:setvar x y\n*/` (the same inside a block comment) |
| 21 | `:foo\nGO` | `:foo` (an unknown colon word is SQL text; the server rejects it, Msg 102) |
| 22 | `CREATE TABLE t (id INT,\n:setvar x y\n x INT)\nGO` | `UnsupportedMetaCommandError` (line 2: sqlcmd consumes the line mid-statement and the statement goes on) |
| 23 | `SELECT 1\n/* c */ GO\nSELECT 2` | `error` (the splitter refuses a `GO` that follows a comment on its line; sqlcmd takes it as a command after one comment and as text after two; go-sqlcmd takes `/* c */ GO` as text, `Msg 102`) |
| 24 | `CREATE TABLE t (\n  exit INT\n)\nGO` | `UnsupportedMetaCommandError` (line 2, `exit`: both clients error on a column named like a command at the start of a line) |
| 24a | `CREATE TABLE t (\n  quit INT\n)\nGO` | `UnsupportedMetaCommandError` (line 2, `quit`; measured alone) |
| 24b | `CREATE TABLE t (\n  reset INT\n)\nGO` | `UnsupportedMetaCommandError` (line 2, `reset`; measured alone) |
| 24c | `CREATE TABLE t (\n  ed INT\n)\nGO` | `UnsupportedMetaCommandError` (line 2, `ed`; measured alone) |
| 24d | `SELECT 1\nquit;\nSELECT 2` | `SELECT 1\nquit;\nSELECT 2` (quit; is text for sqlcmd, a column named quit; measured) |
| 25 | `SELECT 1 /* x\nGO\nSELECT 2` | `UnsafeStatementSplitError` (unterminated block comment; sqlcmd sends the rest as one batch and the server rejects it) |
| 26 | `SELECT 'abc\nGO\n` | `UnsafeStatementSplitError` (unterminated string literal swallows the `GO`) |
| 27 | `USE db\nCREATE PROCEDURE p AS SELECT 1\nGO` | `USE db\nCREATE PROCEDURE p AS SELECT 1` (one batch; the server rejects it, Msg 111) |
| 29 | `;\nGO\nSELECT 2` | `SELECT 2` (a batch of only a semicolon is not a statement) |
| 29a | `\xa0;\nGO\nSELECT 2` | `SELECT 2` (a batch holding only a semicolon and the spec's blanks is not a statement; the same for a form feed, a vertical tab, U+0085, U+200B and U+3000 in place of the no-break space) |
| 29b | `;\xa0\nGO\nSELECT 2` | `SELECT 2` (the order of the semicolon and the blanks does not matter) |
| 30 | `SELECT 1\nGO 1000001` | `UnsafeStatementSplitError` (the splitter's own bound: split_statements returns one string per repetition; sqlcmd accepts the count) |
| 31 | `\x0c\nGO\nSELECT 2` | `SELECT 2` (a batch holding only a form feed is not a statement; measured 2026-10-14, sqlcmd 18.6.0002.1: only the second batch runs, exit 0.) |
| 32 | `SELECT 1\n\xa0GO\nSELECT 2` | `SELECT 1\n\xa0GO\nSELECT 2` (one batch: a no-break space before GO makes the line text; measured 2026-10-14, sqlcmd 18.6.0002.1: Msg 102 near GO, exit 1, the same for a form feed, U+001C, U+0085 and U+2028 before GO) |
| 33 | `DROP TABLE t\xa0` | `DROP TABLE t` **exact text** (a no-break space is a blank to SQL Server; sqlcmd agrees, measured 2026-10-17) |
| 33a | `DROP TABLE t\u200b` | `DROP TABLE t` **exact text** (a zero width space is a blank to SQL Server though it is not Unicode white space) |
| 33b | `SELECT 1\ufeff` | `SELECT 1\ufeff` **exact text** (a byte order mark is a name character: kept; the server reports a syntax error) |
| 33c | `SELECT 1\u2029` | `SELECT 1\u2029` **exact text** (a paragraph separator is not measured, so it is kept until it is) |
| 34 | `\xa0` | `(empty)` (a script of a no-break space alone is a batch of blanks and not a statement; not re-measured: it follows from rows 31 and 33, where sqlcmd 18.6.0002.1 reads a no-break space as a blank and runs nothing for a batch of blanks) |
| 34a | `SELECT 1\nGO\n\xa0\nGO\nSELECT 2` | `SELECT 1` · `SELECT 2` (the middle batch holds only a no-break space, so it is not a statement and no record is returned for it; not re-measured: it follows from rows 31 and 33, measured 2026-10-14 and 2026-10-17 with sqlcmd 18.6.0002.1) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| `SET QUOTED_IDENTIFIER OFF` making `"…"` a string | `"…"` is read as an identifier. Splitting does not change: neither the splitter nor sqlcmd cuts at a `GO` alone on a line inside `"…"` (measured 2026-10-11, sqlcmd 18.6.0002.1, SQL Server 16.0.4255.1: `SET QUOTED_IDENTIFIER OFF`, then `INSERT INTO ta VALUES ("a\nGO\nb")` stores one row) | the setting is a session state the splitter cannot track; vanishingly rare in migrations |
| sqlcmd scripting variables, `:r` includes and every other sqlcmd command | rejected | they are a client preprocessor, not SQL; a placeholder service is the supported equivalent |
| A `GO` after a block comment on its line | rejected | sqlcmd takes it as a command after one comment and as text after two; the splitter does not model the difference |
| `GO` with a count above 1 000 000 | rejected (row 30) | `split_statements` returns the batch that many times; sqlcmd accepts any count |
| Per-statement error location inside a batch | the error names the batch and the server's line number within it | consequence of the batch decision; the extractor may annotate statement spans for reports |

## 12. Current implementation

Code in `dblift/core/sql_parser/` and `dblift/db/plugins/sqlserver/parser/`:

- `lexical_spec.py` (plugin): `SQLSERVER_SPEC`. Lexical facts: bracketed
  identifiers with `]]` as the escape, a leading BOM that offsets skip, unclaimed
  characters as symbols without a warning, block comments that end at the first
  `*/`, no `${...}` placeholder token. Batch rules (`BatchScriptRules`): the
  separator, the word alphabet, the command words, the follower sets, the count
  limit, the blank set `" \t\r"` and the division data (`DivisionRules`).
  The field `unmeasured_blanks` retains its historical name: `GO` immediately
  followed by a vertical tab or form feed was measured on 2026-10-14 with
  ODBC sqlcmd 18.6.0002.1 (`SELECT 1 AS a\nGO\x0b\nSELECT 2 AS b` and
  the same script with `\x0c`): exit 1, Msg 102 near `GO`. The splitter's
  existing refusal is preserved.
- `batch_commands.py`: `read_command` classifies the line whose first token is a
  command word (separator, client command, malformed separator) and the refusals
  for scripting variables and lone carriage returns, all raised by the tokenizer
  in source order with the messages of the previous scanner.
- `batch_script.py`: `BatchScript` groups the tokens into batches and builds the
  records (`text`, `line`, terminator `GO`, `repeat`, offsets, analysis
  statements); it raises nothing. `batch_division.py` divides a batch into the
  statements analysis reads from the code outside lexemes and comments.
- `SqlserverQuirks.lexical_spec()` returns the spec; `StatementSplitter("sqlserver")` reads it
  directly.
- `sqlserver_tokenizer.py` and the shared comment stripper
  are unchanged. They read block comments the way the **server** does (they nest):
  object extraction, the comment-only check and literal masking ask what the server
  will see, not where the client cuts. SQL Server literal masking keeps this reader
  (`LexicalSpec.redaction_reads_engine` is false). Moving the extraction view and the
  masking onto the engine is a separate change.
- The notice about `GO 0` is logged at INFO by `dblift.core.sql_parser.lexical_engine`
  (it was logged by the removed SQL Server regex parser). The engine has no unknown characters.
- The four unterminated-lexeme refusals read `unterminated string|bracketed
  identifier|quoted identifier|block comment opened at line L, column C` (they
  read `unterminated string literal|... starting at ...`); class, line and column
  are unchanged.

### Current implementation gaps

Behaviours kept from the previous scanner on purpose and recorded here (each has
a test; none is changed by the move to the engine):

- A batch holding only a form feed, a vertical tab or a no-break space is a batch
  with code: the splitter returns an empty-text record where sqlcmd runs nothing
  (row 31, listed in `KNOWN_GAPS` of the conformance test).
  A batch holding only U+001C is a record with that character as its text (not an
  empty one); the executor skips it. How sqlcmd reads a batch holding only U+001C is
  unmeasured.
- The blank set of the line-head rules is `" \t\r"` only: a command word or `GO`
  after any other whitespace character on its line is text. Before `GO`, agreement
  with sqlcmd was measured on 2026-10-14 for NBSP, form feed, U+001C, U+0085 and
  U+2028 (row 32); the broader rule preserves the previous scanner's behaviour.
- In the analysis view a keyword is read inside a number (`1END`) and next to a
  non-ASCII letter (`\u00e9END`).

Tests: `tests/unit/core/sql_parser/test_sqlserver_spec_conformance.py` compiles
§10 in the public tree; `tests/unit/core/sql_parser/test_sqlserver_batches.py`,
`test_sqlserver_commands.py` and `test_sqlserver_division.py` pin the rules;
`tests/unit/db/plugins/sqlserver/test_extraction_view_unchanged.py` pins the
secondary readers.

## 13. Statement facts

The default SQL Server parser now reads object and DML facts from one T-SQL
SQLGlot AST per analysis statement. The lexical engine still owns batch
splitting, including `GO`; SQLGlot never splits execution batches. The
explicit regex parser remains available. Names keep their written case and
decode doubled bracket or double-quote escapes. A `SELECT ... INTO` creates
its target table, and an index records its owning table, including a written
schema or database qualifier. Simple `CREATE SCHEMA`, `DROP SCHEMA` and
single-table `TRUNCATE TABLE`
statements report their named object. A partition-scoped truncate is opaque
because its effect is narrower than a whole-table truncate.

The reader reports an informational diagnostic and no object or DML target
when SQLGlot cannot establish the identity: this includes unsupported
`Command` and `Block` forms, unmodelled procedure/function/trigger bodies,
unparsed `TOP` or `OUTPUT INTO` mutations, XML index forms, temporary table
prefixes,
CTE write aliases that are not resolved to a base table, CTE bodies with
unmodelled write effects, omitted schema parts, `SELECT INTO` with a temporary
scope modifier, materialized-view modifiers, and four-part references whose
AST does not retain every part in its table identity. An index without a resolved owning
table, or a qualified index name SQLGlot misreads as its owner, is also
opaque. `MERGE` remains DML with unknown effects; `EXEC` has unknown effects.
`CREATE FULLTEXT INDEX` is also opaque, with a diagnostic naming its unsupported
grammar; it has no separate index name in the SQL text.
These are reader limits, not assertions
that SQL Server rejects the statements. An unread statement still keeps a
leading operation and kind where the text establishes them.

Parsed but unmapped `COPY`, privilege, `COMMENT ON`, `DESCRIBE` and `USE`
forms also report unread facts; old text-extracted names are not carried forward. The
corpus contains cross-dialect and truncated SQL, so a diagnostic is not a
native SQL Server grammar verdict.

SQLGlot's T-SQL tokenizer reads nested block comments. The facts reader uses
that same nesting rule when it classifies an unread statement's leading word.
An unterminated nested comment reports a tokenization error and names no
object; text still inside the comment does not establish an operation.

A narrow SQL Server 2022 CU25 probe confirmed stored mixed-case spelling,
`[a]]b]`, two-, three- and local four-part lookups, `UPDATE TOP ... OUTPUT`
and `SELECT ... INTO` under the measured
`SQL_Latin1_General_CP1_CI_AS` collation. It did not qualify other server
versions, collations or the full grammar. The four-part AST limitation above
therefore remains an explicit reader gap even though that native query ran.
