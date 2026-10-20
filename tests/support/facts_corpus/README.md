# Statement facts corpus

A snapshot of what the statement-facts reader and the two text-extraction paths
(`SqlParserFactory.extract_objects` and `SqlAnalyzer.extract_objects`) return today, for every
distinct statement the parser tests feed them, per dialect family. It exists so a reader change
shows up as a diff against a frozen baseline and the readers can be compared with the extraction
they are meant to replace. Real inputs only: no generated cases.

## Files

| File | Content |
| --- | --- |
| `inputs.jsonl` | One row per input script: `id` (sha256 of the text, 16 hex), `sql`, `origins` (`file`, `dialects`; no line numbers, so reformatting a test file never changes the corpus). Append-only. Origins are provenance for the reader of a diff; nothing classifies by them. |
| `<family>.jsonl` | One row per distinct statement after the family's `split_for_analysis`, sorted by `sql`: `inputs` (ids), `facts`, `old`, and `facts_newest` / `old_newest` only where the newest sqlglot differs. |
| `VERSIONS.json` | The two recorded sqlglot versions, the size and input count measured at the first recording (write-once: `measure` never rewrites the size and refuses to lower the count), and the number of rows that differ between the arms. |
| `input_ids.txt` | The input ids of the first recording; the corpus test requires all of them to remain, so removing one input and adding another fails. |
| `not_idempotent.json` | Statements that do not split back to themselves (the splitter refuses a lone PL/SQL unit, a client command, or drops a trailing comment). Listed so the idempotence test is exact. |
| `reserved/<family>.txt` | The vendor's reserved words, with source URL, retrieval date, engine version and category in the header. SQLite (the vendor draws no reserved/non-reserved line) and Db2 (page not retrievable in a checkable form) have none. |
| `gated.json` | The families whose differences between extraction and reader must all be classified or explained (see below). |
| `<family>.review.json` | The reasons given for differences that need one, per statement id. |
| `SOURCES.md` | The test files the inputs were harvested from (string constants that start with an SQL verb; docstrings, f-string parts and the text of raise, exception, log and assert-message expressions are skipped). |

Families: `postgresql` (also covers the PostgreSQL derivatives), `mysql` (also MariaDB), `oracle`,
`sqlserver`, `sqlite`, `duckdb`, `redshift`, `snowflake`, `db2`.

## Row fields

* `facts`: the reader's `StatementFacts`, `None` and empty fields dropped, enums by value,
  `objects` as `[name, type, role, schema]` in reader order, `events` sorted. `null` for Db2, which has
  no reader. Families whose plugin has no reader are read through `SqlglotStatementFactsReader`
  for their sqlglot dialect.
* `old.hybrid` / `old.analyzer`: `[type, name, schema]` / `[type, "schema.name"]` lists from the two
  extraction paths, frozen separately because they disagree on a quarter of the statements. A path
  that raises is recorded as `{"raised": ...}`. `old.dml` (DML statements only): `table`
  (`statement_dml_table`), `events` and `updated_columns` (`analyze_dml`), `predicate`
  (`dml_where_predicate`), `full_table` (`is_full_table_dml`), each called for the family's quirks.
  `old` is `null` for SQLite and DuckDB, whose extraction already is the facts reader.
* The parse models are not stored: they can be recomputed from the statement.

## Why JSONL

The golden corpora next to the parser tests are pretty-printed JSON, which suits a few hundred
hand-reviewed cases. Here there are about 14 000 machine-recorded rows; one canonical line per
statement makes a changed fact one diff line next to the statement it belongs to, and keeps a
re-recording byte-stable (`sort_keys`, ASCII, compact separators).

## Keying and growth

Rows are keyed by statement text after splitting, never by script, so a splitter change adds rows
for new statements and removes rows no longer produced instead of altering existing ones. Inputs
are only ever added (a removed test keeps its inputs). The size of the first complete recording
is in `VERSIONS.json`; the corpus test caps the total at 1.2 times that figure.

## Commands

Run from the repository root, in an environment whose `dblift` is this checkout.

```
python -m tests.support.facts_corpus seed            # harvest inputs, rewrite SOURCES.md
python -m tests.support.facts_corpus record floor    # with sqlglot == VERSIONS.json["floor"]
python -m tests.support.facts_corpus record newest   # with sqlglot == VERSIONS.json["newest"]
python -m tests.support.facts_corpus measure         # sizes, counts, not_idempotent.json
```

`record floor` recreates every row; `record newest` must follow it and only adds the
`*_newest` fields. The recorder refuses any other sqlglot version.

## Comparing the extraction with the facts

```
python -m tests.support.facts_corpus diff <family|all> [--report] [--json] [--skeleton]
```

Every row is compared with each frozen extraction path (`hybrid`, `analyzer`) separately and falls
in one class per path (`classes.py`, tried in this order: the first match wins):

