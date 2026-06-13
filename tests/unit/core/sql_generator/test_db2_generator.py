"""Tests for DB2SqlGenerator class."""

from unittest.mock import MagicMock

import pytest

from core.sql_model.base import SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from db.plugins.db2.generator.ddl_generator import DB2SqlGenerator


@pytest.mark.unit
class TestDB2SqlGeneratorInit:
    """Tests for DB2SqlGenerator initialization."""

    def test_init(self):
        """Test initialization."""
        generator = DB2SqlGenerator()
        assert generator is not None


@pytest.mark.unit
class TestDB2SqlGeneratorAdditionalStatements:
    """Tests for _generate_additional_statements method."""

    def test_generate_additional_statements_check_constraints(self):
        """Test generating additional ALTER TABLE for CHECK constraints."""
        generator = DB2SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        table.generate_alter_table_check_constraints = MagicMock(
            return_value=["ALTER TABLE users ADD CONSTRAINT ck_age CHECK (age >= 0)"]
        )
        result = generator._generate_additional_statements(table, "db2")
        assert len(result) > 0
        assert "ALTER TABLE" in result[0].upper()

    def test_generate_additional_statements_self_referencing_fk(self):
        """Test generating additional ALTER TABLE for self-referencing FKs."""
        generator = DB2SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        table.generate_alter_table_self_referencing_foreign_keys = MagicMock(
            return_value=[
                "ALTER TABLE users ADD CONSTRAINT fk_manager FOREIGN KEY (manager_id) REFERENCES users(id)"
            ]
        )
        result = generator._generate_additional_statements(table, "db2")
        assert len(result) > 0
        assert "FOREIGN KEY" in result[0].upper()

    def test_generate_additional_statements_both(self):
        """Test generating both CHECK constraints and self-referencing FKs."""
        generator = DB2SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        table.generate_alter_table_check_constraints = MagicMock(
            return_value=["ALTER TABLE users ADD CONSTRAINT ck_age CHECK (age >= 0)"]
        )
        table.generate_alter_table_self_referencing_foreign_keys = MagicMock(
            return_value=[
                "ALTER TABLE users ADD CONSTRAINT fk_manager FOREIGN KEY (manager_id) REFERENCES users(id)"
            ]
        )
        result = generator._generate_additional_statements(table, "db2")
        assert len(result) == 2

    def test_generate_additional_statements_no_methods(self):
        """Test when object has no additional statement methods."""
        generator = DB2SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        result = generator._generate_additional_statements(table, "db2")
        assert result == []

    def test_generate_additional_statements_wrong_dialect(self):
        """Test when dialect is not db2."""
        generator = DB2SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.generate_alter_table_check_constraints = MagicMock(
            return_value=["ALTER TABLE users..."]
        )
        result = generator._generate_additional_statements(table, "postgresql")
        assert result == []


@pytest.mark.unit
class TestDB2SqlGeneratorFormatStatements:
    """Tests for _format_statements method."""

    def test_format_statements_empty(self):
        """Test formatting empty statements list."""
        generator = DB2SqlGenerator()
        result = generator._format_statements([], "db2")
        assert result == ""

    def test_format_statements_single(self):
        """Test formatting single statement."""
        generator = DB2SqlGenerator()
        statements = ["CREATE TABLE users (id INT)"]
        result = generator._format_statements(statements, "db2")
        assert result == "CREATE TABLE users (id INT)"

    def test_format_statements_multiple(self):
        """Test formatting multiple statements."""
        generator = DB2SqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "db2")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result
        assert "\n\n" in result

    def test_format_statements_filters_empty(self):
        """Test filtering empty statements."""
        generator = DB2SqlGenerator()
        statements = ["CREATE TABLE users (id INT)", "", "   ", "CREATE TABLE orders (id INT)"]
        result = generator._format_statements(statements, "db2")
        assert "CREATE TABLE users" in result
        assert "CREATE TABLE orders" in result


