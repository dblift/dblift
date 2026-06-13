"""Extended unit tests for vendor-specific introspection query files.

Targets uncovered paths in:
- db/introspection/databases/db2/db2_queries.py          (85 stmts, 39%)
- db/introspection/databases/mysql/mysql_queries.py      (68 stmts, 41%)
- db/introspection/databases/oracle/oracle_queries.py    (99 stmts, 37%)
- db/introspection/databases/sqlite/sqlite_queries.py    (86 stmts, 42%)
- db/introspection/databases/sqlserver/sqlserver_queries.py (83 stmts, 46%)

All methods return (sql_string, params_list) tuples — zero mocking needed.
"""

import unittest

from db.plugins.db2.introspection.db2_queries import DB2MetadataQueries
from db.plugins.mysql.introspection.mysql_queries import MySQLMetadataQueries
from db.plugins.oracle.introspection.oracle_queries import OracleMetadataQueries
from db.plugins.sqlite.introspection.sqlite_queries import SQLiteMetadataQueries
from db.plugins.sqlserver.introspection.sqlserver_queries import SQLServerMetadataQueries

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_query_tuple(tc, result, expected_params):
    """Helper: ensure result is (non-empty-str, expected_params)."""
    sql, params = result
    tc.assertIsInstance(sql, str)
    tc.assertGreater(len(sql.strip()), 0, "SQL string should not be empty")
    tc.assertEqual(params, expected_params)


def _assert_keywords(tc, sql, *keywords):
    """Check that each keyword appears in the SQL (case-insensitive)."""
    sql_upper = sql.upper()
    for kw in keywords:
        tc.assertIn(kw.upper(), sql_upper, f"Expected keyword '{kw}' in SQL:\n{sql}")


# ---------------------------------------------------------------------------
# DB2MetadataQueries
# ---------------------------------------------------------------------------


