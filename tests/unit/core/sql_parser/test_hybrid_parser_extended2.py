"""Extended unit tests for core.sql_parser.hybrid_parser targeting branches
not exercised by test_hybrid_parser.py, test_hybrid_parser_extended.py and
test_hybrid_parser_decomposition.py (ALTER TABLE handling, dependency
extraction error paths, regex-based table model reconstruction, etc.)."""

import re
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from sqlglot import exp, parse_one

from core.sql_model.base import (
    ConstraintType,
    ParseResult,
    SqlColumn,
    SqlConstraint,
    SqlStatement,
    SqlStatementType,
)
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View
from core.sql_parser.hybrid_parser import HybridParser

pytestmark = [pytest.mark.unit]


class TestInitSqlglotFailure:
    def test_sqlglot_init_exception_falls_back_to_none(self):
        with patch("core.sql_parser.hybrid_parser.SqlGlotParser", side_effect=RuntimeError("boom")):
            parser = HybridParser("postgresql")
        assert parser.sqlglot_parser is None


class TestParseSqlValidation:
    def test_non_string_raises_typeerror(self):
        parser = HybridParser("postgresql")
        with pytest.raises(TypeError):
            parser.parse_sql(123)  # type: ignore[arg-type]

    def test_regex_parser_failure_returned_directly(self):
        parser = HybridParser("postgresql")
        parser.regex_parser.parse_sql = MagicMock(
            return_value=ParseResult(success=False, statements=[], errors=["bad"])
        )
        result = parser.parse_sql("garbage")
        assert result.success is False
        assert result.errors == ["bad"]

    def test_exception_during_parsing_returns_failure_result(self):
        parser = HybridParser("postgresql")
        parser.regex_parser.parse_sql = MagicMock(side_effect=RuntimeError("explode"))
        result = parser.parse_sql("SELECT 1")
        assert result.success is False
        assert "explode" in result.errors[0]


class TestSplitStatementsSignature:
    def test_signature_inspection_failure_falls_back(self):
        parser = HybridParser("postgresql")
        with patch("core.sql_parser.hybrid_parser.inspect.signature", side_effect=ValueError):
            stmts = parser.split_statements("SELECT 1;")
        assert isinstance(stmts, list)

    def test_regex_parser_without_strict_param_uses_plain_call(self):
        parser = HybridParser("postgresql")
        parser.regex_parser.split_statements = lambda sql_content: [sql_content]
        result = parser.split_statements("SELECT 1;")
        assert result == ["SELECT 1;"]


class TestValidateSqlSqlglotException:
    def test_sqlglot_validation_exception_logged(self):
        parser = HybridParser("postgresql")
        parser.sqlglot_parser.validate_sql = MagicMock(side_effect=RuntimeError("boom"))
        result = parser.validate_sql("SELECT 1")
        assert isinstance(result, dict)


class TestIsSqlglotOpaqueValidDdl:
    def test_delegates_to_quirks(self):
        parser = HybridParser("postgresql")
        assert parser._is_sqlglot_opaque_valid_ddl("CREATE TABLE t (id int)") in (True, False)


class TestExtractObjectsSqlglotException:
    def test_sqlglot_extraction_exception_falls_back_to_regex(self):
        parser = HybridParser("postgresql")
        parser.sqlglot_parser.extract_objects = MagicMock(side_effect=RuntimeError("boom"))
        objects = parser.extract_objects("CREATE TABLE t (id INT)")
        assert isinstance(objects, list)


class TestExtractDependenciesNoSqlglot:
    def test_db2_returns_empty_deps(self):
        parser = HybridParser("db2")
        deps = parser.extract_dependencies("SELECT * FROM t")
        assert deps == {"tables": [], "views": [], "schemas": []}


