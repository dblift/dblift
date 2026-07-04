"""Unit tests for SQL parser dialect configuration modules."""

import re

import pytest

from core.sql_parser.dialects.base_config import DialectConfig
from db.plugins.db2.parser.parser_config import DB2Config
from db.plugins.mysql.parser.parser_config import MySqlConfig
from db.plugins.oracle.parser.parser_config import OracleConfig
from db.plugins.postgresql.parser.parser_config import PostgreSqlConfig
from db.plugins.sqlserver.parser.parser_config import SqlServerConfig


@pytest.mark.unit
class TestDialectConfigBase:
    """Test base DialectConfig class."""

    def test_init(self):
        """Test DialectConfig initialization."""

        # Create a concrete implementation for testing
        class TestConfig(DialectConfig):
            def get_ddl_keywords(self):
                return {"CREATE", "ALTER", "DROP"}

            def get_dml_keywords(self):
                return {"INSERT", "UPDATE", "DELETE"}

            def get_query_keywords(self):
                return {"SELECT"}

            def get_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

            def get_qualified_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*")

            def get_string_literal_pattern(self):
                return re.compile(r"'[^']*'")

            def get_comment_pattern(self):
                return re.compile(r"--.*")

            def get_statement_separator_pattern(self):
                return re.compile(r";")

            def is_ddl_statement(self, statement: str) -> bool:
                return statement.upper().startswith("CREATE")

            def is_dml_statement(self, statement: str) -> bool:
                return statement.upper().startswith("INSERT")

            def is_query_statement(self, statement: str) -> bool:
                return statement.upper().startswith("SELECT")

            def get_batch_separator(self) -> str:
                return ";"

            def supports_block_comments(self) -> bool:
                return True

            def supports_line_comments(self) -> bool:
                return True

        config = TestConfig()

        assert config.identifier_quote_char == '"'
        assert config.string_quote_char == "'"
        assert config.statement_separator == ";"
        assert config.line_comment_prefix == "--"
        assert config.block_comment_start == "/*"
        assert config.block_comment_end == "*/"
        assert config.supports_dollar_quoting is False
        assert config.supports_copy_statements is False
        assert config.supports_plpgsql_blocks is False
        assert config.supports_cte_with_recursive is False
        assert config.supports_on_conflict is False
        assert config.supports_returning is False

    def test_get_transaction_keywords(self):
        """Test get_transaction_keywords method."""

        class TestConfig(DialectConfig):
            def get_ddl_keywords(self):
                return set()

            def get_dml_keywords(self):
                return set()

            def get_query_keywords(self):
                return set()

            def get_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

            def get_qualified_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*")

            def get_string_literal_pattern(self):
                return re.compile(r"'[^']*'")

            def get_comment_pattern(self):
                return re.compile(r"--.*")

            def get_statement_separator_pattern(self):
                return re.compile(r";")

            def is_ddl_statement(self, statement: str) -> bool:
                return False

            def is_dml_statement(self, statement: str) -> bool:
                return False

            def is_query_statement(self, statement: str) -> bool:
                return False

            def get_batch_separator(self) -> str:
                return ";"

            def supports_block_comments(self) -> bool:
                return True

            def supports_line_comments(self) -> bool:
                return True

        config = TestConfig()
        keywords = config.get_transaction_keywords()

        assert "BEGIN" in keywords
        assert "COMMIT" in keywords
        assert "ROLLBACK" in keywords
        assert "SAVEPOINT" in keywords

    def test_get_block_keywords_for_splitting(self):
        """Test get_block_keywords_for_splitting method."""

        class TestConfig(DialectConfig):
            def get_ddl_keywords(self):
                return set()

            def get_dml_keywords(self):
                return set()

            def get_query_keywords(self):
                return set()

            def get_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

            def get_qualified_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*")

            def get_string_literal_pattern(self):
                return re.compile(r"'[^']*'")

            def get_comment_pattern(self):
                return re.compile(r"--.*")

            def get_statement_separator_pattern(self):
                return re.compile(r";")

            def is_ddl_statement(self, statement: str) -> bool:
                return False

            def is_dml_statement(self, statement: str) -> bool:
                return False

            def is_query_statement(self, statement: str) -> bool:
                return False

            def get_batch_separator(self) -> str:
                return ";"

            def supports_block_comments(self) -> bool:
                return True

            def supports_line_comments(self) -> bool:
                return True

        config = TestConfig()
        keywords = config.get_block_keywords_for_splitting()

        assert "BEGIN" in keywords
        assert "END" in keywords
        assert "DECLARE" in keywords
        assert "IF" in keywords
        assert "LOOP" in keywords

    def test_get_default_schema(self):
        """Test get_default_schema method."""

        class TestConfig(DialectConfig):
            def get_ddl_keywords(self):
                return set()

            def get_dml_keywords(self):
                return set()

            def get_query_keywords(self):
                return set()

            def get_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

            def get_qualified_identifier_pattern(self):
                return re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*")

            def get_string_literal_pattern(self):
                return re.compile(r"'[^']*'")

            def get_comment_pattern(self):
                return re.compile(r"--.*")

            def get_statement_separator_pattern(self):
                return re.compile(r";")

            def is_ddl_statement(self, statement: str) -> bool:
                return False

            def is_dml_statement(self, statement: str) -> bool:
                return False

            def is_query_statement(self, statement: str) -> bool:
                return False

            def get_batch_separator(self) -> str:
                return ";"

            def supports_block_comments(self) -> bool:
                return True

            def supports_line_comments(self) -> bool:
                return True

        config = TestConfig()
        schema = config.get_default_schema()

        assert schema is None


