"""Unit tests for `db.plugins.oracle.parser._object_extractor` (Phase-Oracle-04)."""

from __future__ import annotations

import pytest

from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.table import Table
from core.sql_model.view import View
from db.plugins.oracle.parser._object_extractor import extract_objects


@pytest.mark.unit
class TestCreateTable:
    def test_unquoted_name_is_upper_cased(self):
        [obj] = extract_objects("CREATE TABLE employees (id NUMBER)")
        assert isinstance(obj, Table)
        assert obj.name == "EMPLOYEES"
        assert obj.schema is None

    def test_quoted_name_preserved(self):
        [obj] = extract_objects('CREATE TABLE "Employees" (id NUMBER)')
        assert obj.name == "Employees"

    def test_alter_and_drop_also_extracted(self):
        sql = "ALTER TABLE t1 ADD col NUMBER; DROP TABLE t2;"
        names = sorted(o.name for o in extract_objects(sql))
        assert names == ["T1", "T2"]

    def test_quoted_schema_and_name_independent(self):
        sql = 'CREATE TABLE "Sch"."Name" (id NUMBER)'
        [obj] = extract_objects(sql)
        assert obj.schema == "Sch"
        assert obj.name == "Name"

    def test_unquoted_schema_and_name_upper_cased(self):
        [obj] = extract_objects("CREATE TABLE sch.name (id NUMBER)")
        assert obj.schema == "SCH"
        assert obj.name == "NAME"

    def test_dollar_and_hash_in_identifier(self):
        [obj] = extract_objects("CREATE TABLE a$b#c (id NUMBER)")
        assert obj.name == "A$B#C"


@pytest.mark.unit
class TestCreateView:
    def test_plain_view(self):
        [obj] = extract_objects("CREATE VIEW v AS SELECT 1 FROM DUAL")
        assert isinstance(obj, View)
        assert obj.name == "V"

    def test_or_replace_view(self):
        [obj] = extract_objects("CREATE OR REPLACE VIEW vw AS SELECT 1 FROM DUAL")
        assert obj.name == "VW"

    def test_noforce_view_name_extracted(self):
        [obj] = extract_objects("CREATE OR REPLACE NOFORCE VIEW vw AS SELECT 1 FROM DUAL")
        assert isinstance(obj, View)
        assert obj.name == "VW"

    def test_force_view_name_extracted(self):
        [obj] = extract_objects("CREATE OR REPLACE FORCE VIEW vw AS SELECT 1 FROM DUAL")
        assert obj.name == "VW"

    def test_editionable_view_name_extracted(self):
        sql = "CREATE OR REPLACE EDITIONABLE VIEW vw AS SELECT 1 FROM DUAL"
        [obj] = extract_objects(sql)
        assert obj.name == "VW"

    def test_noneditionable_view_name_extracted(self):
        sql = "CREATE OR REPLACE NONEDITIONABLE VIEW vw AS SELECT 1 FROM DUAL"
        [obj] = extract_objects(sql)
        assert obj.name == "VW"

    def test_force_editionable_view_combined(self):
        sql = "CREATE OR REPLACE FORCE EDITIONABLE VIEW vw AS SELECT 1 FROM DUAL"
        [obj] = extract_objects(sql)
        assert obj.name == "VW"


@pytest.mark.unit
class TestCreateSequence:
    def test_sequence(self):
        [obj] = extract_objects("CREATE SEQUENCE seq_id START WITH 1")
        assert isinstance(obj, Sequence)
        assert obj.name == "SEQ_ID"


@pytest.mark.unit
class TestCreateProcedureOrFunction:
    def test_procedure(self):
        [obj] = extract_objects("CREATE PROCEDURE p AS BEGIN NULL; END;")
        assert isinstance(obj, Procedure)
        assert obj.name == "P"

    def test_or_replace_procedure(self):
        [obj] = extract_objects("CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;")
        assert obj.name == "P"

    def test_function_is_classified_as_function(self):
        # Fixed in PR-B (ADR-0012 §Follow-ups): FUNCTION now flips the
        # `is_function` flag so `object_type` is SqlObjectType.FUNCTION
        # rather than PROCEDURE.
        [obj] = extract_objects("CREATE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;")
        assert isinstance(obj, Procedure)  # same concrete class, different flag
        assert obj.is_function is True
        assert obj.object_type.value == "FUNCTION"
        assert obj.name == "F"

    def test_or_replace_function_classified_as_function(self):
        sql = "CREATE OR REPLACE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;"
        [obj] = extract_objects(sql)
        assert obj.is_function is True
        assert obj.object_type.value == "FUNCTION"
        assert obj.name == "F"

    def test_procedure_is_not_flagged_as_function(self):
        [obj] = extract_objects("CREATE PROCEDURE p AS BEGIN NULL; END;")
        assert obj.is_function is False
        assert obj.object_type.value == "PROCEDURE"