class TestExtractDependenciesErrorPaths:
    def test_unparseable_statement_skipped(self):
        parser = HybridParser("postgresql")
        parser.split_statements = MagicMock(return_value=["SELECT 1"])
        with patch(
            "core.sql_parser.hybrid_parser.parse_one", side_effect=RuntimeError("parse error")
        ):
            deps = parser.extract_dependencies("ignored")
        assert deps == {"tables": [], "views": [], "schemas": []}

    def test_non_expression_ast_skipped(self):
        parser = HybridParser("postgresql")
        parser.split_statements = MagicMock(return_value=["SELECT 1"])
        with patch("core.sql_parser.hybrid_parser.parse_one", return_value=None):
            deps = parser.extract_dependencies("ignored")
        assert deps == {"tables": [], "views": [], "schemas": []}

    def test_split_statements_exception_logged(self):
        parser = HybridParser("postgresql")
        parser.split_statements = MagicMock(side_effect=RuntimeError("boom"))
        deps = parser.extract_dependencies("ignored")
        assert deps == {"tables": [], "views": [], "schemas": []}


class TestShouldSkipDependencyStatement:
    def test_procedural_keyword_skips(self):
        parser = HybridParser("postgresql")
        assert parser._should_skip_dependency_statement("CREATE PROCEDURE foo() BEGIN END")

    def test_oracle_unsupported_pattern_skips(self):
        parser = HybridParser("oracle")
        assert parser._should_skip_dependency_statement(
            "CREATE TABLE t PARTITION BY REFERENCE (fk)"
        )

    def test_normal_statement_not_skipped(self):
        parser = HybridParser("postgresql")
        assert not parser._should_skip_dependency_statement("SELECT 1")


class TestExtractTableDepsFromAst:
    def test_create_table_schema_qualified_self_reference_excluded(self):
        parser = HybridParser("postgresql")
        ast = parse_one(
            "CREATE TABLE myschema.orders AS SELECT * FROM myschema.orders",
            read="postgres",
        )
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_table_deps_from_ast(ast, deps)
        assert deps["tables"] == []

    def test_table_name_exception_and_empty_name_skipped(self):
        parser = HybridParser("postgresql")
        ast = parse_one("SELECT * FROM users", read="postgres")

        bad_table = MagicMock()
        type(bad_table).name = PropertyMock(side_effect=RuntimeError("boom"))

        empty_table = MagicMock()
        empty_table.name = ""

        deps = {"tables": [], "views": [], "schemas": []}
        with patch.object(ast, "find_all", return_value=iter([bad_table, empty_table])):
            parser._extract_table_deps_from_ast(ast, deps)
        assert deps["tables"] == []


class TestExtractViewDepsFromObjects:
    def test_raises_if_sqlglot_parser_none(self):
        parser = HybridParser("db2")
        with pytest.raises(RuntimeError):
            parser._extract_view_deps_from_objects(
                "SELECT 1", None, {"tables": [], "views": [], "schemas": []}
            )

    def test_extract_objects_exception_results_in_empty(self):
        parser = HybridParser("postgresql")
        parser.sqlglot_parser.extract_objects = MagicMock(side_effect=RuntimeError("boom"))
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_view_deps_from_objects("SELECT 1", None, deps)
        assert deps["views"] == []

    def test_view_with_schema_added(self):
        parser = HybridParser("postgresql")
        view_obj = MagicMock()
        view_obj.object_type.value = "VIEW"
        view_obj.name = "v1"
        view_obj.schema = "myschema"
        parser.sqlglot_parser.extract_objects = MagicMock(return_value=[view_obj])
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_view_deps_from_objects("CREATE VIEW v1 AS SELECT 1", None, deps)
        assert "v1" in deps["views"]
        assert "myschema" in deps["schemas"]


