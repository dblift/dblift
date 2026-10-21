# v5 alpha deprecation inventory

This inventory describes the OSS source tree at `13cd540abe7ee0c18844588f4a46d519b8d28882`.
The alpha notices described here preserve parsing, undo generation, and
execution behavior. Internal paths below are not stable Python APIs under
[`docs/semver-policy.md`](../semver-policy.md); documented examples and plugin
hooks still need a migration path before removal.

To list textual references to the inventoried names from the exact base tree,
run this command from the repository root:

```sh
git grep -n -I -w -E \
  -e 'SqlParserFactory|parser_type|strict_tokenizer|SqlAnalyzer|HybridParser|SqlGlotParser' \
  -e 'RegexBasedParser|RegexParser|EnhancedRegexParser|SnowflakeStatementParser|RedshiftRegexParser|_SqlglotBuildersMixin' \
  -e 'sqlglot_unsupported_sql_patterns|sqlglot_unsupported_sql_regex_patterns|sqlglot_dialect|is_comment_only_statement' \
  -e 'UndoScriptGenerator|generate_undo_script|generate_undo_scripts|_reverse_statement_facts|_review_statement_facts|undo_reverses_statement_facts' \
  13cd540abe7ee0c18844588f4a46d519b8d28882 -- dblift tests docs packages README.md pyproject.toml
```

The output includes production, plugin, test, package and documentation lines,
including declarations, imports and comments. It is broader than a runtime
caller list; the tables below identify the active routes.

## Parsing and analysis