@pytest.mark.unit
class TestCreateIndex:
    def test_single_column_index(self):
        [obj] = extract_objects("CREATE INDEX idx_t ON t (id)")
        assert isinstance(obj, Index)
        assert obj.name == "IDX_T"
        assert obj.table_name == "T"
        assert obj.columns == ["id"]

    def test_multi_column_index_preserves_column_case(self):
        [obj] = extract_objects("CREATE INDEX idx_t ON t (A, b, C)")
        assert obj.columns == ["A", "b", "C"]

    def test_unique_index(self):
        [obj] = extract_objects("CREATE UNIQUE INDEX idx_u ON t (id)")
        assert obj.name == "IDX_U"

    def test_bitmap_index(self):
        [obj] = extract_objects("CREATE BITMAP INDEX idx_b ON t (id)")
        assert obj.name == "IDX_B"

    def test_quoted_column_name_preserves_case(self):
        [obj] = extract_objects('CREATE INDEX idx_t ON t ("ColA", colB)')
        assert "ColA" in obj.columns
        assert "colB" in obj.columns

    def test_empty_column_entry_skipped(self):
        # Trailing / empty commas must not crash on split()[0].
        [obj] = extract_objects("CREATE INDEX idx ON t (a, , b)")
        assert obj.columns == ["a", "b"]

    def test_schema_qualified_index_and_table(self):
        sql = "CREATE INDEX s1.idx_t ON s2.t (id)"
        [obj] = extract_objects(sql)
        assert obj.schema == "S1"
        assert obj.table_schema == "S2"


@pytest.mark.unit
class TestTemporaryTables:
    """Oracle temporary-table variants (ADR-0012 follow-up fix)."""

    def test_global_temporary_table_name_extracted(self):
        [obj] = extract_objects("CREATE GLOBAL TEMPORARY TABLE t (id NUMBER)")
        assert isinstance(obj, Table)
        assert obj.name == "T"

    def test_global_temporary_qualified_name(self):
        sql = "CREATE GLOBAL TEMPORARY TABLE sch.my_temp (id NUMBER)"
        [obj] = extract_objects(sql)
        assert obj.name == "MY_TEMP"
        assert obj.schema == "SCH"

    def test_private_temporary_table_name_extracted(self):
        # Oracle 18c+ — `PRIVATE TEMPORARY` uses the reserved ``ora$ptt_``
        # prefix but the extractor only cares about the keyword sequence.
        sql = "CREATE PRIVATE TEMPORARY TABLE ora$ptt_t (id NUMBER)"
        [obj] = extract_objects(sql)
        assert isinstance(obj, Table)
        assert obj.name == "ORA$PTT_T"


@pytest.mark.unit
class TestDefaultSchemaPropagation:
    """PR-C (ADR-0012 §Follow-ups): default_schema on unqualified names.

    Legacy behaviour silently dropped the default: ``match.group(1) or
    match.group(2) or default_schema`` was truthy, which entered the
    ``if schema:`` branch where the else-of-else returned ``None``
    because both capture groups were empty. The fallback to
    ``default_schema.upper()`` was unreachable.
    """

    def test_unqualified_table_gets_default_schema_upper_cased(self):
        [obj] = extract_objects("CREATE TABLE t (id NUMBER)", default_schema="scott")
        assert obj.name == "T"
        assert obj.schema == "SCOTT"

    def test_unqualified_view_gets_default_schema(self):
        [obj] = extract_objects("CREATE VIEW v AS SELECT 1 FROM DUAL", default_schema="scott")
        assert obj.schema == "SCOTT"

    def test_unqualified_sequence_gets_default_schema(self):
        [obj] = extract_objects("CREATE SEQUENCE s", default_schema="scott")
        assert obj.schema == "SCOTT"

    def test_unqualified_procedure_gets_default_schema(self):
        [obj] = extract_objects("CREATE PROCEDURE p AS BEGIN NULL; END;", default_schema="scott")
        assert obj.schema == "SCOTT"

    def test_unqualified_function_gets_default_schema(self):
        [obj] = extract_objects(
            "CREATE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;",
            default_schema="scott",
        )
        assert obj.schema == "SCOTT"

    def test_unqualified_index_both_schemas_fill_from_default(self):
        [obj] = extract_objects("CREATE INDEX idx ON t (id)", default_schema="scott")
        assert obj.schema == "SCOTT"
        assert obj.table_schema == "SCOTT"

    def test_default_schema_none_leaves_schema_none(self):
        [obj] = extract_objects("CREATE TABLE t (id NUMBER)")
        assert obj.schema is None

    def test_explicit_schema_overrides_default(self):
        [obj] = extract_objects("CREATE TABLE my_sch.t (id NUMBER)", default_schema="scott")
        assert obj.schema == "MY_SCH"

    def test_quoted_schema_preserved_case_not_overridden(self):
        [obj] = extract_objects('CREATE TABLE "Sch"."T" (id NUMBER)', default_schema="scott")
        assert obj.schema == "Sch"
        assert obj.name == "T"

    def test_index_mixed_qualified_table_and_unqualified_index(self):
        # Index name is unqualified → picks up default; table is
        # qualified → uses its own schema.
        [obj] = extract_objects("CREATE INDEX idx ON my_sch.t (id)", default_schema="scott")
        assert obj.schema == "SCOTT"
        assert obj.table_schema == "MY_SCH"


@pytest.mark.unit
class TestEdgeCases:
    def test_empty_input(self):
        assert extract_objects("") == []

    def test_plain_select_yields_nothing(self):
        assert extract_objects("SELECT * FROM employees") == []

    def test_multi_statement_input(self):
        sql = (
            "CREATE TABLE t1 (id NUMBER);\n"
            "CREATE VIEW v1 AS SELECT * FROM t1;\n"
            "CREATE SEQUENCE s1;\n"
            "CREATE INDEX idx1 ON t1 (id);"
        )
        names = sorted(o.name for o in extract_objects(sql))
        assert names == ["IDX1", "S1", "T1", "V1"]

    def test_returns_a_list(self):
        result = extract_objects("CREATE TABLE t (id NUMBER)")
        assert isinstance(result, list)