@pytest.mark.unit
class TestOracleConfig:
    """Test OracleConfig class - OracleConfig is abstract and incomplete."""

    def test_oracle_config_is_abstract(self):
        """Test that OracleConfig cannot be instantiated (missing abstract methods)."""
        # OracleConfig doesn't implement all abstract methods from DialectConfig
        # So it cannot be instantiated directly
        with pytest.raises(TypeError):
            OracleConfig()

    def test_oracle_config_properties_exist(self):
        """Test that OracleConfig properties exist (via class inspection)."""
        # Check that properties are defined
        assert hasattr(OracleConfig, "name")
        assert hasattr(OracleConfig, "batch_separators")
        assert hasattr(OracleConfig, "quoted_identifiers")
        assert hasattr(OracleConfig, "comment_patterns")
        assert hasattr(OracleConfig, "block_keywords")
        assert hasattr(OracleConfig, "ddl_patterns")
        assert hasattr(OracleConfig, "dml_patterns")
        assert hasattr(OracleConfig, "query_patterns")
        assert hasattr(OracleConfig, "object_patterns")
        assert hasattr(OracleConfig, "get_default_schema")
        assert hasattr(OracleConfig, "get_identifier_pattern")
        assert hasattr(OracleConfig, "get_qualified_identifier_pattern")
        assert hasattr(OracleConfig, "normalize_identifier")

    def test_oracle_config_via_concrete_subclass(self):
        """Test OracleConfig properties via a concrete subclass."""

        # Create a concrete subclass that implements missing abstract methods
        class ConcreteOracleConfig(OracleConfig):
            def get_ddl_keywords(self):
                return {"CREATE", "ALTER", "DROP"}

            def get_dml_keywords(self):
                return {"INSERT", "UPDATE", "DELETE"}

            def get_query_keywords(self):
                return {"SELECT"}

            def get_string_literal_pattern(self):
                return re.compile(r"'[^']*'")

            def get_comment_pattern(self):
                return re.compile(r"--.*")

            def get_statement_separator_pattern(self):
                return re.compile(r";")

            def is_ddl_statement(self, statement: str) -> bool:
                return False

            def is_dml_statement(self, statement: str) -> bool:
                return False

            def is_query_statement(self, statement: str) -> bool:
                return False

            def get_batch_separator(self) -> str:
                return "/"

            def supports_block_comments(self) -> bool:
                return True

            def supports_line_comments(self) -> bool:
                return True

        config = ConcreteOracleConfig()

        # Test properties
        assert config.name == "oracle"
        assert len(config.batch_separators) == 1
        assert len(config.quoted_identifiers) == 1
        assert len(config.comment_patterns) == 2
        assert "CREATE PROCEDURE" in config.block_keywords
        assert "create_table" in config.ddl_patterns
        assert "insert" in config.dml_patterns
        assert "select" in config.query_patterns
        assert "table_create" in config.object_patterns

        # Test methods
        assert config.get_default_schema() == "DEFAULT_SCHEMA"
        assert isinstance(config.get_identifier_pattern(), re.Pattern)
        assert isinstance(config.get_qualified_identifier_pattern(), re.Pattern)
        assert config.normalize_identifier("TestName", is_quoted=True) == "TestName"
        assert config.normalize_identifier("TestName", is_quoted=False) == "TESTNAME"


