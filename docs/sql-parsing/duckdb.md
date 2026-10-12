# DuckDB — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | DuckDB 1.x scripts run through the Python `duckdb` driver (the path dblift executes through) and written for the `duckdb` command-line shell. Measured: shell v1.5.6 (Variegata, Homebrew) and v1.5.5 (Variegata, the `duckdb-cli` wheel) and the Python driver 1.5.5 and 1.5.6 (`duckdb.connect()`, `execute`, `duckdb.extract_statements`) with `duckdb_engine` 0.17.0 on SQLAlchemy 2.0.52 |
| Code facts taken from | OSS `develop` `5074c563`, before the scanner of §12 |
| Vendor references, fetched 2026-10-12 from `duckdb.org/docs/current` | *Literal Types* (`sql/data_types/literal_types`: strings, escape strings, dollar-quoted strings); *Keywords and Identifiers* (`sql/dialect/keywords_and_identifiers`: quoted identifiers); *SQL Dialect, Overview* ("DuckDB's SQL dialect is based on PostgreSQL."); *Prepared Statements* (`sql/query_syntax/prepared_statements`: `?`, `$1`, `$name`); *CLI, Dot Commands* (`clients/cli/dot_commands`); *CLI, Overview* (`clients/cli/overview`: scripts from standard input, `.read`, multi-line statements). No page on comments could be found: block-comment nesting rests on measurement alone |
| Live verification | `duckdb -init /dev/null -bail <db> < script.sql` against the Python driver dblift executes through (`SqlAnalyzer("duckdb").split_statements`, then one `execute` per statement through `duckdb_engine`); the resulting files are compared through the `duckdb_*()` catalogue functions and the table rows; `duckdb.extract_statements` is compared with the splitter on every script it accepts. |
| Second ground truth | the driver: `execute` takes **several** statements in one text, parses the whole text before it runs anything (a parse error in the last statement runs none of the first), and a runtime error leaves the statements before it done; dblift sends one statement per call, so the two stop at different places on a script with a parse error |
| How the shell cuts | the shell reads the script line by line and sends the text so far to the engine when a line ends a statement: statements on one line are one chunk run as one text, like the driver (a parse error in the chunk runs none of it, a run-time error stops the rest of it), statements on later lines are separate chunks; its exit status is 0 when every statement ran and 1 when any failed, even if a later one succeeded; without `-bail` it goes on with the next line; standard input, `.read` and `-f` give the same result for every script tried |
| Engine subclass | none: the scanner is one character scanner with one dollar-quote rule |

DuckDB's lexer is PostgreSQL's ("DuckDB's SQL dialect is based on PostgreSQL."), and
every lexical fact below that was checked against the engine agrees with
PostgreSQL's lexer: strings with `''`, `E'…'` strings, `$tag$…$tag$` strings,
`"…"` identifiers, nested block comments. What differs is everything around
the lexer: no psql meta-commands, no `COPY … FROM STDIN` data block, no
`BEGIN ATOMIC`, no procedural body; and a client, the `duckdb` shell, whose
dot-commands start with a period. The measured rule for where a statement
ends is therefore the shortest one of any dialect: a `;` outside strings,
quoted identifiers, dollar-quoted strings and comments.

## 1. String literals

| Form | Opens | Closes | Escape inside | Note |
| --- | --- | --- | --- | --- |
| String | `'` | `'` | `''` | "To escape a single quote (apostrophe) character in a string literal, use ''." (*Literal Types*). A backslash is an ordinary character: `'a\'` is a complete string and `'a\''` leaves one open; `;`, `--`, `/*`, `*/` and `$$` inside are text |
| Escape string | `E'` / `e'` | `'` | `''` and a backslash that takes the next character | "prefix a string literal with e (or E)" (*Literal Types*). The measured effect on splitting: `E'a\'b;c'` is one string, `E'a\\'` ends at the last quote, a doubled quote keeps the string open. The `E` is a prefix unless an identifier character precedes it: `xE'a\'` is the name `xE` and a plain string; after a quote, a closing parenthesis, a dollar-quoted string or digits the `E` still opens an escape string |
| Dollar-quoted | `$$` or `$tag$` | the same `$$` / `$tag$` | none | "DuckDB supports dollar-quoted string literals, which are surrounded by double-dollar symbols ($$)" and "you can insert alphanumeric tags in the double-dollar symbols" (*Literal Types*). The tag starts with a letter, an underscore or a non-ASCII character and goes on with those and digits, no `$`; it is case sensitive and closes only on the identical tag; `$1a$` and `$a b$` are not tags; `;`, quotes and comment markers inside are text |

