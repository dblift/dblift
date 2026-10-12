# SQLite — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | SQLite 3.x scripts written for the `sqlite3` command-line shell and run through Python's `sqlite3` driver. Measured: shell 3.51.0 (`/usr/bin/sqlite3`) and shell 3.45.1 (built from the amalgamation `sqlite-autoconf-3450100`, sha256 `cd9c27841b7a5932c9897651e20b86c701dd740556989b01ca596fcfa3d49a0a`) against the 3.45.1 library of the Python 3.11.8 `sqlite3` module; 557 shell runs, 9 differ between the two shells and none concerns splitting (`.timer`, `EXPLAIN` comments, `load_extension`) |
| Code facts taken from | OSS `develop` `c5513b99` (§12 describes this commit) |
| Vendor references, fetched 2026-10-11 from `sqlite.org` | *SQL Comment Syntax* (`lang_comment.html`); *SQLite Keywords* (`lang_keywords.html`: the quoting forms); *Command Line Shell For SQLite* (`cli.html`: "CLI comments", dot-commands); *Test For Complete SQL Statements* (`c3ref/complete.html`); *BEGIN TRANSACTION* (`lang_transaction.html`); *VACUUM* (`lang_vacuum.html`) |
| Live verification | `sqlite3 -bail <db> < script.sql` (shell 3.51.0 and 3.45.1) against the driver dblift executes through (`SqlAnalyzer("sqlite").split_statements`, then one `cursor.execute` per statement on a connection in autocommit with `PRAGMA foreign_keys = ON`); the resulting files are compared through `sqlite_master`, `PRAGMA table_xinfo`, `index_list`, `foreign_key_list` and the table rows. |
| Second ground truth | the driver dblift executes through: `cursor.execute` takes **one** statement and raises `ProgrammingError: You can only execute one statement at a time.` for a text that holds two, so a piece cut too late fails loudly; the silent hazards are in the shell, not in the driver |
| Engine subclass | none |

The central decision of this specification is that **the shell asks the
library, and the library's answer is a small rule**. The shell reads a script
line by line and gives the library the text so far; the library
(`sqlite3_complete`, reachable from Python as `sqlite3.complete_statement`)
says whether that text is a whole statement: "A statement is judged to be
complete if it ends with a semicolon token and is not a prefix of a
well-formed CREATE TRIGGER statement. Semicolons that are embedded within
string literals or quoted identifier names or comments are not independent
tokens" (*Test For Complete SQL Statements*). The scanner reproduces that
rule with the same token classes, and the conformance tests compare it with
`sqlite3.complete_statement` on generated token sequences. Around it the shell has behaviours the
library does not have, and they are the only places the scanner reads
anything but tokens: a line that starts with a dot is a shell command (§6), a
line that holds only `go` or `/` ends the statement (§6), and a script's
unterminated `/*` silently swallows the rest of the script (§3).

## 1. String literals

| Form | Opens | Closes | Escape inside | Note |
| --- | --- | --- | --- | --- |
| String | `'` | `'` | `''` | measured: `INSERT INTO t VALUES('it''s;')` stores `it's;` in the shell and the driver; a backslash is an ordinary character, `'a\'` is a complete string and `'a\''` is a string followed by an unterminated one |
| Blob | `X'` / `x'` | `'` | none | the quote opens a string whatever stands before it; a `;` inside is hidden; the lexeme ends at the quote and the engine rejects the digits |