class TestDB2MetadataQueries(unittest.TestCase):

    def setUp(self):
        self.q = DB2MetadataQueries()

    # --- check constraints ---

    def test_get_check_constraints_query_returns_tuple(self):
        sql, params = self.q.get_check_constraints_query("MYSCHEMA", "MYTABLE")
        self.assertEqual(params, ["MYSCHEMA", "MYTABLE"])
        _assert_keywords(self, sql, "syscat.checks", "tabschema", "tabname")

    def test_get_check_constraints_filters_user_defined(self):
        sql, _ = self.q.get_check_constraints_query("S", "T")
        _assert_keywords(self, sql, "type = 'C'")

    # --- unique constraints ---

    def test_get_unique_constraints_query(self):
        sql, params = self.q.get_unique_constraints_query("S", "T")
        self.assertEqual(params, ["S", "T"])
        _assert_keywords(self, sql, "syscat.tabconst", "syscat.keycoluse", "type = 'U'")

    # --- sequences ---

    def test_get_sequences_query(self):
        sql, params = self.q.get_sequences_query("MYSCHEMA")
        self.assertEqual(params, ["MYSCHEMA"])
        _assert_keywords(self, sql, "syscat.sequences", "seqschema")

    # --- views ---

    def test_get_views_query(self):
        sql, params = self.q.get_views_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "syscat.views", "viewschema")

    def test_get_view_definition_query(self):
        sql, params = self.q.get_view_definition_query("S", "V")
        self.assertEqual(params, ["S", "V"])
        _assert_keywords(self, sql, "syscat.views", "viewname")

    # --- indexes ---

    def test_get_indexes_query(self):
        sql, params = self.q.get_indexes_query("S", "T")
        self.assertEqual(params, ["S", "T"])
        _assert_keywords(self, sql, "syscat.indexes", "syscat.indexcoluse", "tabschema", "tabname")

    # --- procedures / functions ---

    def test_get_procedures_query(self):
        sql, params = self.q.get_procedures_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "syscat.procedures")

    def test_get_functions_query(self):
        sql, params = self.q.get_functions_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "syscat.functions")

    # --- packages ---

    def test_get_packages_query(self):
        sql, params = self.q.get_packages_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "syscat.modules", "moduleschema")

    # --- triggers with table ---

    def test_get_triggers_query_with_table(self):
        sql, params = self.q.get_triggers_query("S", "T")
        self.assertEqual(params, ["S", "T"])
        _assert_keywords(self, sql, "syscat.triggers", "tabschema", "tabname")

    def test_get_triggers_query_without_table(self):
        sql, params = self.q.get_triggers_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "syscat.triggers", "tabschema")
        # Should NOT have tabname filter (only schema-level)
        self.assertNotIn("AND tabname = ?", sql)

    # --- computed / identity columns ---

    def test_get_computed_columns_query(self):
        sql, params = self.q.get_computed_columns_query("S", "T")
        self.assertEqual(params, ["S", "S", "T", "T"])
        _assert_keywords(self, sql, "syscat.columns", "generated = 'A'")

    def test_get_identity_columns_query(self):
        sql, params = self.q.get_identity_columns_query("S", "T")
        self.assertEqual(params, ["S", "T"])
        _assert_keywords(self, sql, "syscat.columns", "identity = 'Y'")

    # --- partitions ---

    def test_get_table_partitions_query(self):
        sql, params = self.q.get_table_partitions_query("S", "T")
        self.assertEqual(params, ["S", "T"])
        _assert_keywords(self, sql, "syscat.datapartitions")

    # --- materialized views ---

    def test_get_materialized_views_query(self):
        sql, params = self.q.get_materialized_views_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "syscat.tables", "type = 'M'")

    # --- table properties ---

    def test_get_table_properties_query(self):
        sql, params = self.q.get_table_properties_query("S", "T")
        self.assertEqual(params, ["S", "T"])
        _assert_keywords(self, sql, "syscat.tables", "tabschema", "tabname")

    # --- user defined types ---

    def test_get_user_defined_types_query(self):
        sql, params = self.q.get_user_defined_types_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "SYSCAT.TYPES", "TYPESCHEMA")

    def test_get_composite_type_attributes_query(self):
        sql, params = self.q.get_composite_type_attributes_query("S", "MY_TYPE")
        self.assertEqual(params, ["S", "MY_TYPE"])
        _assert_keywords(self, sql, "SYSCAT.ATTRIBUTES", "TYPESCHEMA", "TYPENAME")

    # --- synonyms ---

    def test_get_synonyms_query(self):
        sql, params = self.q.get_synonyms_query("S")
        self.assertEqual(params, ["S"])
        _assert_keywords(self, sql, "SYSCAT.TABLES", "TYPE = 'A'")

    # --- partition scheme ---

    def test_get_partition_scheme_query_returns_empty(self):
        """DB2 disables partition scheme query."""
        sql, params = self.q.get_partition_scheme_query("S", "T")
        self.assertEqual(sql, "")
        self.assertEqual(params, [])

    # --- supports_* methods ---

    def test_supports_flags(self):
        self.assertTrue(self.q.supports_check_constraints())
        self.assertTrue(self.q.supports_sequences())
        self.assertTrue(self.q.supports_views())
        self.assertTrue(self.q.supports_triggers())
        self.assertTrue(self.q.supports_computed_columns())
        self.assertTrue(self.q.supports_partitions())
        self.assertTrue(self.q.supports_materialized_views())
        self.assertTrue(self.q.supports_procedures())
        self.assertTrue(self.q.supports_functions())
        self.assertTrue(self.q.supports_synonyms())
        self.assertFalse(self.q.supports_user_defined_types())


# ---------------------------------------------------------------------------
# MySQLMetadataQueries
# ---------------------------------------------------------------------------