| Surface and status | Active callers or contract tests | Replacement and notice boundary |
| --- | --- | --- |
| `SqlParserFactory` in `dblift/core/sql_parser/parser_factory.py`: internal under semver policy, but documented for direct import in `dblift/core/sql_parser/README.md`; `parser_type` selects `hybrid`, `regex`, or `sqlglot`. | `script_analysis.py`, `statement_splitter.py`, `sql_analyzer.py`, `redaction.py`, and `UndoScriptGenerator`; factory routing tests and provider hooks. | For execution splitting use `StatementSplitter(dialect).split()`; for analysis or object identity use the dialect's `statement_facts()` only where that reader is active. Do **not** promise that facts replace `parse_sql()` or model construction. A constructor notice would also warn during canonical execution and analysis, so it is **not** an acceptable alpha warning point without a separate public boundary. Keep dispatch working. |
| `strict_tokenizer` on factory, parser interface and subclasses, `StatementSplitter`, `SqlAnalyzer`, and execution contracts: internal optional argument, present in dialect documentation. | `statement_splitter.py` forwards it to fallback parsers; `SqlAnalyzer` forwards it to splitting; parser implementations accept it. `SqlParserFactory.split_statements()` currently accepts but does not forward it. Oracle, Db2, DuckDB, MySQL, SQL Server and SQLite lexical contracts say it has no effect. | No universal replacement or universal no-op claim: preserve signature and actual dialect behavior until each route is tested. A future notice, if desired, should be on the user-facing argument path, not every parser invocation. |
| `SqlAnalyzer` in `dblift/core/migration/sql/sql_analyzer.py`: internal but directly documented and used by examples. | Migration executor, execution engine, `Migration.parse_sql_statements`, undo generator; many dialect conformance tests. It owns classification, object extraction, validation, execution and analysis splitting. | `StatementSplitter` is a replacement only for execution boundaries; statement facts can replace selected classifications/extractions for activated dialects. Neither is a full replacement for every analyzer method. A constructor notice would warn during canonical migration execution, so do not add one at that shared constructor. |
| `HybridParser` in `dblift/core/sql_parser/hybrid_parser.py`: internal; plugin `parser_class("hybrid")` hook and direct constructor. | PostgreSQL, SQL Server and Oracle quirks still return the class, but `SqlParserFactory` substitutes `StatementFactsParser` for facts-enabled `hybrid` routes. The current built-in default routes produce facts parsers except Snowflake, which produces `SqlGlotParser`; direct use and rich model tests remain. | Direct root-class construction warns once per process. `StatementFactsParser` is a limited statement/object projection and does not build equivalent table, column, constraint, view, index or dependency models. A custom plugin that directly instantiates this class has not been inventoried. |
| `SqlGlotParser` in `dblift/core/sql_parser/sqlglot_parser.py`: internal direct constructor and plugin class result. | `SnowflakeQuirks.parser_class("hybrid"/"sqlglot")` returns the exact class; `SnowflakeLexicalParser` inherits it; `HybridParser` constructs it internally. Oracle, PostgreSQL and SQL Server quirks can also return the exact class for explicit `sqlglot` selection. | Direct root-class construction warns once per process; factory and nested parser construction are explicitly silent. `StatementSplitter` replaces only splitting, statement facts only supported analysis, and live introspection is the named rich-model successor. |
| `RegexBasedParser`, `RegexParser`, `EnhancedRegexParser` in `common/base_parser.py`, `unified_regex_parser.py`, `enhanced_regex_parser.py`: internal inheritance roots with direct constructor use in tests. | Oracle derives from `RegexBasedParser`; Db2, DuckDB, MySQL, PostgreSQL and SQL Server derive from `EnhancedRegexParser`; MariaDB and Redshift inherit those dialect parsers. The provider guide describes the retained `EnhancedRegexParser` bridge. | Each exact root-class direct constructor warns once per process; plugin subclasses stay silent. `LexicalEngine`/`LexicalSpec` covers script boundaries where a plugin provides a spec, but does not replace inherited classification, redaction or model extraction. |
| `RedshiftRegexParser` in `dblift/db/plugins/redshift/parser/redshift_regex_parser.py`: plugin internal, active class. | `RedshiftQuirks.parser_class("regex")` returns it; fallback classification and direct tests use the hook. | Redshift's lexical spec handles boundaries and statement facts handle supported object/DML projections. No proven complete replacement for regex classification or masking. Do not warn at a shared plugin constructor reached by canonical paths. |
| `SnowflakeStatementParser` in `dblift/db/plugins/snowflake/statement_parser.py`: plugin internal, disconnected from default routes. | `SnowflakeQuirks.parser_class` now chooses `SqlGlotParser`/`SnowflakeLexicalParser`; direct safety tests still construct the old class. | `SnowflakeLexicalParser`/lexical spec replaces split behavior, while `SqlGlotParser` handles current AST projection. A direct constructor notice is feasible because no canonical path constructs it; this lot does not modify the plugin or its lexical engine. |
| `_SqlglotBuildersMixin` in `dblift/core/sql_parser/_sqlglot_builders.py`: internal AST-to-SQL-model builder. | `HybridParser` inherits it; model/parser tests exercise table, column, constraint, view and index construction. | No current statement-facts equivalent for the full model output. Inventory only; do not claim it can be replaced by `StatementFacts` or warn from a mixin method reached by ordinary parsing. |
| `sqlglot_unsupported_sql_patterns` (Oracle) and `sqlglot_unsupported_sql_regex_patterns` (MySQL/SQL Server) in quirks: internal plugin hooks. | `HybridParser._contains_oracle_sqlglot_unsupported()` and `_contains_sqlglot_unsupported_shape()` still read them; direct hybrid/parser tests may exercise them, even if default facts routing bypasses some paths. | Treat as reachable until direct-call coverage proves otherwise. No notice on passive class attributes; removal is outside alpha. |
| Legacy `sqlglot_dialect=` and `dialect=` argument forms in `dblift/db/dml_analysis.py`: internal helpers. | `_quirks_for()` already emits `DeprecationWarning` for `sqlglot_dialect=` and routes to `quirks=`; `sql_analyzer.py`, `script_analysis.py`, PostgreSQL parser and tests still call dialect forms. | Migrate callers to plugin `quirks=` where accepted. Some pure SQLGlot grammar uses have no plugin and need separate handling. Keep existing warning; avoid a duplicate alpha notice. |
| `is_comment_only_statement` in `dblift/core/migration/sql/execution_statement.py`: internal path exported from `dblift.core.migration.sql`, documented compatibility helper. | Production execution uses `_comment_only()`/statement records; direct compatibility and boundary tests call the exported helper. | It already warns on every call with `DeprecationWarning`; `StatementSplitter(dialect).split()` is documented for statement filtering. A boolean check of a standalone string without a dialect has no identical drop-in. Keep existing warning and behavior. |