@pytest.mark.unit
class TestDB2SqlGeneratorDropStatement:
    """Tests for _generate_drop_statement method."""

    def test_generate_drop_statement_table(self):
        """Test generating DROP TABLE statement."""
        generator = DB2SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="db2")
        result = generator._generate_drop_statement(table, "db2")
        assert "DROP TABLE" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_drop_statement_table_with_schema(self):
        """Test generating DROP TABLE with schema."""
        generator = DB2SqlGenerator()
        table = Table(
            name="users", schema="myschema", columns=[SqlColumn("id", "INTEGER")], dialect="db2"
        )
        result = generator._generate_drop_statement(table, "db2")
        assert "DROP TABLE" in result.upper()
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_drop_statement_view(self):
        """Test generating DROP VIEW statement."""
        generator = DB2SqlGenerator()
        view = View(name="active_users", query="SELECT 1", dialect="db2")
        result = generator._generate_drop_statement(view, "db2")
        assert "DROP VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_drop_statement_index(self):
        """Test generating DROP INDEX statement."""
        generator = DB2SqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="db2")
        result = generator._generate_drop_statement(index, "db2")
        assert "DROP INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_drop_statement_sequence(self):
        """Test generating DROP SEQUENCE statement."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", dialect="db2")
        result = generator._generate_drop_statement(sequence, "db2")
        assert "DROP SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_drop_statement_procedure(self):
        """Test generating DROP PROCEDURE statement."""
        generator = DB2SqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN END", dialect="db2")
        result = generator._generate_drop_statement(procedure, "db2")
        assert "DROP PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result

    def test_generate_drop_statement_function(self):
        """Test generating DROP FUNCTION statement."""
        generator = DB2SqlGenerator()
        function = Procedure(name="func_test", body="RETURN 1", is_function=True, dialect="db2")
        result = generator._generate_drop_statement(function, "db2")
        assert "DROP FUNCTION" in result.upper()
        assert "func_test" in result.lower() or '"func_test"' in result

    def test_generate_drop_statement_trigger(self):
        """Test generating DROP TRIGGER statement."""
        generator = DB2SqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="db2")
        result = generator._generate_drop_statement(trigger, "db2")
        assert "DROP TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_drop_statement_fallback(self):
        """Test generating DROP statement fallback."""
        generator = DB2SqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_drop_statement(obj, "db2")
        assert "DROP UNKNOWN_TYPE" in result.upper()


@pytest.mark.unit
class TestDB2SqlGeneratorCreateStatement:
    """Tests for generate_create_statement method."""

    def test_generate_create_statement_view(self):
        """Test generating CREATE VIEW statement."""
        generator = DB2SqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="db2")
        result = generator.generate_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result

    def test_generate_create_statement_index(self):
        """Test generating CREATE INDEX statement."""
        generator = DB2SqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="db2")
        result = generator.generate_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result

    def test_generate_create_statement_procedure(self):
        """Test generating CREATE PROCEDURE statement."""
        generator = DB2SqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="db2")
        result = generator.generate_create_statement(procedure)
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result

    def test_generate_create_statement_table(self):
        """Test generating CREATE TABLE statement."""
        generator = DB2SqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="db2",
        )
        result = generator.generate_create_statement(table)
        assert "CREATE TABLE" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_create_statement_synonym(self):
        """Test generating CREATE ALIAS statement."""
        generator = DB2SqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="db2")
        result = generator.generate_create_statement(synonym)
        assert "CREATE ALIAS" in result.upper()
        assert "syn_test" in result.lower() or '"syn_test"' in result

    def test_generate_create_statement_sequence(self):
        """Test generating CREATE SEQUENCE statement."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", dialect="db2")
        result = generator.generate_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_create_statement_user_defined_type(self):
        """Test generating CREATE DISTINCT TYPE statement."""
        generator = DB2SqlGenerator()
        udt = UserDefinedType(
            name="status_type", type_category="DISTINCT", base_type="VARCHAR(50)", dialect="db2"
        )
        result = generator.generate_create_statement(udt)
        assert "CREATE DISTINCT TYPE" in result.upper()
        assert "status_type" in result.lower() or '"status_type"' in result

    def test_generate_create_statement_trigger(self):
        """Test generating CREATE TRIGGER statement."""
        generator = DB2SqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="db2")
        result = generator.generate_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result

    def test_generate_create_statement_fallback(self):
        """Test generating CREATE statement fallback."""
        generator = DB2SqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator.generate_create_statement(obj)
        assert "CREATE UNKNOWN_TYPE" in result.upper()