class TestMySQLMetadataQueries(unittest.TestCase):

    def setUp(self):
        self.q = MySQLMetadataQueries()

    def test_get_check_constraints_query(self):
        sql, params = self.q.get_check_constraints_query("mydb", "users")
        self.assertEqual(params, ["mydb", "users"])
        _assert_keywords(
            self,
            sql,
            "information_schema.check_constraints",
            "information_schema.table_constraints",
        )

    def test_get_sequences_query(self):
        sql, params = self.q.get_sequences_query("mydb")
        self.assertEqual(params, ["mydb"])
        _assert_keywords(self, sql, "information_schema.SEQUENCES")

    def test_get_table_properties_query(self):
        sql, params = self.q.get_table_properties_query("mydb", "orders")
        self.assertEqual(params, ["mydb", "orders"])
        _assert_keywords(self, sql, "information_schema.TABLES", "ENGINE", "ROW_FORMAT")

    def test_get_views_query(self):
        sql, params = self.q.get_views_query("mydb")
        self.assertEqual(params, ["mydb"])
        _assert_keywords(self, sql, "information_schema.views", "table_schema")

    def test_get_view_definition_query(self):
        sql, params = self.q.get_view_definition_query("mydb", "v1")
        self.assertEqual(params, ["mydb", "v1"])
        _assert_keywords(self, sql, "information_schema.views")

    def test_get_indexes_query(self):
        sql, params = self.q.get_indexes_query("mydb", "orders")
        self.assertEqual(params, ["mydb", "orders"])
        _assert_keywords(self, sql, "information_schema.STATISTICS", "TABLE_SCHEMA", "TABLE_NAME")

    def test_get_procedures_query(self):
        sql, params = self.q.get_procedures_query("mydb")
        self.assertEqual(params, ["mydb"])
        _assert_keywords(self, sql, "information_schema.ROUTINES", "PROCEDURE")

    def test_get_functions_query(self):
        sql, params = self.q.get_functions_query("mydb")
        self.assertEqual(params, ["mydb"])
        _assert_keywords(self, sql, "information_schema.ROUTINES", "FUNCTION")

    def test_get_parameters_query(self):
        sql, params = self.q.get_parameters_query("mydb", "sp_test")
        self.assertEqual(params, ["mydb", "sp_test"])
        _assert_keywords(
            self, sql, "information_schema.PARAMETERS", "SPECIFIC_SCHEMA", "SPECIFIC_NAME"
        )

    def test_get_parameters_query_excludes_return_row(self):
        """PARAMETER_MODE IS NOT NULL filter is present to exclude the return row."""
        sql, _ = self.q.get_parameters_query("mydb", "fn1")
        _assert_keywords(self, sql, "PARAMETER_MODE IS NOT NULL")

    def test_get_triggers_query_with_table(self):
        sql, params = self.q.get_triggers_query("mydb", "orders")
        self.assertEqual(params, ["mydb", "orders"])
        _assert_keywords(
            self, sql, "information_schema.TRIGGERS", "TRIGGER_SCHEMA", "EVENT_OBJECT_TABLE"
        )

    def test_get_triggers_query_without_table(self):
        sql, params = self.q.get_triggers_query("mydb")
        self.assertEqual(params, ["mydb"])
        _assert_keywords(self, sql, "information_schema.TRIGGERS")
        self.assertNotIn("EVENT_OBJECT_TABLE = ?", sql)

    def test_get_events_query(self):
        sql, params = self.q.get_events_query("mydb")
        self.assertEqual(params, ["mydb"])
        _assert_keywords(self, sql, "information_schema.EVENTS", "EVENT_SCHEMA")

    def test_get_computed_columns_query(self):
        sql, params = self.q.get_computed_columns_query("mydb", "t")
        self.assertEqual(params, ["mydb", "t"])
        _assert_keywords(self, sql, "information_schema.COLUMNS", "GENERATION_EXPRESSION")

    def test_get_identity_columns_query(self):
        sql, params = self.q.get_identity_columns_query("mydb", "t")
        self.assertEqual(params, ["mydb", "t"])
        _assert_keywords(self, sql, "information_schema.COLUMNS", "auto_increment")

    def test_get_table_partitions_query(self):
        sql, params = self.q.get_table_partitions_query("mydb", "t")
        self.assertEqual(params, ["mydb", "t"])
        _assert_keywords(self, sql, "information_schema.PARTITIONS")

    def test_get_partition_scheme_query(self):
        sql, params = self.q.get_partition_scheme_query("mydb", "t")
        self.assertEqual(params, ["mydb", "t"])
        _assert_keywords(self, sql, "information_schema.partitions", "partition_method")

    def test_supports_flags(self):
        self.assertTrue(self.q.supports_check_constraints())
        self.assertFalse(self.q.supports_sequences())  # MySQL default
        self.assertTrue(self.q.supports_views())
        self.assertTrue(self.q.supports_triggers())
        self.assertTrue(self.q.supports_computed_columns())
        self.assertTrue(self.q.supports_partitions())
        self.assertTrue(self.q.supports_procedures())
        self.assertTrue(self.q.supports_functions())


