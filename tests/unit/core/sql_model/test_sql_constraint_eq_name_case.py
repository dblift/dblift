"""``SqlConstraint`` equality compares constraint names case-insensitively."""

import pytest

from dblift.core.sql_model.base import ConstraintType, SqlConstraint

pytestmark = [pytest.mark.unit]


def test_names_differing_only_in_case_are_equal():
    a = SqlConstraint(ConstraintType.UNIQUE, "UQ_Email", ["email"])
    b = SqlConstraint(ConstraintType.UNIQUE, "uq_email", ["email"])

    assert a == b
    assert hash(a) == hash(b)


def test_different_names_are_not_equal():
    a = SqlConstraint(ConstraintType.UNIQUE, "uq_email", ["email"])
    b = SqlConstraint(ConstraintType.UNIQUE, "uq_mail", ["email"])

    assert a != b
