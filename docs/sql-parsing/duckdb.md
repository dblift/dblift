# DuckDB — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | DuckDB 1.x scripts run through the Python `duckdb` driver (the path dblift executes through) and written for the `duckdb` command-line shell. Measured: shell v1.5.6 (Variegata, Homebrew) and v1.5.5 (Variegata, the `duckdb-cli` wheel) and the Python driver 1.5.5 and 1.5.6 (`duckdb.connect()`, `execute`, `duckdb.extract_statements`) with `duckdb_engine` 0.17.0 on SQLAlchemy 2.0.52 |
| Code facts taken from | the shared lexical engine with the DuckDB specification; §12 describes it. The DuckDB part of the conformance run is 89 rows: 87 passes and the two known gaps 74 and 75 (expected failures) |
| Vendor references, fetched 2026-10-12 from `duckdb.org/docs/current` | *Literal Types* (`sql/data_types/literal_types`: strings, escape strings, dollar-quoted strings); *Keywords and Identifiers* (`sql/dialect/keywords_and_identifiers`: quoted identifiers); *SQL Dialect, Overview* ("DuckDB's SQL dialect is based on PostgreSQL."); *Prepared Statements* (`sql/query_syntax/prepared_statements`: `?`, `$1`, `$name`); *CLI, Dot Commands* (`clients/cli/dot_commands`); *CLI, Overview* (`clients/cli/overview`: scripts from standard input, `.read`, multi-line statements). No page on comments could be found: block-comment nesting rests on measurement alone |
| Live verification | `duckdb -init /dev/null -bail <db> < script.sql` against the Python driver dblift executes through (`SqlAnalyzer("duckdb").split_statements`, then one `execute` per statement through `duckdb_engine`); the resulting files are compared through the `duckdb_*()` catalogue functions and the table rows; `duckdb.extract_statements` is compared with the splitter on every script it accepts. |
| Second ground truth | the driver: `execute` takes **several** statements in one text, parses the whole text before it runs anything (a parse error in the last statement runs none of the first), and a runtime error leaves the statements before it done; dblift sends one statement per call, so the two stop at different places on a script with a parse error |
| How the shell cuts | the shell reads the script line by line and sends the text so far to the engine when a line ends a statement: statements on one line are one chunk run as one text, like the driver (a parse error in the chunk runs none of it, a run-time error stops the rest of it), statements on later lines are separate chunks; its exit status is 0 when every statement ran and 1 when any failed, even if a later one succeeded; without `-bail` it goes on with the next line; standard input, `.read` and `-f` give the same result for every script tried |
| Engine subclass | none: the lexeme rules and the shell's dot-command rule are data of the shared tokenizer (`SegmentScriptRules`) |

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
| Escape string | `E'` / `e'` | `'` | `''` and a backslash that takes the next character | "prefix a string literal with e (or E)" (*Literal Types*). The measured effect on splitting: `E'a\'b;c'` is one string, `E'a\\'` ends at the last quote, a doubled quote keeps the string open. The `E` is a prefix unless an identifier character precedes it: `xE'a\'` is the name `xE` and a plain string; after a quote, a closing parenthesis, a dollar-quoted string or digits the `E` still opens an escape string; a superscript or a digit of another script before the `E` (U+00B2 or U+0663) is part of a name for the engine, so a plain string follows it (row 75) |
| Dollar-quoted | `$$` or `$tag$` | the same `$$` / `$tag$` | none | "DuckDB supports dollar-quoted string literals, which are surrounded by double-dollar symbols ($$)" and "you can insert alphanumeric tags in the double-dollar symbols" (*Literal Types*). The tag starts with a letter, an underscore or a non-ASCII character and goes on with those and digits, no `$`; it is case sensitive and closes only on the identical tag; `$1a$` and `$a b$` are not tags; `;`, quotes and comment markers inside are text |