| Class | Meaning |
| --- | --- |
| `raised` | a path, the DML helpers or the reader raised |
| `no-reader` | the family has no reader (Db2) |
| `no-old-side` | the family's extraction already is the reader (SQLite, DuckDB): nothing to compare |
| `no-old` | an activated family's row that has no recorded extraction |
| `dml-differs` | target, predicate, events, updated columns or full-table flag differ |
| `role-differs` | a name the statement mentions (schema and name: the same name in two schemas is two objects) has another role in the facts than in the statement: created, dropped, altered (also a truncated table and a DML target), or only referenced (the table under an index, a joined table, a COPY source, a foreign key target) |
| `same` | identities are equal |
| `old-cte-alias` | the extraction took CTE aliases for tables; none is written to |
| `old-keyword` | the extraction took a word the engine reserves, unquoted and not after a dot, for an object; it is not written to and the reader names everything else |
| `type-refined` | same name, the type moves to a strict subtype (`UNKNOWN` to any, `VIEW` to `MATERIALIZED_VIEW`) |
| `quote-decoded` | the extraction cut the name at an escaped quote |
| `case-folded` | the reader keeps an unquoted name as the statement spells it, the extraction holds the engine's folding of it (PostgreSQL, Redshift: lower; Oracle, Snowflake: upper; never MySQL or SQL Server), and the reader is not opaque; never the reverse direction |
| `facts-adds-referenced` | the reader names extra objects that are only read |
| `opaque-safety` | the reader names nothing because a name holds a character the engine may read as part of it |
| `opaque-both-empty` | the reader is opaque and the extraction names nothing |
| `opaque-reader-gap` | the reader is opaque and the extraction named something |
| `facts-fewer` | the reader leaves out an object the extraction named |
| `facts-adds-acted` | the reader names an extra object the statement creates, alters or drops |
| `disagree` | any other difference |

Every mechanical class also needs the statement-level fields equal, and none ever excuses an
object the statement writes to. Names are compared case-exact, after the schema the extraction
assigns to an unqualified name is removed from both sides. Nothing consults which test a statement
was harvested from.

`opaque-reader-gap`, `facts-fewer`, `facts-adds-acted`, `disagree`, `dml-differs`, `role-differs`,
`no-old` and `no-reader` need a reason. Reasons live in `<family>.review.json`, keyed by the statement id
(`<id>` for both paths, `<id>/hybrid` or `<id>/analyzer` for one) with `path`, `class`, `reason`
and, for a reader gap, an `issue` (or `rejected_by`, below). `class` is one string, or `{"floor": ..., "newest": ...}` for a
row whose class depends on the sqlglot release (`same` is allowed there for the arm that agrees,
never on every arm). An entry whose row is gone, whose class is no longer the row's class on the arm
being run (an entry without a key for that arm included), or that explains nothing is stale. A
stale entry fails `diff` and the test module in every family, gated or not.

A reader gap the engine never runs has nothing to fix, so instead of an `issue` its entry may carry
`rejected_by`: a mapping from an engine and its version to the error identifier with which that
engine's grammar rejected the statement (`{"postgresql 16.14": "42601"}`; MySQL answers with
numbers such as `"1064"`). It is a human assertion, and `diff` checks only its shape (a non-empty
mapping of non-empty strings). The evidence, which engines and versions and how the statement was
run, belongs in the pull request that adds the entries.

`gated.json` lists the families whose differences must all be classified or explained: `diff` exits 1
and `tests/unit/core/sql_parser/test_facts_differential.py` fails on a row with neither, in a listed
family. `--report` prints without failing; `--skeleton` adds an empty entry to the review file for
each row that needs one, and on an entry that is stale on the running arm sets only that arm's
class and lists the arm under `unreviewed`. The other arm's class and the reason are kept; the
reason belonged to the class it explained, so the arm does not count as explained until a person
has read the row for its new class and removes the arm from `unreviewed`. `unreviewed` is a list of
`floor` and `newest` only; anything else (a misspelt arm, a string) is stale and fails the run.
When the row's paths no longer share one class, or its new class here is mechanical (`case-folded`,
`old-keyword`, ...), the skeleton drops a string-class entry, reason included, and leaves a per-arm
entry as it is. The other arm's row then shows as unclassified until the entry is written again and
re-reviewed; git keeps the text of a dropped reason.

The list of gated families is empty until a family's differences are explained; a family
joins it when its plugin reads statements through the reader.

## Once a family reads through the reader

The extraction of such a family can no longer be recomputed, so it is frozen:
`record floor` and `record newest` refuse to run while a family is in that state. `record <arm>
--frozen` reads the facts again and carries every row's extraction over; a row whose statement text
changed only by outer whitespace or one trailing terminator inherits the extraction of the row it
replaces, any other new row gets `old: null` and the class `no-old`.