@pytest.mark.unit
class TestDB2SqlGeneratorViewCreate:
    """Tests for _generate_view_create_statement method."""

    def test_generate_view_create_statement_simple(self):
        """Test generating simple CREATE VIEW statement."""
        generator = DB2SqlGenerator()
        view = View(name="active_users", query="SELECT id FROM users", dialect="db2")
        result = generator._generate_view_create_statement(view)
        assert "CREATE VIEW" in result.upper()
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "SELECT id FROM users" in result

    def test_generate_view_create_statement_with_schema(self):
        """Test generating CREATE VIEW with schema."""
        generator = DB2SqlGenerator()
        view = View(name="active_users", schema="myschema", query="SELECT 1", dialect="db2")
        result = generator._generate_view_create_statement(view)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_view_create_statement_with_columns(self):
        """Test generating CREATE VIEW with column list."""
        generator = DB2SqlGenerator()
        view = View(
            name="active_users",
            columns=["id", "name"],
            query="SELECT id, name FROM users",
            dialect="db2",
        )
        result = generator._generate_view_create_statement(view)
        assert "active_users" in result.lower() or '"active_users"' in result
        assert "id" in result.lower() or '"id"' in result


@pytest.mark.unit
class TestDB2SqlGeneratorIndexCreate:
    """Tests for _generate_index_create_statement method."""

    def test_generate_index_create_statement_simple(self):
        """Test generating simple CREATE INDEX statement."""
        generator = DB2SqlGenerator()
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="db2")
        result = generator._generate_index_create_statement(index)
        assert "CREATE INDEX" in result.upper()
        assert "idx_email" in result.lower() or '"idx_email"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_index_create_statement_unique(self):
        """Test generating CREATE UNIQUE INDEX statement."""
        generator = DB2SqlGenerator()
        index = Index(
            name="idx_email", table_name="users", columns=["email"], unique=True, dialect="db2"
        )
        result = generator._generate_index_create_statement(index)
        assert "CREATE UNIQUE INDEX" in result.upper()

    def test_generate_index_create_statement_with_schema(self):
        """Test generating CREATE INDEX with schema."""
        generator = DB2SqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            schema="myschema",
            columns=["email"],
            dialect="db2",
        )
        result = generator._generate_index_create_statement(index)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_index_create_statement_with_table_schema(self):
        """Test generating CREATE INDEX with table schema."""
        generator = DB2SqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            table_schema="myschema",
            columns=["email"],
            dialect="db2",
        )
        result = generator._generate_index_create_statement(index)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_index_create_statement_with_expression(self):
        """Test generating CREATE INDEX with expression."""
        generator = DB2SqlGenerator()
        index = Index(
            name="idx_expr",
            table_name="users",
            columns=["UPPER(email)"],
            expression_flags=[True],
            dialect="db2",
        )
        result = generator._generate_index_create_statement(index)
        assert "UPPER(email)" in result

    def test_generate_index_create_statement_with_sort_direction(self):
        """Test generating CREATE INDEX with sort direction."""
        generator = DB2SqlGenerator()
        index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            sort_directions=["DESC"],
            dialect="db2",
        )
        result = generator._generate_index_create_statement(index)
        assert "DESC" in result.upper()