Words and parameters decide where a dollar quote may open. A word is a letter,
an underscore or a non-ASCII character followed by those, digits and `$`, so a
`$$` inside a word is part of it and a dollar tag opens only at a lexeme boundary; after a
digit, an operator, a comma or an opening parenthesis a `$$` opens a string. A
`$` followed by digits or by a name that is not closed by another `$` is a parameter
(`$1`, `$name`: "Prepared statements can use positional parameters, where parameters
are denoted with an integer ($1, $2)" and "named parameters where parameters are
denoted with $parameter_name", *Prepared Statements*), and `;` after it ends the
statement.

The engine reads a positional parameter as the dollar sign and its digits only: in
`PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$;` the letters after `$1` start a word,
the dollar pair inside that word opens nothing and each semicolon ends a statement (row 76).

Adjacent literals separated by a newline are one string (`SELECT 'a'` newline `'b'`
is `'ab'`); on one line they are a syntax error. The statement is cut at the same place either way when no escape string comes first.
`x'…'`, `b'…'` and `N'…'` are a word followed by a plain string; `U&'…'` is read by the lexer and
rejected by the engine; `[…]` is a list and
`{…}` a struct, never an identifier.

An escape string's mode continues into the next string only across a line break: `SELECT E'a'` newline
`'b\'` is one string, but on one line (`SELECT E'a' 'b\';`) the second string is a plain string
that the backslash does not escape, and the engine rejects the first statement (row 74).

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
so the splitter returns it as the last statement and refuses nothing (rows 40, 41). This
differs from SQLite, where the same text is silently dropped.

**Where the shell and the engine differ on comments** (measured on the shell v1.5.6 with
`duckdb -init /dev/null -bail`, script on stdin). A script whose first line starts with `--` and holds a lone CR
(`-- a` CR `SELECT 1 AS x;` LF `SELECT 2 AS y;`): the shell drops the whole line, runs only
`SELECT 2 AS y` and exits 0, while `extract_statements` ends the comment at the CR and
returns `SELECT 1 AS x` first, and the splitter does the same, so dblift runs one statement
more than the shell and never silently. An unterminated block comment after a statement
(`SELECT 1 AS a;` LF `/* open` LF `SELECT 2 AS b;` LF `SELECT 3 AS c;`): the shell runs
the first statement, then rejects the rest as one unterminated comment and exits 1, as the
engine does; the splitter returns the rest as the last statement and the engine rejects it,
so all three agree (the later lines do not run). A later `*/` closes it for the shell as
for the engine (`SELECT 9 AS z` runs).

**A comment-only segment is not a statement.** `extract_statements` returns nothing for
`-- c` newline `;` and for a script of comments; the splitter returns nothing for them
(rows 44-46). A comment that follows a `;` on its line belongs to the next
statement's text, as `extract_statements` hands it over (row 48); a comment before the `;` stays in the statement. `extract_statements` keeps a comment that trails the last
statement in that statement's text; the splitter
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
one still opens (rows 72, 73), while any other non-ASCII character is part of the word before it. The engine reaches these blanks through a pass of its own (§11): a blank is a space until the pass stops, and from there it is part of the adjacent name, so the outcome depends on its position and not on a rule against blanks. A lone no-break space after the last statement is a syntax error; after the pass has stopped, `SELECT 1 AS a$$,` U+00A0 `2;` parses and fails binding on a column named with a leading blank; `WHERE i` U+00A0 `=` U+00A0 `1` fails binding on a column `i` with a trailing blank; `CREATE TABLE u(c` U+00A0 `INT)` is a syntax error; `CREATE TABLE u(` U+00A0 `c INT)` succeeds with a column named U+00A0 `c`; a keyword followed by a blank and a token is a syntax error (`SELECT 1 AS a$$; SELECT` U+00A0 `2;`); a segment of one such blank
between two terminators is nothing. A UTF-8 byte order mark is whitespace for the
engine at the start and in the middle of a script and
the splitter drops the one at the start.

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
pending. A byte order mark before the first dot is not a command for the shell, which the splitter, dropping the mark first, refuses: the stricter side.
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

None. The lexeme rules (blanks, words, numbers, dollar-quote tags, parameters, the escape letters,
the end of a line comment) and the shell's one line rule (the command prefix) are data, `SegmentScriptRules`, on the
DuckDB specification; the shared tokenizer reads them and one core module assembles the records between `;`.

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
| 74 | `SELECT E'a' 'b\'; SELECT 1; SELECT 'z';` | `SELECT E'a' 'b\'` · `SELECT 1` · `SELECT 'z'` (measured: on one line the engine does not carry the escape mode of an E string into the next string, reads the second string as a plain string closed after the backslash and rejects the first statement; known gap: the splitter carries the escape mode across blanks on one line and sends the three statements as one) |
| 75 | `SELECT \u00b2E'b\';c'; SELECT 2;` | `SELECT \u00b2E'b\'` · `c'; SELECT 2;` (measured: a superscript two followed by E is one name for the engine, so a plain string follows and the first semicolon ends the statement; known gap: the splitter reads any character Python counts as a digit before E as a number and opens an escape string) |
| 76 | `PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$;` | `PREPARE p AS SELECT $1a$$x` · `SELECT 2` · `SELECT 3 AS y$$` (measured: a positional parameter is the dollar sign and its digits with underscore separators, so the letters after it start a word, the dollar pair inside that word opens nothing and each semicolon ends a statement; the driver's own statement splitter returns the same three) |
| 77 | `SELECT 1a$$x; DROP TABLE t; SELECT 3 AS y$$;` | `SELECT 1a$$x` · `DROP TABLE t` · `SELECT 3 AS y$$` (measured: a number is digits with underscore separators, an optional fraction and an optional exponent, so the letters after it start a word, the dollar pair inside that word opens nothing and each semicolon ends a statement; the same for 1_000a, 1.5a, 1e5a and 0x1g, which is the number 0 and the word x1g, and the driver and the shell dropped the table) |
| 78 | `SELECT 1 AS a$$\u00a0$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$$\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: a no-break space after a dollar sign inside a word is part of the word, so the word runs on through the dollar tag, no dollar-quoted string opens and each semicolon ends a statement; the driver's own statement splitter returns the same three, and the driver and the shell dropped the table) |
| 79 | `SELECT 1 AS a$b\u3000$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$b\u3000$t$x` · `DROP TABLE t` · `SELECT 3` (the same for an ideographic space, U+3000, and for all 18 blanks, after a dollar sign that is followed by letters) |
| 80 | `SELECT 1 AS \u00e9$\u2003\u2003$$x; DROP TABLE t; SELECT 3 AS y$$;` | `SELECT 1 AS \u00e9$\u2003\u2003$$x` · `DROP TABLE t` · `SELECT 3 AS y$$` (the same after a non-ASCII letter, with two blanks in a row) |
| 81 | `SELECT a$\u00a0E'x\'; DROP TABLE t; SELECT 'y';` | `SELECT a$\u00a0E'x\'` · `DROP TABLE t` · `SELECT 'y'` (measured: the E after such a blank is part of the word, so a plain string follows and its backslash escapes nothing) |
| 82 | `SELECT 1 AS a$$ $t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$$ $t$x; DROP TABLE t; SELECT 3;` (an ASCII blank ends the word, so the dollar tag opens a string that never closes; the driver rejects it as unterminated) |
| 83 | `SELECT 1 AS a\u00a0$$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a\u00a0$$t$x; DROP TABLE t; SELECT 3;` (a blank before any dollar sign ends the word as before, so a dollar-quoted string opens and the driver rejects it as unterminated) |
| 84 | `SELECT 1 AS a$1\u00a0$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$1\u00a0$t$x; DROP TABLE t; SELECT 3;` (measured: a dollar sign followed by a digit is a parameter and does not make a blank continue the word, so the dollar tag after the blank opens a string that never closes) |
| 85 | `SELECT 1 AS a$$, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$$, 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: before it parses, DuckDB runs one pass over the whole text that replaces its 18 blanks with spaces; the pass skips single-quoted strings and quoted names (a backslash means nothing to it, so an escape string with a backslash before its quote leaves a quote open for it) and line comments, does not know block comments (an apostrophe, a double quote or a dollar tag inside one counts), and stops at the first dollar tag whose closing tag never appears (two dollars, a tag, or a tag made of blanks); from there every blank is kept and is an identifier character for the parser, whether or not any statement is valid. A dollar sign that opens no tag (a name followed by a dollar and a comma, a digit or a line comment; a dollar and a letter open a tag only when a matching closing dollar follows), a tag in a string, a quoted name or a line comment, and a tag that closes later do not stop it. A dollar followed by tag characters but no closing dollar keeps the blanks inside that run, and the character that ended the run is read as usual. The splitter reproduces the pass over the whole script, so an unclosed tag in an earlier statement stops the pass for every later one) |
| 86 | `/* don't */ SELECT 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `/* don't */ SELECT 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: the pass of row 85 does not know block comments, so the apostrophe opens a quote that never closes and every later blank is kept; the same for a double quote) |
| 87 | `/* $$ */ SELECT 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `/* $$ */ SELECT 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: a dollar tag with no closing tag inside a block comment stops the pass of row 85 too; the pass stops as in row 86) |
| 88 | `SELECT E'a\'b' AS c, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `SELECT E'a\'b' AS c, 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: the pass reads a backslash as an ordinary character, so the quote after it closes the string and the last quote opens one that never closes; every later blank is kept; the pass stops as in row 86) |
| 89 | `SELECT 1 AS a$$x$$$, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$$x$$$, 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: the pass shares a dollar sign between a tag and its closing tag, so the last dollar sign of a closed dollar-quoted string can begin the next tag; here a second tag opens and never closes, while a letter and a comma after the closing tag start none; the pass stops as in row 86) |
| 90 | `DROP TABLE t\xa0;\nSELECT 1;` | `UnsafeStatementSplitError` (measured: before a terminator a no-break space is a blank to DuckDB: the driver's `extract_statements` returns `DROP TABLE t ` and the rest, `execute` drops `t`, and the shell exits 0 and drops it. The statement alone ends in a no-break space, which the pass never reads, so it is kept and names another table; the statement reads differently alone than in its script and is refused (row 100), naming the character, its line and its column. Refusing it replaces the exact text `DROP TABLE t` that an earlier version of this row sent) |
| 90a | `DROP TABLE t\xa0` | `DROP TABLE t\xa0` **exact text** (no terminator and the script ends in a no-break space: sent as the shell sends it; DuckDB reads a no-break space that ends the text as part of the name, and only there) |
| 90b | `DROP TABLE t\u3000` | `DROP TABLE t` **exact text** (an ideographic space is a blank to DuckDB, at the end too) |
| 90c | `DROP TABLE t\xa0\n` | `UnsafeStatementSplitError` (measured: the driver replaces the no-break space, which is followed by a line feed, and drops `t`; the shell removes one final line ending, so its text ends in the no-break space, reads a name that does not exist and exits 1 with `t` kept. The two readings of the same script disagree, and the statement alone ends in the no-break space the pass never reads (row 100): refused, naming the character) |
| 90d | `DROP TABLE t\xa0\x0d\n` | `UnsafeStatementSplitError` (the same for a carriage return and a line feed: the driver drops `t`, the shell exits 1 and keeps it; refused as in row 90c) |
| 90e | `DROP TABLE t\xa0\n\n` | `UnsafeStatementSplitError` (measured: only one line ending is removed by the shell, so the no-break space is followed by a blank and the driver and the shell both drop `t`; the statement alone ends in the no-break space, which the pass never reads: refused as in row 100) |
| 90f | `DROP TABLE t \xa0` | `DROP TABLE t` **exact text** (a space then a no-break space at the end of the file: the shell drops t; the driver given this text reports a parser error, and the shell is the reference) |
| 90g | `DROP TABLE t\xa0\xa0` | `DROP TABLE t` **exact text** (two no-break spaces: the shell drops t, the driver reports a parser error) |
| 90h | `SELECT 1\x0b` | `SELECT 1` **exact text** (the shell drops a leading or trailing vertical tab before it sends the statement, so it runs; a vertical tab in the middle of a statement is still rejected; the driver rejects the text with the tab, and the shell is the reference) |
| 91 | `SELECT 1 AS a$$; DROP TABLE t\u00a0CASCADE;` | `UnsafeStatementSplitError` (measured: the driver rejects the script (`Catalog Error: Table with name t\u00a0CASCADE does not exist!`; `extract_statements` returns 2 statements) and the shell exits 1 with the same error, so the table `t` stays. The cut is right, but dblift runs each statement on its own and the engine then reads that statement afresh: the blank the pass of the whole script kept is replaced by a space, `DROP TABLE t CASCADE` runs and drops `t`. Such a statement reads differently alone than in its script and is refused, naming the character, its line and its column, before anything runs (the live `dblift migrate` fails and `t` is still there)) |
| 92 | `/* ' */ SELECT 1; DROP TABLE t\u00a0CASCADE;` | `UnsafeStatementSplitError` (the stop comes from the apostrophe in the block comment; measured: the driver rejects the script (`Catalog Error: Table with name t\u00a0CASCADE does not exist!`; `extract_statements` returns 2 statements) and the shell exits 1 with the same error, so the table `t` stays. The cut is right, but dblift runs each statement on its own and the engine then reads that statement afresh: the blank the pass of the whole script kept is replaced by a space, `DROP TABLE t CASCADE` runs and drops `t`.  Such a statement reads differently alone than in its script and is refused, naming the character, its line and its column, before anything runs (the live `dblift migrate` fails and `t` is still there)) |
| 93 | `SELECT 1 AS a$t$; DROP TABLE t\u00a0CASCADE; SELECT 2 AS b$t$;` | `UnsafeStatementSplitError` (a stretch the pass reads as a closed dollar-quoted string, from `$t$` to the next `$t$`, is code for the parser, so the pass keeps the blank in the second statement; measured: the driver rejects the script (`Catalog Error: Table with name t\u00a0CASCADE does not exist!`; `extract_statements` returns 3 statements) and the shell exits 1 with the same error, so the table `t` stays. The cut is right, but dblift runs each statement on its own and the engine then reads that statement afresh: the blank the pass of the whole script kept is replaced by a space, `DROP TABLE t CASCADE` runs and drops `t`.  Such a statement reads differently alone than in its script and is refused, naming the character, its line and its column, before anything runs (the live `dblift migrate` fails and `t` is still there)) |
| 94 | `SELECT 1 AS a$$; DROP TABLE t\u00a0CASCADE; SELECT 2 AS b$$;` | `UnsafeStatementSplitError` (the same with `$$` as the tag; measured: the driver rejects the script (`Catalog Error: Table with name t\u00a0CASCADE does not exist!`; `extract_statements` returns 3 statements) and the shell exits 1 with the same error, so the table `t` stays. The cut is right, but dblift runs each statement on its own and the engine then reads that statement afresh: the blank the pass of the whole script kept is replaced by a space, `DROP TABLE t CASCADE` runs and drops `t`.  Such a statement reads differently alone than in its script and is refused, naming the character, its line and its column, before anything runs (the live `dblift migrate` fails and `t` is still there)) |
| 95 | `-- x␍SELECT 1 AS a$$, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `-- x␍SELECT 1 AS a$$, 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: the pass ends a line comment at a CR as at a LF, so it stops at the first dollar pair as in row 85; the driver cuts three statements and drops the table, and the splitter does the same. The shell differs, as in §3: it ends the comment only at a LF, drops the whole first line, exits 0 and keeps the table) |
| 96 | `SELECT 1 AS a$t$a$b; SELECT 1 e\u205fy; DROP TABLE t; SELECT 3 AS f\u2000$t$z;` | `UnsafeStatementSplitError` (found by running random scripts through the driver and through dblift, 1 in 342 accepted scripts: the driver and the shell run all four statements and drop `t`, because the pass keeps the blank between `e` and `y` after the unclosed tag of the first statement; the second statement alone reads `SELECT 1 e y`, a syntax error, so dblift used to fail on it after running the first. The refusal now covers it, before anything runs) |
| 97 | `/* ' */ SELECT 1 AS e\u00a0x; SELECT 2 AS f\u00a0$t$y; DROP TABLE t; SELECT 3;` | `UnsafeStatementSplitError` (the driver and the shell accept the script and drop `t`: the apostrophe in the comment stops the pass and every blank after it is a letter. The second statement alone has its blank replaced before an unclosed dollar tag, so it would not parse; the refusal is the same as in row 91) |
| 98 | `/* ' */ SELECT 1 AS e\u00a0; SELECT 2;` | `/* ' */ SELECT 1 AS e\u00a0` · `SELECT 2` (measured with duckdb 1.5.6, the Python driver and the shell: the driver's statement extraction returns the first statement with the blank kept, its execution runs both and the shell exits 0. A blank kept in the script that is kept alone too is no refusal: the pass reads the last two bytes of a text no further, so a final U+00A0 is kept when the statement runs alone, and the apostrophe in the comment keeps it in the script. The first statement alone has the same alias as in the script) |
| 99 | `SELECT 1;\u00a0` | `SELECT 1` (measured: the pass keeps a final U+00A0, so the engine reads it as a one-character statement that does not parse: the driver's statement extraction and its execution reject the whole script (syntax error at the NBSP) and run nothing, while the shell exits 0 and runs the first statement. The splitter drops the trailing blank like the shell and runs one statement. A final U+3000 or a space is accepted by all three: only a two-byte blank at the very end is kept) |
| 100 | `DROP TABLE IF EXISTS t\u00a0; SELECT 1;` | `UnsafeStatementSplitError` (measured: the pass of the script reads the blank before the `;` and replaces it, so the driver and the shell drop `t`. The first statement alone ends in the U+00A0, which the pass never reads, so it is kept and `DROP TABLE IF EXISTS t\u00a0` names another table: a silent no-op. The statement reads differently alone than in its script and is refused, naming the character, its line and its column, and saying that the blank is kept when run alone, replaced in its script (the live `dblift migrate` fails and `t` is still there)) |
| 101 | `SELECT 1 AS x\u00a0; SELECT 2;` | `UnsafeStatementSplitError` (measured with duckdb 1.5.6, the Python driver and the shell: the driver's `extract_statements` returns `SELECT 1 AS x ` with a space, so the script reads the alias `x`, and the statement alone keeps the blank and reads the alias `x\u00a0`; both run and the shell exits 0. The same direction as row 100, harmless in effect: it is refused as well, since a loud failure beats a quiet divergence; the message ends with `remove the character`) |
| 102 | `SELECT 1 AS a$t$; /* $t$ */ DROP TABLE IF EXISTS t\u00a0CASCADE;` | `UnsafeStatementSplitError` (measured with duckdb 1.5.6, the Python driver and the shell: the pass of the script reads the tag in the comment as the closing tag of the one opened in the first statement, so it replaces the blank, `DROP TABLE IF EXISTS t CASCADE` runs, `t` is dropped and the shell exits 0. The second statement alone has an unclosed tag, so its pass stops, keeps the blank and names another table: a silent no-op. The same with `$$`, a quote or a double quote in the comment, and with an ideographic space. Refused as in row 100: a blank is refused whenever the pass keeps it in one reading and replaces it in the other, whichever direction) |
| 103 | `/* it's */ SELECT 1; /* don't */ CREATE TABLE x(a INT,\u00a0b INT);` | `UnsafeStatementSplitError` (measured with duckdb 1.5.6, the Python driver and the shell: the apostrophe in the first comment is closed by the apostrophe in the second, so the pass of the script replaces the blank and the table gets the columns `a` and `b`, in the driver and in the shell. The second statement alone has an unclosed quote, keeps the blank and creates a column named `\u00a0b`: a silent rename. Refused as in row 102) |
| 104 | `/* ' */ SELECT 1 AS x\u00a0y; /* ' */ SELECT 1 AS x\u00a0y; DROP TABLE t;` | `UnsafeStatementSplitError` (measured with duckdb 1.5.6, the Python driver and the shell: the script is rejected (`syntax error at or near "y"`, the shell exits 1) and `t` stays, because the second comment closes the quote of the first and the blank in the second statement is replaced. Each statement alone has an unclosed quote and keeps its blank, so it would parse, and dblift would have dropped `t`. Refused as in row 102) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| a NUL character anywhere | rejected with `UnsafeStatementSplitError` | the driver hands the text to the engine as a C string: `SELECT 1;` NUL `SELECT 2;` runs only the first statement and reports success, and a NUL inside a literal reads as an unterminated string; the shell does the same |
| shell dot-commands | rejected (§6) | not SQL |
| a BOM in the middle of a script | kept as whitespace | the engine treats it as a blank |
| a dollar-quote tag made of Unicode blanks (`$` U+00A0 `$`) | read as a parameter and blanks, so a `;` inside splits (three pieces where the engine reads two statements) and the pieces fail loudly | before it parses, DuckDB runs one pass over the whole text that replaces its 18 blanks with spaces; the pass skips single-quoted strings and quoted names (a backslash means nothing to it, so an escape string with a backslash before its quote leaves a quote open for it) and line comments, does not know block comments (an apostrophe, a double quote or a dollar tag inside one counts), and stops at the first dollar tag whose closing tag never appears (two dollars, a tag, or a tag made of blanks); from there every blank is kept and is an identifier character for the parser, whether or not any statement is valid; so a `$` inside a word continues the word, blanks included, and a dollar tag opens only at a lexeme boundary (rows 78 to 84); the splitter reproduces this pass (rows 78 to 89) |

## 12. Current implementation

Code: the shared lexical engine. `DuckDBQuirks.lexical_spec()` returns `DUCKDB_SPEC`
(`dblift/db/plugins/duckdb/parser/lexical_spec.py`), whose rules, `DUCKDB_RULES`, are a
`SegmentScriptRules`: the blank characters, the word, number, dollar-quote tag and parameter
patterns, the escape letters, the characters that end a line comment, the command prefix and
the refused character are data. The shared tokenizer (`LexicalTokenizer`) reads a script in one
pass with its string, escape-string, quoted-identifier and nested-comment readers, and
`SegmentScript` (`dblift/core/sql_parser/segment_script.py`) cuts the tokens at each `;` into the
records. `StatementSplitter` (and so `SqlAnalyzer.split_statements`) reaches the engine through the
specification without constructing a parser; `SqlAnalyzer.split_statements_for_analysis` reaches it through
`DuckDBFactsParser.split_for_analysis`, which delegates to it. `DuckDBRegexParser` and `DuckDBFactsParser` are thin delegates: `split()`
returns `Statement` records, `split_statements()` their execution text, `split_for_analysis()`
and `split_for_extraction()` add comment-only segments, and `parse_sql()` honours the refusals.
Statement facts, `DuckDBQuirks.blank_comments` and the provider's row-count rewrite blank
comments through the same engine. There is no DuckDB subclass of the engine and no second
scanner.

The engine reads a script as DuckDB's lexer does. A word is a letter, an
underscore or a non-ASCII character followed by those, digits and `$`, and a `$` inside a word continues the word, so a dollar tag opens only at a lexeme boundary (the 18 non-ASCII blanks continue the word too where DuckDB's pass over the whole text kept them, rows 78 to 89); DuckDB reads a number as digits with single `_` separators, an optional fraction (also one with no integer part, `.5`) and an optional exponent, so
the letters after it start a word (`1a$$x` is the number 1 and the word `a$$x`; `1e5x` is a number and the name x), and the splitter reads it the same way (row 77); a `$$` opens a string
after a number or an operator and never inside a word. A `$` that starts a token opens a dollar-quoted string when a tag
(letters, underscore, non-ASCII, digits, no `$`) and a second `$` follow, and closes it on
the identical tag; otherwise it starts a parameter (`$1`, `$1_0`, `$name`): a `$` followed by digits with single `_` separators, and a name after a `$` is the next word (`$E'a'` is a `$` and an escape string). `E'` and `e'` open an
escape string unless the `E` ends a longer word, and the 18 non-ASCII blanks DuckDB reads (U+00A0, U+2000 to U+200B, U+202F, U+205F, U+2060, U+3000, U+FEFF) are blanks, so a dollar quote or an `E` right after one still opens; inside it a backslash takes the next
character and a doubled quote stays inside. Adjacent string literals separated by a newline,
including a line comment, continue an `E` string's escape mode. A plain string and a quoted identifier end at
the next quote, a doubled quote being two lexemes in a row. A line comment ends at the
first LF or CR, a block comment nests and one that is never closed is sent as it stands,
like a string, an identifier or a dollar-quoted string that is never closed: DuckDB
rejects each of them loudly, so nothing is refused for them. A `;` ends a statement
wherever it stands outside those lexemes. A segment of comments only is not a statement
for execution. The one line rule reads each line where no lexeme is open: a line that
starts with `.` in column 0 while no statement text is pending is a `duckdb` shell
command and is refused with `UnsupportedMetaCommandError`, with the message
`duckdb shell command '.mode' on line 1: the shell runs it and the engine cannot; dblift does not run client commands`
(the command is the first word of the line). A NUL character is refused first, before any other reading, with `UnsafeStatementSplitError` and the message
`a NUL character on line 2: the engine reads the script up to it and silently drops the rest`:
DuckDB reads the script as a C string and would silently drop everything after it. A byte order mark
at the start of the script is dropped; elsewhere it is a blank.

The splitter reproduces DuckDB's pass over the whole text (row 85) before it lexes, in one linear scan that finds
the stretches where the pass keeps blanks: quoted text and names (doubled quotes stay inside, a backslash is
ordinary), line comments to a CR or LF, dollar-quoted strings with the closing tag searched from the opener's last
dollar sign (which may begin the next tag), a failed tag run, and everything from a quote or a tag that is never closed.
A blank in such a stretch continues a word and starts one; a blank elsewhere is a blank. The pass runs only when the script
holds one of the 18 blanks, and the pass reads the last two bytes of the text no further, so a final U+00A0 is kept. That does not change a cut, but the engine then refuses the script (`SELECT 1;` followed by U+00A0: `extract_statements` and `execute` reject it, `syntax error at or near` the NBSP, and run nothing) while the shell exits 0 and runs `SELECT 1`, as dblift does (row 99).
The splitter does not use sqlglot. Measured: the stretches equal the text DuckDB returns after its pass for all 5 229 042 accepted
strings of up to six characters over thirteen (quotes, dollars, dashes, line breaks, blanks) and 300 000 longer random ones.

dblift runs each statement the splitter returns with its own call, so the engine reads that statement afresh and runs the pass over it alone, and the
two passes can disagree about which blanks to keep. A statement can hold a blank that the pass of the whole script kept and the pass of the statement
replaces (`SELECT 1 AS a$$; DROP TABLE t` U+00A0 `CASCADE;`: the engine rejects the script and keeps `t`; the second statement alone is
`DROP TABLE t CASCADE` and drops it), and the reverse: an opener in a comment that closes, for the script, a quote or tag opened by an earlier statement
leaves the blank replaced in the script and kept in the statement alone (`SELECT 1 AS a$t$; /* $t$ */ DROP TABLE IF EXISTS t` U+00A0 `CASCADE;`:
the script drops `t`, the statement alone names another table and does nothing; rows 102 to 104).

For each statement that holds code and a non-ASCII blank, the splitter runs the pass over that statement's text alone, one more linear scan of that
text only, and compares it blank by blank with the pass of the whole script. A blank is kept in the script when it lies in a stretch the pass keeps, or
when it is a two-byte blank that begins one of the last two bytes of the script; it is kept alone by the same two tests on the statement's own text. A
blank whose status differs is refused with `UnsafeStatementSplitError` before anything runs, naming the character (`U+00A0`), its line and its column,
saying that the statement reads differently run alone than in its script, which way it differs ("kept in its script, replaced when run alone" or "kept
when run alone, replaced in its script") and ending with "remove the character" (rows 91 to 97 and 100 to 104). Two edge rules decide a blank at the end
of a text, because the pass never reads the last two bytes: a final U+00A0 of a statement is kept alone, and is no refusal when the statement ends the
script (row 99) or lies in a stretch the script keeps too (row 98); when the script goes on after it (a `;` or more text) the script replaces it and the
statement is refused (rows 90, 100 and 101). A final U+3000 or any three-byte blank is replaced in both readings.

Measured on both shell versions and both driver versions: U+0085, U+2028, U+2029, U+1680 and
U+200C are part of the word before them (`SELECT 1 AS a` followed by one of them and `b` returns a
single column named by all three characters), so a statement that starts with one of them has it in its text; a
vertical tab is a syntax error for DuckDB and is code for the splitter, not a blank.

The text of a statement is the slice of the script between two `;` without the ASCII blanks (space, tab,
line feed, form feed, carriage return) at its ends: comments before and inside it, line breaks, CRs and
non-ASCII blanks stay, and the terminator is not part of it. Its line is the line of its first
character, and its start and end are offsets in the script with a byte order mark counted. The last
statement needs no terminator.

Literal masking in failure messages reads a DuckDB statement through the specification (the engine), so a
dollar-quoted string (`$$…$$`, `$tag$…$tag$`, one holding quotes or line breaks) and an escape string with a
backslash are literals and become `'?'`. A quoted name or a block comment that is never closed, and a dollar-quoted
string that is never closed, run to the end of the text and are masked to the end, as the engine reads them.
A shell command line (a line starting with `.`) is read as SQL text, not refused. Rows 74 and 75 apply to masking as well: where the splitter and DuckDB differ on them, a literal can be left in the clear. Object extraction strips
comments with the DuckDB nesting tokenizer; it did not move with the splitter, and a parser object has no
`lexical_spec` attribute, so extraction is not re-pointed. `strict_tokenizer` has no effect: the engine has no unknown
characters, every character that is no other lexeme is one symbol. A split writes no log record (measured: 0 records for a split before and after the change; building a regex
parser object writes one DEBUG record, before and after).

Cost: cutting a script through the engine takes about 3.5 times as long as the separate scanner it replaced and
about 8 times its peak memory (measured on one host, best of three, twice: a script of 3 240 000 characters took about
2 to 2.5 s against 0.65 s and 212 MB against 26 MB; a file of 66 characters 39 us against 12 us). The worst shapes
measured take 4.5 to 8 times as long (nested comments, or one huge escape string, depending on the host), and large
literals and comments take much longer in proportion (a 1 MiB string literal 0.0004 s before, 0.045 s now; a 1 MiB block comment of
lines 0.006 s before, 0.39 s now), because the old scanner searched for the end of a literal in one call; they stay small in absolute terms. The time still grows in proportion to the script: a four-fold script takes 4.0 to
4.3 times as long, and a test counts the operations per character on twenty-one shapes.

Current implementation gaps, each a place where the splitter and DuckDB differ (rows 74 and 75 record them):
the splitter carries an escape string's mode across blanks on one line, where DuckDB carries it only across a line
break (row 74; the first statement fails for DuckDB either way); and it opens an escape string after any character
that Python counts as a digit, a superscript or a digit of another script, where DuckDB reads a name (row 75). In the analysis view, a segment of only non-ASCII blanks between two `;`
is a statement whose text is that blank (execution drops it). A byte order mark before a dot line on the first
line is refused (§6).
