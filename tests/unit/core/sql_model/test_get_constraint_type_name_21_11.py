"""Tests for get_constraint_type_name utility function (story 21-11, DEDUP-30)."""

import pytest

from dblift.core.sql_model.base import ConstraintType, get_constraint_type_name

pytestmark = [pytest.mark.unit]


class _ConstraintWithEnum:
    """Stub constraint whose constraint_type is a ConstraintType enum member."""

    def __init__(self, ct: ConstraintType) -> None:
        self.constraint_type = ct


class _ConstraintWithString:
    """Stub constraint whose constraint_type is a plain string (duck-typed)."""

    def __init__(self, ct: str) -> None:
        self.constraint_type = ct


class TestGetConstraintTypeName:
    """AC#2 — identical behaviour for enum, str and fallback inputs."""

    def test_enum_primary_key_returns_value(self) -> None:
        constraint = _ConstraintWithEnum(ConstraintType.PRIMARY_KEY)
        assert get_constraint_type_name(constraint) == "PRIMARY KEY"

    def test_enum_foreign_key_returns_value(self) -> None:
        constraint = _ConstraintWithEnum(ConstraintType.FOREIGN_KEY)
        assert get_constraint_type_name(constraint) == "FOREIGN KEY"

    def test_enum_unique_returns_value(self) -> None:
        constraint = _ConstraintWithEnum(ConstraintType.UNIQUE)
        assert get_constraint_type_name(constraint) == "UNIQUE"

    def test_enum_check_returns_value(self) -> None:
        constraint = _ConstraintWithEnum(ConstraintType.CHECK)
        assert get_constraint_type_name(constraint) == "CHECK"

    def test_string_type_returned_as_is(self) -> None:
        """A plain string constraint_type passes through str() unchanged."""
        constraint = _ConstraintWithString("FOREIGN KEY")
        assert get_constraint_type_name(constraint) == "FOREIGN KEY"

    def test_fallback_arbitrary_object_uses_str(self) -> None:
        """Any non-ConstraintType object is converted via str()."""

        class _CustomType:
            def __str__(self) -> str:
                return "CUSTOM_TYPE"

        constraint = _ConstraintWithString.__new__(_ConstraintWithString)
        constraint.constraint_type = _CustomType()
        assert get_constraint_type_name(constraint) == "CUSTOM_TYPE"

    def test_return_type_is_always_str(self) -> None:
        for ct in ConstraintType:
            result = get_constraint_type_name(_ConstraintWithEnum(ct))
            assert isinstance(result, str), f"Expected str for {ct!r}, got {type(result)}"


class TestGetConstraintTypeNameExported:
    """AC#1 — function is reachable from core.sql_model package."""

    def test_importable_from_package(self) -> None:
        from dblift.core.sql_model import get_constraint_type_name as fn  # noqa: F401

        assert callable(fn)

    def test_in_all(self) -> None:
        import dblift.core.sql_model as pkg

        assert "get_constraint_type_name" in pkg.__all__