@pytest.mark.unit
class TestDB2Config:
    """Test DB2Config class."""

    def test_init(self):
        """Test DB2Config initialization."""
        config = DB2Config()

        assert config.dialect_name == "db2"
        assert hasattr(config, "_ddl_patterns")
        assert hasattr(config, "_dml_patterns")
        assert hasattr(config, "_query_patterns")

    def test_get_ddl_keywords(self):
        """Test get_ddl_keywords method."""
        config = DB2Config()

        keywords = config.get_ddl_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "CREATE" in keywords
        assert "ALTER" in keywords
        assert "DROP" in keywords

    def test_get_dml_keywords(self):
        """Test get_dml_keywords method."""
        config = DB2Config()

        keywords = config.get_dml_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "INSERT" in keywords
        assert "UPDATE" in keywords
        assert "DELETE" in keywords

    def test_get_query_keywords(self):
        """Test get_query_keywords method."""
        config = DB2Config()

        keywords = config.get_query_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "SELECT" in keywords

    def test_get_identifier_pattern(self):
        """Test get_identifier_pattern method."""
        config = DB2Config()

        pattern = config.get_identifier_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_qualified_identifier_pattern(self):
        """Test get_qualified_identifier_pattern method."""
        config = DB2Config()

        pattern = config.get_qualified_identifier_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_string_literal_pattern(self):
        """Test get_string_literal_pattern method."""
        config = DB2Config()

        pattern = config.get_string_literal_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_comment_pattern(self):
        """Test get_comment_pattern method."""
        config = DB2Config()

        pattern = config.get_comment_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_statement_separator_pattern(self):
        """Test get_statement_separator_pattern method."""
        config = DB2Config()

        pattern = config.get_statement_separator_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_is_ddl_statement(self):
        """Test is_ddl_statement method."""
        config = DB2Config()

        assert config.is_ddl_statement("CREATE TABLE t1") is True
        assert config.is_ddl_statement("ALTER TABLE t1") is True
        assert config.is_ddl_statement("SELECT * FROM t1") is False

    def test_is_dml_statement(self):
        """Test is_dml_statement method."""
        config = DB2Config()

        assert config.is_dml_statement("INSERT INTO t1 VALUES (1)") is True
        assert config.is_dml_statement("UPDATE t1 SET col = 1") is True
        assert config.is_dml_statement("SELECT * FROM t1") is False

    def test_is_query_statement(self):
        """Test is_query_statement method."""
        config = DB2Config()

        assert config.is_query_statement("SELECT * FROM t1") is True
        assert config.is_query_statement("CREATE TABLE t1") is False

    def test_get_batch_separator(self):
        """Test get_batch_separator method."""
        config = DB2Config()

        separator = config.get_batch_separator()
        assert isinstance(separator, str)
        assert len(separator) > 0

    def test_supports_block_comments(self):
        """Test supports_block_comments method."""
        config = DB2Config()

        assert isinstance(config.supports_block_comments(), bool)

    def test_supports_line_comments(self):
        """Test supports_line_comments method."""
        config = DB2Config()

        assert isinstance(config.supports_line_comments(), bool)

    def test_get_default_schema(self):
        """Test get_default_schema method."""
        config = DB2Config()

        schema = config.get_default_schema()
        assert schema == "SYSIBM"

    def test_name_property(self):
        """Test name property."""
        config = DB2Config()

        assert config.name == "db2"

    def test_ddl_patterns_property(self):
        """Test ddl_patterns property."""
        config = DB2Config()

        patterns = config.ddl_patterns
        assert isinstance(patterns, dict)
        assert "create_table" in patterns

    def test_dml_patterns_property(self):
        """Test dml_patterns property."""
        config = DB2Config()

        patterns = config.dml_patterns
        assert isinstance(patterns, dict)
        assert "insert" in patterns

    def test_query_patterns_property(self):
        """Test query_patterns property."""
        config = DB2Config()

        patterns = config.query_patterns
        assert isinstance(patterns, dict)
        assert "select" in patterns

    def test_object_patterns_property(self):
        """Test object_patterns property."""
        config = DB2Config()

        patterns = config.object_patterns
        assert isinstance(patterns, dict)

    def test_comment_patterns_property(self):
        """Test comment_patterns property."""
        config = DB2Config()

        patterns = config.comment_patterns
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_batch_separators_property(self):
        """Test batch_separators property."""
        config = DB2Config()

        separators = config.batch_separators
        assert isinstance(separators, list)
        assert len(separators) > 0

    def test_quoted_identifiers_property(self):
        """Test quoted_identifiers property."""
        config = DB2Config()

        patterns = config.quoted_identifiers
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_block_keywords_property(self):
        """Test block_keywords property."""
        config = DB2Config()

        keywords = config.block_keywords
        assert isinstance(keywords, list)
        assert "BEGIN" in keywords

    def test_normalize_identifier_quoted(self):
        """Test normalize_identifier with quoted identifier."""
        config = DB2Config()

        result = config.normalize_identifier('"TestName"', is_quoted=False)
        assert result == "TestName"  # Quotes removed

    def test_normalize_identifier_unquoted(self):
        """Test normalize_identifier with unquoted identifier."""
        config = DB2Config()

        result = config.normalize_identifier("TestName", is_quoted=False)
        assert result == "TESTNAME"  # Uppercase

    def test_normalize_identifier_empty(self):
        """Test normalize_identifier with empty identifier."""
        config = DB2Config()

        result = config.normalize_identifier("", is_quoted=False)
        assert result == ""

    def test_extract_sqlpl_blocks(self):
        """Test extract_sqlpl_blocks method."""
        config = DB2Config()

        sql = "CREATE PROCEDURE test_proc BEGIN SELECT 1; END;"
        blocks = config.extract_sqlpl_blocks(sql)

        assert isinstance(blocks, list)

    def test_extract_compound_statements(self):
        """Test extract_compound_statements method."""
        config = DB2Config()

        sql = "BEGIN ATOMIC SELECT 1; END;"
        blocks = config.extract_compound_statements(sql)

        assert isinstance(blocks, list)

    def test_extract_trigger_blocks(self):
        """Test extract_trigger_blocks method."""
        config = DB2Config()

        sql = "CREATE TRIGGER test_trigger BEGIN ATOMIC SELECT 1; END;"
        blocks = config.extract_trigger_blocks(sql)

        assert isinstance(blocks, list)

    def test_is_db2_utility_statement(self):
        """Test is_db2_utility_statement method."""
        config = DB2Config()

        assert config.is_db2_utility_statement("REORG TABLE t1") is True
        assert config.is_db2_utility_statement("SELECT * FROM t1") is False

    def test_extract_module_blocks(self):
        """Test extract_module_blocks method."""
        config = DB2Config()

        sql = "CREATE MODULE test_module END MODULE;"
        blocks = config.extract_module_blocks(sql)

        assert isinstance(blocks, list)

    def test_extract_exec_sql_blocks(self):
        """Test extract_exec_sql_blocks method."""
        config = DB2Config()

        sql = "EXEC SQL SELECT 1 END-EXEC"
        blocks = config.extract_exec_sql_blocks(sql)

        assert isinstance(blocks, list)

    def test_split_statements(self):
        """Test split_statements method."""
        config = DB2Config()

        sql = "CREATE TABLE t1 (id INT); SELECT * FROM t1;"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)
        assert len(statements) >= 1

    def test_split_statements_with_procedure(self):
        """Test split_statements with procedure."""
        config = DB2Config()

        sql = "CREATE PROCEDURE test() BEGIN SELECT 1; END; CREATE TABLE t1 (id INT);"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)

    def test_split_statements_with_function(self):
        """Test split_statements with function."""
        config = DB2Config()

        sql = "CREATE FUNCTION test() RETURNS INT BEGIN RETURN 1; END;"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)

    def test_split_statements_with_trigger(self):
        """Test split_statements with trigger."""
        config = DB2Config()

        sql = "CREATE TRIGGER test_trigger BEGIN ATOMIC SELECT 1; END;"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)

    def test_split_statements_with_module(self):
        """Test split_statements with module."""
        config = DB2Config()

        sql = "CREATE MODULE test_module END MODULE; CREATE TABLE t1 (id INT);"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)

    def test_split_statements_empty(self):
        """Test split_statements with empty SQL."""
        config = DB2Config()

        statements = config.split_statements("")

        assert isinstance(statements, list)

    def test_split_statements_with_strings(self):
        """Test split_statements with string literals."""
        config = DB2Config()

        sql = "INSERT INTO t1 VALUES ('test;value'); SELECT * FROM t1;"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)
        assert len(statements) >= 1

    def test_split_statements_with_comments(self):
        """Test split_statements with comments."""
        config = DB2Config()

        sql = "CREATE TABLE t1 (id INT); -- comment\nSELECT * FROM t1;"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)
        assert len(statements) >= 1

    def test_split_statements_with_block_comments(self):
        """Test split_statements with block comments."""
        config = DB2Config()

        sql = "CREATE TABLE t1 (id INT); /* comment */ SELECT * FROM t1;"
        statements = config.split_statements(sql)

        assert isinstance(statements, list)
        assert len(statements) >= 1


