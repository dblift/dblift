"""Extended unit tests for sql_model base, procedure, and table modules.

Targets uncovered paths in:
- core/sql_model/base.py   (515 stmts, 63%)
- core/sql_model/procedure.py (144 stmts, 42%)
- core/sql_model/table.py  (225 stmts, 61%)
"""

import unittest

from core.sql_model.base import (
    ConstraintType,
    ParseResult,
    SqlColumn,
    SqlConstraint,
    SqlObject,
    SqlObjectType,
    SqlStatement,
    SqlStatementType,
    _norm_constraint_deferrable,
    _norm_constraint_enabled,
    get_constraint_type_name,
    get_object_type_name,
)
from core.sql_model.procedure import Parameter, Procedure
from core.sql_model.table import Table
from core.sql_model.table_options import (
    OracleStorageOptions,
    PostgresTableOptions,
    SqlServerTableOptions,
    TableOptions,
)

# ---------------------------------------------------------------------------
# SqlObject
# ---------------------------------------------------------------------------


class TestSqlObjectStringType(unittest.TestCase):
    """SqlObject accepts string object_type and converts / falls back."""

    def test_valid_string_type_converted(self):
        obj = SqlObject("t", "TABLE")
        self.assertEqual(obj.object_type, SqlObjectType.TABLE)

    def test_unknown_string_type_falls_back(self):
        obj = SqlObject("t", "NONEXISTENT_TYPE")
        self.assertEqual(obj.object_type, SqlObjectType.UNKNOWN)

    def test_case_insensitive_string_type(self):
        obj = SqlObject("t", "view")
        self.assertEqual(obj.object_type, SqlObjectType.VIEW)

    def test_dialect_lowercased(self):
        obj = SqlObject("t", SqlObjectType.TABLE, dialect="PostgreSQL")
        self.assertEqual(obj.dialect, "postgresql")

    def test_none_dialect_stays_none(self):
        obj = SqlObject("t", SqlObjectType.TABLE)
        self.assertIsNone(obj.dialect)

    def test_str_with_schema(self):
        obj = SqlObject("tbl", SqlObjectType.TABLE, schema="myschema")
        s = str(obj)
        self.assertIn("myschema", s)
        self.assertIn("tbl", s)

    def test_str_without_schema(self):
        obj = SqlObject("tbl", SqlObjectType.TABLE)
        s = str(obj)
        self.assertIn("tbl", s)
        self.assertNotIn(".", s)

    def test_equality_case_insensitive_name(self):
        obj1 = SqlObject("MyTable", SqlObjectType.TABLE)
        obj2 = SqlObject("mytable", SqlObjectType.TABLE)
        self.assertEqual(obj1, obj2)

    def test_equality_different_type_returns_false(self):
        obj1 = SqlObject("t", SqlObjectType.TABLE)
        self.assertNotEqual(obj1, "not an SqlObject")

    def test_hash_consistent_with_eq(self):
        obj1 = SqlObject("T", SqlObjectType.TABLE, "S")
        obj2 = SqlObject("t", SqlObjectType.TABLE, "s")
        self.assertEqual(hash(obj1), hash(obj2))
        s = {obj1, obj2}
        self.assertEqual(len(s), 1)

    def test_format_identifier_mysql(self):
        obj = SqlObject("t", SqlObjectType.TABLE, dialect="mysql")
        self.assertEqual(obj.format_identifier("col"), "`col`")

    def test_format_identifier_sqlserver(self):
        obj = SqlObject("t", SqlObjectType.TABLE, dialect="sqlserver")
        self.assertEqual(obj.format_identifier("col"), "[col]")

    def test_format_identifier_default(self):
        obj = SqlObject("t", SqlObjectType.TABLE, dialect="unknown_dialect")
        self.assertEqual(obj.format_identifier("col"), "col")

    def test_format_identifier_empty_string(self):
        obj = SqlObject("t", SqlObjectType.TABLE, dialect="postgresql")
        self.assertEqual(obj.format_identifier(""), "")

    def test_mark_and_check_property_explicit(self):
        obj = SqlObject("t", SqlObjectType.TABLE)
        self.assertFalse(obj.is_property_explicit("foo"))
        obj.mark_property_explicit("foo")
        self.assertTrue(obj.is_property_explicit("foo"))

    def test_is_property_explicit_none_dict(self):
        obj = SqlObject("t", SqlObjectType.TABLE)
        obj.explicit_properties = None
        self.assertFalse(obj.is_property_explicit("bar"))

    def test_compare_with_defaults_type_mismatch(self):
        obj1 = SqlObject("t", SqlObjectType.TABLE)
        obj2 = SqlObject("t", SqlObjectType.VIEW)
        result = obj1.compare_with_defaults(obj2)
        self.assertIn("error", result)

    def test_compare_with_defaults_different_name(self):
        obj1 = SqlObject("table_a", SqlObjectType.TABLE)
        obj2 = SqlObject("table_b", SqlObjectType.TABLE)
        result = obj1.compare_with_defaults(obj2)
        self.assertIn("name", result)

    def test_compare_with_defaults_different_schema(self):
        obj1 = SqlObject("t", SqlObjectType.TABLE, schema="schema_a")
        obj2 = SqlObject("t", SqlObjectType.TABLE, schema="schema_b")
        result = obj1.compare_with_defaults(obj2)
        self.assertIn("schema", result)

    def test_compare_with_defaults_equal_objects(self):
        obj1 = SqlObject("t", SqlObjectType.TABLE, schema="s")
        obj2 = SqlObject("t", SqlObjectType.TABLE, schema="s")
        result = obj1.compare_with_defaults(obj2)
        self.assertNotIn("error", result)
        self.assertNotIn("name", result)
        self.assertNotIn("schema", result)

    def test_compare_with_non_sqlobject(self):
        obj = SqlObject("t", SqlObjectType.TABLE)
        result = obj.compare_with_defaults("not_an_object")
        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# get_object_type_name / get_constraint_type_name
