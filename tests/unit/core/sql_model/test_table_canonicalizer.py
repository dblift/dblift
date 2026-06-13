"""Tests for core.sql_model.table_canonicalizer.

The canonicalizer normalizes constraint default-flag values so snapshot-loaded
and live-introspected Tables produce identical DDL when semantically equivalent.

Mirrors comparator equality semantics in core.sql_model.base:
- is_deferrable, initially_deferred: default False -> None
- is_enabled, is_validated:          default True  -> None
"""

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.sql_model.table_canonicalizer import TableCanonicalizer


def _col(name="id", data_type="int4", **kwargs):
    return SqlColumn(name=name, data_type=data_type, **kwargs)


def _constraint(ctype=ConstraintType.PRIMARY_KEY, name="pk", columns=None, **kwargs):
    return SqlConstraint(
        constraint_type=ctype,
        name=name,
        column_names=columns or ["id"],
        **kwargs,
    )


def _table(constraints=None, columns=None, name="t"):
    return Table(name=name, columns=columns or [_col()], constraints=constraints or [])


@pytest.mark.unit
class TestDeferrableNormalization:
    def test_is_deferrable_false_becomes_none(self):
        c = _constraint(is_deferrable=False)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_deferrable is None

    def test_is_deferrable_true_preserved(self):
        c = _constraint(is_deferrable=True)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_deferrable is True

    def test_is_deferrable_none_preserved(self):
        c = _constraint(is_deferrable=None)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_deferrable is None

    def test_initially_deferred_false_becomes_none(self):
        c = _constraint(initially_deferred=False)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.initially_deferred is None

    def test_initially_deferred_true_preserved(self):
        c = _constraint(initially_deferred=True)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.initially_deferred is True


@pytest.mark.unit
class TestEnabledValidatedNormalization:
    def test_is_enabled_true_becomes_none(self):
        c = _constraint(is_enabled=True)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_enabled is None

    def test_is_enabled_false_preserved(self):
        c = _constraint(is_enabled=False)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_enabled is False

    def test_is_validated_true_becomes_none(self):
        c = _constraint(is_validated=True)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_validated is None

    def test_is_validated_false_preserved(self):
        c = _constraint(is_validated=False)
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.is_validated is False


@pytest.mark.unit
class TestNonDestructive:
    def test_columns_untouched(self):
        col = _col(name="email", data_type="varchar(255)")
        original_type = col.data_type
        TableCanonicalizer().canonicalize(_table(columns=[col]))
        assert col.data_type == original_type
        assert col.name == "email"

    def test_constraint_identity_preserved(self):
        c = _constraint(
            name="orders_status_check",
            ctype=ConstraintType.CHECK,
            columns=[],
            check_expression="status::text = ANY (ARRAY['a'::text])",
            is_deferrable=False,
        )
        TableCanonicalizer().canonicalize(_table(constraints=[c]))
        assert c.name == "orders_status_check"
        assert c.constraint_type == ConstraintType.CHECK
        assert c.check_expression == "status::text = ANY (ARRAY['a'::text])"

    def test_no_constraint_dedup(self):
        c1 = _constraint(name="pk1", columns=["id"])
        c2 = _constraint(name="pk2", columns=["id"])
        table = _table(constraints=[c1, c2])
        TableCanonicalizer().canonicalize(table)
        assert len(table.constraints) == 2

    def test_no_type_normalization(self):
        col = _col(name="x", data_type="int4")
        TableCanonicalizer().canonicalize(_table(columns=[col]))
        assert col.data_type == "int4"


@pytest.mark.unit
class TestReturnAndIdempotence:
    def test_returns_same_table_instance(self):
        t = _table()
        result = TableCanonicalizer().canonicalize(t)
        assert result is t

    def test_idempotent(self):
        c = _constraint(is_deferrable=False, is_enabled=True)
        t = _table(constraints=[c])
        canonicalizer = TableCanonicalizer()
        canonicalizer.canonicalize(t)
        canonicalizer.canonicalize(t)
        assert c.is_deferrable is None
        assert c.is_enabled is None

    def test_handles_table_with_no_constraints(self):
        t = Table(name="empty", columns=[_col()], constraints=[])
        TableCanonicalizer().canonicalize(t)

    def test_handles_table_with_none_constraints(self):
        t = Table(name="empty", columns=[_col()])
        t.constraints = None
        TableCanonicalizer().canonicalize(t)


@pytest.mark.unit
class TestBatchAPI:
    def test_canonicalize_tables_processes_all(self):
        c1 = _constraint(is_deferrable=False)
        c2 = _constraint(is_enabled=True)
        t1 = _table(constraints=[c1], name="t1")
        t2 = _table(constraints=[c2], name="t2")
        TableCanonicalizer().canonicalize_tables([t1, t2])
        assert c1.is_deferrable is None
        assert c2.is_enabled is None


@pytest.mark.unit
class TestSnapshotLiveParity:
    """Acceptance: snapshot-loaded (None defaults) == live-introspected (False/True defaults) after canonicalization."""

    def test_snapshot_and_live_pk_constraints_match(self):
        snapshot_pk = _constraint(name="orders_pkey")  # all flags None (from JSON)
        live_pk = _constraint(
            name="orders_pkey",
            is_deferrable=False,
            initially_deferred=False,
            is_enabled=True,
            is_validated=True,
        )
        snap_table = _table(constraints=[snapshot_pk], name="orders")
        live_table = _table(constraints=[live_pk], name="orders")

        canonicalizer = TableCanonicalizer()
        canonicalizer.canonicalize(snap_table)
        canonicalizer.canonicalize(live_table)

        assert snap_table.constraints[0].is_deferrable == live_table.constraints[0].is_deferrable
        assert (
            snap_table.constraints[0].initially_deferred
            == live_table.constraints[0].initially_deferred
        )
        assert snap_table.constraints[0].is_enabled == live_table.constraints[0].is_enabled
        assert snap_table.constraints[0].is_validated == live_table.constraints[0].is_validated