`SqlParserFactory._resolve_parser()` is itself a live bridge: when a plugin has
statement facts, `hybrid` or `regex` can resolve to `StatementFactsParser`.
Consequently, `parser_type="regex"` does not always mean a regex parser, and
deprecating the factory must not be framed as deleting facts routing.

For rich `ParseResult` models, the named successor is **schema
introspection** of a live database. That is a different operation from parsing
SQL text: a caller with only a migration script has no live schema to inspect.
There is no equivalent OSS callable in this checkout for every AST-to-model
builder result. This is a migration gap to track for v5, not a reason to
describe statement facts as a model replacement.

## Automatic undo generation

| Surface and status | Active callers or contract tests | Replacement and notice boundary |
| --- | --- | --- |
| `DBLiftClient.generate_undo_script()` and `generate_undo_scripts()` in `dblift/api/client.py`: stable client methods. | `dblift/api/_client_operations.py` prepares migrations, invokes `UndoScriptGenerator`, emits results/events; `tests/unit/api/test_undo_generation_deprecation.py` checks one caller-attributed warning **per call** and unchanged output. | Handwrite a matching `U*__.sql` or `U*__.py` script. Both methods have warned since 4.10; the alpha message now names 5.0 and handwritten `U*__` scripts. Process-once behavior would change the existing contract. |
| `AsyncDBLiftClient.generate_undo_script()` and `generate_undo_scripts()` in `dblift/api/async_client.py`: stable async methods. | Each warns at the async caller line, then silences the nested synchronous warning with a thread-local gate. Same contract tests cover both. | Same handwritten `U*__` replacement. Preserve exactly one warning for a single async call; do not add a second notice in the operation helper. |
| `UndoScriptGenerator` in `dblift/core/migration/scripting/undo_script_generator/_generator.py`: internal class but directly imported by tests and usable by callers. | Constructed by `_client_operations.py`; `generate_undo_script()`, `generate_undo_script_for_migration()`, `_generate_undo_statements()` call reversers/extractors. `pyproject.toml` quality configuration names its modules. | Direct calls currently have no warning. Its constructor and generation methods are reached from the stable client API, so warning there would duplicate client warnings. Leave this internal path without an alpha notice unless a distinct public boundary is created. |
| `_UndoReversersMixin`, `_UndoExtractorsMixin`, `UndoStatement`, and helpers in `undo_script_generator/`: internal implementation. | `_generator.py` composes both mixins; `_helpers.py` resolves SQLGlot read dialect. Undo and reverser tests exercise them. | No standalone user migration target. Do not warn in each reverser or extractor: one generation can invoke many. Retain while automatic generation exists. |
| `BaseQuirks.undo_reverses_statement_facts`: internal plugin flag, true for SQLite. | `_generator.py` selects `_reverse_statement_facts` versus `_review_statement_facts`; routing tests assert SQLite behavior. | Only controls automatic text reversal. Do not use the flag as evidence that handwritten undo execution is obsolete. No warning on flag reads. |

`dblift undo` in `dblift/cli/_parser_setup.py` and `cli/handlers/undo.py`
executes discovered handwritten `U*__` migrations through
`core/migration/commands/undo_command.py` and `core/migration/state/undo_plan.py`.
The CLI has no automatic undo-generation option. `README.md`,
`docs/user-guide/commands.md`, and Python migration examples describe this
handwritten execution contract. Keep it. The automatic-generation API is
documented in `docs/api-reference/api.md`; the existing 4.10 notice there
already names the loss of prior-state information from SQL text.