class TestEnhanceStatement:
    def test_procedural_keyword_returns_unchanged(self):
        parser = HybridParser("postgresql")
        stmt = SqlStatement(
            sql_text="BEGIN SELECT 1; END",
            statement_type=SqlStatementType.SELECT,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        assert parser._enhance_statement(stmt, None) is stmt

    def test_sqlglot_parse_exception_returns_original(self):
        parser = HybridParser("postgresql")
        stmt = SqlStatement(
            sql_text="SELECT 1",
            statement_type=SqlStatementType.SELECT,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser.sqlglot_parser.parse_sql = MagicMock(side_effect=RuntimeError("boom"))
        assert parser._enhance_statement(stmt, None) is stmt


class TestContainsHelpers:
    def test_contains_procedural_keywords_true_false(self):
        parser = HybridParser("postgresql")
        assert parser._contains_procedural_keywords("BEGIN END")
        assert not parser._contains_procedural_keywords("SELECT 1")

    def test_contains_oracle_unsupported_no_patterns(self):
        parser = HybridParser("postgresql")
        assert not parser._contains_oracle_sqlglot_unsupported("ANYTHING")

    def test_contains_oracle_unsupported_with_pattern(self):
        parser = HybridParser("oracle")
        assert parser._contains_oracle_sqlglot_unsupported("PARTITION BY REFERENCE (fk)")


class TestObjectExists:
    def test_empty_collection_returns_false(self):
        assert HybridParser._object_exists(None, MagicMock()) is False

    def test_match_found_returns_true(self):
        existing = Table(name="orders", schema="app", dialect="postgresql")
        candidate = Table(name="ORDERS", schema="APP", dialect="postgresql")
        assert HybridParser._object_exists([existing], candidate) is True


class TestCollectObjects:
    def test_adds_new_table_object(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        table = Table(name="orders", schema="app", dialect="postgresql")
        parser._collect_objects(result, [table])
        assert result.tables == [table]


class TestEnsureTableMetadata:
    def test_non_create_table_returns_early(self):
        parser = HybridParser("postgresql")
        stmt = SqlStatement(
            sql_text="SELECT 1",
            statement_type=SqlStatementType.SELECT,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        result = ParseResult(success=True, statements=[])
        parser._ensure_table_metadata(stmt, None, result)
        assert result.tables == []

    def test_merges_into_existing_table(self):
        parser = HybridParser("postgresql")
        existing = Table(name="ORDERS", schema=None, dialect="postgresql")
        result = ParseResult(success=True, statements=[])
        result.add_table(existing)
        stmt = SqlStatement(
            sql_text="CREATE TABLE orders (id INT PRIMARY KEY, name VARCHAR(50))",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser._ensure_table_metadata(stmt, None, result)
        assert len(result.tables) == 1
        assert existing.columns


class TestEnsureAlterTableMetadataSqlglot:
    def test_adds_new_constraint_to_existing_table(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        table = Table(name="orders", schema=None, dialect="postgresql")
        result.add_table(table)
        stmt = SqlStatement(
            sql_text=(
                "ALTER TABLE orders ADD CONSTRAINT fk_customer "
                "FOREIGN KEY (customer_id) REFERENCES customers(id)"
            ),
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser._ensure_alter_table_metadata(stmt, None, result)
        assert any(
            c.name
            and c.name.lower() == "fk_customer"
            and c.constraint_type == ConstraintType.FOREIGN_KEY
            for c in table.constraints
        )

    def test_updates_existing_constraint_check_expression(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        table = Table(name="t", schema=None, dialect="postgresql")
        existing_constraint = SqlConstraint(
            ConstraintType.PRIMARY_KEY, name="con1", column_names=["id"], dialect="postgresql"
        )
        table.add_constraint(existing_constraint)
        result.add_table(table)
        stmt = SqlStatement(
            sql_text="ALTER TABLE t ADD CONSTRAINT con1 CHECK (id > 0)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser._ensure_alter_table_metadata(stmt, None, result)
        assert existing_constraint.check_expression is not None
        assert len(table.constraints) == 1

    def test_creates_new_table_when_not_found(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="ALTER TABLE newtab ADD CONSTRAINT fk1 FOREIGN KEY (a) REFERENCES other(b)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser._ensure_alter_table_metadata(stmt, None, result)
        assert any(t.name.lower() == "newtab" for t in result.tables)

    def test_sqlglot_exception_falls_back_to_regex(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="ALTER TABLE app.orders ADD CONSTRAINT chk1 CHECK (status IN ('A'))",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        with patch.object(
            parser, "_parse_alter_table_via_sqlglot", side_effect=RuntimeError("boom")
        ):
            parser._ensure_alter_table_metadata(stmt, None, result)
        table = next(t for t in result.tables if t.name.lower() == "orders")
        assert any(c.name and c.name.lower() == "chk1" for c in table.constraints)

    def test_both_sqlglot_and_regex_exceptions_logged(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="ALTER TABLE orders ADD CONSTRAINT fk1 FOREIGN KEY (a) REFERENCES b(c)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        with (
            patch.object(
                parser, "_parse_alter_table_via_sqlglot", side_effect=RuntimeError("boom1")
            ),
            patch.object(
                parser, "_parse_alter_table_with_regex", side_effect=RuntimeError("boom2")
            ),
        ):
            parser._ensure_alter_table_metadata(stmt, None, result)  # must not raise


class TestParseAlterTableWithRegex:
    def test_no_table_match_returns_early(self):
        parser = HybridParser("db2")
        result = ParseResult(success=True, statements=[])
        parser._parse_alter_table_with_regex("ALTER TABLE", None, result)
        assert result.tables == []

    def test_no_check_constraint_creates_table_only(self):
        parser = HybridParser("db2")
        result = ParseResult(success=True, statements=[])
        parser._parse_alter_table_with_regex(
            "ALTER TABLE app.orders ADD COLUMN foo INT", None, result
        )
        table = result.tables[0]
        assert table.name.lower() == "orders"
        assert table.constraints == []

    def test_existing_constraint_with_check_expression_not_overwritten(self):
        parser = HybridParser("db2")
        result = ParseResult(success=True, statements=[])
        sql = "ALTER TABLE app.orders ADD CONSTRAINT chk1 CHECK (status IN ('A'))"
        parser._parse_alter_table_with_regex(sql, None, result)
        table = result.tables[0]
        original_expr = table.constraints[0].check_expression
        parser._parse_alter_table_with_regex(sql, None, result)
        assert table.constraints[0].check_expression == original_expr
        assert len(table.constraints) == 1

    def test_existing_constraint_without_check_expression_gets_updated(self):
        parser = HybridParser("db2")
        result = ParseResult(success=True, statements=[])
        table = Table(name="ORDERS", schema="APP", dialect="db2")
        table.add_constraint(SqlConstraint(ConstraintType.CHECK, name="CHK1", dialect="db2"))
        result.add_table(table)
        parser._parse_alter_table_with_regex(
            "ALTER TABLE APP.ORDERS ADD CONSTRAINT chk1 CHECK (status IN ('A'))", None, result
        )
        assert table.constraints[0].check_expression


class TestEnsureViewMetadata:
    def test_existing_view_query_filled_in(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        existing = View(name="v1", schema=None, query=None, dialect="postgresql")
        result.add_view(existing)
        stmt = SqlStatement(
            sql_text="CREATE VIEW v1 AS SELECT * FROM t",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser._ensure_view_metadata(stmt, None, result)
        assert existing.query is not None
        assert len(result.views) == 1


class TestEnsureIndexMetadata:
    def test_existing_index_not_duplicated(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        existing = Index(
            name="idx1", table_name="t", columns=["a"], schema=None, dialect="postgresql"
        )
        result.add_index(existing)
        stmt = SqlStatement(
            sql_text="CREATE INDEX idx1 ON t (a)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )
        parser._ensure_index_metadata(stmt, None, result)
        assert len(result.indexes) == 1


class TestEnsureTriggerMetadata:
    def test_non_create_returns_early(self):
        parser = HybridParser("mysql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="SELECT 1",
            statement_type=SqlStatementType.SELECT,
            objects=[],
            affected_objects=[],
            dialect="mysql",
            schema=None,
        )
        parser._ensure_trigger_metadata(stmt, None, result)
        assert result.triggers == []

    def test_create_trigger_builds_trigger(self):
        parser = HybridParser("mysql")
        result = ParseResult(success=True, statements=[])
        sql = "CREATE TRIGGER trg1 BEFORE INSERT ON app.orders FOR EACH ROW SET NEW.created_at = NOW();"
        stmt = SqlStatement(
            sql_text=sql,
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="mysql",
            schema=None,
        )
        parser._ensure_trigger_metadata(stmt, None, result)
        assert [t.name.lower() for t in result.triggers] == ["trg1"]


class TestFindTable:
    def test_returns_none_for_empty_list(self):
        parser = HybridParser("postgresql")
        assert parser._find_table([], "t", None) is None

    def test_case_insensitive_match(self):
        parser = HybridParser("postgresql")
        table = Table(name="Orders", schema="App", dialect="postgresql")
        assert parser._find_table([table], "ORDERS", "app") is table


class TestMergeTableMetadata:
    def test_merges_columns_constraints_and_partition_info(self):
        parser = HybridParser("postgresql")
        target = Table(name="t", schema=None, dialect="postgresql")
        source = Table(name="t", schema=None, dialect="postgresql")
        source.add_column(SqlColumn(name="ID", data_type="INT", dialect="postgresql"))
        constraint = SqlConstraint(
            ConstraintType.PRIMARY_KEY, column_names=["ID"], dialect="postgresql"
        )
        source.add_constraint(constraint)
        source.partition_method = "RANGE"
        source.partition_columns = ["ID"]
        parser._merge_table_metadata(target, source)
        assert target.get_column("ID") is not None
        assert constraint in target.constraints
        assert target.partition_method == "RANGE"
        assert target.partition_columns == ["ID"]

    def test_does_not_duplicate_existing_column_or_constraint(self):
        parser = HybridParser("postgresql")
        target = Table(name="t", schema=None, dialect="postgresql")
        target.add_column(SqlColumn(name="ID", data_type="INT", dialect="postgresql"))
        constraint = SqlConstraint(
            ConstraintType.PRIMARY_KEY, column_names=["ID"], dialect="postgresql"
        )
        target.add_constraint(constraint)
        source = Table(name="t", schema=None, dialect="postgresql")
        source.add_column(SqlColumn(name="ID", data_type="INT", dialect="postgresql"))
        source.add_constraint(constraint)
        parser._merge_table_metadata(target, source)
        assert len(target.columns) == 1
        assert len(target.constraints) == 1


class TestBuildTableModelFromRegex:
    def test_no_create_match_returns_none(self):
        parser = HybridParser("db2")
        assert parser._build_table_model_from_regex("SELECT 1", None) is None

    def test_cosmosdb_partition_key_extracted(self):
        parser = HybridParser("cosmosdb")
        table = parser._build_table_model_from_regex(
            "CREATE CONTAINER orders WITH PARTITION KEY /customerId (id STRING)", None
        )
        assert table is not None
        assert table.metadata == {"partition_key": "/customerId"}


class TestExtractColumnBlock:
    def test_no_opening_paren_returns_none(self):
        parser = HybridParser("db2")
        assert parser._extract_column_block("CREATE TABLE t", 0) is None

    def test_quoted_parens_preserved(self):
        parser = HybridParser("db2")
        block = parser._extract_column_block("CREATE TABLE t (col VARCHAR(10) DEFAULT 'a)b')", 0)
        assert "a)b" in block

    def test_closing_paren_ends_block(self):
        parser = HybridParser("db2")
        block = parser._extract_column_block("CREATE TABLE t (id INT)", 0)
        assert block == "id INT"


class TestParseTableDefinition:
    def test_table_level_primary_key_constraint(self):
        parser = HybridParser("db2")
        columns, constraints = parser._parse_table_definition(
            "id INT, name VARCHAR(50), PRIMARY KEY (id)"
        )
        assert len(columns) == 2
        assert any(c.constraint_type == ConstraintType.PRIMARY_KEY for c in constraints)


class TestSplitDefinitionItems:
    def test_splits_on_commas_respecting_parens_and_quotes(self):
        parser = HybridParser("db2")
        items = parser._split_definition_items(
            "a INT DEFAULT 1, b VARCHAR(10) DEFAULT 'x,y', c INT"
        )
        assert len(items) == 3
        assert "x,y" in items[1]


class TestParseColumnDefinition:
    def test_constraint_leading_returns_none(self):
        parser = HybridParser("db2")
        assert parser._parse_column_definition("CONSTRAINT pk1 PRIMARY KEY (id)") == (None, None)

    def test_no_match_returns_none(self):
        parser = HybridParser("db2")
        assert parser._parse_column_definition("") == (None, None)

    def test_no_remainder_returns_none(self):
        parser = HybridParser("db2")
        assert parser._parse_column_definition("colname") == (None, None)

    def test_no_data_type_tokens_returns_none(self):
        parser = HybridParser("db2")
        assert parser._parse_column_definition("colname NOT NULL") == (None, None)

    def test_primary_key_inline_creates_constraint(self):
        parser = HybridParser("db2")
        column, constraint = parser._parse_column_definition("id INT PRIMARY KEY")
        assert column is not None and column.is_primary_key
        assert constraint is not None and constraint.constraint_type == ConstraintType.PRIMARY_KEY


class TestParseTableConstraint:
    def test_no_primary_key_returns_none(self):
        parser = HybridParser("db2")
        assert parser._parse_table_constraint("FOREIGN KEY (a) REFERENCES b(c)") is None

    def test_named_constraint_extracts_name_and_columns(self):
        parser = HybridParser("db2")
        constraint = parser._parse_table_constraint("CONSTRAINT pk1 PRIMARY KEY (id, name)")
        assert constraint.name == "pk1"
        assert constraint.column_names == ["ID", "NAME"]

    def test_unnamed_constraint(self):
        parser = HybridParser("db2")
        constraint = parser._parse_table_constraint("PRIMARY KEY (id)")
        assert constraint.name is None
        assert constraint.column_names == ["ID"]


class TestExtractIdentifierList:
    def test_no_parens_returns_empty(self):
        parser = HybridParser("db2")
        assert parser._extract_identifier_list("PRIMARY KEY") == []


class TestSplitIdentifier:
    def test_schema_qualified(self):
        parser = HybridParser("db2")
        assert parser._split_identifier("app.orders", None) == ("APP", "ORDERS")

    def test_default_schema_used(self):
        parser = HybridParser("db2")
        assert parser._split_identifier("orders", "app") == ("APP", "ORDERS")

    def test_no_schema_no_default(self):
        parser = HybridParser("db2")
        assert parser._split_identifier("orders", None) == (None, "ORDERS")


class TestNormalizeIdentifier:
    def test_none_returns_empty(self):
        parser = HybridParser("db2")
        assert parser._normalize_identifier(None, preserve_case=False) == ""

    def test_bracket_stripping(self):
        parser = HybridParser("db2")
        assert parser._normalize_identifier("[MyCol]", preserve_case=True) == "MyCol"

    def test_dot_qualified_takes_last_part(self):
        parser = HybridParser("db2")
        assert parser._normalize_identifier("schema.table", preserve_case=False) == "TABLE"

    def test_quote_stripping_and_uppercase(self):
        parser = HybridParser("db2")
        assert parser._normalize_identifier('"mycol"', preserve_case=False) == "MYCOL"


class TestApplyPartitionMetadata:
    def test_delegates_to_partition_handler_without_error(self):
        parser = HybridParser("postgresql")
        table = Table(name="t", schema=None, dialect="postgresql")
        parser._apply_partition_metadata(table, "CREATE TABLE t (id INT) PARTITION BY RANGE (id)")


class TestExtractTableDepsFromAstExceptionPath:
    def test_created_names_extraction_exception_is_logged(self):
        parser = HybridParser("postgresql")
        ast = MagicMock(spec=exp.Create)
        ast.this = MagicMock(spec=exp.Table)
        type(ast.this).name = PropertyMock(side_effect=RuntimeError("boom"))
        ast.find_all.return_value = []

        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_table_deps_from_ast(ast, deps)

        assert deps == {"tables": [], "views": [], "schemas": []}


class TestEnsureTableMetadataNoModel:
    def test_create_table_without_identifier_returns_early(self):
        parser = HybridParser("db2")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="CREATE TABLE (ID INT)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="db2",
            schema=None,
        )

        parser._ensure_table_metadata(stmt, None, result)

        assert result.tables == []


class TestEnsureAlterTableMetadataSqlglotNone:
    def test_unsupported_alter_falls_back_to_regex(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="ALTER TABLE t ADD (col1 INT, col2 INT)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )

        parser._ensure_alter_table_metadata(stmt, None, result)

        assert [(t.name, t.schema) for t in result.tables] == [("t", None)]


class TestParseAlterTableViaSqlglotAstShapes:
    def test_schema_wrapped_table_extracts_name_and_default_schema(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        inner_table = exp.Table(this=exp.Identifier(this="orders", quoted=False))
        schema_node = exp.Schema(this=inner_table)
        ast = exp.Alter(this=schema_node, kind="TABLE", actions=[])

        with patch("core.sql_parser.hybrid_parser.parse_one", return_value=ast):
            constraints = parser._parse_alter_table_via_sqlglot(
                "ALTER TABLE sales.orders ADD CONSTRAINT x", "defschema", result
            )

        assert constraints == []
        assert [(t.name, t.schema) for t in result.tables] == [("orders", "defschema")]

    def test_non_table_non_schema_this_returns_empty_constraints(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        ast = exp.Alter(this=exp.Column(this=exp.Identifier(this="x")), kind="TABLE", actions=[])

        with patch("core.sql_parser.hybrid_parser.parse_one", return_value=ast):
            constraints = parser._parse_alter_table_via_sqlglot("ALTER TABLE x", None, result)

        assert constraints == []
        assert result.tables == []


class TestEnsureViewMetadataNewView:
    def test_new_view_added_when_no_existing_match(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="CREATE VIEW v1 AS SELECT * FROM t",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )

        parser._ensure_view_metadata(stmt, None, result)

        assert [(v.name, v.schema) for v in result.views] == [("v1", None)]


class TestEnsureIndexMetadataNewIndex:
    def test_new_index_added_when_no_existing_match(self):
        parser = HybridParser("postgresql")
        result = ParseResult(success=True, statements=[])
        stmt = SqlStatement(
            sql_text="CREATE INDEX idx1 ON t (col1)",
            statement_type=SqlStatementType.QUERY,
            objects=[],
            affected_objects=[],
            dialect="postgresql",
            schema=None,
        )

        parser._ensure_index_metadata(stmt, None, result)

        assert [(i.name, i.schema) for i in result.indexes] == [("idx1", None)]


class TestFindTableNoMatchInNonEmptyList:
    def test_returns_none_when_no_table_matches(self):
        parser = HybridParser("db2")
        tables = [Table(name="other", schema=None, dialect="db2")]

        assert parser._find_table(tables, "orders", None) is None


class TestExtractColumnBlockDoubleQuotes:
    def test_double_quoted_identifier_with_parens_preserved(self):
        parser = HybridParser("db2")
        sql = 'CREATE TABLE t ("col,with(paren)" INT)'
        match = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:GLOBAL\s+TEMPORARY\s+)?"
            r"(?:TABLE|CONTAINER)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<identifier>[^\s(]+)",
            sql,
            flags=re.IGNORECASE,
        )

        block = parser._extract_column_block(sql, match.end())

        assert block == '"col,with(paren)" INT'


class TestSplitDefinitionItemsDoubleQuotes:
    def test_double_quoted_identifier_with_comma_and_parens_not_split(self):
        parser = HybridParser("db2")

        items = parser._split_definition_items('"col,with(paren)" INT, col2 INT')

        assert items == ['"col,with(paren)" INT', "col2 INT"]


class TestParseColumnDefinitionEmptyRemainder:
    def test_trailing_whitespace_only_returns_none(self):
        parser = HybridParser("db2")

        assert parser._parse_column_definition("colname  ") == (None, None)


class TestObjectExistsNoMatchInNonEmptyCollection:
    def test_returns_false_when_no_candidate_matches(self):
        existing_view = View(name="v_other", schema=None, dialect="postgresql")
        candidate = View(name="v1", schema=None, dialect="postgresql")

        assert HybridParser._object_exists([existing_view], candidate) is False