# ---------------------------------------------------------------------------


class TestHelperFunctions(unittest.TestCase):

    def test_get_object_type_name_enum(self):
        obj = SqlObject("t", SqlObjectType.TABLE)
        self.assertEqual(get_object_type_name(obj), "TABLE")

    def test_get_object_type_name_non_enum(self):
        obj = SqlObject("t", SqlObjectType.TABLE)
        obj.object_type = "CUSTOM_TYPE"
        self.assertEqual(get_object_type_name(obj), "CUSTOM_TYPE")

    def test_get_constraint_type_name_enum(self):
        c = SqlConstraint(ConstraintType.PRIMARY_KEY)
        self.assertEqual(get_constraint_type_name(c), "PRIMARY KEY")

    def test_get_constraint_type_name_non_enum(self):
        c = SqlConstraint(ConstraintType.CHECK)
        c.constraint_type = "CUSTOM_CONSTRAINT"
        self.assertEqual(get_constraint_type_name(c), "CUSTOM_CONSTRAINT")

    def test_norm_constraint_enabled_none(self):
        self.assertTrue(_norm_constraint_enabled(None))

    def test_norm_constraint_enabled_explicit(self):
        self.assertFalse(_norm_constraint_enabled(False))
        self.assertTrue(_norm_constraint_enabled(True))

    def test_norm_constraint_deferrable_none(self):
        self.assertFalse(_norm_constraint_deferrable(None))

    def test_norm_constraint_deferrable_explicit(self):
        self.assertTrue(_norm_constraint_deferrable(True))
        self.assertFalse(_norm_constraint_deferrable(False))


# ---------------------------------------------------------------------------
# SqlStatement
# ---------------------------------------------------------------------------


class TestSqlStatement(unittest.TestCase):

    def test_basic_construction(self):
        stmt = SqlStatement("SELECT 1", SqlStatementType.SELECT)
        self.assertEqual(stmt.statement_type, SqlStatementType.SELECT)
        self.assertEqual(stmt.sql_text, "SELECT 1")
        self.assertEqual(stmt.objects, [])
        self.assertEqual(stmt.affected_objects, [])

    def test_string_statement_type_valid(self):
        stmt = SqlStatement("DROP TABLE t", "DROP")
        self.assertEqual(stmt.statement_type, SqlStatementType.DROP)

    def test_string_statement_type_unknown(self):
        stmt = SqlStatement("SOMETHING", "NOTEXISTING")
        self.assertEqual(stmt.statement_type, SqlStatementType.UNKNOWN)

    def test_dialect_lowercased(self):
        stmt = SqlStatement("SELECT 1", SqlStatementType.SELECT, dialect="MySQL")
        self.assertEqual(stmt.dialect, "mysql")

    def test_get_primary_object_empty(self):
        stmt = SqlStatement("SELECT 1", SqlStatementType.SELECT)
        self.assertIsNone(stmt.get_primary_object())

    def test_get_primary_object_returns_first(self):
        obj1 = SqlObject("t1", SqlObjectType.TABLE)
        obj2 = SqlObject("t2", SqlObjectType.TABLE)
        stmt = SqlStatement("SELECT 1", SqlStatementType.SELECT, objects=[obj1, obj2])
        self.assertEqual(stmt.get_primary_object(), obj1)

    def test_str_representation(self):
        stmt = SqlStatement("SELECT 1", SqlStatementType.SELECT)
        s = str(stmt)
        self.assertIn("SELECT", s)


# ---------------------------------------------------------------------------
# SqlColumn
# ---------------------------------------------------------------------------