## Alpha edit boundary and verification targets

Only an explicit legacy entrypoint that canonical built-in paths do not traverse
should warn. Do not warn in constructors shared with canonical migration, info, or splitting paths; do
not inspect call stacks or change process-wide warning filters to distinguish
callers. No notices belong in the lexical engine, Snowflake routing,
`sqlglot_statement_facts.py`, or per-statement builders/reversers. Existing
client tests require one warning **per call**; changing to process-once would
alter that contract. Canonical `migrate`, `info`, and `split_statements` need
zero `DeprecationWarning` under an error filter. Add focused RED tests for each
chosen public notice, then verify both the notice and silent canonical paths.

Known external consumers may directly import the documented parser factory,
analyzer, or plugin classes, although the semver policy classifies these Python
paths as internal. Their usage is a migration concern, not proof of a stable
public constructor that can safely warn. The public client undo methods have
an explicit warning boundary already. No external-consumer usage counts were
verified in this repository.

| Candidate for focused RED contract | Canonical path that must stay silent | Known external consumer | Gap or exact replacement |
| --- | --- | --- | --- |
| Existing sync/async client `generate_undo_script(s)` warning: assert one caller-attributed warning per call and unchanged generation. | `migrate`, `info`, `undo`, and script splitting do not call these methods. | Stable client method callers. | Hand-authored `U*__` files replace generated text. No duplicate warning or frequency change. |
| Existing `is_comment_only_statement` warning: retain its current caller-attributed behavior. | Internal execution uses `_comment_only()` or statement records, not this compatibility helper. | Direct helper callers, despite its internal semver status. | `StatementSplitter` has a dialect argument and does not exactly replace a standalone boolean call without one. |
| `HybridParser()` direct construction: RED test can assert a role-specific `DeprecationWarning` and unchanged rich `ParseResult`; warning text should point to `StatementSplitter` for script boundaries, facts for supported statement analysis, and introspection for a live schema. | All current built-in default factory routes: facts parser for active readers, `SqlGlotParser` for Snowflake. Assert canonical migrate/info/split silence under an error filter. | Direct constructor callers are evidenced by tests; third-party plugin use is unknown. | Schema introspection is the named successor for rich models, but SQL-file-only consumers have no equivalent current OSS callable. |
| `SqlGlotParser()` direct construction: warn once per process only if an explicit internal construction boundary keeps factory-created Snowflake parsers and `SnowflakeLexicalParser` subclasses silent. | Snowflake's factory returns this exact class; `HybridParser` also constructs it. | Direct constructor callers are evidenced by tests. | Splitting/facts/introspection each replace only their respective projection; script-only rich model gap remains. |
| Direct `RegexBasedParser()`, `RegexParser()`, and `EnhancedRegexParser()` construction: warn once per process per selected root, with unchanged constructor behavior. | Oracle, Db2, DuckDB, MySQL, PostgreSQL, SQL Server, MariaDB and Redshift subclasses must not inherit a warning. | Direct root constructors occur in semantic-base tests; provider subclass authors follow the current developer guide. | Lexical engine replaces split boundaries when a spec exists; inherited object extraction/model projection has no universal drop-in. |
| Direct `SnowflakeStatementParser()` notice, only if plugin editing is authorized in a separate lot. | Current Snowflake factory routing uses `SnowflakeLexicalParser` and `SqlGlotParser`; assert zero warning on those routes. | Direct legacy imports are evidenced by tests. | Lexical parser replaces splitting; richer AST behavior needs separate qualification. |
| No constructor notice for `SqlParserFactory`, `SqlAnalyzer`, Redshift parser, or undo generator in this alpha lot. | They remain in canonical migrate/info/split or client call chains; test with `DeprecationWarning` treated as an error. | Documented factory imports and direct parser use may exist outside this repo; no usage count established. | Internal bridges must migrate before removal. Rich `ParseResult` model users need introspection, which has no fully equivalent OSS callable here. |
