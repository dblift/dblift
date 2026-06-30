"""ADR-26 B2: ``is_generated_not_null_check`` quirks hook.

Oracle drops its system-generated ``IS NOT NULL`` check constraints
(``GENERATED NAME``) during introspection. That dialect-specific filter
now lives in the Oracle plugin quirks; the base default is False so
non-Oracle dialects never lose check constraints.
"""

from db.base_quirks import BaseQuirks
from db.plugins.oracle.quirks import OracleQuirks


def test_oracle_filters_generated_not_null_check() -> None:
    q = OracleQuirks()
    assert (
        q.is_generated_not_null_check({"generated": "GENERATED NAME"}, '"COL" IS NOT NULL') is True
    )


def test_oracle_keeps_when_not_generated_name() -> None:
    q = OracleQuirks()
    assert q.is_generated_not_null_check({"generated": "USER NAME"}, '"COL" IS NOT NULL') is False


def test_oracle_keeps_when_expression_does_not_match() -> None:
    q = OracleQuirks()
    assert q.is_generated_not_null_check({"generated": "GENERATED NAME"}, "age > 0") is False


def test_oracle_reads_uppercase_generated_column() -> None:
    q = OracleQuirks()
    assert q.is_generated_not_null_check({"GENERATED": "GENERATED NAME"}, '"X" IS NOT NULL') is True


def test_base_default_is_false() -> None:
    q = BaseQuirks()
    assert (
        q.is_generated_not_null_check({"generated": "GENERATED NAME"}, '"COL" IS NOT NULL') is False
    )