class TestSqlColumn(unittest.TestCase):

    def test_basic_column(self):
        col = SqlColumn("id", "INT")
        self.assertEqual(col.name, "id")
        self.assertEqual(col.data_type, "INT")
        self.assertTrue(col.nullable)
        self.assertFalse(col.is_primary_key)
        self.assertFalse(col.is_identity)
        self.assertFalse(col.is_computed)

    def test_not_null_str(self):
        col = SqlColumn("id", "INT", is_nullable=False)
        self.assertIn("NOT NULL", str(col))

    def test_nullable_str(self):
        col = SqlColumn("name", "VARCHAR(100)")
        self.assertNotIn("NOT NULL", str(col))

    def test_equality_case_insensitive(self):
        col1 = SqlColumn("MyCol", "INT")
        col2 = SqlColumn("mycol", "int")
        self.assertEqual(col1, col2)

    def test_equality_different_type(self):
        col1 = SqlColumn("col", "INT")
        self.assertNotEqual(col1, "not_a_column")

    def test_equality_with_collation(self):
        col1 = SqlColumn("col", "VARCHAR", collation="utf8mb4_unicode_ci")
        col2 = SqlColumn("col", "VARCHAR", collation="utf8mb4_unicode_ci")
        col3 = SqlColumn("col", "VARCHAR", collation="latin1_swedish_ci")
        self.assertEqual(col1, col2)
        self.assertNotEqual(col1, col3)

    def test_hash_consistent_with_eq(self):
        col1 = SqlColumn("C", "INT")
        col2 = SqlColumn("c", "int")
        self.assertEqual(hash(col1), hash(col2))

    def test_mark_is_property_explicit(self):
        col = SqlColumn("id", "INT")
        self.assertFalse(col.is_property_explicit("nullable"))
        col.mark_property_explicit("nullable")
        self.assertTrue(col.is_property_explicit("nullable"))

    def test_to_dict_round_trip(self):
        col = SqlColumn(
            "id",
            "BIGINT",
            is_nullable=False,
            default_value="0",
            is_primary_key=True,
            is_identity=True,
            identity_seed=1,
            identity_increment=1,
            is_computed=False,
            comment="PK column",
            ordinal_position=1,
            collation="utf8",
            dialect="mysql",
        )
        d = col.to_dict()
        self.assertEqual(d["name"], "id")
        self.assertEqual(d["data_type"], "BIGINT")
        self.assertFalse(d["nullable"])
        self.assertEqual(d["default_value"], "0")
        self.assertTrue(d["is_identity"])
        self.assertEqual(d["identity_seed"], 1)

    def test_from_dict_basic(self):
        data = {"name": "age", "data_type": "INT", "nullable": False}
        col = SqlColumn.from_dict(data)
        self.assertEqual(col.name, "age")
        self.assertEqual(col.data_type, "INT")
        self.assertFalse(col.nullable)

    def test_from_dict_restores_explicit_properties(self):
        data = {
            "name": "x",
            "data_type": "INT",
            "explicit_properties": {"nullable": True, "default_value": False},
        }
        col = SqlColumn.from_dict(data)
        self.assertTrue(col.is_property_explicit("nullable"))
        self.assertFalse(col.is_property_explicit("default_value"))

    def test_identity_fields(self):
        col = SqlColumn(
            "id",
            "INT",
            is_identity=True,
            identity_generation="ALWAYS",
            identity_seed=100,
            identity_increment=5,
        )
        self.assertTrue(col.is_identity)
        self.assertEqual(col.identity_generation, "ALWAYS")
        self.assertEqual(col.identity_seed, 100)
        self.assertEqual(col.identity_increment, 5)

    def test_computed_fields(self):
        col = SqlColumn(
            "total",
            "DECIMAL",
            is_computed=True,
            computed_expression="price * qty",
            computed_stored=True,
        )
        self.assertTrue(col.is_computed)
        self.assertEqual(col.computed_expression, "price * qty")
        self.assertTrue(col.computed_stored)


# ---------------------------------------------------------------------------
# SqlConstraint
# ---------------------------------------------------------------------------


class TestSqlConstraint(unittest.TestCase):

    def test_primary_key_construction(self):
        c = SqlConstraint(ConstraintType.PRIMARY_KEY, name="pk_t", column_names=["id"])
        self.assertEqual(c.constraint_type, ConstraintType.PRIMARY_KEY)
        self.assertEqual(c.name, "pk_t")
        self.assertEqual(c.column_names, ["id"])
        self.assertEqual(c.columns, ["id"])  # alias

    def test_string_constraint_type_valid(self):
        c = SqlConstraint("FOREIGN KEY")
        self.assertEqual(c.constraint_type, ConstraintType.FOREIGN_KEY)

    def test_string_constraint_type_unknown(self):
        c = SqlConstraint("NONEXISTENT")
        self.assertEqual(c.constraint_type, ConstraintType.UNKNOWN)

    def test_str_with_name(self):
        c = SqlConstraint(ConstraintType.UNIQUE, name="uq_email", column_names=["email"])
        s = str(c)
        self.assertIn("uq_email", s)
        self.assertIn("email", s)

    def test_str_without_name(self):
        c = SqlConstraint(ConstraintType.UNIQUE, column_names=["email"])
        s = str(c)
        self.assertIn("email", s)

    def test_equality_basic(self):
        c1 = SqlConstraint(ConstraintType.UNIQUE, name="uq1", column_names=["a", "b"])
        c2 = SqlConstraint(ConstraintType.UNIQUE, name="uq1", column_names=["b", "a"])
        self.assertEqual(c1, c2)  # column order does not matter

    def test_equality_different_type(self):
        c1 = SqlConstraint(ConstraintType.UNIQUE, column_names=["a"])
        self.assertNotEqual(c1, "not_a_constraint")

    def test_equality_different_constraint_type(self):
        c1 = SqlConstraint(ConstraintType.UNIQUE, column_names=["a"])
        c2 = SqlConstraint(ConstraintType.PRIMARY_KEY, column_names=["a"])
        self.assertNotEqual(c1, c2)

    def test_equality_fk_details(self):
        c1 = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        c2 = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        self.assertEqual(c1, c2)

    def test_equality_fk_different_reference_table(self):
        c1 = SqlConstraint(
            ConstraintType.FOREIGN_KEY, column_names=["uid"], reference_table="users"
        )
        c2 = SqlConstraint(
            ConstraintType.FOREIGN_KEY, column_names=["uid"], reference_table="accounts"
        )
        self.assertNotEqual(c1, c2)

    def test_equality_on_delete_action(self):
        c1 = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            column_names=["uid"],
            reference_table="t",
            on_delete="CASCADE",
        )
        c2 = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            column_names=["uid"],
            reference_table="t",
            on_delete="SET NULL",
        )
        self.assertNotEqual(c1, c2)

    def test_equality_check_expression(self):
        c1 = SqlConstraint(ConstraintType.CHECK, check_expression="age > 0")
        c2 = SqlConstraint(ConstraintType.CHECK, check_expression="age > 0")
        c3 = SqlConstraint(ConstraintType.CHECK, check_expression="age > 10")
        self.assertEqual(c1, c2)
        self.assertNotEqual(c1, c3)

    def test_equality_is_enabled_none_vs_true(self):
        """None and True are both treated as 'enabled'."""
        c1 = SqlConstraint(ConstraintType.CHECK, is_enabled=None)
        c2 = SqlConstraint(ConstraintType.CHECK, is_enabled=True)
        self.assertEqual(c1, c2)

    def test_equality_is_enabled_false_differs(self):
        c1 = SqlConstraint(ConstraintType.CHECK, is_enabled=False)
        c2 = SqlConstraint(ConstraintType.CHECK, is_enabled=True)
        self.assertNotEqual(c1, c2)

    def test_equality_deferrable_none_vs_false(self):
        """None and False are both treated as 'not deferrable'."""
        c1 = SqlConstraint(ConstraintType.UNIQUE, is_deferrable=None)
        c2 = SqlConstraint(ConstraintType.UNIQUE, is_deferrable=False)
        self.assertEqual(c1, c2)

    def test_equality_deferrable_true_differs(self):
        c1 = SqlConstraint(ConstraintType.UNIQUE, is_deferrable=True)
        c2 = SqlConstraint(ConstraintType.UNIQUE, is_deferrable=False)
        self.assertNotEqual(c1, c2)

    def test_equality_reference_schema(self):
        c1 = SqlConstraint(ConstraintType.FOREIGN_KEY, column_names=["uid"])
        c2 = SqlConstraint(ConstraintType.FOREIGN_KEY, column_names=["uid"])
        c1.reference_schema = "schema_a"
        c2.reference_schema = "schema_b"
        self.assertNotEqual(c1, c2)

    def test_hash_consistent_with_eq(self):
        c1 = SqlConstraint(ConstraintType.UNIQUE, name="UQ", column_names=["A"])
        c2 = SqlConstraint(ConstraintType.UNIQUE, name="uq", column_names=["a"])
        self.assertEqual(hash(c1), hash(c2))

    def test_mark_and_check_explicit(self):
        c = SqlConstraint(ConstraintType.CHECK)
        self.assertFalse(c.is_property_explicit("check_expression"))
        c.mark_property_explicit("check_expression")
        self.assertTrue(c.is_property_explicit("check_expression"))

    def test_dialect_lowercased(self):
        c = SqlConstraint(ConstraintType.UNIQUE, dialect="MySQL")
        self.assertEqual(c.dialect, "mysql")


