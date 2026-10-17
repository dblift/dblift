# Statement facts corpus

A snapshot of what the statement-facts reader and the two text-extraction paths
(`SqlParserFactory.extract_objects` and `SqlAnalyzer.extract_objects`) return today, for every
distinct statement the parser tests feed them, per dialect family. It exists so a reader change
shows up as a diff against a frozen baseline and the readers can be compared with the extraction
they are meant to replace. Real inputs only: no generated cases.

## Files

| File | Content |
| --- | --- |
| `inputs.jsonl` | One row per input script: `id` (sha256 of the text, 16 hex), `sql`, `origins` (`file`, `line`, `dialects`). Append-only. Origins are provenance for the reader of a diff; nothing classifies by them. |
| `<family>.jsonl` | One row per distinct statement after the family's `split_for_analysis`, sorted by `sql`: `inputs` (ids), `facts`, `old`, and `facts_newest` / `old_newest` only where the newest sqlglot differs. |
| `VERSIONS.json` | The two recorded sqlglot versions, the size and input count measured at the first recording, and the number of rows that differ between the arms. |
| `not_idempotent.json` | Statements that do not split back to themselves (the splitter refuses a lone PL/SQL unit, a client command, or drops a trailing comment). Listed so the idempotence test is exact. |
| `reserved/<family>.txt` | The vendor's reserved words, with source URL, retrieval date, engine version and category in the header. SQLite (the vendor draws no reserved/non-reserved line) and Db2 (page not retrievable in a checkable form) have none. |
| `SOURCES.md` | The test files the inputs were harvested from. |

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
