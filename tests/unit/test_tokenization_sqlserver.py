"""Unit tests for SQL Server-specific tokenization."""

import pytest

from core.sql_parser.parser_context import ParserContext
from core.sql_parser.tokens import TokenType
from db.plugins.sqlserver.parser.sqlserver_statement_parser import SQLServerStatementParser
from db.plugins.sqlserver.parser.sqlserver_tokenizer import SQLServerTokenizer


class TestSQLServerTokenizer:
    """Test SQL Server-specific tokenization features."""

    def test_go_delimiter(self):
        """Test GO batch delimiter."""
        sql = "SELECT 1;\nGO\nSELECT 2;\nGO"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        delimiter_tokens = [
            t for t in tokens if t.type == TokenType.DELIMITER and t.text.upper() == "GO"
        ]
        assert len(delimiter_tokens) >= 2

    def test_bracket_identifiers(self):
        """Test bracket-quoted identifiers."""
        sql = "SELECT [column name] FROM [table name];"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_double_quoted_identifiers(self):
        """Test double-quoted identifiers."""
        sql = 'SELECT "column_name" FROM "table_name";'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_go_at_end_of_file(self):
        """Test GO at end of file without newline."""
        sql = "SELECT 1\nGO"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        delimiter_tokens = [
            t for t in tokens if t.type == TokenType.DELIMITER and t.text.upper() == "GO"
        ]
        assert len(delimiter_tokens) >= 1

    def test_go_with_trailing_line_comment_is_delimiter(self):
        """GO-- comment must be a batch delimiter, not the keyword GO."""
        sql = "SELECT 1; GO-- next batch\nSELECT 2;"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()
        assert any(t.type == TokenType.DELIMITER and t.text.upper() == "GO" for t in tokens)
        assert not any(t.type == TokenType.KEYWORD and t.text.upper() == "GO" for t in tokens)

    def test_tsql_parameter_tokens(self):
        """@parameters must be tokenized (base tokenizer drops @)."""
        sql = "CREATE PROCEDURE p @MinPrice DECIMAL(10,2) AS SELECT @MinPrice;"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()
        at_params = [
            t.text for t in tokens if t.type == TokenType.IDENTIFIER and t.text.startswith("@")
        ]
        assert at_params.count("@MinPrice") == 2

    def test_tsql_double_at_system_function_token(self):
        tokenizer = SQLServerTokenizer("IF @@TRANCOUNT > 0 ROLLBACK;")
        tokens = tokenizer.tokenize()
        assert any(t.type == TokenType.IDENTIFIER and t.text == "@@TRANCOUNT" for t in tokens)


class TestSQLServerStatementParser:
    """Test SQL Server-specific statement parsing."""

    def test_simple_sql_split(self):
        """Test simple SQL statement splitting."""
        sql = "SELECT * FROM table1; SELECT * FROM table2;"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = SQLServerStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 2

    def test_go_delimiter_split(self):
        """Test GO delimiter splits statements."""
        sql = "CREATE TABLE test1 (id INT);\nGO\nCREATE TABLE test2 (name VARCHAR(100));\nGO"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = SQLServerStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 2 CREATE TABLE statements
        assert len(statements) >= 2

    def test_go_not_emitted_as_own_statement(self):
        """GO is a batch separator only; providers must not receive it as SQL."""
        sql = """IF OBJECT_ID('dbo.v', 'V') IS NOT NULL DROP VIEW dbo.v;
GO
CREATE VIEW dbo.v AS SELECT 1 AS x;"""
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()
        parser = SQLServerStatementParser(tokens)
        statements = parser.split_statements()
        assert not any(s.strip().upper() == "GO" for s in statements)
        assert len(statements) == 2

    def test_create_procedure_preserves_at_parameters_in_roundtrip(self):
        """Reconstructed SQL must keep T-SQL @parameter names."""
        sql = """CREATE PROCEDURE GetExpensiveProducts
    @MinPrice DECIMAL(10, 2)
AS
BEGIN
    SELECT * FROM Products WHERE Price >= @MinPrice;
END;"""
        tokenizer = SQLServerTokenizer(sql)
        parser = SQLServerStatementParser(tokenizer.tokenize())
        statements = parser.split_statements()
        assert len(statements) == 1
        assert statements[0].count("@MinPrice") == 2

    def test_unicode_string_prefix_adjacent_in_roundtrip(self):
        """N'str' must not become N 'str' when reconstructing from tokens (invalid T-SQL)."""
        sql = "SET @SQL = N'SELECT * FROM ' + QUOTENAME(@TableName);"
        tokenizer = SQLServerTokenizer(sql)
        parser = SQLServerStatementParser(tokenizer.tokenize())
        statements = parser.split_statements()
        assert len(statements) == 1
        assert "N'SELECT * FROM '" in statements[0]
        assert "N 'SELECT" not in statements[0]

    def test_stored_procedure_with_begin_end(self):
        """Test stored procedure with BEGIN/END blocks."""
        sql = """CREATE PROCEDURE test_proc AS
BEGIN
    SELECT 1;
    SELECT 2;
END;"""
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = SQLServerStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (entire procedure)
        assert len(statements) == 1

    def test_begin_transaction_not_block(self):
        """Test BEGIN TRANSACTION doesn't increase block depth."""
        sql = """BEGIN TRANSACTION;
SELECT * FROM table1;
COMMIT;"""
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = SQLServerStatementParser(tokens)
        statements = parser.split_statements()

        # Should be 3 statements: BEGIN TRAN, SELECT, COMMIT
        assert len(statements) >= 3

    def test_begin_block_vs_begin_tran(self):
        """Test disambiguation of BEGIN block vs BEGIN TRANSACTION."""
        sql1 = """BEGIN
    SELECT 1;
END;"""
        tokenizer1 = SQLServerTokenizer(sql1)
        tokens1 = tokenizer1.tokenize()
        parser1 = SQLServerStatementParser(tokens1)
        statements1 = parser1.split_statements()

        # BEGIN/END block should be one statement
        assert len(statements1) == 1

        sql2 = """BEGIN TRANSACTION
SELECT 1;
COMMIT;"""
        tokenizer2 = SQLServerTokenizer(sql2)
        tokens2 = tokenizer2.tokenize()
        parser2 = SQLServerStatementParser(tokens2)
        statements2 = parser2.split_statements()

        # BEGIN TRANSACTION should be separate statement
        assert len(statements2) >= 2

    def test_begin_conversation(self):
        """Test BEGIN CONVERSATION doesn't start block."""
        sql = "BEGIN CONVERSATION @handle;"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = SQLServerStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (not a block)
        assert len(statements) == 1

    def test_transaction_compatibility(self):
        """Test transaction compatibility detection."""
        sql1 = "CREATE TABLE test (id INT);"
        tokenizer1 = SQLServerTokenizer(sql1)
        tokens1 = tokenizer1.tokenize()
        parser1 = SQLServerStatementParser(tokens1, ParserContext())
        statements1 = parser1.split_statements()

        # Regular DDL can run in transaction
        assert parser1.can_execute_in_transaction()

        sql2 = "BACKUP DATABASE testdb TO DISK = 'backup.bak';"
        tokenizer2 = SQLServerTokenizer(sql2)
        tokens2 = tokenizer2.tokenize()
        parser2 = SQLServerStatementParser(tokens2, ParserContext())
        statements2 = parser2.split_statements()

        # BACKUP cannot run in transaction
        assert not parser2.can_execute_in_transaction()