Words and parameters decide where a dollar quote may open. A word is a letter,
an underscore or a non-ASCII character followed by those, digits and `$`, so a
`$$` inside a word is part of it; after a
digit, an operator, a comma or an opening parenthesis a `$$` opens a string. A
`$` followed by digits or by a name that is not closed by another `$` is a parameter
(`$1`, `$name`: "Prepared statements can use positional parameters, where parameters
are denoted with an integer ($1, $2)" and "named parameters where parameters are
denoted with $parameter_name", *Prepared Statements*), and `;` after it ends the
statement.

Adjacent literals separated by a newline are one string (`SELECT 'a'` newline `'b'`
is `'ab'`); on one line they are a syntax error. The statement is cut at the same place either way.
`x'…'`, `b'…'` and `N'…'` are a word followed by a plain string; `U&'…'` is read by the lexer and
rejected by the engine; `[…]` is a list and
`{…}` a struct, never an identifier.

An unterminated string, quoted identifier or dollar-quoted string at the end of a
script is returned as the last statement and the engine rejects it loudly: there is nothing to refuse (row 29).

## 2. Identifiers

| Form | Opens | Closes | Escape inside |
| --- | --- | --- | --- |
| Quoted | `"` | `"` | `""` |

"Identifiers can be quoted using double-quote characters" and "Double quotes can
be escaped by repeating the quote character" (*Keywords and Identifiers*). `;`,
`--`, `/*` and `'` inside are text and a quoted identifier spans lines; a backslash is ordinary. A backtick and a
square bracket are not quotes: a backtick name and `[a;b]` are syntax errors for the engine and the `;` inside ends the statement. An empty
quoted identifier is rejected by the engine. Keywords as quoted
names are fine.

## 3. Comments

| Form | Opens | Closes | Nests |
| --- | --- | --- | --- |
| Line | `--` | the first LF or CR | — |
| Block | `/*` | `*/` | **yes** |

No documentation page on comments was found, so the rules are measured: block
comments nest to any depth (`/* a /* b */ ; */ SELECT 1;` is one statement and the
engine runs it, and `duckdb.extract_statements` returns the same single statement); a
`*/` that closes nothing is rejected by the engine, as a parse error or as an unknown operator;
`/*/` opens a comment. A CR ends a line comment as a LF does, and `;`, `*/` and `/*` inside a line
comment change nothing. `5--1` is `5`. `#` and `//` are not
comments (`//` is integer division).

An unterminated block comment is **loud**: the driver and `extract_statements` both
raise `unterminated /* comment` and nothing runs,
so the scanner returns it as the last statement and refuses nothing (rows 40, 41). This
differs from SQLite, where the same text is silently dropped.

**Where the shell and the engine differ on comments** (measured on the shell v1.5.6 with
`duckdb -init /dev/null -bail`, script on stdin). A script whose first line starts with `--` and holds a lone CR
(`-- a` CR `SELECT 1 AS x;` LF `SELECT 2 AS y;`): the shell drops the whole line, runs only
`SELECT 2 AS y` and exits 0, while `extract_statements` ends the comment at the CR and
returns `SELECT 1 AS x` first, and the scanner does the same, so dblift runs one statement
more than the shell and never silently. An unterminated block comment after a statement
(`SELECT 1 AS a;` LF `/* open` LF `SELECT 2 AS b;` LF `SELECT 3 AS c;`): the shell runs
the first statement, then rejects the rest as one unterminated comment and exits 1, as the
engine does; the scanner returns the rest as the last statement and the engine rejects it,
so all three agree (the later lines do not run). A later `*/` closes it for the shell as
for the engine (`SELECT 9 AS z` runs).

**A comment-only segment is not a statement.** `extract_statements` returns nothing for
`-- c` newline `;` and for a script of comments; the scanner returns nothing for them
(rows 44-46). A comment that follows a `;` on its line belongs to the next
statement's text, as `extract_statements` hands it over (row 48); a comment before the `;` stays in the statement. `extract_statements` keeps a comment that trails the last
statement in that statement's text; the scanner
drops it, as it drops every segment of comments only: the statement is the same.

## 4. Terminators

| Terminator | Rule |
| --- | --- |
| `;` | ends a statement at any depth: there are no blocks |

No batch separator and no directive that changes the terminator. A statement
needs no terminator at the end of the script, so the last statement is returned with
`terminator=None` (row 49). Two statements on a line, or none between (`SELECT 1;SELECT 2;`),
are two; a terminator on its own line ends the
statement above it (row 50); an empty statement (`;;`) is nothing
(rows 46, 47). A CR before the LF is part
of the line end and a lone CR is whitespace that ends no statement (rows 51, 52). A tab, a form feed and a no-break space
between statements are blanks; a vertical tab is
rejected by the engine. The engine reads exactly 18 non-ASCII code points as blanks: U+00A0,
U+2000 to U+200B, U+202F, U+205F, U+2060, U+3000 and U+FEFF (measured over U+0001 to U+10FFFF with a
code point between `SELECT` and a dollar quote), so a dollar quote or an `E'…'` string right after
one still opens (rows 72, 73), while any other non-ASCII character is part of the word before it. The engine reaches these blanks through a fallback of its parser, which is
stricter than its main path: a lone no-break space after the last statement is a syntax error, and a script that holds a
word with `$$` and a Unicode blank is rejected as a whole; a segment of one such blank
between two terminators is nothing. A UTF-8 byte order mark is whitespace for the
engine at the start and in the middle of a script and
the scanner drops the one at the start.

The shell removes the CR of a CRLF pair from every line it reads, also inside a literal and a
macro body, and keeps a lone CR; the driver and dblift keep both, so the one divergence is a CR inside a
literal or a body. The shell, like the driver, runs the script up to a NUL and reports success. It accepts what the driver rejects in three places: a vertical tab between
statements, a lone no-break space after the last statement and a dot-command.

The driver is not the only reader of a script. `duckdb.extract_statements` is the
engine's own cut: it agrees with the rules above on every script it accepts
(it rejects what the parser rejects, so a text with a syntax error gives no cut), with
two exceptions that are rewrites and not cuts: a `PRAGMA` that calls a function comes
back as `SELECT * FROM pragma_…()` and a `PIVOT` as several statements. The first changes the text and not the count; the second
changes both, so the oracle is read with that exception.

## 5. Blocks

None. DuckDB has no procedural language: `CREATE PROCEDURE`, `CREATE TRIGGER`, `DO`,
`BEGIN ATOMIC` and `CREATE FUNCTION … LANGUAGE` are syntax errors. `CREATE MACRO` and its alias `CREATE FUNCTION` take an
expression or a table query and hold no `;` outside a string. `BEGIN [TRANSACTION]`, `START TRANSACTION`,
`COMMIT`, `ROLLBACK`, `ABORT` and `END` are statements (§8); `CASE … END` and a table
called `begin_log` open nothing.

## 6. Client directives

The `duckdb` shell: "Dot commands begin with a period: begin the line with a period (.)
immediately followed by the name of the command" and "no whitespace may occur before the
period" (*CLI, Dot Commands*, as read). The engine rejects every one of them: the driver
and `extract_statements` answer `syntax error at or near "."` for each of the dot lines
tried, including `.mode`, `.read`, `.exit`, `.shell`, `.system`, `.open`, `.output`,
`.bail`, `.import`, `.timer`, `.tables`, so a dot line that reaches the engine fails loudly.

| Directive | Client | Splitter action |
| --- | --- | --- |
| a line that starts with `.` in column 0 while no statement text is pending, any word (`.mode`, `.read`, `.exit`, `.shell`, `.5`, a lone `.`) | `duckdb` shell | **reject** with `UnsupportedMetaCommandError`, command and line named |

The shell runs such a line as a command: `.mode csv` changes the output of every later
statement and exits 0, `.shell` and `.system` run an operating-system command, `.open` moves every later statement to
another database file, `.output` redirects the results, `.exit [code]` and `.quit` stop the run, `.exit 3` exits with status 3 and
nothing after it runs, `.bail on` makes the next
error stop the run, `.read file` runs a file that
may hold dot-commands and statements, and
`.timer`, `.echo`, `.headers`, `.maxrows`, `.changes`, `.help`, `.tables` change or print
something. A word that is no command (`.5`, `.MODE`, `.nosuch`,
`.;`) is an error of the shell, exit 1, and the next line still runs without `-bail`; commands are case sensitive. A lone `.`
is accepted. A trailing `;` is an argument, not a terminator.

"Nothing pending" means no token other than comments and blanks since the start of the
script or the last `;`. The shell reads a dot line as a command in exactly those places and as
text everywhere else, which the engine then rejects: while a statement is pending, including
after a comment on the pending statement's line, indented by spaces or a tab, after code or a
comment on its own line, and inside a string, a quoted identifier, a dollar-quoted string or a
comment. `.read` is no different: while a statement is pending it is text too. `SELECT` newline `.5;` is one valid statement, so a dot at a line start is not a command while a statement is
pending. A byte order mark before the first dot is not a command for the shell, which the scanner, dropping the mark first, refuses: the stricter side.
A comment line or a block comment that closed leaves nothing pending, so the dot line after it
is a command.

A line that starts with a backslash is not a directive: it is a syntax error for the engine, and there is no
continuation character. A line that holds only `go` or `/` is part of the statement for
the driver and for the shell alike (`SELECT 6` newline `/` newline `2` is 3.0, `go` is an
alias; rows 64, 65): unlike SQLite's shell, this one
has no terminator line.

## 7. Raw blocks

None. There is no `COPY … FROM STDIN` data block: the statement is a syntax error for the
engine and what follows the `;` is ordinary text (row 63).
`COPY … TO`, `COPY … FROM 'file'`, `EXPORT DATABASE` and `IMPORT DATABASE` name files and are
ordinary statements.

## 8. Transaction markers

The splitter flags none: `BEGIN`, `COMMIT`, `ROLLBACK` and the others are ordinary
statements (row 66; `duckdb.extract_statements` reports each as a
`TRANSACTION` statement). DuckDB DDL is transactional (`supports_transactional_ddl = True`).
What they do **inside dblift** is an execution matter, not a splitting one: the
connection always holds dblift's transaction, so a script's own `BEGIN` would fail
(`cannot start a transaction within a transaction`) and its `COMMIT`, `END`,
`ROLLBACK` or `ABORT` would end that transaction early (the rows written before it
and after it stay when the migrate rolls back). `transaction_control_sql_patterns`
(`quirks.py`) classifies them after the split, on the statement with its comments
blanked (`COMMIT /* c */;` is a `COMMIT`). A script whose first statement is
`BEGIN [TRANSACTION|WORK]` or `START TRANSACTION` and whose last is `COMMIT` or
`END` (each with an optional `TRANSACTION` or `WORK`) has both dropped with a
warning (it is the transaction dblift opens, and the outcome is the shell's); any
other `BEGIN`, `COMMIT`, `END`, `ROLLBACK` or `ABORT` (each with an optional
`TRANSACTION` or `WORK`) is refused before anything runs, naming the statement and
its line. A `BEGIN` or `START TRANSACTION` with options (`BEGIN TRANSACTION READ
ONLY`) is not an envelope and is refused, named as the cause. A bare `COMMIT`
therefore never reaches the `duckdb_engine` cursor, which turns the exact text
`commit` into `connection.commit()` and answers success when no transaction is
open. The shell answers `cannot commit - no transaction is active` for a `COMMIT`
with nothing open, exit 1.

## 9. Engine subclass

None. The one rule that is not a fixed pair, a dollar-quote closing on the tag that
opened it, is a regular expression and a substring search in the scanner.

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| 1 | `CREATE TABLE t(a INT); INSERT INTO t VALUES (1);` | `CREATE TABLE t(a INT)` · `INSERT INTO t VALUES (1)` |
| 2 | `SELECT 'a;b'; SELECT 2;` | `SELECT 'a;b'` · `SELECT 2` |
| 3 | `SELECT E'a\'b;c'; SELECT 2;` | `SELECT E'a\'b;c'` · `SELECT 2` |
| 4 | `SELECT 'a\'; SELECT 2;` | `SELECT 'a\'` · `SELECT 2` (plain strings have no backslash escape) |
| 5 | `SELECT $$a;'b$$; SELECT 2;` | `SELECT $$a;'b$$` · `SELECT 2` |
| 6 | `SELECT $x$ a $$ ; $x$; SELECT 2;` | `SELECT $x$ a $$ ; $x$` · `SELECT 2` |
| 7 | `CREATE TABLE "weird;name"(a INT); CREATE TABLE "a--b"(c INT);` | `CREATE TABLE "weird;name"(a INT)` · `CREATE TABLE "a--b"(c INT)` |
| 8 | `/* a /* b */ ; */ SELECT 1;` | `/* a /* b */ ; */ SELECT 1` (nested comment; a comment before a statement stays in its text) |
| 9 | `CREATE MACRO add(a, b) AS a + b; SELECT add(1, 2);` | `CREATE MACRO add(a, b) AS a + b` · `SELECT add(1, 2)` |
| 10 | `.mode csv\nSELECT 1;` | `UnsupportedMetaCommandError` (line 1, the dot command: refusal; the engine cannot run it and the shell does, printing the result as CSV and exiting 0) |
| 11 | `SELECT 'it''s;'; SELECT 2;` | `SELECT 'it''s;'` · `SELECT 2` |
| 12 | `SELECT E'it''s;'; SELECT 2;` | `SELECT E'it''s;'` · `SELECT 2` |
| 13 | `SELECT E'a\\\\'; SELECT 2;` | `SELECT E'a\\\\'` · `SELECT 2` (in an escape string a doubled backslash is one escaped character, so the quote closes) |
| 14 | `SELECT E'a''\'b;c'; SELECT 2;` | `SELECT E'a''\'b;c'` · `SELECT 2` (a doubled quote keeps the escape string open) |
| 15 | `SELECT xE'a\'; SELECT 2;` | `SELECT xE'a\'` · `SELECT 2` (an E after an identifier character is part of the name: a plain string follows; the engine rejects the type) |
| 16 | `SELECT (1)E'a\'b;c'; SELECT 2;` | `SELECT (1)E'a\'b;c'` · `SELECT 2` (an E that touches a quote opens an escape string after a closing parenthesis; the engine rejects the text at the grammar level, the lexeme is the whole literal) |
| 17 | `SELECT $X$ a $x$ ; $X$; SELECT 2;` | `SELECT $X$ a $x$ ; $X$` · `SELECT 2` (tags are case sensitive) |
| 18 | `SELECT $a1$ ; $a1$; SELECT 2;` | `SELECT $a1$ ; $a1$` · `SELECT 2` |
| 19 | `SELECT $é$ ; $é$; SELECT 2;` | `SELECT $é$ ; $é$` · `SELECT 2` (a non-ASCII letter is a tag character) |
| 20 | `SELECT $a$ x $b$ ; $b$ y ; $a$; SELECT 2;` | `SELECT $a$ x $b$ ; $b$ y ; $a$` · `SELECT 2` (another tag inside is text) |
| 21 | `SELECT $ab$ $a$ ; $ab$; SELECT 2;` | `SELECT $ab$ $a$ ; $ab$` · `SELECT 2` (only the identical tag closes) |
| 22 | `SELECT $$a\n;\nb$$; SELECT 2;` | `SELECT $$a\n;\nb$$` · `SELECT 2` |
| 23 | `SELECT $$$$; SELECT 2;` | `SELECT $$$$` · `SELECT 2` (empty dollar-quoted string) |
| 24 | `PREPARE p AS SELECT $1; EXECUTE p(5);` | `PREPARE p AS SELECT $1` · `EXECUTE p(5)` (a positional parameter is not a tag) |
| 25 | `PREPARE p AS SELECT $a; SELECT 2;` | `PREPARE p AS SELECT $a` · `SELECT 2` (a named parameter is not a tag) |
| 26 | `SELECT 1 AS a$$; SELECT 'x$$'; SELECT 2;` | `SELECT 1 AS a$$` · `SELECT 'x$$'` · `SELECT 2` (a dollar pair inside a word opens nothing) |
| 27 | `SELECT$$a;b$$; SELECT 2;` | `SELECT$$a` · `b$$` · `SELECT 2` (the dollar pair is part of the word SELECT$$a, so the first semicolon ends the statement; the engine rejects the first) |
| 28 | `SELECT ($$a;b$$); SELECT 2;` | `SELECT ($$a;b$$)` · `SELECT 2` |
| 29 | `SELECT $$a; SELECT 2;` | `SELECT $$a; SELECT 2` (an unterminated dollar-quoted string is the rest of the script; the engine rejects it) |
| 30 | `CREATE TABLE "a""b;c"(x INT); SELECT 1;` | `CREATE TABLE "a""b;c"(x INT)` · `SELECT 1` |
| 31 | `CREATE TABLE "it's;"(x INT); SELECT 1;` | `CREATE TABLE "it's;"(x INT)` · `SELECT 1` |
| 32 | `CREATE TABLE "a--b;"(x INT); CREATE TABLE "c/*d"(y INT); SELECT 1;` | `CREATE TABLE "a--b;"(x INT)` · `CREATE TABLE "c/*d"(y INT)` · `SELECT 1` |
| 33 | `CREATE TABLE "a;\nb"(x INT); SELECT 1;` | `CREATE TABLE "a;\nb"(x INT)` · `SELECT 1` |
| 34 | `CREATE TABLE [a;b](x INT); SELECT 1;` | `CREATE TABLE [a` · `b](x INT)` · `SELECT 1` (a square bracket is not an identifier quote; the engine rejects the first two) |
| 35 | `SELECT ['a;b'][1]; SELECT 2;` | `SELECT ['a;b'][1]` · `SELECT 2` |
| 36 | `SELECT {'a': ';'}; SELECT 2;` | `SELECT {'a': ';'}` · `SELECT 2` |
| 37 | `/* a /* b */ SELECT 1; */ SELECT 2;` | `/* a /* b */ SELECT 1; */ SELECT 2` (the comment ends at the matching close marker: one statement) |
| 38 | `/* a /* b /* c */ ; */ ; */ SELECT 1;` | `/* a /* b /* c */ ; */ ; */ SELECT 1` |
| 39 | `SELECT 1; */ SELECT 2;` | `SELECT 1` · `*/ SELECT 2` (a stray close marker is sent; the engine rejects it) |
| 40 | `SELECT 1; /* open` | `SELECT 1` · `/* open` (an unterminated comment is sent as the last statement; the engine rejects it, nothing is dropped) |
| 41 | `SELECT 1; /* never closed\nSELECT 2;` | `SELECT 1` · `/* never closed\nSELECT 2` (the semicolon inside the open comment ends nothing) |
| 42 | `SELECT 1 -- ; \n+ 1; SELECT 2;` | `SELECT 1 -- ; \n+ 1` · `SELECT 2` (a semicolon inside a line comment ends nothing) |
| 43 | `SELECT 1; -- c␍SELECT 2;` | `SELECT 1` · `-- c␍SELECT 2` (a CR ends a line comment: the second statement is code) |
| 44 | `SELECT 1; -- bye` | `SELECT 1` (a segment of comments only is not a statement) |
| 45 | `-- only a comment\n/* here */` | `(empty)` |
| 46 | `;;;` | `(empty)` |
| 47 | `SELECT 1;; SELECT 2;` | `SELECT 1` · `SELECT 2` (an empty statement is nothing) |
| 48 | `SELECT 1; -- c\nSELECT 2;` | `SELECT 1` · `-- c\nSELECT 2` (a comment after a terminator goes with the next statement) |
| 49 | `SELECT 1; SELECT 2` | `SELECT 1` · `SELECT 2` (no terminator: the last statement is returned) |
| 50 | `SELECT 1\n;\nSELECT 2\n;` | `SELECT 1` · `SELECT 2` |
| 51 | `SELECT 1;␍\nSELECT 2;␍\n` | `SELECT 1` · `SELECT 2` |
| 52 | `SELECT 1;␍SELECT 2;␍` | `SELECT 1` · `SELECT 2` (a lone CR is a blank) |
| 53 | `SELECT 'a'\n'b';` | `SELECT 'a'\n'b'` (adjacent literals across a newline are one string) |
| 54 | `SELECT 'a\n.mode csv\nb'; SELECT 2;` | `SELECT 'a\n.mode csv\nb'` · `SELECT 2` (a dot line inside a string is text) |
| 55 | `/*\n.mode csv\n*/ SELECT 1;` | `/*\n.mode csv\n*/ SELECT 1` |
| 56 | `SELECT 1\n.mode csv\n;` | `SELECT 1\n.mode csv` (a statement is pending: text, the shell sends it to the engine, which rejects it, exit 1) |
| 57 | `SELECT 1;\n.mode csv\nSELECT 2;` | `UnsupportedMetaCommandError` (line 2: a dot line after a complete statement; the shell runs it) |
| 58 | `-- c\n.mode csv\nSELECT 1;` | `UnsupportedMetaCommandError` (line 2: a comment line leaves nothing pending; the shell runs the command) |
| 59 | `  .mode csv\nSELECT 1;` | `.mode csv\nSELECT 1` (indented: no whitespace may precede the period, so it is text and the engine rejects it; the shell does the same with a space or a tab) |
| 60 | `SELECT\n.5;` | `SELECT\n.5` (a dot at a line start inside a pending statement is part of a number) |
| 61 | `SELECT 1 AS "a\n.mode csv\nb"; SELECT 2;` | `SELECT 1 AS "a\n.mode csv\nb"` · `SELECT 2` |
| 62 | `SELECT 1;\n\\d t\nSELECT 2;` | `SELECT 1` · `\\d t\nSELECT 2` (a backslash line is text, not a directive; the engine rejects it) |
| 63 | `CREATE TABLE t(a INT); COPY t FROM STDIN;\n1\n\\.\nSELECT 2;` | `CREATE TABLE t(a INT)` · `COPY t FROM STDIN` · `1\n\\.\nSELECT 2` (there is no data block to read: the engine rejects both of the last two) |
| 64 | `SELECT 6\n/\n2;` | `SELECT 6\n/\n2` (one statement for the driver and for the shell, which divide and print 3.0; a slash alone on a line ends nothing) |
| 65 | `SELECT 1\ngo\n;` | `SELECT 1\ngo` (one statement for the driver and for the shell, where go is an alias; a go line ends nothing) |
| 66 | `BEGIN; INSERT INTO t VALUES (1); COMMIT;` | `BEGIN` · `INSERT INTO t VALUES (1)` · `COMMIT` |
| 67 | `PRAGMA threads=1; SELECT 2;` | `PRAGMA threads=1` · `SELECT 2` |
| 68 | `ATTACH ':memory:' AS o; DETACH o;` | `ATTACH ':memory:' AS o` · `DETACH o` |
| 69 | `CREATE MACRO m(a) AS a \|\| ';'; SELECT m('x');` | `CREATE MACRO m(a) AS a \|\| ';'` · `SELECT m('x')` |
| 70 | `CREATE TYPE mood AS ENUM ('a;b', 'c'); SELECT 'a;b'::mood;` | `CREATE TYPE mood AS ENUM ('a;b', 'c')` · `SELECT 'a;b'::mood` |
| 71 | `SELECT 'a /* b'; SELECT 'c -- d'; SELECT 3;` | `SELECT 'a /* b'` · `SELECT 'c -- d'` · `SELECT 3` |
| 72 | `SELECT $$a;b$$; SELECT 2;` | `SELECT $$a;b$$` · `SELECT 2` (a no-break space, U+00A0, is a blank for the engine: the dollar quote still opens) |
| 73 | `SELECT　E'a\'b;c'; SELECT 2;` | `SELECT　E'a\'b;c'` · `SELECT 2` (an ideographic space, U+3000, is a blank: the letter E still opens an escape string) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| a NUL character anywhere | rejected with `UnsafeStatementSplitError` | the driver hands the text to the engine as a C string: `SELECT 1;` NUL `SELECT 2;` runs only the first statement and reports success, and a NUL inside a literal reads as an unterminated string; the shell does the same |
| shell dot-commands | rejected (§6) | not SQL |
| a BOM in the middle of a script | kept as whitespace | the engine treats it as a blank |
| a dollar-quote tag made of Unicode blanks (`$` U+00A0 `$`) | read as a parameter and blanks, so a `;` inside splits (three pieces where the engine reads two statements) and the pieces fail loudly | the engine parses first with those code points as identifier characters and reads the tag; it falls back to blanks only when that fails |

## 12. Current implementation

Code: `dblift/db/plugins/duckdb/parser/_script.py` (`scan_script`, the engine's
character scanner), wired by `DuckDBRegexParser`: `split()` returns `Statement`
records, `split_statements()` their execution text, and `split_for_analysis()`
adds comment-only segments. `split_for_extraction()` uses the same scanner view;
`parse_sql()` honors its shell-command and unsafe-split refusals.

The scanner reads a script as the engine's lexer does. A word is a letter, an
underscore or a non-ASCII character followed by those, digits and `$`; a number is read
up to its last letter or digit, so a `$$` opens a string after a number or an operator and
never inside a word. A `$` that starts a token opens a dollar-quoted string when a tag
(letters, underscore, non-ASCII, digits, no `$`) and a second `$` follow, and closes it on
the identical tag; otherwise it starts a parameter (`$1`, `$name`). `E'` and `e'` open an
escape string unless the `E` ends a longer word, and the 18 non-ASCII blanks the engine reads (U+00A0, U+2000 to U+200B, U+202F, U+205F, U+2060, U+3000, U+FEFF) are blanks, so a dollar quote or an `E` right after one still opens; inside it a backslash takes the next
character and a doubled quote stays inside. Adjacent string literals separated by a newline,
including a line comment, continue an `E` string's escape mode. A plain string and a quoted identifier end at
the next quote, a doubled quote being two lexemes in a row. A line comment ends at the
first LF or CR, a block comment nests and one that is never closed is sent as it stands,
like a string, an identifier or a dollar-quoted string that is never closed: the engine
rejects each of them loudly, so nothing is refused for them. A `;` ends a statement
wherever it stands outside those lexemes. A segment of comments only is not a statement
for execution. The one line rule reads each line where no lexeme is open: a line that
starts with `.` in column 0 while no statement text is pending is a `duckdb` shell
command and is refused with `UnsupportedMetaCommandError`, the command and the line
named. A NUL character is refused with `UnsafeStatementSplitError`: the engine reads
the script as a C string and would silently drop everything after it. A byte order mark
at the start of the script is dropped.

The text of a statement is a slice of the script (comments, line breaks and CRs kept)
without its terminator. Before this scanner `split_statements` was a regex-free
character scan that did not read dollar-quoted strings (a `;` inside `$$…$$` split),
returned a segment of comments only and a bare `;` as statements, glued a dot-command
onto the following statement, and kept the `;` in the text of every statement.