@pytest.mark.unit
class TestMySqlConfig:
    """Test MySqlConfig class."""

    def test_init(self):
        """Test MySqlConfig initialization."""
        config = MySqlConfig()

        assert config.dialect_name == "mysql"
        assert hasattr(config, "_ddl_patterns")
        assert hasattr(config, "_dml_patterns")
        assert hasattr(config, "_query_patterns")

    def test_get_ddl_keywords(self):
        """Test get_ddl_keywords method."""
        config = MySqlConfig()

        keywords = config.get_ddl_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "CREATE" in keywords
        assert "ALTER" in keywords
        assert "DROP" in keywords

    def test_get_dml_keywords(self):
        """Test get_dml_keywords method."""
        config = MySqlConfig()

        keywords = config.get_dml_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "INSERT" in keywords
        assert "UPDATE" in keywords
        assert "DELETE" in keywords

    def test_get_query_keywords(self):
        """Test get_query_keywords method."""
        config = MySqlConfig()

        keywords = config.get_query_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "SELECT" in keywords

    def test_get_identifier_pattern(self):
        """Test get_identifier_pattern method."""
        config = MySqlConfig()

        pattern = config.get_identifier_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_qualified_identifier_pattern(self):
        """Test get_qualified_identifier_pattern method."""
        config = MySqlConfig()

        pattern = config.get_qualified_identifier_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_string_literal_pattern(self):
        """Test get_string_literal_pattern method."""
        config = MySqlConfig()

        pattern = config.get_string_literal_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_comment_pattern(self):
        """Test get_comment_pattern method."""
        config = MySqlConfig()

        pattern = config.get_comment_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_statement_separator_pattern(self):
        """Test get_statement_separator_pattern method."""
        config = MySqlConfig()

        pattern = config.get_statement_separator_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_is_ddl_statement(self):
        """Test is_ddl_statement method."""
        config = MySqlConfig()

        assert config.is_ddl_statement("CREATE TABLE t1") is True
        assert config.is_ddl_statement("ALTER TABLE t1") is True
        assert config.is_dml_statement("SELECT * FROM t1") is False

    def test_is_dml_statement(self):
        """Test is_dml_statement method."""
        config = MySqlConfig()

        assert config.is_dml_statement("INSERT INTO t1 VALUES (1)") is True
        assert config.is_dml_statement("UPDATE t1 SET col = 1") is True
        assert config.is_dml_statement("SELECT * FROM t1") is False

    def test_is_query_statement(self):
        """Test is_query_statement method."""
        config = MySqlConfig()

        assert config.is_query_statement("SELECT * FROM t1") is True
        assert config.is_query_statement("CREATE TABLE t1") is False

    def test_get_batch_separator(self):
        """Test get_batch_separator method."""
        config = MySqlConfig()

        separator = config.get_batch_separator()
        assert isinstance(separator, str)
        assert len(separator) > 0

    def test_supports_block_comments(self):
        """Test supports_block_comments method."""
        config = MySqlConfig()

        assert isinstance(config.supports_block_comments(), bool)

    def test_supports_line_comments(self):
        """Test supports_line_comments method."""
        config = MySqlConfig()

        assert isinstance(config.supports_line_comments(), bool)

    def test_get_default_schema(self):
        """Test get_default_schema method."""
        config = MySqlConfig()

        schema = config.get_default_schema()
        assert schema == "mysql"

    def test_name_property(self):
        """Test name property."""
        config = MySqlConfig()

        assert config.name == "mysql"

    def test_ddl_patterns_property(self):
        """Test ddl_patterns property."""
        config = MySqlConfig()

        patterns = config.ddl_patterns
        assert isinstance(patterns, dict)
        assert "create_table" in patterns

    def test_dml_patterns_property(self):
        """Test dml_patterns property."""
        config = MySqlConfig()

        patterns = config.dml_patterns
        assert isinstance(patterns, dict)
        assert "insert" in patterns

    def test_query_patterns_property(self):
        """Test query_patterns property."""
        config = MySqlConfig()

        patterns = config.query_patterns
        assert isinstance(patterns, dict)
        assert "select" in patterns

    def test_object_patterns_property(self):
        """Test object_patterns property."""
        config = MySqlConfig()

        patterns = config.object_patterns
        assert isinstance(patterns, dict)

    def test_comment_patterns_property(self):
        """Test comment_patterns property."""
        config = MySqlConfig()

        patterns = config.comment_patterns
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_batch_separators_property(self):
        """Test batch_separators property."""
        config = MySqlConfig()

        separators = config.batch_separators
        assert isinstance(separators, list)
        assert len(separators) > 0

    def test_quoted_identifiers_property(self):
        """Test quoted_identifiers property."""
        config = MySqlConfig()

        patterns = config.quoted_identifiers
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_block_keywords_property(self):
        """Test block_keywords property."""
        config = MySqlConfig()

        keywords = config.block_keywords
        assert isinstance(keywords, list)
        assert "BEGIN" in keywords

    def test_normalize_identifier_backticks(self):
        """Test normalize_identifier with backtick identifiers."""
        config = MySqlConfig()

        result = config.normalize_identifier("`TestName`", is_quoted=False)
        assert result == "testname"  # Backticks removed, lowercase

    def test_normalize_identifier_unquoted(self):
        """Test normalize_identifier with unquoted identifier."""
        config = MySqlConfig()

        result = config.normalize_identifier("TestName", is_quoted=False)
        assert result == "testname"  # Lowercase

    def test_normalize_identifier_empty(self):
        """Test normalize_identifier with empty identifier."""
        config = MySqlConfig()

        result = config.normalize_identifier("", is_quoted=False)
        assert result == ""

    def test_extract_backtick_identifiers(self):
        """Test extract_backtick_identifiers method."""
        config = MySqlConfig()

        sql = "CREATE TABLE `test_table` (`id` INT)"
        identifiers = config.extract_backtick_identifiers(sql)

        assert isinstance(identifiers, list)
        assert "test_table" in identifiers
        assert "id" in identifiers

    def test_is_hash_comment(self):
        """Test is_hash_comment method."""
        config = MySqlConfig()

        assert config.is_hash_comment("# This is a comment") is True
        assert config.is_hash_comment("SELECT * FROM t1") is False

    def test_extract_stored_procedure_body(self):
        """Test extract_stored_procedure_body method."""
        config = MySqlConfig()

        sql = "CREATE PROCEDURE test() BEGIN SELECT 1; END"
        body = config.extract_stored_procedure_body(sql)

        assert isinstance(body, str)
        assert "BEGIN" in body

    def test_extract_delimiter_blocks(self):
        """Test extract_delimiter_blocks method."""
        config = MySqlConfig()

        sql = "DELIMITER //\nCREATE PROCEDURE test() BEGIN SELECT 1; END//\nDELIMITER ;"
        blocks = config.extract_delimiter_blocks(sql)

        assert isinstance(blocks, list)