# ---------------------------------------------------------------------------
# ParseResult
# ---------------------------------------------------------------------------


class TestParseResult(unittest.TestCase):

    def _make_table(self, name):
        from core.sql_model.table import Table

        return Table(name, columns=[])

    def _make_view(self, name):
        from core.sql_model.view import View

        return View(name)

    def _make_proc(self, name):
        return Procedure(name)

    def _make_trigger(self, name, table_name="t"):
        from core.sql_model.trigger import Trigger

        trig = Trigger(name, table_name=table_name)
        return trig

    def _make_pkg(self, name, schema=None):
        from core.sql_model.package import Package

        return Package(name, schema=schema)

    def test_success_result(self):
        pr = ParseResult(success=True)
        self.assertTrue(bool(pr))
        self.assertEqual(pr.statements, [])
        self.assertEqual(pr.errors, [])

    def test_failure_result(self):
        pr = ParseResult(success=False, errors=["syntax error"])
        self.assertFalse(bool(pr))
        self.assertIn("syntax error", pr.errors)

    def test_add_table(self):
        pr = ParseResult(success=True)
        t = self._make_table("users")
        pr.add_table(t)
        self.assertIn(t, pr.tables)

    def test_get_table_found(self):
        pr = ParseResult(success=True)
        t = self._make_table("Users")
        pr.add_table(t)
        found = pr.get_table("users")
        self.assertEqual(found, t)

    def test_get_table_not_found(self):
        pr = ParseResult(success=True)
        self.assertIsNone(pr.get_table("nobody"))

    def test_add_view(self):
        pr = ParseResult(success=True)
        v = self._make_view("v1")
        pr.add_view(v)
        self.assertIn(v, pr.views)

    def test_get_view_found(self):
        pr = ParseResult(success=True)
        v = self._make_view("MyView")
        pr.add_view(v)
        found = pr.get_view("myview")
        self.assertEqual(found, v)

    def test_get_view_not_found(self):
        pr = ParseResult(success=True)
        self.assertIsNone(pr.get_view("nope"))

    def test_add_index(self):
        pr = ParseResult(success=True)
        from core.sql_model.index import Index

        idx = Index("idx_1", table_name="t", columns=["id"])
        pr.add_index(idx)
        self.assertIn(idx, pr.indexes)

    def test_add_sequence(self):
        pr = ParseResult(success=True)
        from core.sql_model.sequence import Sequence

        seq = Sequence("seq1")
        pr.add_sequence(seq)
        self.assertIn(seq, pr.sequences)

    def test_add_procedure(self):
        pr = ParseResult(success=True)
        p = self._make_proc("sp1")
        pr.add_procedure(p)
        self.assertIn(p, pr.procedures)

    def test_add_trigger_no_duplicate(self):
        pr = ParseResult(success=True)
        trig = self._make_trigger("trg1", "tbl")
        pr.add_trigger(trig)
        pr.add_trigger(trig)  # same trigger added twice
        self.assertEqual(len(pr.triggers), 1)

    def test_add_function_no_duplicate(self):
        pr = ParseResult(success=True)
        fn = Procedure("fn1", schema="public", is_function=True)
        pr.add_function(fn)
        pr.add_function(fn)
        self.assertEqual(len(pr.functions), 1)

    def test_add_synonym(self):
        pr = ParseResult(success=True)
        from core.sql_model.synonym import Synonym

        syn = Synonym("syn1", target_object="other_table")
        pr.add_synonym(syn)
        self.assertIn(syn, pr.synonyms)

    def test_add_user_defined_type(self):
        pr = ParseResult(success=True)
        from core.sql_model.user_defined_type import UserDefinedType

        udt = UserDefinedType("my_type", type_category="OBJECT")
        pr.add_user_defined_type(udt)
        self.assertIn(udt, pr.user_defined_types)

    def test_add_package_deduplication_updates_spec_body(self):
        pr = ParseResult(success=True)
        pkg1 = self._make_pkg("pkg1", "s")
        pkg1.spec = "spec_v1"
        pr.add_package(pkg1)
        # Same package with updated body
        pkg2 = self._make_pkg("PKG1", "S")
        pkg2.spec = None
        pkg2.body = "body_v1"
        pr.add_package(pkg2)
        self.assertEqual(len(pr.packages), 1)
        self.assertEqual(pr.packages[0].body, "body_v1")
        self.assertEqual(pr.packages[0].spec, "spec_v1")

    def test_add_package_new_entry(self):
        pr = ParseResult(success=True)
        pkg1 = self._make_pkg("pkgA")
        pkg2 = self._make_pkg("pkgB")
        pr.add_package(pkg1)
        pr.add_package(pkg2)
        self.assertEqual(len(pr.packages), 2)

    def test_add_event(self):
        pr = ParseResult(success=True)
        from core.sql_model.event import Event

        ev = Event("ev1")
        pr.add_event(ev)
        self.assertIn(ev, pr.events)

    def test_add_extension(self):
        pr = ParseResult(success=True)
        from core.sql_model.extension import Extension

        ext = Extension("pgcrypto")
        pr.add_extension(ext)
        self.assertIn(ext, pr.extensions)

    def test_add_foreign_data_wrapper(self):
        pr = ParseResult(success=True)
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        fdw = ForeignDataWrapper("postgres_fdw")
        pr.add_foreign_data_wrapper(fdw)
        self.assertIn(fdw, pr.foreign_data_wrappers)

    def test_add_foreign_server(self):
        pr = ParseResult(success=True)
        from core.sql_model.foreign_server import ForeignServer

        fs = ForeignServer("remote_server", fdw_name="postgres_fdw")
        pr.add_foreign_server(fs)
        self.assertIn(fs, pr.foreign_servers)

    def test_add_database_link(self):
        pr = ParseResult(success=True)
        from core.sql_model.database_link import DatabaseLink

        dl = DatabaseLink("dblink1")
        pr.add_database_link(dl)
        self.assertIn(dl, pr.database_links)

    def test_add_partition(self):
        pr = ParseResult(success=True)
        from core.sql_model.partition import Partition

        part = Partition("p1", table="t", partition_method="RANGE")
        pr.add_partition(part)
        self.assertIn(part, pr.partitions)

    def test_get_all_objects(self):
        pr = ParseResult(success=True)
        t = self._make_table("t")
        v = self._make_view("v")
        pr.add_table(t)
        pr.add_view(v)
        objects = pr.get_all_objects()
        self.assertIn(t, objects)
        self.assertIn(v, objects)

    def test_add_dependency(self):
        pr = ParseResult(success=True)
        pr.add_dependency("view_a", "table_b")
        pr.add_dependency("view_a", "table_c")
        pr.add_dependency("view_a", "table_b")  # duplicate
        deps = pr.get_dependencies_for("view_a")
        self.assertEqual(sorted(deps), ["table_b", "table_c"])

    def test_get_dependencies_for_unknown_object(self):
        pr = ParseResult(success=True)
        self.assertEqual(pr.get_dependencies_for("x"), [])

    def test_has_circular_dependencies_no_cycle(self):
        pr = ParseResult(success=True)
        pr.add_dependency("a", "b")
        pr.add_dependency("b", "c")
        self.assertFalse(pr.has_circular_dependencies())

    def test_has_circular_dependencies_with_cycle(self):
        pr = ParseResult(success=True)
        pr.add_dependency("a", "b")
        pr.add_dependency("b", "c")
        pr.add_dependency("c", "a")
        self.assertTrue(pr.has_circular_dependencies())

    def test_has_circular_dependencies_empty(self):
        pr = ParseResult(success=True)
        self.assertFalse(pr.has_circular_dependencies())

    def test_get_summary_empty(self):
        pr = ParseResult(success=True)
        self.assertEqual(pr.get_summary(), "Empty result")

    def test_get_summary_with_tables(self):
        pr = ParseResult(success=True)
        pr.add_table(self._make_table("t"))
        summary = pr.get_summary()
        self.assertIn("table", summary)

    def test_get_summary_with_errors(self):
        pr = ParseResult(success=False, errors=["err"])
        summary = pr.get_summary()
        self.assertIn("error", summary)

    def test_get_summary_with_statements(self):
        pr = ParseResult(
            success=True, statements=[SqlStatement("SELECT 1", SqlStatementType.SELECT)]
        )
        summary = pr.get_summary()
        self.assertIn("statement", summary)


