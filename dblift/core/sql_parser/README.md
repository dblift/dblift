# SQL parsing

Every SQL dialect is split by its `LexicalSpec` and read through its statement facts. The
legacy regex, hybrid and SQLGlot parser classes are gone; `SqlParserFactory` and `parser_type`
remain only as deprecated entry points that return the facts parser whatever type is asked.
See the [v5 alpha deprecation inventory](../../../docs/developer-guide/v5-alpha-deprecation-inventory.md)
for what is left and its replacements.

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
from dblift.core.sql_parser.parser_factory import SqlParserFactory

parser = SqlParserFactory("postgresql").get_parser()
execution_units = parser.split_statements("SELECT 1; SELECT 2;")
result = parser.parse_sql("SELECT 1; SELECT 2;")
```

For applications that need original script locations, concrete dialect parsers
expose `split(sql)` records with half-open `source_start` and `source_end`
offsets into the original Python string. These include client terminators
consumed with an execution unit. Analysis projects constituents once per
executed unit and excludes directives and `GO 0` batches. The offsets are
optional for records constructed outside a scanner and preserve the original
indexing across a BOM or CRLF newlines.