A doubled quote needs no rule of its own: it is a string that ends and a
string that starts at once, and `;` stays hidden throughout. A double-quoted token the engine reads as a string
(*SQLite Keywords*: "If a keyword in double quotes … is used in a context
where it cannot be resolved to an identifier but where a string literal is
allowed, then the token is understood to be a string literal") scans as a
quoted identifier (§2); the effect on splitting is the same.

An unterminated string at the end of a script is returned as the last
statement and the engine rejects it with `unrecognized token` in the shell
and in the driver: loud, so there is
nothing to refuse (row 29).

A line break inside a string is sent as written. The shell removes the CR of
a CRLF pair from each line it reads, the driver does not: `'x` CRLF `y'` is
stored as `x` LF `y` through the shell and as `x` CR LF `y` through dblift
(`hex(a)` is `780A79` in the shell). A deliberate
difference (§11).

## 2. Identifiers

| Form | Opens | Closes | Escape inside |
| --- | --- | --- | --- |
| Quoted | `"` | `"` | `""` |
| Bracketed | `[` | `]` | none |
| Backtick | `` ` `` | `` ` `` | ``` `` ``` |

*SQLite Keywords*: "A keyword in single quotes is a string literal. A keyword
in double-quotes is an identifier. A keyword enclosed in square brackets is an
identifier. … A keyword enclosed in grave accents (ASCII code 96) is an
identifier." All three hide `;`, the other quote characters and the comment
markers; an identifier may span
lines. `""` and ``` `` ``` are two
lexemes in a row; a bracketed identifier
has **no** escape: `[a]]b]` is `[a]` followed by `]b]`; the engine reports
`unrecognized token: "]"`, so the `]` is outside the identifier. A word is a run of letters, digits, `_`, `$` and
non-ASCII characters (the library's identifier characters): `end_at`, `end$`
and `endé` are not the keyword `END` and `sqlite3.complete_statement` agrees; `"end"`, `[end]`, `` `end` `` and `'end'` are
not either.

## 3. Comments

| Form | Opens | Closes | Nests |
| --- | --- | --- | --- |
| Line | `--` | the next LF, or the end of the script | — |
| Block | `/*` | `*/` or the end of the script | **no** |

*SQL Comment Syntax*: "SQL comments begin with two consecutive "-"
characters (ASCII 0x2d) and extend up to and including the next newline
character (ASCII 0x0a) or until the end of input, whichever comes first.
C-style comments begin with "/*" and extend up to and including the next "*/"
character pair or until the end of input, whichever comes first. … Comments
do not nest." Measured: `/* a /* b */ SELECT 1; */ SELECT 2;` runs `SELECT 1`
and fails on the stray `*/` in the shell and the driver; a CR does not end a line comment, the comment runs to the LF
(the `INSERT` after a lone CR is inside the comment);
`;` and `*/` and `/*` inside a line comment change nothing;
`5--1` is `5`.

**An unterminated `/*` swallows the rest of the script without an error.**
Measured through the shell, `.read` and the driver's `executescript`:
`CREATE TABLE t(a);` newline `/* never closed` newline `INSERT INTO t VALUES(1);`
creates the table, inserts nothing and exits 0; the library's
`complete_statement` is false for it. This is the one silent comment hazard,
and the scanner refuses it with `UnsafeStatementSplitError` naming the line
(rows 18, 19). A line comment at the end of the script without a newline is
fine.

A segment that holds only comments, whitespace and `;` is **not a
statement**: the shell sends nothing for it and the
scanner returns nothing (rows 14-16, 31). A comment that follows a `;` on its
line belongs to the next statement's text, as the shell hands it over
(row 17); a comment before the `;` stays in the
statement.

Callers that read a script statement by statement (linting, analysis) go
through `split_for_analysis`, which returns a segment of comments only as a
unit of its own, as the splitter did before the scanner: those readers look
at the explanatory comments a script holds, and execution, which sends
nothing for them, is the only caller that drops them. Dropping them for the
readers too would silently remove information they receive today, so the two
splits differ in this one respect and nowhere else.

## 4. Terminators

| Terminator | Rule |
| --- | --- |
| `;` | ends a statement outside strings, quoted identifiers and comments, and outside a `CREATE TRIGGER` body (§5) |

No batch separator, no directive that changes the terminator. A statement
needs no terminator at the end of the script: the shell runs it
(`INSERT INTO t VALUES(1)` with nothing after it runs, exit 0), so the last
statement is returned with `terminator=None` (row 13). Two statements on a
line are two statements, a terminator on its own line ends
the statement above it (row 30), and an empty statement
(`;;`, or a `;` with nothing pending) is nothing (rows 14, 31). Line ends are LF; a CR
before the LF is part of the line end (row 57), a CR
that stands alone is whitespace and ends no line (`.print x` CR `SELECT 1;` is
one line for the shell, row 58).

The scanner's text for a statement is the script between the previous
terminator and this one, trimmed of blanks, **verbatim**: comments, line
breaks and CRs stay. The terminator is not part of it.

## 5. Blocks

| Opener | Condition | Closer |
| --- | --- | --- |
| `CREATE [TEMP\|TEMPORARY] TRIGGER` (optionally after `EXPLAIN`) | the statement's first tokens, comments and blanks between them ignored | a `;`, then the word `END`, then a `;` or the end of the script |

`BEGIN` and `CASE` are not tracked at all, and neither is a depth. The rule is
the library's table (*Test For Complete SQL Statements*: "is not a prefix of
a well-formed CREATE TRIGGER statement"): seven states, eight token classes
(`;`, whitespace, other, `EXPLAIN`, `CREATE`, `TEMP`/`TEMPORARY`, `TRIGGER`,
`END`). After `CREATE` (and optional `TEMP`) the word `TRIGGER` opens the body;
inside it a `;` is not a cut; a `;` followed by `END` and a `;` is. Measured
against the library with `sqlite3.complete_statement`: the
trigger ends only at `; END ;`; a `CASE … END` before the
`;` does not close it; `TEMP`, `TEMPORARY`, `IF NOT EXISTS`, a
schema-qualified name, `INSTEAD OF`, `UPDATE OF`, lower case, comments between
the words and `EXPLAIN` in front all work; the words `END` and `BEGIN` and a `;` in strings, quoted
identifiers and comments count for nothing; a table called
`trigger_log`, a column called `trigger`, an index called `idx_trigger`, a
string or a comment that mentions `CREATE TRIGGER` and a `CREATE TABLE` that
holds the word `begin` open nothing; a trigger is recognised only at the head of a
statement (row 44).

A trigger body without its closing `END` is not refused: the shell and the
driver both reject it with `incomplete input`, so the rest of the script becomes one statement the
engine rejects (row 39). `END` without a final `;` at the end of the script is
accepted by the shell (row 38). `END` followed by
other text goes back into the body, as in the library (the engine rejects the text).

`BEGIN [DEFERRED|IMMEDIATE|EXCLUSIVE] [TRANSACTION]`, `COMMIT`, `END
[TRANSACTION]`, `ROLLBACK`, `SAVEPOINT` and `RELEASE` are **statements**, not
block markers (*BEGIN TRANSACTION*: "END TRANSACTION is an alias for COMMIT.
Transactions created using BEGIN...COMMIT do not nest."). The scanner treats
them like any other statement (rows 4, 5). The current splitter's `BEGIN` counter swallows the statements after them
(§12).

## 6. Client directives

| Directive | Client | Splitter action |
| --- | --- | --- |
| A line whose first character is `.` (column 0) when no statement is pending: `.read`, `.mode`, `.print`, `.tables`, `.exit`, `.quit`, `.bail`, `.shell`, `.system`, `.open`, `.output`, `.parameter`, any other word, a lone `.` | `sqlite3` shell | **reject** with `UnsupportedMetaCommandError` (command and line named) |
| A line that holds only `go` (any case) or `/`, blanks (space, tab, form feed, CR, vertical tab) around it allowed and a trailing line comment or closed block comments after it allowed, while the statement so far would be complete once a `;` is added (not when its last line ends in a line comment) | `sqlite3` shell | **reject** with `UnsafeStatementSplitError` (line named) |

*Command Line Shell*: "Dot-commands must begin with a "." at the left margin
with no preceding whitespace. Dot-commands must be entirely contained on a
single input line. Dot-commands cannot occur in the middle of an ordinary SQL
statement. In other words, dot-commands cannot occur at a continuation
prompt." Measured, the shell runs a dot line when nothing is pending: at the
start of the script, after a complete
statement, after a `;` and a comment on its line, after a line or block comment line, after blank lines, right after a closed trigger, with CRLF, as the last
line without a newline, in any case (`.PRINT` is reported as an
unknown command and the run goes on) and for words that are no command; a lone
`.` does nothing. It does **not** when a statement is pending: after unterminated
statement text,
after a comment line that follows pending text,
inside a string, a quoted or bracketed identifier, or a block comment, inside a trigger body, after a `;` plus
code on the same line, after a comment on
its line, indented with spaces or a tab and after a BOM. In those cases the dot line is text and the engine rejects it
loudly (`near ".": syntax error`), for the shell and the driver alike.

Every dot command is refused rather than passed on, because each one the shell
runs is silent or does something the driver cannot: `.exit` and `.quit` stop
the run (the `INSERT` after it never runs, exit 0),
`.bail on` changes error handling, `.read` runs another file, `.shell` and `.system` run an operating-system command, `.open` moves every later statement to another
database file (the first file stays empty), `.output` redirects
results, `.mode`, `.headers`, `.echo`, `.timer` and
`.parameter` change what the shell prints or binds.

A line `go` or `/` is not in the manual; it is in the shell's behaviour and
was measured: with a statement pending it ends it, as a `;` would
(`CREATE TABLE t(a)` newline `go` creates the table, `/` the same; `GO`, blanks
around it and CRLF work, and so do a comment after it, `go -- c`, `/-- c`, `go/**/`, `/ /* c */`, and a vertical tab; `go;`, `go to`, `go /* c` and a comment before it, `/* c */ go`, do not), also inside parentheses. The driver reads the same lines as part
of the statement: `SELECT 6` newline `/` newline `2` is `3` through the driver
and `6` followed by a syntax error through the shell. That is a silent divergence, so the
scanner refuses the line. The same holds when the statement so far ends in a line
comment, with one exception: the shell tests completeness with a `;` appended to the text,
so a last line that ends in a line comment swallows it, the line is no terminator, and shell
and driver agree (`SELECT 6 -- six` newline `/` newline `2` is `3` for both, row 62; a
`go` line there is read by both as an alias and the statement fails loudly). A line that is
text inside a string, a quoted identifier, a
comment, and in a trigger body that is not yet closed: the library says the text
is incomplete, so the shell leaves the line in the statement; and with nothing pending the shell skips it while the engine rejects `go` or `/` as a
statement, loudly. dblift is narrower than the shell there, by design (row 59):
the script runs through the shell and fails through dblift with `near "go":
syntax error`, never silently.

## 7. Raw blocks

None. SQLite has no dollar quoting and no heredoc.

## 8. Transaction markers

| Pattern (first keywords) | Status |
| --- | --- |
| `PRAGMA foreign_keys = …` | in current code (`quirks.py:44-49`): no effect inside a transaction, so run outside one; inside `BEGIN IMMEDIATE` the pragma is accepted and does nothing |
| `VACUUM` | **to add** (a quirks matter, not a splitting one): "A VACUUM will fail if there is an open transaction on the database connection that is attempting to run the VACUUM." (*VACUUM*); measured inside the `BEGIN IMMEDIATE` a transactional migrate opens: `cannot VACUUM from within a transaction` |

A migration that holds its own `BEGIN`, `COMMIT`, `END` or `ROLLBACK` runs
inside the transaction dblift opens: `BEGIN` fails (`cannot start a
transaction within a transaction`) and `COMMIT` commits dblift's transaction
early, after which later statements autocommit and a failure can no longer
roll back what came before: after `COMMIT inside, then an error` the table
stays and the migrate's own `ROLLBACK` answers `cannot rollback - no
transaction is active`. That is execution, not splitting;
recorded here so the scanner is not blamed for it, and filed as a separate
issue.

## 9. Engine subclass

None: the head check, the one-token lookahead after `;` and the two line
rules are a table and two regular expressions.

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `CREATE TABLE t(a); INSERT INTO t VALUES(1);` | `CREATE TABLE t(a)` · `INSERT INTO t VALUES(1)` |
| 2 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET a=1; DELETE FROM u; END; SELECT 1;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET a=1; DELETE FROM u; END` · `SELECT 1` (as written the engine rejects the trigger, no such table; a runnable variant creates the tables first) |
| 3 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET a = CASE WHEN 1 THEN 2 END; END;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET a = CASE WHEN 1 THEN 2 END; END` |
| 4 | `BEGIN; INSERT INTO t VALUES(1); COMMIT;` | `BEGIN` · `INSERT INTO t VALUES(1)` · `COMMIT` |
| 5 | `BEGIN IMMEDIATE TRANSACTION; UPDATE t SET a=2; END TRANSACTION;` | `BEGIN IMMEDIATE TRANSACTION` · `UPDATE t SET a=2` · `END TRANSACTION` |
| 6 | `CREATE TABLE t(begin_at TEXT); INSERT INTO t VALUES('x');` | `CREATE TABLE t(begin_at TEXT)` · `INSERT INTO t VALUES('x')` |
| 7 | `CREATE TABLE "a;b"(x); SELECT 1;` | `CREATE TABLE "a;b"(x)` · `SELECT 1` |
| 8 | ``CREATE TABLE `it's`(x); SELECT 1;`` | ``CREATE TABLE `it's`(x)`` · `SELECT 1` |
| 9 | `CREATE TABLE [a;b](x); SELECT 1;` | `CREATE TABLE [a;b](x)` · `SELECT 1` |
| 10 | `INSERT INTO t VALUES (X'3B3B'); SELECT 1;` | `INSERT INTO t VALUES (X'3B3B')` · `SELECT 1` |
| 11 | `/* a /* b */ SELECT 1; */ SELECT 2;` | `/* a /* b */ SELECT 1` · `*/ SELECT 2` (the comment ends at the first close marker; the stray close marker is sent and the engine rejects it, exactly as sqlite3 does) |
| 12 | `.mode csv\nSELECT 1;` | `UnsupportedMetaCommandError` (line 1, `.mode`; refusal: the shell runs it, the engine cannot) |
| 13 | `SELECT 1 -- trailing\n` | `SELECT 1 -- trailing` (no terminator; the last statement is returned, the shell runs it) |
| 14 | `CREATE TABLE t(a);; INSERT INTO t VALUES(1);` | `CREATE TABLE t(a)` · `INSERT INTO t VALUES(1)` (an empty statement is nothing) |
| 15 | `SELECT 1; -- bye` | `SELECT 1` (a segment of comments only is not a statement) |
| 16 | `-- only a comment\n/* here */` | `(empty)` |
| 17 | `SELECT 1; -- c\nSELECT 2;` | `SELECT 1` · `-- c\nSELECT 2` (a comment after a terminator goes with the next statement, as the shell hands it over) |
| 18 | `CREATE TABLE t(a);\n/* never closed\nINSERT INTO t VALUES(1);` | `UnsafeStatementSplitError` (line 2; refusal: the shell and the driver silently drop the rest of the script) |
| 19 | `SELECT 1; /* open` | `UnsafeStatementSplitError` (line 1; refusal) |
| 20 | `INSERT INTO t VALUES('a;\nb'); SELECT 1;` | `INSERT INTO t VALUES('a;\nb')` · `SELECT 1` |
| 21 | `INSERT INTO t VALUES('it''s;'); SELECT 1;` | `INSERT INTO t VALUES('it''s;')` · `SELECT 1` |
| 22 | `INSERT INTO t VALUES('a\\'); SELECT 1;` | `INSERT INTO t VALUES('a\\')` · `SELECT 1` (a backslash is an ordinary character) |
| 23 | `CREATE TABLE "a""b;c"(x); SELECT 1;` | `CREATE TABLE "a""b;c"(x)` · `SELECT 1` |
| 24 | `CREATE TABLE "it's;"(x); SELECT 1;` | `CREATE TABLE "it's;"(x)` · `SELECT 1` |
| 25 | `CREATE TABLE [it's;](x); SELECT 1;` | `CREATE TABLE [it's;](x)` · `SELECT 1` |
| 26 | `CREATE TABLE [a--b;](x); CREATE TABLE "c/*d"(y); SELECT 1;` | `CREATE TABLE [a--b;](x)` · `CREATE TABLE "c/*d"(y)` · `SELECT 1` |
| 27 | ``` CREATE TABLE `a``b;c`(x); SELECT 1; ``` | ``` CREATE TABLE `a``b;c`(x) ``` · `SELECT 1` |
| 28 | `SELECT [a]]; SELECT 1;` | `SELECT [a]]` · `SELECT 1` (a bracketed identifier has no escape) |
| 29 | `CREATE TABLE t(a); SELECT 'abc;` | `CREATE TABLE t(a)` · `SELECT 'abc;` (an unterminated string is the last statement; the engine rejects it) |
| 30 | `CREATE TABLE t(a)\n;\nINSERT INTO t VALUES(1)\n;` | `CREATE TABLE t(a)` · `INSERT INTO t VALUES(1)` |
| 31 | `;;;` | `(empty)` |
| 32 | `CREATE TEMP TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END; SELECT 2;` | `CREATE TEMP TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END` · `SELECT 2` |
| 33 | `CREATE TRIGGER IF NOT EXISTS tr AFTER INSERT ON t WHEN CASE WHEN new.a > 0 THEN 1 ELSE 0 END = 1 BEGIN SELECT 1; END; SELECT 2;` | `CREATE TRIGGER IF NOT EXISTS tr AFTER INSERT ON t WHEN CASE WHEN new.a > 0 THEN 1 ELSE 0 END = 1 BEGIN SELECT 1; END` · `SELECT 2` |
| 34 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN INSERT INTO u VALUES(1); SELECT 1 AS "end"; END; SELECT 2;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN INSERT INTO u VALUES(1); SELECT 1 AS "end"; END` · `SELECT 2` |
| 35 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN INSERT INTO [end] VALUES(1); SELECT 1 AS end$; END; SELECT 2;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN INSERT INTO [end] VALUES(1); SELECT 1 AS end$; END` · `SELECT 2` |
| 36 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 'END;'; SELECT 'BEGIN'; END; SELECT 2;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 'END;'; SELECT 'BEGIN'; END` · `SELECT 2` |
| 37 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN\n-- ; END;\nSELECT 1; /* ; END; */\nEND;\nSELECT 2;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN\n-- ; END;\nSELECT 1; /* ; END; */\nEND` · `SELECT 2` |
| 38 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END` |
| 39 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1;\nSELECT 2;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1;\nSELECT 2` (the body is never closed: one statement, the engine rejects it) |
| 40 | `CREATE TABLE trigger_log(a); SELECT 1;` | `CREATE TABLE trigger_log(a)` · `SELECT 1` |
| 41 | `EXPLAIN CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END; SELECT 2;` | `EXPLAIN CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END` · `SELECT 2` |
| 42 | `CREATE /* c */ TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END; SELECT 2;` | `CREATE /* c */ TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END` · `SELECT 2` |
| 43 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END /* c */ ; SELECT 2;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END /* c */` · `SELECT 2` |
| 44 | `SELECT 1 CREATE TRIGGER tr BEGIN SELECT 1; END; SELECT 2;` | `SELECT 1 CREATE TRIGGER tr BEGIN SELECT 1` · `END` · `SELECT 2` (a trigger is recognised at the head of a statement only) |
| 45 | `CREATE TABLE t(a);\n.print x\nINSERT INTO t VALUES(1);` | `UnsupportedMetaCommandError` (line 2, `.print`) |
| 46 | `-- c\n.print x\nSELECT 1;` | `UnsupportedMetaCommandError` (line 2: a comment line leaves nothing pending) |
| 47 | `INSERT INTO t VALUES('a\n.print x\nb'); SELECT 1;` | `INSERT INTO t VALUES('a\n.print x\nb')` · `SELECT 1` (a dot line inside a string is text) |
| 48 | `/*\n.print x\n*/ SELECT 1;` | `/*\n.print x\n*/ SELECT 1` |
| 49 | `SELECT 1\n.print x\n;` | `SELECT 1\n.print x` (a statement is pending: text; the engine rejects it) |
| 50 | `  .print x\nSELECT 1;` | `.print x\nSELECT 1` (indented: not a command; text the engine rejects) |
| 51 | `CREATE TABLE t(a);\n.exit\nINSERT INTO t VALUES(1);` | `UnsupportedMetaCommandError` (line 2, `.exit`: the shell stops the run, exit 0) |
| 52 | `.shell echo hi\nSELECT 1;` | `UnsupportedMetaCommandError` (line 1, `.shell`: the shell runs an operating-system command) |
| 53 | `CREATE TABLE t(a)\ngo\nINSERT INTO t VALUES(1);` | `UnsafeStatementSplitError` (line 2: the shell ends the statement at go, the engine reads it as part of the statement) |
| 54 | `SELECT 6\n/\n2;` | `UnsafeStatementSplitError` (line 2: the shell ends the statement at the slash and prints 6, the driver divides and prints 3) |
| 55 | `INSERT INTO t VALUES('a\ngo\nb'); SELECT 1;` | `INSERT INTO t VALUES('a\ngo\nb')` · `SELECT 1` |
| 56 | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN\nSELECT 1;\ngo\nSELECT 2; END;` | `CREATE TRIGGER tr AFTER INSERT ON t BEGIN\nSELECT 1;\ngo\nSELECT 2; END` (inside an unfinished trigger a go line is text; the engine rejects it) |
| 57 | `CREATE TABLE t(a);␍\n.print x␍\nINSERT INTO t VALUES(1);␍\n` | `UnsupportedMetaCommandError` (line 2: the CR of a CRLF pair is part of the line end) |
| 58 | `SELECT 1;␍.print x␍SELECT 2;␍` | `SELECT 1` · `.print x␍SELECT 2` (a CR that stands alone ends no line: the dot is not at a line start) |
| 59 | `CREATE TABLE t(a);\ngo\nINSERT INTO t VALUES(1);` | `CREATE TABLE t(a)` · `go\nINSERT INTO t VALUES(1)` (nothing is pending at the go line: the shell skips it, dblift sends it as text and the engine rejects it, loudly; narrower than the shell by design) |
| 60 | `SELECT 6\n/ -- c\n2;` | `UnsafeStatementSplitError` (line 2: a line comment after the slash does not stop the shell from ending the statement there) |
| 61 | `SELECT 6\ngo /* c */ -- d\n2;` | `UnsafeStatementSplitError` (line 2: closed block comments and a line comment after go) |
| 62 | `SELECT 6 -- six\n/\n2;` | `SELECT 6 -- six\n/\n2` (the statement so far ends in a line comment: a semicolon added to it would be inside the comment, the shell does not end the statement, and shell and driver both print 3) |
| 63 | `SELECT 6\ngo x\n;` | `SELECT 6\ngo x` (go with other text after it is text; the engine rejects it) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| Shell dot-commands | rejected (rows 12, 45, 46, 51, 52, 57) | they are not SQL and SQLite's C API cannot run them; the shell runs them silently |
| A `go` or `/` line that would end the statement | rejected (rows 53, 54, 60, 61) | the shell cuts there and the driver does not; for a slash inside an expression the two read different statements |
| A `go` or `/` line with nothing pending | text (row 59) | the shell skips it and the engine rejects it as a statement: loud, and dblift is narrower than the shell |
| An unterminated `/*` | rejected (rows 18, 19) | silent in the shell and in the driver |
| An unterminated string, quoted identifier or trigger body at the end | returned as the last statement (rows 29, 39) | both clients reject it loudly (`unrecognized token`, `incomplete input`) |
| A CR inside a string, a quoted identifier or a trigger body | sent as written | the shell removes the CR of a CRLF pair from every line it reads and the driver keeps it: a literal that spans lines is stored with CR LF by dblift and with LF through the shell; the text of a trigger or a view differs by CRs only |
| A NUL byte | text | the shell cuts the line at it and the driver refuses the statement (`the query contains a null character`); loud on both sides |
| A vertical tab, a no-break space | text | the shell accepts a vertical tab (3.45.1 and 3.51.0) and the library 3.45.1 rejects it; both reject a no-break space: whatever the engine says, the splitter sends the text |
| `ATTACH`, `VACUUM INTO`, `DETACH` | SQL, passed through | they run through the driver; only the dot forms are refused |
| A leading UTF-8 byte order mark | dropped | the shell and the library treat it as whitespace; a dot command after it is not a command for the shell, the scanner drops the mark first and refuses the command, the stricter side |
| `PRAGMA foreign_keys` and `VACUUM` inside a transaction, `BEGIN` and `COMMIT` inside a migration | execution matters (§8) | not splitting questions |
| The foreign-key setting | differs between the sides | the provider runs `PRAGMA foreign_keys = ON` on connect and the shell starts with it off (`.dump` prints `PRAGMA foreign_keys=OFF`); a script that violates a foreign key behaves differently on the two sides |

## 12. Current implementation and the gaps this spec closes

Code: `dblift/db/plugins/sqlite/parser/sqlite_regex_parser.py` (hand-written
character scanner, `split_statements` lines 41-175 at `c5513b99`) and
`parser_config.py`.

- **No identifier quoting is tracked by the splitter** (`"…"`, `[…]`,
  `` `…` `` all ignored; only `char in "'"` opens a string, line 111):
  `CREATE TABLE "a;b"(x)` splits in two, `"it's"` and `[it's]` open a string,
  a comment marker inside a bracketed or quoted name opens a comment (rows 7-9,
  23-27).
- **Any `BEGIN` opens a block** (`sqlite_regex_parser.py:141-144`, verified at
  `c5513b99`) with no `CREATE TRIGGER` condition, so `BEGIN;` and
  `BEGIN IMMEDIATE;` swallow every following `;` until some `END`, and `COMMIT`
  does not close it (rows 4, 5). The result is one piece the driver rejects
  with `You can only execute one statement at a time.` (measured).
- **Word boundaries use `isalnum()` only** (`:136-152`): `begin_at` counts as
  `BEGIN`, `end_at` and `end$` as `END`, and the keyword search runs on text
  outside single quotes only, so a quoted `"end"` or `[end]` closes a trigger
  (rows 6, 34, 35).
- **Block comments are read, but loosely** (`:75-90`): a `*/` outside any
  comment is taken as a comment end, an unterminated `/*` is accepted and the
  rest of the script is returned inside it (rows 18, 19). A `;` or `END` inside
  a closed comment is skipped correctly (row 37 passes).
- **Dot-commands are glued onto the following statement** (rows 12, 45, 46, 51, 52, 57): the
  driver then rejects the piece with `near ".": syntax error`.
- **`go` and `/` lines pass into the statement** (rows 53, 54, 60, 61).
- **Empty and comment-only segments are statements** (`;` alone, a trailing
  `-- bye`, a script of comments; rows 14-16, 31): the driver accepts them, so
  this is harmless but not the shell's behaviour.
- **A UTF-8 byte order mark stays in the first statement**.
- `_trigger_block_pattern`, `block_keywords` and `batch_separators` in the
  config are compiled and never used.
