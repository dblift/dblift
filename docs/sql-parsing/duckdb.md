# DuckDB — lexical specification for statement splitting

## Status

| Item | Value |
| --- | --- |
| Covers | DuckDB 1.x scripts run through the Python `duckdb` driver (the path dblift executes through) and written for the `duckdb` command-line shell. Measured: shell v1.5.6 (Variegata, Homebrew) and v1.5.5 (Variegata, the `duckdb-cli` wheel) and the Python driver 1.5.5 and 1.5.6 (`duckdb.connect()`, `execute`, `duckdb.extract_statements`) with `duckdb_engine` 0.17.0 on SQLAlchemy 2.0.52 |
| Code facts taken from | the shared lexical engine with the DuckDB specification; §12 describes it. The DuckDB part of the conformance run is 85 rows: 82 passes and the three known gaps 74, 75 and 85 (expected failures) |
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
one still opens (rows 72, 73), while any other non-ASCII character is part of the word before it. The engine reaches these blanks through a fallback of its parser, which is
stricter than its main path: a lone no-break space after the last statement is a syntax error, and a script that holds a
word with `$$` and a Unicode blank where a keyword is expected (`SELECT 1 AS a$$; SELECT` U+00A0 `2;`) is rejected as a whole, while a blank inside a word that holds a `$` is part of that word (rows 78 to 85); a segment of one such blank
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
| 85 | `SELECT 1 AS a$$, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;` | `SELECT 1 AS a$$, 2 AS e\u00a0$t$x` · `DROP TABLE t` · `SELECT 3` (measured: once a dollar sign that is not followed by a digit has appeared earlier in the text, outside a quoted name or string, even in an earlier statement or a comment, every later non-ASCII blank continues the word it follows; known gap, unsafe direction: the splitter lets the blank after the second name end the word, opens a dollar-quoted string at the tag and sends the three statements as one, which the driver then runs one after another) |

## 11. Not handled

| Construct | Behaviour | Why |
| --- | --- | --- |
| a NUL character anywhere | rejected with `UnsafeStatementSplitError` | the driver hands the text to the engine as a C string: `SELECT 1;` NUL `SELECT 2;` runs only the first statement and reports success, and a NUL inside a literal reads as an unterminated string; the shell does the same |
| shell dot-commands | rejected (§6) | not SQL |
| a BOM in the middle of a script | kept as whitespace | the engine treats it as a blank |
| a dollar-quote tag made of Unicode blanks (`$` U+00A0 `$`) | read as a parameter and blanks, so a `;` inside splits (three pieces where the engine reads two statements) and the pieces fail loudly | the engine parses first with those code points as identifier characters and reads the tag; it falls back to blanks only when that fails; the same reading makes a `$` inside a word continue the word, blanks included, so a dollar tag opens only at a lexeme boundary (rows 78 to 85) |

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
underscore or a non-ASCII character followed by those, digits and `$`, and a `$` inside a word continues the word, so a dollar tag opens only at a lexeme boundary (from the first `$` not followed by a digit the 18 non-ASCII blanks continue the word too, rows 78 to 84; DuckDB does so for a `$` anywhere earlier in the text, row 85); DuckDB reads a number as digits with single `_` separators, an optional fraction (also one with no integer part, `.5`) and an optional exponent, so
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
4.3 times as long, and a test counts the operations per character on fourteen shapes.

Current implementation gaps, each a place where the splitter and DuckDB differ (rows 74, 75 and 85 record them):
the splitter carries an escape string's mode across blanks on one line, where DuckDB carries it only across a line
break (row 74; the first statement fails for DuckDB either way); and it opens an escape string after any character
that Python counts as a digit, a superscript or a digit of another script, where DuckDB reads a name (row 75); and it ends a word at a non-ASCII blank unless the same word already holds a `$` not followed by a digit, where DuckDB keeps every later blank of the text as a word character once such a `$` has appeared before it, even in an earlier statement or a comment (row 85, the unsafe direction: a dollar tag after the blank opens a string in the splitter and hides later statements that the driver runs). In the analysis view, a segment of only non-ASCII blanks between two `;`
is a statement whose text is that blank (execution drops it). A byte order mark before a dot line on the first
line is refused (§6).