# ---------------------------------------------------------------------------
# Parameter
# ---------------------------------------------------------------------------


class TestParameter(unittest.TestCase):

    def test_basic_in_parameter(self):
        p = Parameter("p_name", "VARCHAR(100)")
        self.assertEqual(p.name, "p_name")
        self.assertEqual(p.direction, "IN")
        s = str(p)
        self.assertIn("p_name", s)
        self.assertIn("VARCHAR", s)
        self.assertNotIn("IN ", s)  # IN is suppressed in str output

    def test_out_parameter(self):
        p = Parameter("p_out", "INT", direction="OUT")
        s = str(p)
        self.assertIn("OUT", s)

    def test_inout_parameter(self):
        p = Parameter("p_io", "INT", direction="INOUT")
        s = str(p)
        self.assertIn("INOUT", s)

    def test_sqlserver_inout_becomes_output(self):
        p = Parameter("p_io", "INT", direction="INOUT", dialect="sqlserver")
        s = str(p)
        self.assertIn("OUTPUT", s)

    def test_default_value(self):
        p = Parameter("p", "INT", default_value="42")
        s = str(p)
        self.assertIn("42", s)

    def test_db2_no_default_value(self):
        p = Parameter("p", "INT", default_value="0", dialect="db2")
        s = str(p)
        self.assertNotIn("= 0", s)

    def test_to_dict(self):
        p = Parameter("x", "BIGINT", direction="OUT", default_value="0", dialect="postgresql")
        d = p.to_dict()
        self.assertEqual(d["name"], "x")
        self.assertEqual(d["data_type"], "BIGINT")
        self.assertEqual(d["direction"], "OUT")
        self.assertEqual(d["default_value"], "0")
        self.assertEqual(d["dialect"], "postgresql")

    def test_from_dict(self):
        data = {
            "name": "p",
            "data_type": "INT",
            "direction": "INOUT",
            "default_value": None,
            "dialect": None,
        }
        p = Parameter.from_dict(data)
        self.assertEqual(p.name, "p")
        self.assertEqual(p.direction, "INOUT")

    def test_direction_uppercased(self):
        p = Parameter("p", "INT", direction="inout")
        self.assertEqual(p.direction, "INOUT")