@pytest.mark.unit
class TestDB2SqlGeneratorProcedureCreate:
    """Tests for _generate_procedure_create_statement method."""

    def test_generate_procedure_create_statement_with_definition(self):
        """Test generating CREATE PROCEDURE from definition."""
        generator = DB2SqlGenerator()
        procedure = Procedure(
            name="proc_test",
            body="BEGIN SELECT 1 END",
            definition="CREATE PROCEDURE proc_test AS BEGIN SELECT 1 END",
            dialect="db2",
        )
        result = generator._generate_procedure_create_statement(procedure)
        # When definition is provided, it's returned as-is
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower()

    def test_generate_procedure_create_statement_simple(self):
        """Test generating simple CREATE PROCEDURE statement."""
        generator = DB2SqlGenerator()
        procedure = Procedure(name="proc_test", body="BEGIN SELECT 1 END", dialect="db2")
        result = generator._generate_procedure_create_statement(procedure)
        assert "CREATE PROCEDURE" in result.upper()
        assert "proc_test" in result.lower() or '"proc_test"' in result
        assert "BEGIN" in result.upper()
        assert "SELECT 1" in result

    def test_generate_procedure_create_statement_with_schema(self):
        """Test generating CREATE PROCEDURE with schema."""
        generator = DB2SqlGenerator()
        procedure = Procedure(
            name="proc_test", schema="myschema", body="BEGIN SELECT 1 END", dialect="db2"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "myschema" in result.lower() or '"myschema"' in result

    def test_generate_procedure_create_statement_with_parameters(self):
        """Test generating CREATE PROCEDURE with parameters."""
        generator = DB2SqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="id", data_type="INT")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SELECT id END", dialect="db2"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "id" in result.lower() or '"id"' in result
        assert "INT" in result.upper()

    def test_generate_procedure_create_statement_with_output_parameter(self):
        """Test generating CREATE PROCEDURE with OUTPUT parameter."""
        generator = DB2SqlGenerator()
        from core.sql_model.procedure import Parameter

        param = Parameter(name="result", data_type="INT", direction="OUT")
        procedure = Procedure(
            name="proc_test", parameters=[param], body="BEGIN SET result = 1 END", dialect="db2"
        )
        result = generator._generate_procedure_create_statement(procedure)
        assert "OUT" in result.upper()

    def test_generate_procedure_create_statement_function(self):
        """Test generating CREATE FUNCTION statement."""
        generator = DB2SqlGenerator()
        function = Procedure(
            name="func_test", body="RETURN 1", is_function=True, return_type="INT", dialect="db2"
        )
        result = generator._generate_procedure_create_statement(function)
        assert "CREATE FUNCTION" in result.upper()
        assert "RETURNS INT" in result.upper()

    def test_generate_procedure_create_statement_system_function(self):
        """Test skipping system functions."""
        generator = DB2SqlGenerator()
        function = Procedure(name="<", is_function=True, dialect="db2")
        result = generator._generate_procedure_create_statement(function)
        assert result == ""


@pytest.mark.unit
class TestDB2SqlGeneratorSynonymCreate:
    """Tests for _generate_synonym_create_statement method."""

    def test_generate_synonym_create_statement_simple(self):
        """Test generating simple CREATE ALIAS statement."""
        generator = DB2SqlGenerator()
        synonym = Synonym(name="syn_test", target_object="users", dialect="db2")
        result = generator._generate_synonym_create_statement(synonym)
        assert "CREATE ALIAS" in result.upper()
        assert "syn_test" in result.lower() or '"syn_test"' in result
        assert "FOR" in result.upper()

    def test_generate_synonym_create_statement_with_schema(self):
        """Test generating CREATE ALIAS with schema."""
        generator = DB2SqlGenerator()
        synonym = Synonym(name="syn_test", schema="myschema", target_object="users", dialect="db2")
        result = generator._generate_synonym_create_statement(synonym)
        assert "myschema" in result.lower() or '"myschema"' in result


