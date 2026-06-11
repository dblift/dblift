"""Extended tests for core/sql_parser/hybrid_parser.py."""

import unittest


class TestHybridParserInit(unittest.TestCase):
    def _make(self, dialect="postgresql"):
        from core.sql_parser.hybrid_parser import HybridParser

        return HybridParser(dialect=dialect)

    def test_postgresql_dialect(self):
        p = self._make("postgresql")
        self.assertEqual(p.dialect, "postgresql")

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
