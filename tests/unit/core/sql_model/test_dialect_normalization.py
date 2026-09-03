"""Tests for dialect normalization in SQL model classes (story 19-15).

Verifies that self.dialect is normalized to lowercase in all __init__ constructors,
eliminating the need for .lower() calls throughout the codebase.
"""

import inspect

import pytest

from dblift.core.sql_model.base import (
    SqlColumn,
    SqlConstraint,
    SqlObject,
    SqlObjectType,
    SqlStatement,
)
from dblift.core.sql_model.index import Index
from dblift.core.sql_model.procedure import Parameter


@pytest.mark.unit
class TestSqlObjectDialectNormalization:
    """AC#2 — SqlObject normalizes dialect to lowercase."""

    def test_sql_object_dialect_normalized_to_lowercase(self):
        obj = SqlObject(name="t", object_type=SqlObjectType.TABLE, dialect="ORACLE")
        assert obj.dialect == "oracle"

    def test_sql_object_dialect_none_stays_none(self):
        obj = SqlObject(name="t", object_type=SqlObjectType.TABLE, dialect=None)
        assert obj.dialect is None

    def test_sql_object_dialect_lowercase_idempotent(self):
        obj = SqlObject(name="t", object_type=SqlObjectType.TABLE, dialect="postgresql")
        assert obj.dialect == "postgresql"


@pytest.mark.unit
class TestSqlStatementDialectNormalization:
    """AC#2 — SqlStatement normalizes dialect to lowercase."""

    def test_sql_statement_dialect_normalized(self):
        stmt = SqlStatement(sql_text="SELECT 1", statement_type="SELECT", dialect="MySQL")
        assert stmt.dialect == "mysql"

    def test_sql_statement_dialect_none_stays_none(self):
        stmt = SqlStatement(sql_text="SELECT 1", statement_type="SELECT", dialect=None)
        assert stmt.dialect is None


@pytest.mark.unit
class TestSqlColumnDialectNormalization:
    """AC#2 — SqlColumn normalizes dialect to lowercase."""

    def test_sql_column_dialect_normalized(self):
        col = SqlColumn(name="id", data_type="INT", dialect="PostgreSQL")
        assert col.dialect == "postgresql"

    def test_sql_column_dialect_none_stays_none(self):
        col = SqlColumn(name="id", data_type="INT", dialect=None)
        assert col.dialect is None


@pytest.mark.unit
class TestSqlConstraintDialectNormalization:
    """AC#2 — SqlConstraint normalizes dialect to lowercase."""

    def test_sql_constraint_dialect_normalized(self):
        c = SqlConstraint(name="pk", constraint_type="PRIMARY KEY", dialect="SQLServer")
        assert c.dialect == "sqlserver"

    def test_sql_constraint_dialect_none_stays_none(self):
        c = SqlConstraint(name="pk", constraint_type="PRIMARY KEY", dialect=None)
        assert c.dialect is None


@pytest.mark.unit
class TestParameterDialectNormalization:
    """AC#3 — Parameter normalizes dialect to lowercase."""

    def test_parameter_dialect_normalized(self):
        p = Parameter(name="p", data_type="INT", dialect="DB2")
        assert p.dialect == "db2"

    def test_procedure_propagates_normalized_dialect_to_params(self):
        """M3 fix: Procedure.__init__ doit propager self.dialect (normalisé) aux paramètres."""
        from dblift.core.sql_model.procedure import Procedure

        param = Parameter(name="p", data_type="INT", dialect=None)
        proc = Procedure(name="my_proc", parameters=[param], dialect="ORACLE")
        # self.dialect == "oracle" — les paramètres hérités doivent aussi être "oracle"
        assert proc.parameters[0].dialect == "oracle"


@pytest.mark.unit
class TestIndexSubclassInheritsNormalization:
    """AC#5 — Subclasses inherit normalization from SqlObject."""

    def test_index_subclass_inherits_normalization(self):
        idx = Index(name="idx1", table_name="t", columns=["id"], dialect="Oracle")
        assert idx.dialect == "oracle"


@pytest.mark.unit
class TestNoSelfDialectLowerInSqlModel:
    """AC#5 — Structural test: no self.dialect.lower() remains in core/sql_model/."""

    def test_no_self_dialect_lower_in_sql_model(self):
        """Verify that no source file in core/sql_model/ uses self.dialect.lower()."""
        import dblift.core.sql_model.base as base_mod
        import dblift.core.sql_model.event as event_mod
        import dblift.core.sql_model.index as index_mod
        import dblift.core.sql_model.procedure as proc_mod
        import dblift.core.sql_model.sequence as seq_mod
        import dblift.core.sql_model.synonym as syn_mod
        import dblift.core.sql_model.trigger as trig_mod
        import dblift.core.sql_model.user_defined_type as udt_mod
        import dblift.core.sql_model.view as view_mod

        modules = [
            base_mod,
            event_mod,
            index_mod,
            proc_mod,
            seq_mod,
            syn_mod,
            trig_mod,
            udt_mod,
            view_mod,
        ]

        for mod in modules:
            source = inspect.getsource(mod)
            # Check both patterns: self.dialect.lower() and (self.dialect or "").lower()
            for pattern in ("self.dialect.lower()", '(self.dialect or "").lower()'):
                occurrences = source.count(pattern)
                assert occurrences == 0, (
                    f"{mod.__name__} still contains {occurrences} " f"occurrence(s) of `{pattern}`"
                )