@pytest.mark.unit
class TestSqlServerConfig:
    """Test SqlServerConfig class."""

    def test_init(self):
        """Test SqlServerConfig initialization."""
        config = SqlServerConfig()

        assert config.name == "sqlserver"
        assert hasattr(config, "ddl_patterns")
        assert hasattr(config, "dml_patterns")
        assert hasattr(config, "query_patterns")

    def test_name_property(self):
        """Test name property."""
        config = SqlServerConfig()

        assert config.name == "sqlserver"

    def test_batch_separators_property(self):
        """Test batch_separators property."""
        config = SqlServerConfig()

        separators = config.batch_separators
        assert len(separators) == 1

    def test_quoted_identifiers_property(self):
        """Test quoted_identifiers property."""
        config = SqlServerConfig()

        patterns = config.quoted_identifiers
        assert len(patterns) == 2  # Brackets and double quotes

    def test_comment_patterns_property(self):
        """Test comment_patterns property."""
        config = SqlServerConfig()

        patterns = config.comment_patterns
        assert len(patterns) == 2  # Line and block comments

    def test_block_keywords_property(self):
        """Test block_keywords property."""
        config = SqlServerConfig()

        keywords = config.block_keywords
        assert "CREATE PROCEDURE" in keywords
        assert "CREATE FUNCTION" in keywords

    def test_ddl_patterns_property(self):
        """Test ddl_patterns property."""
        config = SqlServerConfig()

        patterns = config.ddl_patterns
        assert "create_table" in patterns
        assert "alter_table" in patterns
        assert "drop_table" in patterns

    def test_dml_patterns_property(self):
        """Test dml_patterns property."""
        config = SqlServerConfig()

        patterns = config.dml_patterns
        assert "insert" in patterns
        assert "update" in patterns
        assert "delete" in patterns

    def test_query_patterns_property(self):
        """Test query_patterns property."""
        config = SqlServerConfig()

        patterns = config.query_patterns
        assert "select" in patterns
        assert "with" in patterns

    def test_object_patterns_property(self):
        """Test object_patterns property."""
        config = SqlServerConfig()

        patterns = config.object_patterns
        assert "table_create" in patterns
        assert "table_alter" in patterns
        assert "view_create" in patterns

    def test_get_default_schema(self):
        """Test get_default_schema method."""
        config = SqlServerConfig()

        schema = config.get_default_schema()
        assert schema == "dbo"

    def test_get_identifier_pattern(self):
        """Test get_identifier_pattern method."""
        config = SqlServerConfig()

        pattern = config.get_identifier_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_qualified_identifier_pattern(self):
        """Test get_qualified_identifier_pattern method."""
        config = SqlServerConfig()

        pattern = config.get_qualified_identifier_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_normalize_identifier_brackets(self):
        """Test normalize_identifier with bracket identifiers."""
        config = SqlServerConfig()

        result = config.normalize_identifier("[TestName]", is_quoted=False)
        assert result == "TestName"  # Brackets removed, case preserved

    def test_normalize_identifier_double_quotes(self):
        """Test normalize_identifier with double-quoted identifiers."""
        config = SqlServerConfig()

        result = config.normalize_identifier('"TestName"', is_quoted=False)
        assert result == "TestName"  # Quotes removed, case preserved

    def test_normalize_identifier_unquoted(self):
        """Test normalize_identifier with unquoted identifier."""
        config = SqlServerConfig()

        result = config.normalize_identifier("TestName", is_quoted=False)
        assert result == "TestName"  # Case preserved

    def test_normalize_identifier_quoted_flag(self):
        """Test normalize_identifier with is_quoted=True."""
        config = SqlServerConfig()

        result = config.normalize_identifier("TestName", is_quoted=True)
        assert result == "TestName"  # Case preserved

    def test_get_ddl_keywords(self):
        """Test get_ddl_keywords method."""
        config = SqlServerConfig()

        keywords = config.get_ddl_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "CREATE" in keywords
        assert "ALTER" in keywords
        assert "DROP" in keywords

    def test_get_dml_keywords(self):
        """Test get_dml_keywords method."""
        config = SqlServerConfig()

        keywords = config.get_dml_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "INSERT" in keywords
        assert "UPDATE" in keywords
        assert "DELETE" in keywords

    def test_get_query_keywords(self):
        """Test get_query_keywords method."""
        config = SqlServerConfig()

        keywords = config.get_query_keywords()
        assert isinstance(keywords, set)
        assert len(keywords) > 0
        assert "SELECT" in keywords

    def test_get_string_literal_pattern(self):
        """Test get_string_literal_pattern method."""
        config = SqlServerConfig()

        pattern = config.get_string_literal_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_comment_pattern(self):
        """Test get_comment_pattern method."""
        config = SqlServerConfig()

        pattern = config.get_comment_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_get_statement_separator_pattern(self):
        """Test get_statement_separator_pattern method."""
        config = SqlServerConfig()

        pattern = config.get_statement_separator_pattern()
        assert isinstance(pattern, re.Pattern)

    def test_is_ddl_statement(self):
        """Test is_ddl_statement method."""
        config = SqlServerConfig()

        assert config.is_ddl_statement("CREATE TABLE t1") is True
        assert config.is_ddl_statement("ALTER TABLE t1") is True
        assert config.is_ddl_statement("SELECT * FROM t1") is False

    def test_is_dml_statement(self):
        """Test is_dml_statement method."""
        config = SqlServerConfig()

        assert config.is_dml_statement("INSERT INTO t1 VALUES (1)") is True
        assert config.is_dml_statement("UPDATE t1 SET col = 1") is True
        assert config.is_dml_statement("SELECT * FROM t1") is False

    def test_is_query_statement(self):
        """Test is_query_statement method."""
        config = SqlServerConfig()

        assert config.is_query_statement("SELECT * FROM t1") is True
        assert config.is_query_statement("CREATE TABLE t1") is False

    def test_get_batch_separator(self):
        """Test get_batch_separator method."""
        config = SqlServerConfig()

        separator = config.get_batch_separator()
        assert separator == "GO"

    def test_supports_block_comments(self):
        """Test supports_block_comments method."""
        config = SqlServerConfig()

        assert config.supports_block_comments() is True

    def test_supports_line_comments(self):
        """Test supports_line_comments method."""
        config = SqlServerConfig()

        assert config.supports_line_comments() is True


@pytest.mark.unit
class TestPostgreSqlConfig:
    """Test PostgreSQL dialect configuration."""

    def test_drop_trigger_pattern_consumes_on_table_clause(self):
        config = PostgreSqlConfig()
        pattern = config.object_patterns["drop_trigger"]
        sql = 'DROP TRIGGER IF EXISTS "trg_orders_insert" ON "dblift_test"."orders"'

        match = pattern.match(sql)

        assert match is not None
        assert match.group(0) == sql