@pytest.mark.unit
class TestDB2SqlGeneratorSequenceCreate:
    """Tests for _generate_sequence_create_statement method."""

    def test_generate_sequence_create_statement_simple(self):
        """Test generating simple CREATE SEQUENCE statement."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CREATE SEQUENCE" in result.upper()
        assert "seq_id" in result.lower() or '"seq_id"' in result

    def test_generate_sequence_create_statement_with_start(self):
        """Test generating CREATE SEQUENCE with START WITH."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", start_with=100, dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "START WITH 100" in result.upper()

    def test_generate_sequence_create_statement_with_increment(self):
        """Test generating CREATE SEQUENCE with INCREMENT BY."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", increment_by=2, dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "INCREMENT BY 2" in result.upper()

    def test_generate_sequence_create_statement_with_min_max(self):
        """Test generating CREATE SEQUENCE with MINVALUE and MAXVALUE."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", min_value=1, max_value=1000, dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "MINVALUE 1" in result.upper()
        assert "MAXVALUE 1000" in result.upper()

    def test_generate_sequence_create_statement_with_cycle(self):
        """Test generating CREATE SEQUENCE with CYCLE."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", cycle=True, dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CYCLE" in result.upper()

    def test_generate_sequence_create_statement_nocycle(self):
        """Test generating CREATE SEQUENCE with NOCYCLE."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", cycle=False, dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "NOCYCLE" in result.upper()

    def test_generate_sequence_create_statement_with_cache(self):
        """Test generating CREATE SEQUENCE with CACHE."""
        generator = DB2SqlGenerator()
        sequence = Sequence(name="seq_id", cache=10, dialect="db2")
        result = generator._generate_sequence_create_statement(sequence)
        assert "CACHE 10" in result.upper()