# ---------------------------------------------------------------------------
# OracleMetadataQueries
# ---------------------------------------------------------------------------


class TestOracleMetadataQueries(unittest.TestCase):

    def setUp(self):
        self.q = OracleMetadataQueries()

    def test_get_check_constraints_query(self):
        sql, params = self.q.get_check_constraints_query("OWNER", "MY_TABLE")
        self.assertEqual(params, ["OWNER", "MY_TABLE"])
        _assert_keywords(self, sql, "all_constraints", "constraint_type = 'C'")

    def test_get_check_constraints_upper_filtering(self):
        """Oracle uses UPPER() on both sides for case-insensitive match."""
        sql, _ = self.q.get_check_constraints_query("owner", "table")
        _assert_keywords(self, sql, "UPPER")

    def test_get_sequences_query(self):
        sql, params = self.q.get_sequences_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "ALL_SEQUENCES", "sequence_owner")

    def test_get_views_query(self):
        sql, params = self.q.get_views_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_views", "owner", "BIN$")

    def test_get_view_definition_query(self):
        sql, params = self.q.get_view_definition_query("OWNER", "MY_VIEW")
        self.assertEqual(params, ["OWNER", "MY_VIEW"])
        _assert_keywords(self, sql, "all_views", "view_definition")

    def test_get_indexes_query(self):
        sql, params = self.q.get_indexes_query("OWNER", "MY_TABLE")
        self.assertEqual(params, ["OWNER", "MY_TABLE"])
        _assert_keywords(self, sql, "all_indexes", "all_ind_columns", "table_owner", "table_name")

    def test_get_triggers_query_with_table(self):
        sql, params = self.q.get_triggers_query("OWNER", "MY_TABLE")
        self.assertEqual(params, ["OWNER", "MY_TABLE"])
        _assert_keywords(self, sql, "all_triggers", "owner", "table_name")

    def test_get_triggers_query_without_table(self):
        sql, params = self.q.get_triggers_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_triggers", "UPPER(owner)")

    def test_get_computed_columns_query(self):
        sql, params = self.q.get_computed_columns_query("OWNER", "T")
        self.assertEqual(params, ["OWNER", "T"])
        _assert_keywords(self, sql, "all_tab_cols", "virtual_column = 'YES'")

    def test_get_identity_columns_query(self):
        sql, params = self.q.get_identity_columns_query("OWNER", "T")
        self.assertEqual(params, ["OWNER", "T"])
        _assert_keywords(self, sql, "all_tab_identity_cols")

    def test_get_table_partitions_query(self):
        sql, params = self.q.get_table_partitions_query("OWNER", "T")
        # 4 params: schema, table, schema, table
        self.assertEqual(params, ["OWNER", "T", "OWNER", "T"])
        _assert_keywords(self, sql, "all_tab_partitions")

    def test_get_procedures_query(self):
        sql, params = self.q.get_procedures_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_objects", "object_type = 'PROCEDURE'")

    def test_get_functions_query(self):
        sql, params = self.q.get_functions_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_objects", "object_type = 'FUNCTION'")

    def test_get_function_arguments_query(self):
        sql, params = self.q.get_function_arguments_query("OWNER", "MY_FN")
        self.assertEqual(params, ["OWNER", "MY_FN"])
        _assert_keywords(self, sql, "all_arguments")

    def test_get_procedure_arguments_query(self):
        sql, params = self.q.get_procedure_arguments_query("OWNER", "MY_PROC")
        self.assertEqual(params, ["OWNER", "MY_PROC"])
        _assert_keywords(self, sql, "all_arguments", "position > 0")

    def test_get_function_definition_query(self):
        sql, params = self.q.get_function_definition_query("OWNER", "MY_FN")
        self.assertEqual(params, ["OWNER", "MY_FN"])
        _assert_keywords(self, sql, "all_source", "type = 'FUNCTION'")

    def test_get_packages_query(self):
        sql, params = self.q.get_packages_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_objects", "PACKAGE")

    def test_get_user_defined_types_query(self):
        sql, params = self.q.get_user_defined_types_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_types", "typecode")

    def test_get_composite_type_attributes_query(self):
        sql, params = self.q.get_composite_type_attributes_query("OWNER", "MY_TYPE")
        self.assertEqual(params, ["OWNER", "MY_TYPE"])
        _assert_keywords(self, sql, "all_type_attrs")

    def test_get_materialized_views_query(self):
        sql, params = self.q.get_materialized_views_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_mviews", "mview_name")

    def test_get_synonyms_query(self):
        sql, params = self.q.get_synonyms_query("OWNER")
        self.assertEqual(params, ["OWNER"])
        _assert_keywords(self, sql, "all_synonyms", "synonym_name")

    def test_get_database_links(self):
        sql, params = self.q.get_database_links("OWNER")
        self.assertEqual(params, [])
        _assert_keywords(self, sql, "all_db_links")

    def test_get_table_properties_query(self):
        sql, params = self.q.get_table_properties_query("OWNER", "MY_TABLE")
        self.assertEqual(params, ["OWNER", "MY_TABLE"])
        _assert_keywords(self, sql, "all_tables")

    def test_get_table_properties_strips_quotes(self):
        """Quotes are stripped before passing to the query."""
        sql, params = self.q.get_table_properties_query('"OWNER"', '"MY_TABLE"')
        self.assertEqual(params, ["OWNER", "MY_TABLE"])

    def test_get_partition_scheme_query(self):
        sql, params = self.q.get_partition_scheme_query("OWNER", "T")
        self.assertEqual(params, ["OWNER", "T"])
        _assert_keywords(self, sql, "all_part_tables", "partitioning_type")

    def test_supports_flags(self):
        self.assertTrue(self.q.supports_check_constraints())
        self.assertTrue(self.q.supports_sequences())
        self.assertTrue(self.q.supports_views())
        self.assertTrue(self.q.supports_triggers())
        self.assertTrue(self.q.supports_computed_columns())
        self.assertTrue(self.q.supports_partitions())
        self.assertTrue(self.q.supports_materialized_views())
        self.assertTrue(self.q.supports_procedures())
        self.assertTrue(self.q.supports_functions())
        self.assertTrue(self.q.supports_user_defined_types())
        self.assertTrue(self.q.supports_synonyms())
        self.assertTrue(self.q.supports_database_links())


