# SQL statement splitter — lexical specifications

One specification per dialect, in the same shape, read by one splitting
engine. These documents are **normative**: the engine's behaviour for a dialect
is whatever its specification says, the conformance table in each document is
compiled into the dialect's tests, and a change to splitting starts with a
change here.

## What a specification is for

The splitter has one job: cut a migration script into the statements the
server will receive, exactly as the engine's own client would. It never
interprets SQL. Everything it must know about a dialect is lexical and finite:

| Section | Question it answers |
| --- | --- |
| **Status** | Which revision of the current code the facts were taken from, what is verified live, what is not. |
| **1. String literals** | How does a literal open, how does it close, how is a quote escaped inside it? |
| **2. Identifiers** | Which quoting pairs delimit an identifier? |
| **3. Comments** | Which forms are comments; do block comments nest; which comment-looking forms are *not* comments? |
| **4. Terminators** | What ends a statement; where may the alternative terminators appear; what changes the active terminator? |
| **5. Blocks** | Which statement headers open a body that must stay whole, and how does that body end? |
| **6. Client directives** | Which lines belong to a client tool rather than the server, and what does the splitter do with each? |
| **7. Raw blocks** | Which regions are never scanned? |
| **8. Transaction markers** | Which statements does the splitter flag because execution must run them outside a transaction? The flag never changes the split. |
| **9. Engine subclass** | Which rules, if any, cannot be expressed as data and are implemented in a dialect subclass of the engine. |
| **10. Conformance examples** | Input script → expected statements. Compiled into tests. |
| **11. Not handled** | Constructs the engine accepts that this revision of the spec rejects with an error, and why. |
| **12. Current implementation** | Where today's code implements each fact, and which tests pin it. Deleted when the regex splitter of the dialect is gone. |

A fact that is not in one of these sections is not a splitting fact and does
not belong in the spec. Object extraction (what a `CREATE TABLE` declares) is
the extractor's concern and is covered by the model snapshot corpus, not here.

## Rules every specification follows

- **Facts cite the vendor.** A string, comment, terminator or block rule is
  stated as the engine documents it, with the manual section named. Where the
  current code disagrees with the manual the spec says so in a `SUSPECT`
  line; the engine follows the manual once a live run confirms.
- **No silent drop.** Every client directive is one of: *executed* through a
  documented equivalent, *dropped and recorded* as a `kind="directive"` entry
  in the statement list, or *rejected* with an error naming the directive.
  "Stripped" without a record is not an option.
- **No fallback.** An input the rules do not cover raises
  `UnsafeStatementSplitError` with line and column. The spec's *Not handled*
  section is the list of such inputs the authors know about.
- **The terminator is consumed, not returned.** A statement's text excludes
  its terminator; the `Statement` records which terminator ended it so
  execution can reproduce dialect-specific behaviour (Oracle's `/` after a
  PL/SQL block, for example) without re-scanning. This includes the
  terminator of a raw block (`\.` after `COPY … FROM STDIN` data).
- **An empty statement is not a statement.** Nothing but whitespace and
  comments between two terminators (a bare `;`, a `GO` after a `GO`) yields
  no entry; a comment-only segment is dropped. Every dialect follows this
  rule; a spec states it only where the client's behaviour is worth citing.
- **Examples are tests.** Every row of the conformance table is a test case.
  A bug report adds a row before a fix changes the engine.

## Conformance table format

Section 10 of every spec is compiled into tests by
`tests/support/splitter_spec/spec_tables.py` and run by
`tests/unit/core/sql_parser/test_postgresql_spec_conformance.py`. A row that the compiler cannot read is
a build error, so the tables keep this shape:

| Column | Rule |
| --- | --- |
| `#` | a row id, unique within the spec (`1`, `15a`, `R3`) |
| `Script` | exactly one code span (`` `…` `` or ``` `` … `` ``` when the script contains a backtick); `\n` and `\t` inside it are a newline and a tab, `\\` a backslash, `\|` a pipe; nothing else is escaped |
| `Statements returned` | the expected statements, each in its own code span, separated by ` · `; `\n`, `\t` and `\\` inside a span decode as in the Script cell; `` `(empty)` `` means no statement. An expected refusal is a code span naming the exception as the **first** span of the cell: `` `UnsupportedMetaCommandError` ``, `` `UnsafeStatementSplitError` ``, or `` `error` `` for any error; code spans after an error keyword are explanatory (the directive or line it names) and are not compared. An error keyword or `(empty)` anywhere else is a format error. Prose outside code spans is allowed and ignored by the compiler (it explains the row); a directive record is written in prose, never as a code span. |

A row whose statements cell contains **to verify** or **depends on** is
compiled with status `to_verify` and skipped, not run. Comparison is on
normalised statements: surrounding whitespace removed and one trailing
terminator (`;`) removed; everything else is compared verbatim.

Each row runs through `SqlAnalyzer.split_statements`, the entry point `migrate`
uses, in `tests/unit/core/sql_parser/test_postgresql_spec_conformance.py`. A row
the current code gets wrong is listed by id in that module's list of known gaps and
fails strictly (`xfail(strict=True)`): the list can only shrink honestly.

## Dialects

| Spec | Covers | Engine subclass needed |
| --- | --- | --- |
| [postgresql.md](postgresql.md) | PostgreSQL and the compatible family: AlloyDB, Aurora PostgreSQL, Citus, CockroachDB, Neon, Supabase, TimescaleDB, YugabyteDB | dollar-quote tags |

## Verification sources

Every fact in a spec cites the vendor manual. For PostgreSQL: §4.1 Lexical
Structure and the psql reference, quoted (2026-10-10).