@pytest.mark.unit
class TestDB2SqlGeneratorUserDefinedTypeCreate:
    """Tests for _generate_user_defined_type_create_statement method."""

    def test_generate_user_defined_type_create_statement_composite(self):
        """Test generating CREATE TYPE for composite type."""
        generator = DB2SqlGenerator()
        udt = UserDefinedType(
            name="address_type",
            type_category="COMPOSITE",
            attributes=[
                {"name": "street", "type": "VARCHAR(100)"},
                {"name": "city", "type": "VARCHAR(50)"},
            ],
            dialect="db2",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS (" in result.upper()
        assert "MODE DB2SQL" in result.upper()
        assert "street" in result.lower()
        assert "city" in result.lower()

    def test_generate_user_defined_type_create_statement_enum(self):
        """Test generating CREATE DISTINCT TYPE for ENUM type."""
        generator = DB2SqlGenerator()
        udt = UserDefinedType(
            name="status_enum",
            type_category="ENUM",
            enum_values=["active", "inactive"],
            dialect="db2",
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE DISTINCT TYPE" in result.upper()
        assert "AS VARCHAR" in result.upper()
        assert "active" in result.lower()
        assert "inactive" in result.lower()

    def test_generate_user_defined_type_create_statement_distinct(self):
        """Test generating CREATE DISTINCT TYPE for distinct type."""
        generator = DB2SqlGenerator()
        udt = UserDefinedType(
            name="status_type", type_category="DISTINCT", base_type="VARCHAR(50)", dialect="db2"
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE DISTINCT TYPE" in result.upper()
        assert "AS VARCHAR(50)" in result.upper()

    def test_generate_user_defined_type_create_statement_with_definition(self):
        """Test generating CREATE TYPE with definition."""
        generator = DB2SqlGenerator()
        udt = UserDefinedType(
            name="custom_type", type_category="DISTINCT", definition="VARCHAR(100)", dialect="db2"
        )
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "AS VARCHAR(100)" in result.upper()

    def test_generate_user_defined_type_create_statement_fallback(self):
        """Test generating CREATE TYPE fallback."""
        generator = DB2SqlGenerator()
        udt = UserDefinedType(name="custom_type", type_category="UNKNOWN", dialect="db2")
        result = generator._generate_user_defined_type_create_statement(udt)
        assert "CREATE TYPE" in result.upper()
        assert "custom_type" in result.lower() or '"custom_type"' in result


@pytest.mark.unit
class TestDB2SqlGeneratorTriggerCreate:
    """Tests for _generate_trigger_create_statement method."""

    def test_generate_trigger_create_statement_with_definition(self):
        """Test generating CREATE TRIGGER from definition."""
        generator = DB2SqlGenerator()
        trigger = Trigger(
            name="trg_insert",
            table_name="users",
            events=["INSERT"],
            definition="CREATE TRIGGER trg_insert BEFORE INSERT ON users FOR EACH ROW BEGIN SELECT 1; END",
            dialect="db2",
        )
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()

    def test_generate_trigger_create_statement_simple(self):
        """Test generating simple CREATE TRIGGER statement."""
        generator = DB2SqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="db2")
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "CREATE TRIGGER" in result.upper()
        assert "trg_insert" in result.lower() or '"trg_insert"' in result
        assert "ON" in result.upper()
        assert "users" in result.lower() or '"users"' in result

    def test_generate_trigger_create_statement_with_timing(self):
        """Test generating CREATE TRIGGER with timing."""
        generator = DB2SqlGenerator()
        trigger = Trigger(
            name="trg_insert", table_name="users", events=["INSERT"], timing="AFTER", dialect="db2"
        )
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "AFTER" in result.upper()

    def test_generate_trigger_create_statement_with_orientation(self):
        """Test generating CREATE TRIGGER with FOR EACH ROW."""
        generator = DB2SqlGenerator()
        trigger = Trigger(name="trg_insert", table_name="users", events=["INSERT"], dialect="db2")
        trigger.orientation = "ROW"
        trigger.definition = "SELECT 1;"
        result = generator._generate_trigger_create_statement(trigger)
        assert "FOR EACH ROW" in result.upper()


@pytest.mark.unit
class TestDB2SqlGeneratorBasicCreate:
    """Tests for _generate_basic_create_statement method."""

    def test_generate_basic_create_statement(self):
        """Test generating basic CREATE statement."""
        generator = DB2SqlGenerator()
        obj = MagicMock()
        obj.schema = None
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_basic_create_statement(obj)
        assert "CREATE UNKNOWN_TYPE" in result.upper()
        assert "test_obj" in result.lower()

    def test_generate_basic_create_statement_with_schema(self):
        """Test generating basic CREATE statement with schema."""
        generator = DB2SqlGenerator()
        obj = MagicMock()
        obj.schema = "myschema"
        obj.name = "test_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "UNKNOWN_TYPE"
        result = generator._generate_basic_create_statement(obj)
        assert "myschema" in result.lower()
        assert "test_obj" in result.lower()


@pytest.mark.unit
class TestDB2CreateDispatch:
    """Test _get_create_dispatch registry for DB2."""

    def test_get_create_dispatch_contains_expected_types(self):
        """Verify dispatch contains all 8 DB2 types."""
        from core.sql_model.index import Index
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        generator = DB2SqlGenerator()
        dispatch = generator._get_create_dispatch()
        assert View in dispatch
        assert Index in dispatch
        assert Procedure in dispatch
        assert Table in dispatch
        assert Synonym in dispatch
        assert Sequence in dispatch
        assert UserDefinedType in dispatch
        assert Trigger in dispatch
        assert len(dispatch) == 8

    def test_generate_create_statement_dispatches_view(self):
        """generate_create_statement routes View to _generate_view_create_statement."""
        from unittest.mock import patch

        from core.sql_model.view import View

        gen = DB2SqlGenerator()
        view = View(name="test_view", dialect="db2")
        with patch.object(
            gen, "_generate_view_create_statement", return_value="DB2_VIEW_SQL"
        ) as mock:
            result = gen.generate_create_statement(view)
        mock.assert_called_once_with(view)
        assert result == "DB2_VIEW_SQL"

    def test_generate_create_fallback_delegates_to_basic(self):
        """Verify DB2 fallback delegates to _generate_basic_create_statement."""
        generator = DB2SqlGenerator()
        obj = MagicMock()
        obj.schema = "myschema"
        obj.name = "unknown_obj"
        obj.format_identifier = lambda x: x
        obj.object_type = "CUSTOM"
        result = generator._generate_create_fallback(obj)
        assert result == "CREATE CUSTOM myschema.unknown_obj"