# ---------------------------------------------------------------------------
# Procedure
# ---------------------------------------------------------------------------


class TestProcedure(unittest.TestCase):

    def test_procedure_construction(self):
        proc = Procedure("sp_test", schema="dbo", dialect="sqlserver")
        self.assertEqual(proc.name, "sp_test")
        self.assertEqual(proc.schema, "dbo")
        self.assertFalse(proc.is_function)
        self.assertEqual(proc.object_type, SqlObjectType.PROCEDURE)

    def test_function_construction(self):
        fn = Procedure("fn_test", is_function=True)
        self.assertTrue(fn.is_function)
        self.assertEqual(fn.object_type, SqlObjectType.FUNCTION)

    def test_param_dialect_inherited(self):
        p = Parameter("p1", "INT")
        proc = Procedure("sp1", parameters=[p], dialect="mysql")
        self.assertEqual(proc.parameters[0].dialect, "mysql")

    def test_function_infers_return_type_from_param0(self):
        """If first param starts with param_0 or return_value, it's the return type."""
        p_return = Parameter("param_0", "INT")
        p_actual = Parameter("arg1", "VARCHAR")
        fn = Procedure("fn", is_function=True, parameters=[p_return, p_actual])
        self.assertEqual(fn.return_type, "INT")
        self.assertEqual(len(fn.parameters), 1)
        self.assertEqual(fn.parameters[0].name, "arg1")

    def test_function_infers_return_type_return_value_prefix(self):
        p_return = Parameter("return_value", "BIGINT")
        fn = Procedure("fn", is_function=True, parameters=[p_return])
        self.assertEqual(fn.return_type, "BIGINT")
        self.assertEqual(fn.parameters, [])

    def test_drop_statement_oracle(self):
        proc = Procedure("sp1", dialect="oracle")
        stmt = proc.drop_statement
        self.assertIn("DROP PROCEDURE", stmt)
        self.assertIn("IF EXISTS", stmt)

    def test_drop_statement_non_oracle(self):
        proc = Procedure("sp1", dialect="postgresql")
        stmt = proc.drop_statement
        self.assertIn("IF EXISTS", stmt)

    def test_drop_statement_function(self):
        fn = Procedure("fn1", is_function=True, dialect="postgresql")
        stmt = fn.drop_statement
        self.assertIn("DROP FUNCTION", stmt)

    def test_to_dict(self):
        proc = Procedure(
            "sp1",
            schema="dbo",
            dialect="sqlserver",
            is_function=False,
            language="TSQL",
            body="SELECT 1",
            comment="test",
            volatility="STABLE",
            security_definer=True,
            definer="sa",
            data_access="READS SQL DATA",
        )
        d = proc.to_dict()
        self.assertEqual(d["name"], "sp1")
        self.assertEqual(d["schema"], "dbo")
        self.assertEqual(d["dialect"], "sqlserver")
        self.assertFalse(d["is_function"])
        self.assertEqual(d["language"], "TSQL")
        self.assertEqual(d["security_definer"], True)

    def test_from_dict_procedure(self):
        data = {
            "name": "sp_test",
            "schema": "dbo",
            "dialect": "sqlserver",
            "parameters": [
                {"name": "p1", "data_type": "INT", "direction": "IN", "default_value": None}
            ],
            "body": "SELECT 1",
            "language": "TSQL",
            "is_function": False,
            "return_type": None,
            "comment": None,
            "definition": None,
            "volatility": None,
            "security_definer": None,
            "definer": None,
            "data_access": None,
        }
        proc = Procedure.from_dict(data)
        self.assertEqual(proc.name, "sp_test")
        self.assertEqual(len(proc.parameters), 1)
        self.assertEqual(proc.parameters[0].name, "p1")

    def test_from_dict_function(self):
        data = {
            "name": "fn_test",
            "schema": None,
            "dialect": "postgresql",
            "parameters": [],
            "body": "SELECT 1",
            "language": "SQL",
            "is_function": True,
            "return_type": "INT",
            "comment": None,
            "definition": None,
            "volatility": "STABLE",
            "security_definer": None,
            "definer": None,
            "data_access": None,
        }
        fn = Procedure.from_dict(data)
        self.assertTrue(fn.is_function)
        self.assertEqual(fn.return_type, "INT")


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


