# SQL parsing

Every SQL dialect is split by its `LexicalSpec` and read through its statement facts
(`StatementSplitter` to split, `read_statement_facts` or the plugin's `quirks.statement_facts` to
read one statement). The regex, hybrid and SQLGlot parser classes, `SqlParserFactory`,
`SqlAnalyzer` and `parser_type` are gone. See the
[v5 alpha deprecation inventory](../../../docs/developer-guide/v5-alpha-deprecation-inventory.md)
for the history.

A dialect's script scanner owns execution boundaries. Its `split(sql)` records
contain the SQL sent to the server, client directives, and any scanner-derived
`analysis_statements`. `split_statements(sql)` projects executable text;
`split_for_analysis(sql)` and `split_for_extraction(sql)` project executed SQL
constituents once, even when a client repeats a batch. A `GO 0` batch contributes
nothing to those projections. A scanner refusal is an error, never a request to
try a different semicolon splitter.

The dialect-specific lexical specs live under `dblift/db/plugins/*/parser`. The specification
for each script language is in `docs/sql-parsing/`. `StatementFactsParser` splits with the
spec's engine and reads each statement with the plugin's facts reader; it is not a second
scanner. Tokenizers retained by some plugins support literal masking only; they do not provide
an alternate script split.

In a `Statement` record, `analysis_statements=None` means its execution text
is one analyzable statement. An empty tuple means it contributes none. A
nonempty tuple lists the constituents found by the same dialect scan.

```python
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.provider_registry import ProviderRegistry

splitter = StatementSplitter("postgresql")
execution_units = splitter.split_statements("SELECT 1; SELECT 2;")
facts = ProviderRegistry.get_quirks("postgresql").statement_facts("SELECT 1")
```

For applications that need original script locations, `StatementSplitter.split(sql)`
returns records with half-open `source_start` and `source_end`
offsets into the original Python string. These include client terminators
consumed with an execution unit. Analysis projects constituents once per
executed unit and excludes directives and `GO 0` batches. The offsets are
optional for records constructed outside a scanner and preserve the original
indexing across a BOM or CRLF newlines.
