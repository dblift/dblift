# SQL parsing

A dialect's script scanner owns execution boundaries. Its `split(sql)` records
contain the SQL sent to the server, client directives, and any scanner-derived
`analysis_statements`. `split_statements(sql)` projects executable text;
`split_for_analysis(sql)` and `split_for_extraction(sql)` project executed SQL
constituents once, even when a client repeats a batch. A `GO 0` batch contributes
nothing to those projections. A scanner refusal is an error, never a request to
try a different semicolon splitter.

The dialect-specific implementations live under `dblift/db/plugins/*/parser`.
The specification for each script language is in `docs/sql-parsing/`.
`RegexBasedParser`, `RegexParser`, and `EnhancedRegexParser` provide reusable
classification and object extraction. They do not split scripts; dialect
subclasses must implement that method. This is an intentional source contract
change for custom parser subclasses.

`HybridParser` uses the dialect scanner for statement selection and SQLGlot for
per-statement analysis where available. `SqlGlotParser` also delegates script
splitting to the dialect scanner. Neither uses SQLGlot to decide execution
boundaries. Tokenizers retained by some parsers also support quoted comment
stripping or redaction; they do not provide an alternate script split.

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
