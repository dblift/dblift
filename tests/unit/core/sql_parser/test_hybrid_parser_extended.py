"""Extended tests for core/sql_parser/hybrid_parser.py."""

import unittest


class TestHybridParserInit(unittest.TestCase):
    def _make(self, dialect="postgresql"):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect=dialect)

    def test_postgresql_dialect(self):
        p = self._make("postgresql")
        self.assertEqual(p.dialect, "postgresql")

    def test_db2_no_sqlglot(self):
        p = self._make("db2")
        self.assertIsNone(p.sqlglot_parser)

    def test_cosmosdb_no_sqlglot(self):
        p = self._make("cosmosdb")
        self.assertIsNone(p.sqlglot_parser)

    def test_dialect_name_property(self):
        p = self._make("mysql")
        self.assertEqual(p.dialect_name, "mysql")


class TestHybridParserSplitStatements(unittest.TestCase):
    def _make(self, dialect="postgresql"):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect=dialect)

    def test_single_statement(self):
        p = self._make()
        stmts = p.split_statements("SELECT 1;")
        self.assertIsInstance(stmts, list)
        self.assertGreater(len(stmts), 0)

    def test_multiple_statements(self):
        p = self._make()
        stmts = p.split_statements("SELECT 1;\nSELECT 2;")
        self.assertIsInstance(stmts, list)

    def test_empty_sql(self):
        p = self._make()
        stmts = p.split_statements("")
        self.assertIsInstance(stmts, list)

    def test_db2_dialect(self):
        p = self._make("db2")
        stmts = p.split_statements("SELECT 1 FROM SYSIBM.SYSDUMMY1")
        self.assertIsInstance(stmts, list)


class TestHybridParserValidateSql(unittest.TestCase):
    def _make(self, dialect="postgresql"):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect=dialect)

    def test_valid_sql_returns_dict(self):
        p = self._make()
        result = p.validate_sql("SELECT 1")
        self.assertIsInstance(result, dict)

    def test_empty_sql(self):
        p = self._make()
        result = p.validate_sql("")
        self.assertIsInstance(result, dict)


class TestHybridParserExtractObjects(unittest.TestCase):
    def _make(self, dialect="postgresql"):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect=dialect)

    def test_create_table(self):
        p = self._make()
        result = p.extract_objects("CREATE TABLE users (id INT PRIMARY KEY, name TEXT)")
        self.assertIsNotNone(result)

    def test_create_view(self):
        p = self._make()
        result = p.extract_objects("CREATE VIEW v_users AS SELECT * FROM users")
        self.assertIsNotNone(result)

    def test_empty_sql(self):
        p = self._make()
        result = p.extract_objects("")
        self.assertIsNotNone(result)


class TestHybridParserExtractDependencies(unittest.TestCase):
    def _make(self, dialect="postgresql"):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect=dialect)

    def test_select_from(self):
        p = self._make()
        result = p.extract_dependencies("SELECT * FROM users")
        self.assertIsInstance(result, dict)

    def test_view_dependencies(self):
        p = self._make()
        sql = "CREATE VIEW v AS SELECT * FROM users JOIN orders ON users.id = orders.user_id"
        result = p.extract_dependencies(sql)
        self.assertIsInstance(result, dict)


class TestHybridParserMysql(unittest.TestCase):
    def _make(self):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect="mysql")

    def test_mysql_create_table(self):
        p = self._make()
        result = p.extract_objects("CREATE TABLE `users` (`id` INT PRIMARY KEY)")
        self.assertIsNotNone(result)

    def test_mysql_split(self):
        p = self._make()
        stmts = p.split_statements("SELECT 1; SELECT 2;")
        self.assertIsInstance(stmts, list)


class TestHybridParserCosmosDbPartitionKey(unittest.TestCase):
    def _make(self):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect="cosmosdb")

    def test_with_partition_key_stored_in_metadata(self):
        p = self._make()
        sql = "CREATE CONTAINER users WITH PARTITION KEY /userId;"
        table = p._build_table_model_from_regex(sql, None)
        self.assertIsNotNone(table)
        self.assertIsInstance(table.metadata, dict)
        self.assertEqual(table.metadata["partition_key"], "/userId")

    def test_partition_key_with_nested_path(self):
        p = self._make()
        sql = "CREATE CONTAINER orders WITH PARTITION KEY /customer/id;"
        table = p._build_table_model_from_regex(sql, None)
        self.assertIsNotNone(table)
        self.assertEqual(table.metadata["partition_key"], "/customer/id")

    def test_no_partition_key_leaves_metadata_unset(self):
        p = self._make()
        sql = "CREATE CONTAINER logs (id STRING);"
        table = p._build_table_model_from_regex(sql, None)
        self.assertIsNotNone(table)
        self.assertFalse(
            hasattr(table, "metadata")
            and isinstance(table.metadata, dict)
            and "partition_key" in table.metadata
        )

    def test_if_not_exists_with_partition_key(self):
        p = self._make()
        sql = "CREATE CONTAINER IF NOT EXISTS products WITH PARTITION KEY /category;"
        table = p._build_table_model_from_regex(sql, None)
        self.assertIsNotNone(table)
        self.assertEqual(table.metadata["partition_key"], "/category")

    def test_dblift_generated_syntax_partitionkey_equals(self):
        p = self._make()
        sql = "CREATE CONTAINER users (id STRING) WITH (partitionKey='/userId')"
        table = p._build_table_model_from_regex(sql, None)
        self.assertIsNotNone(table)
        self.assertEqual(table.metadata["partition_key"], "/userId")

    def test_dblift_generated_syntax_nested_path(self):
        p = self._make()
        sql = "CREATE CONTAINER orders (id STRING) WITH (partitionKey='/customer/id')"
        table = p._build_table_model_from_regex(sql, None)
        self.assertIsNotNone(table)
        self.assertEqual(table.metadata["partition_key"], "/customer/id")


class TestHybridParserOracle(unittest.TestCase):
    def _make(self):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect="oracle")

    def test_oracle_create_table(self):
        p = self._make()
        result = p.extract_objects('CREATE TABLE "USERS" (ID NUMBER PRIMARY KEY)')
        self.assertIsNotNone(result)