# ---------------------------------------------------------------------------
# SQLiteMetadataQueries
# ---------------------------------------------------------------------------


class TestSQLiteMetadataQueries(unittest.TestCase):

    def setUp(self):
        self.q = SQLiteMetadataQueries()

    def test_get_check_constraints_query_returns_empty_results(self):
        sql, params = self.q.get_check_constraints_query("main", "t")
        self.assertEqual(params, [])
        # SQLite returns a "WHERE 0" sentinel query
        self.assertIn("WHERE 0", sql)

    def test_get_sequences_query(self):
        sql, params = self.q.get_sequences_query("main")
        self.assertEqual(params, [])
        _assert_keywords(self, sql, "sqlite_sequence")

    def test_get_views_query(self):
        sql, params = self.q.get_views_query("main")
        self.assertEqual(params, [])
        _assert_keywords(self, sql, "sqlite_master", "type = 'view'")

    def test_get_view_definition_query(self):
        sql, params = self.q.get_view_definition_query("main", "my_view")
        self.assertEqual(params, ["my_view"])
        _assert_keywords(self, sql, "sqlite_master", "type = 'view'")

    def test_get_indexes_query(self):
        sql, params = self.q.get_indexes_query("main", "t")
        self.assertEqual(params, ["t"])
        _assert_keywords(self, sql, "sqlite_master", "type = 'index'")

    def test_get_triggers_query_with_table(self):
        sql, params = self.q.get_triggers_query("main", "t")
        self.assertEqual(params, ["t"])
        _assert_keywords(self, sql, "sqlite_master", "type = 'trigger'", "tbl_name = ?")

    def test_get_triggers_query_without_table(self):
        sql, params = self.q.get_triggers_query("main")
        self.assertEqual(params, [])
        _assert_keywords(self, sql, "sqlite_master", "type = 'trigger'")
        self.assertNotIn("tbl_name = ?", sql)

    def test_get_computed_columns_query_sentinel(self):
        sql, params = self.q.get_computed_columns_query("main", "t")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_identity_columns_query_sentinel(self):
        sql, params = self.q.get_identity_columns_query("main", "t")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_table_partitions_query_sentinel(self):
        sql, params = self.q.get_table_partitions_query("main", "t")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_procedures_query_sentinel(self):
        sql, params = self.q.get_procedures_query("main")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_functions_query_sentinel(self):
        sql, params = self.q.get_functions_query("main")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_materialized_views_query_sentinel(self):
        sql, params = self.q.get_materialized_views_query("main")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_user_defined_types_query_sentinel(self):
        sql, params = self.q.get_user_defined_types_query("main")
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_extensions_query(self):
        sql, params = self.q.get_extensions_query()
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_foreign_data_wrappers_query(self):
        sql, params = self.q.get_foreign_data_wrappers_query()
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_foreign_servers_query(self):
        sql, params = self.q.get_foreign_servers_query()
        self.assertEqual(params, [])
        self.assertIn("WHERE 0", sql)

    def test_get_tables_query(self):
        sql, params = self.q.get_tables_query("main")
        self.assertEqual(params, [])
        _assert_keywords(self, sql, "sqlite_master", "type = 'table'")

    def test_get_table_columns_pragma(self):
        pragma = self.q.get_table_columns_pragma("my_table")
        self.assertIn("PRAGMA table_info", pragma)
        self.assertIn("my_table", pragma)

    def test_get_foreign_keys_pragma(self):
        pragma = self.q.get_foreign_keys_pragma("my_table")
        self.assertIn("PRAGMA foreign_key_list", pragma)
        self.assertIn("my_table", pragma)

    def test_get_index_columns_pragma(self):
        pragma = self.q.get_index_columns_pragma("idx_col")
        self.assertIn("PRAGMA index_info", pragma)
        self.assertIn("idx_col", pragma)

    def test_supports_flags(self):
        self.assertFalse(self.q.supports_check_constraints())
        self.assertFalse(self.q.supports_sequences())
        self.assertTrue(self.q.supports_views())
        self.assertTrue(self.q.supports_triggers())
        self.assertFalse(self.q.supports_computed_columns())
        self.assertFalse(self.q.supports_partitions())
        self.assertFalse(self.q.supports_materialized_views())
        self.assertFalse(self.q.supports_procedures())
        self.assertFalse(self.q.supports_functions())
        self.assertFalse(self.q.supports_user_defined_types())
        self.assertFalse(self.q.supports_extensions())


