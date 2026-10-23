# Original sources of the corpus inputs

This is the source inventory at the corpus freeze. Some source tests have since
been removed; their SQL remains in `inputs.jsonl` and is exercised by
`tests/unit/core/migration/sql/test_retained_script_analysis_inputs.py`.

Test files calling `parse_sql(` or `extract_objects(`; their SQL string constants
(under 4000 characters, starting with an SQL verb; docstrings, f-string parts and the text
of raise, exception, log, assert-message and `in` / `not in` expressions are skipped) are the inputs,
plus the statements of the three hand-written facts corpora listed last.
Regenerate with `python -m tests.support.facts_corpus seed`.

- `tests/unit/core/migration/sql/test_authoritative_consumer_contract.py`
- `tests/unit/core/migration/sql/test_sql_analyzer_bracket_escape.py`
- `tests/unit/core/migration/sql/test_sql_analyzer_extended.py`
- `tests/unit/core/migration/sql/test_sql_analyzer_object_recognition.py`
- `tests/unit/core/migration/sql/test_statement_splitter_boundary.py`
- `tests/unit/core/migration/test_undo_script_generator.py`
- `tests/unit/core/sql_parser/oracle/test_object_extractor.py`
- `tests/unit/core/sql_parser/oracle/test_oracle_parser_conformance.py`
- `tests/unit/core/sql_parser/test_base_parser.py`
- `tests/unit/core/sql_parser/test_collation_and_linear_partitioning.py`
- `tests/unit/core/sql_parser/test_db2_index_object_extraction_regressions.py`
- `tests/unit/core/sql_parser/test_db2_parser.py`
- `tests/unit/core/sql_parser/test_db2_regex_parser_extended.py`
- `tests/unit/core/sql_parser/test_duckdb_shared_lexical_path.py`
- `tests/unit/core/sql_parser/test_duckdb_statement_facts_activation.py`
- `tests/unit/core/sql_parser/test_enhanced_regex_parser.py`
- `tests/unit/core/sql_parser/test_extraction_nested_block_comments.py`
- `tests/unit/core/sql_parser/test_fallback_quoted_identifier_case.py`
- `tests/unit/core/sql_parser/test_hybrid_parse_sql_refusals.py`
- `tests/unit/core/sql_parser/test_hybrid_parser.py`
- `tests/unit/core/sql_parser/test_hybrid_parser_extended.py`
- `tests/unit/core/sql_parser/test_hybrid_parser_extended2.py`
- `tests/unit/core/sql_parser/test_hybrid_parser_extraction_of_split_statements.py`
- `tests/unit/core/sql_parser/test_hybrid_parser_refusals_across_dialects.py`
- `tests/unit/core/sql_parser/test_index_method_and_kind.py`
- `tests/unit/core/sql_parser/test_legacy_facts_baseline.py`
- `tests/unit/core/sql_parser/test_mysql_index_object_extraction_regressions.py`
- `tests/unit/core/sql_parser/test_mysql_parser.py`
- `tests/unit/core/sql_parser/test_mysql_regex_parser_extended.py`
- `tests/unit/core/sql_parser/test_nested_block_comments.py`
- `tests/unit/core/sql_parser/test_oracle_parser.py`
- `tests/unit/core/sql_parser/test_oracle_parser_empty_column_guard.py`
- `tests/unit/core/sql_parser/test_parser_factory.py`
- `tests/unit/core/sql_parser/test_partition_details.py`
- `tests/unit/core/sql_parser/test_partition_scheme_support.py`
- `tests/unit/core/sql_parser/test_postgresql_object_extraction_regressions.py`
- `tests/unit/core/sql_parser/test_postgresql_parser.py`
- `tests/unit/core/sql_parser/test_postgresql_regex_parser_extended.py`
- `tests/unit/core/sql_parser/test_scanner_authoritative_views.py`
- `tests/unit/core/sql_parser/test_shared_lexical_engine.py`
- `tests/unit/core/sql_parser/test_sqlglot_builder_losses.py`
- `tests/unit/core/sql_parser/test_sqlglot_parser.py`
- `tests/unit/core/sql_parser/test_sqlite_extractor_facts_corpus.py`
- `tests/unit/core/sql_parser/test_sqlite_statement_facts_contract.py`
- `tests/unit/core/sql_parser/test_sqlite_statement_facts_opaque.py`
- `tests/unit/core/sql_parser/test_sqlite_statement_facts_regressions.py`
- `tests/unit/core/sql_parser/test_sqlserver_object_extraction_regressions.py`
- `tests/unit/core/sql_parser/test_sqlserver_regex_parser_extended.py`
- `tests/unit/core/sql_parser/test_statement_facts_unicode_names.py`
- `tests/unit/core/sql_parser/test_unified_regex_parser.py`
- `tests/unit/core/sql_parser/test_unread_names.py`
- `tests/unit/db/plugins/db2/test_extraction_keeps_statements.py`
- `tests/unit/db/plugins/db2/test_extraction_view_unchanged.py`
- `tests/unit/db/plugins/duckdb/test_duckdb_provider.py`
- `tests/unit/db/plugins/duckdb/test_duckdb_units.py`
- `tests/unit/db/plugins/duckdb/test_extraction_keeps_statements.py`
- `tests/unit/db/plugins/duckdb/test_extraction_view_unchanged.py`
- `tests/unit/db/plugins/mysql/test_extraction_keeps_statements.py`
- `tests/unit/db/plugins/mysql/test_extraction_view_unchanged.py`
- `tests/unit/db/plugins/oracle/test_parser_replacement_regressions.py`
- `tests/unit/db/plugins/postgresql/test_parser_replacement_regressions.py`
- `tests/unit/db/plugins/snowflake/test_snowflake_plugin.py`
- `tests/unit/db/plugins/sqlite/test_extraction_keeps_statements.py`
- `tests/unit/db/plugins/sqlserver/test_authoritative_views.py`
- `tests/unit/db/plugins/sqlserver/test_extraction_keeps_statements.py`
- `tests/unit/db/plugins/sqlserver/test_extraction_view_unchanged.py`
- `tests/unit/lightweight_core/test_analysis_preflight.py`
- `tests/unit/lightweight_core/test_execution_without_analysis.py`
- `tests/unit/sqlite/test_sqlite_parser.py`

Hand-written corpora:

- `tests/unit/core/sql_parser/duckdb_statement_facts_corpus.json`
- `tests/unit/core/sql_parser/sqlite_extractor_facts_corpus.json`
- `tests/unit/core/sql_parser/legacy_facts_baseline.json`