class TestTable(unittest.TestCase):

    def _col(self, name, dtype="INT", nullable=True):
        return SqlColumn(name, dtype, is_nullable=nullable)

    def _pk(self, col_names):
        return SqlConstraint(ConstraintType.PRIMARY_KEY, column_names=col_names)

    def _fk(self, col_names, ref_table):
        return SqlConstraint(
            ConstraintType.FOREIGN_KEY, column_names=col_names, reference_table=ref_table
        )

    def test_basic_construction(self):
        t = Table("users")
        self.assertEqual(t.name, "users")
        self.assertEqual(t.columns, [])
        self.assertEqual(t.constraints, [])
        self.assertFalse(t.temporary)

    def test_column_inherits_dialect(self):
        col = SqlColumn("id", "INT")
        t = Table("t", columns=[col], dialect="postgresql")
        self.assertEqual(t.columns[0].dialect, "postgresql")

    def test_constraint_inherits_dialect(self):
        c = SqlConstraint(ConstraintType.PRIMARY_KEY, column_names=["id"])
        t = Table("t", constraints=[c], dialect="mysql")
        self.assertEqual(t.constraints[0].dialect, "mysql")

    def test_add_column(self):
        t = Table("t", dialect="oracle")
        col = SqlColumn("name", "VARCHAR(100)")
        t.add_column(col)
        self.assertIn(col, t.columns)
        self.assertEqual(col.dialect, "oracle")

    def test_get_column_by_name(self):
        col = SqlColumn("Name", "VARCHAR")
        t = Table("t", columns=[col])
        found = t.get_column("name")
        self.assertEqual(found, col)

    def test_get_column_not_found(self):
        t = Table("t")
        self.assertIsNone(t.get_column("missing"))

    def test_add_constraint(self):
        t = Table("t", dialect="postgresql")
        c = SqlConstraint(ConstraintType.UNIQUE, column_names=["email"])
        t.add_constraint(c)
        self.assertIn(c, t.constraints)
        self.assertEqual(c.dialect, "postgresql")

    def test_get_primary_key(self):
        pk = self._pk(["id"])
        fk = self._fk(["user_id"], "users")
        t = Table("orders", constraints=[pk, fk])
        result = t.get_primary_key()
        self.assertEqual(result.constraint_type, ConstraintType.PRIMARY_KEY)

    def test_get_primary_key_none(self):
        t = Table("t")
        self.assertIsNone(t.get_primary_key())

    def test_get_foreign_keys(self):
        pk = self._pk(["id"])
        fk1 = self._fk(["user_id"], "users")
        fk2 = self._fk(["product_id"], "products")
        t = Table("orders", constraints=[pk, fk1, fk2])
        fks = t.get_foreign_keys()
        self.assertEqual(len(fks), 2)

    def test_get_unique_constraints(self):
        uq = SqlConstraint(ConstraintType.UNIQUE, column_names=["email"])
        t = Table("t", constraints=[uq])
        uqs = t.get_unique_constraints()
        self.assertEqual(len(uqs), 1)

    def test_get_check_constraints(self):
        ck = SqlConstraint(ConstraintType.CHECK, check_expression="age > 0")
        t = Table("t", constraints=[ck])
        cks = t.get_check_constraints()
        self.assertEqual(len(cks), 1)

    def test_explicit_tablespace_tracked(self):
        t = Table("t", tablespace="ts1")
        self.assertTrue(t.is_property_explicit("tablespace"))

    def test_no_tablespace_not_explicit(self):
        t = Table("t")
        self.assertFalse(t.is_property_explicit("tablespace"))

    def test_sqlserver_properties_explicit(self):
        t = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(
                sqlserver=SqlServerTableOptions(
                    filegroup="fg1",
                    memory_optimized=True,
                    system_versioned=True,
                    history_table="ht",
                    history_schema="hs",
                    period_start_column="start_col",
                    period_end_column="end_col",
                )
            ),
        )
        self.assertTrue(t.is_property_explicit("filegroup"))
        self.assertTrue(t.is_property_explicit("memory_optimized"))
        self.assertTrue(t.is_property_explicit("system_versioned"))
        self.assertTrue(t.is_property_explicit("history_table"))
        self.assertTrue(t.is_property_explicit("history_schema"))
        self.assertTrue(t.is_property_explicit("period_start_column"))
        self.assertTrue(t.is_property_explicit("period_end_column"))

    def test_compare_with_defaults_non_table(self):
        t = Table("t")
        other = SqlObject("t", SqlObjectType.VIEW)
        result = t.compare_with_defaults(other)
        self.assertIn("error", result)

    def test_compare_with_defaults_tablespace(self):
        t1 = Table("t", tablespace="ts1")
        t2 = Table("t", tablespace="ts2")
        result = t1.compare_with_defaults(t2)
        self.assertIn("tablespace", result)

    def test_compare_with_defaults_temporary(self):
        t1 = Table("t", temporary=True)
        t2 = Table("t", temporary=False)
        result = t1.compare_with_defaults(t2)
        self.assertIn("temporary", result)

    def test_compare_with_defaults_columns_only_in_self(self):
        col_a = self._col("col_a")
        t1 = Table("t", columns=[col_a])
        t2 = Table("t")
        result = t1.compare_with_defaults(t2)
        self.assertIn("columns_only_in_self", result)
        self.assertIn("col_a", result["columns_only_in_self"])

    def test_compare_with_defaults_columns_only_in_other(self):
        col_b = self._col("col_b")
        t1 = Table("t")
        t2 = Table("t", columns=[col_b])
        result = t1.compare_with_defaults(t2)
        self.assertIn("columns_only_in_other", result)

    def test_compare_with_defaults_column_data_type_diff(self):
        col1 = self._col("col", "INT")
        col2 = self._col("col", "BIGINT")
        t1 = Table("t", columns=[col1])
        t2 = Table("t", columns=[col2])
        result = t1.compare_with_defaults(t2)
        self.assertIn("column_differences", result)
        self.assertIn("col", result["column_differences"])

    def test_compare_with_defaults_nullable_explicit(self):
        col1 = self._col("col", "INT", nullable=True)
        col2 = self._col("col", "INT", nullable=False)
        col1.mark_property_explicit("nullable")
        t1 = Table("t", columns=[col1])
        t2 = Table("t", columns=[col2])
        result = t1.compare_with_defaults(t2)
        self.assertIn("column_differences", result)

    def test_compare_with_defaults_sqlserver_filegroup(self):
        t1 = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(sqlserver=SqlServerTableOptions(filegroup="PRIMARY")),
        )
        t2 = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(sqlserver=SqlServerTableOptions(filegroup="SECONDARY")),
        )
        result = t1.compare_with_defaults(t2)
        self.assertIn("filegroup", result)

    def test_compare_with_defaults_sqlserver_memory_optimized(self):
        t1 = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(sqlserver=SqlServerTableOptions(memory_optimized=True)),
        )
        t2 = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(sqlserver=SqlServerTableOptions(memory_optimized=False)),
        )
        result = t1.compare_with_defaults(t2)
        self.assertIn("memory_optimized", result)

    def test_compare_with_defaults_system_versioned_history(self):
        t1 = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(
                sqlserver=SqlServerTableOptions(system_versioned=True, history_table="ht1")
            ),
        )
        t2 = Table.from_options(
            "t",
            dialect="sqlserver",
            options=TableOptions(
                sqlserver=SqlServerTableOptions(system_versioned=True, history_table="ht2")
            ),
        )
        result = t1.compare_with_defaults(t2)
        self.assertIn("history_table", result)

    def test_to_dict_basic(self):
        col = self._col("id")
        col.is_primary_key = True
        pk = self._pk(["id"])
        t = Table(
            "users",
            columns=[col],
            constraints=[pk],
            schema="public",
            temporary=False,
            dialect="postgresql",
        )
        d = t.to_dict()
        self.assertEqual(d["name"], "users")
        self.assertEqual(d["schema"], "public")
        self.assertEqual(len(d["columns"]), 1)
        self.assertEqual(len(d["constraints"]), 1)

    def test_to_dict_with_partition_info(self):
        t = Table("sales")
        t.partition_method = "RANGE"
        t.partition_columns = ["created_at"]
        d = t.to_dict()
        self.assertEqual(d["partition_method"], "RANGE")
        self.assertEqual(d["partition_columns"], ["created_at"])

    def test_from_dict_basic(self):
        data = {
            "name": "orders",
            "schema": "dbo",
            "dialect": "sqlserver",
            "columns": [
                {
                    "name": "id",
                    "data_type": "INT",
                    "nullable": False,
                    "default_value": None,
                    "is_identity": True,
                    "identity_generation": None,
                    "identity_seed": 1,
                    "identity_increment": 1,
                    "is_computed": False,
                    "computed_expression": None,
                    "computed_stored": False,
                    "comment": None,
                    "ordinal_position": 1,
                    "collation": None,
                    "explicit_properties": {},
                }
            ],
            "constraints": [],
            "temporary": False,
            "tablespace": None,
            "comment": None,
            "storage_engine": None,
            "row_format": None,
            "table_collation": None,
            "next_auto_increment": None,
            "create_options": None,
            "filegroup": "PRIMARY",
            "memory_optimized": False,
            "system_versioned": False,
            "history_table": None,
            "history_schema": None,
            "period_start_column": None,
            "period_end_column": None,
            "raw_ddl": None,
            "explicit_properties": {"tablespace": False},
        }
        t = Table.from_dict(data)
        self.assertEqual(t.name, "orders")
        self.assertEqual(len(t.columns), 1)
        self.assertEqual(t.get_dialect_option("sqlserver", "filegroup"), "PRIMARY")

    def test_from_dict_object_type_enum(self):
        """object_type can be an enum value string."""
        data = {
            "name": "t",
            "columns": [],
            "constraints": [],
            "object_type": "TABLE",
            "dialect": None,
        }
        t = Table.from_dict(data)
        self.assertEqual(t.object_type, SqlObjectType.TABLE)

    def test_from_dict_object_type_invalid_falls_back(self):
        data = {
            "name": "t",
            "columns": [],
            "constraints": [],
            "object_type": "INVALID_TYPE",
            "dialect": None,
        }
        t = Table.from_dict(data)
        self.assertEqual(t.object_type, SqlObjectType.TABLE)

    def test_equality_same(self):
        t1 = Table("t", schema="s", dialect="postgresql")
        t2 = Table("t", schema="s", dialect="postgresql")
        self.assertEqual(t1, t2)

    def test_equality_different_name(self):
        t1 = Table("t1")
        t2 = Table("t2")
        self.assertNotEqual(t1, t2)

    def test_equality_different_type(self):
        t = Table("t")
        self.assertNotEqual(t, "not a table")

    def test_inherits_attribute(self):
        t = Table.from_options(
            "child", options=TableOptions(postgres=PostgresTableOptions(inherits=["parent"]))
        )
        self.assertEqual(t.get_dialect_option("postgresql", "inherits", default=[]), ["parent"])

    def test_storage_parameters(self):
        t = Table.from_options(
            "t",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(pctfree=10, pctused=80, initial=64, next=64)
            ),
        )
        self.assertEqual(t.get_dialect_option("oracle", "pctfree"), 10)
        self.assertEqual(t.get_dialect_option("oracle", "pctused"), 80)

    def test_row_security(self):
        t = Table.from_options(
            "t",
            options=TableOptions(
                postgres=PostgresTableOptions(row_security=True, force_row_security=True)
            ),
        )
        self.assertTrue(t.get_dialect_option("postgresql", "row_security", default=False))
        self.assertTrue(t.get_dialect_option("postgresql", "force_row_security", default=False))


if __name__ == "__main__":
    unittest.main()