# ---------------------------------------------------------------------------
# SQLServerMetadataQueries
# ---------------------------------------------------------------------------


class TestSQLServerMetadataQueries(unittest.TestCase):

    def setUp(self):
        self.q = SQLServerMetadataQueries()

    def test_get_table_properties_query(self):
        sql, params = self.q.get_table_properties_query("dbo", "orders")
        self.assertEqual(params, ["dbo", "orders"])
        _assert_keywords(self, sql, "sys.tables", "sys.schemas")

    def test_get_check_constraints_query(self):
        sql, params = self.q.get_check_constraints_query("dbo", "orders")
        self.assertEqual(params, ["dbo", "orders"])
        _assert_keywords(self, sql, "sys.check_constraints", "is_disabled", "is_not_trusted")

    def test_get_sequences_query(self):
        sql, params = self.q.get_sequences_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.sequences", "sys.schemas", "sequence_name")

    def test_get_views_query(self):
        sql, params = self.q.get_views_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.views", "sys.schemas", "is_ms_shipped")

    def test_get_view_definition_query(self):
        sql, params = self.q.get_view_definition_query("dbo", "v1")
        self.assertEqual(params, ["dbo", "v1"])
        _assert_keywords(self, sql, "sys.views", "OBJECT_DEFINITION")

    def test_get_indexes_query(self):
        sql, params = self.q.get_indexes_query("dbo", "orders")
        self.assertEqual(params, ["dbo", "orders"])
        _assert_keywords(self, sql, "sys.indexes", "sys.index_columns", "sys.schemas")

    def test_get_all_indexes_query(self):
        sql, params = self.q.get_all_indexes_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.indexes", "sys.index_columns", "sys.schemas")

    def test_get_triggers_query_with_table(self):
        sql, params = self.q.get_triggers_query("dbo", "orders")
        self.assertEqual(params, ["dbo", "orders"])
        _assert_keywords(self, sql, "sys.triggers", "is_instead_of_trigger", "is_disabled")

    def test_get_triggers_query_without_table(self):
        sql, params = self.q.get_triggers_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.triggers")
        self.assertNotIn("AND o.name = ?", sql)

    def test_get_computed_columns_query(self):
        sql, params = self.q.get_computed_columns_query("dbo", "t")
        self.assertEqual(params, ["dbo", "t"])
        _assert_keywords(self, sql, "sys.computed_columns", "is_persisted")

    def test_get_identity_columns_query(self):
        sql, params = self.q.get_identity_columns_query("dbo", "t")
        self.assertEqual(params, ["dbo", "t"])
        _assert_keywords(self, sql, "sys.identity_columns", "seed_value", "increment_value")

    def test_get_table_partitions_query(self):
        sql, params = self.q.get_table_partitions_query("dbo", "t")
        self.assertEqual(params, ["dbo", "t"])
        _assert_keywords(self, sql, "sys.partitions", "sys.partition_functions")

    def test_get_procedures_query(self):
        sql, params = self.q.get_procedures_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.procedures", "sys.sql_modules", "parameter_json")

    def test_get_functions_query(self):
        sql, params = self.q.get_functions_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.objects", "sys.sql_modules", "FN")

    def test_get_materialized_views_query(self):
        sql, params = self.q.get_materialized_views_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.views", "sys.indexes", "is_unique")

    def test_get_synonyms_query(self):
        sql, params = self.q.get_synonyms_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.synonyms", "PARSENAME")

    def test_get_user_defined_types_query(self):
        sql, params = self.q.get_user_defined_types_query("dbo")
        self.assertEqual(params, ["dbo"])
        _assert_keywords(self, sql, "sys.types", "is_user_defined")

    def test_get_column_defaults_query(self):
        sql, params = self.q.get_column_defaults_query("dbo", "t")
        self.assertEqual(params, ["dbo", "t"])
        _assert_keywords(self, sql, "sys.columns", "sys.default_constraints", "default_value")

    def test_get_partition_scheme_query(self):
        sql, params = self.q.get_partition_scheme_query("dbo", "t")
        self.assertEqual(params, ["dbo", "t"])
        _assert_keywords(self, sql, "sys.partition_functions", "sys.partition_schemes")

    def test_supports_flags(self):
        self.assertTrue(self.q.supports_check_constraints())
        self.assertTrue(self.q.supports_sequences())
        self.assertTrue(self.q.supports_views())
        self.assertTrue(self.q.supports_triggers())
        self.assertTrue(self.q.supports_computed_columns())
        self.assertTrue(self.q.supports_partitions())
        self.assertTrue(self.q.supports_materialized_views())
        self.assertTrue(self.q.supports_procedures())
        self.assertTrue(self.q.supports_functions())
        self.assertTrue(self.q.supports_user_defined_types())
        self.assertTrue(self.q.supports_synonyms())

    def test_supports_linked_servers(self):
        self.assertTrue(self.q.supports_linked_servers())

    def test_get_linked_servers_query(self):
        sql, params = self.q.get_linked_servers_query()
        self.assertEqual(params, [])
        _assert_keywords(self, sql, "sys.servers", "is_linked")


class TestDB2QueriesModules(unittest.TestCase):
    def setUp(self):
        self.q = DB2MetadataQueries()

    def test_supports_modules(self):
        self.assertTrue(self.q.supports_modules())

    def test_get_modules_query(self):
        sql, params = self.q.get_modules_query("MYSCHEMA")
        self.assertEqual(params, ["MYSCHEMA"])
        _assert_keywords(self, sql, "SYSCAT.MODULES", "MODULENAME")


if __name__ == "__main__":
    unittest.main()
