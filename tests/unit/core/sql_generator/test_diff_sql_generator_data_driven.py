"""Tests for DiffSqlGenerator data-driven registry refactoring (Story 13-10)."""

from unittest.mock import MagicMock

import pytest

from core.sql_generator.diff_sql_generator import (
    _OBJECT_TYPE_SPECS,
    _OBJECT_TYPE_SPECS_BY_TYPE,
    DiffGenerationContext,
    DiffSqlGenerator,
    _ObjectTypeSpec,
)
from core.sql_generator.sql_statement import GenerationOptions
from core.sql_model.sequence import Sequence
from core.sql_model.view import View


def _make_generator():
    """Create a DiffSqlGenerator with mocked internals.

    Uses __new__ to bypass __init__, then wires up the DiffSqlStatementBuilder
    directly so shim methods (_generate_create_for_type etc.) can delegate to it.
    """
    from core.sql_generator.diff_sql_generator import DiffSqlStatementBuilder

    gen = DiffSqlGenerator.__new__(DiffSqlGenerator)
    gen.dialect = "postgresql"
    gen.logger = MagicMock()
    gen.sql_generator = MagicMock()
    # Wire the builder using the same mocked sql_generator so tests that
    # set gen.sql_generator.xxx.return_value continue to work transparently.
    gen.builder = DiffSqlStatementBuilder.__new__(DiffSqlStatementBuilder)
    gen.builder.dialect = gen.dialect
    gen.builder.logger = gen.logger
    gen.builder.sql_generator = gen.sql_generator
    gen.builder.alter_generator = MagicMock()
    gen.builder.column_converter = MagicMock()
    return gen


# ── AC#13 — Registry completeness ───────────────────────────────────────


@pytest.mark.unit
class TestObjectTypeSpecRegistry:
    def test_registry_covers_16_types(self):
        assert len(_OBJECT_TYPE_SPECS) == 16
        for spec in _OBJECT_TYPE_SPECS:
            assert spec.object_type, "object_type must be non-empty"
            assert spec.object_class is not None, "object_class must not be None"
            assert (
                spec.diff_missing_attr
            ), f"diff_missing_attr must be non-empty for {spec.object_type}"
            assert spec.diff_extra_attr, f"diff_extra_attr must be non-empty for {spec.object_type}"
            assert (
                spec.diff_modified_attr
            ), f"diff_modified_attr must be non-empty for {spec.object_type}"
            assert spec.expected_attr, f"expected_attr must be non-empty for {spec.object_type}"


# ── AC#10 — _generate_create_for_type ────────────────────────────────────


@pytest.mark.unit
class TestGenerateCreateForType:
    def setup_method(self):
        self.gen = _make_generator()

    def test_generate_create_for_type_success(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        obj = MagicMock()
        obj.name = "my_view"
        self.gen.sql_generator.generate_create_statement.return_value = (
            "CREATE VIEW my_view AS SELECT 1"
        )
        options = MagicMock(spec=GenerationOptions)

        stmt = self.gen._generate_create_for_type(spec, obj, options)

        assert stmt is not None
        assert stmt.statement_type == "CREATE"
        assert stmt.object_type == "VIEW"
        assert stmt.object_name == "my_view"
        assert stmt.sql.endswith(";")

    def test_generate_create_for_type_exception_returns_none(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        obj = MagicMock()
        obj.name = "bad_view"
        self.gen.sql_generator.generate_create_statement.side_effect = RuntimeError("boom")
        options = MagicMock(spec=GenerationOptions)

        stmt = self.gen._generate_create_for_type(spec, obj, options)

        assert stmt is None
        self.gen.logger.warning.assert_called_once()


# ── AC#11 — _generate_drop_for_type ─────────────────────────────────────


@pytest.mark.unit
class TestGenerateDropForType:
    def setup_method(self):
        self.gen = _make_generator()

    def test_generate_drop_for_type_success(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["SEQUENCE"]
        assert spec.object_type == "SEQUENCE"
        self.gen.sql_generator._generate_drop_statement.return_value = "DROP SEQUENCE my_seq"
        options = MagicMock(spec=GenerationOptions)

        stmt = self.gen._generate_drop_for_type(spec, "public.my_seq", options)

        assert stmt is not None
        assert stmt.statement_type == "DROP"
        assert stmt.object_type == "SEQUENCE"
        assert stmt.object_name == "public.my_seq"
        assert stmt.sql.endswith(";")
        # Verify dummy object was created with schema split
        call_args = self.gen.sql_generator._generate_drop_statement.call_args
        dummy = call_args[0][0]
        assert dummy.name == "my_seq"
        assert dummy.schema == "public"

    def test_generate_drop_for_type_exception_returns_none(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["SEQUENCE"]  # SEQUENCE
        self.gen.sql_generator._generate_drop_statement.side_effect = RuntimeError("fail")
        options = MagicMock(spec=GenerationOptions)

        stmt = self.gen._generate_drop_for_type(spec, "my_seq", options)

        assert stmt is None
        self.gen.logger.warning.assert_called_once()


# ── AC#12 — _generate_statements_for_type ────────────────────────────────


@pytest.mark.unit
class TestGenerateStatementsForType:
    def setup_method(self):
        self.gen = _make_generator()
        self.gen.sql_generator.generate_create_statement.return_value = "CREATE VIEW v AS SELECT 1"
        self.gen.sql_generator._generate_drop_statement.return_value = "DROP VIEW v2"
        self.options = MagicMock(spec=GenerationOptions)

    def test_generate_statements_missing_creates(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        diff = MagicMock()
        diff.missing_views = ["v1"]
        diff.modified_views = []
        diff.extra_views = []
        obj = MagicMock()
        obj.name = "v1"
        expected = {"v1": obj}

        stmts = self.gen._generate_statements_for_type(spec, diff, expected, self.options)

        assert len(stmts) == 1
        assert stmts[0].statement_type == "CREATE"
        assert stmts[0].object_type == "VIEW"

    def test_generate_statements_extra_drops(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        diff = MagicMock()
        diff.missing_views = []
        diff.modified_views = []
        diff.extra_views = ["v2"]

        stmts = self.gen._generate_statements_for_type(spec, diff, {}, self.options)

        assert len(stmts) == 1
        assert stmts[0].statement_type == "DROP"

    def test_generate_statements_modified_create_or_replace(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW (supports COR)
        assert spec.supports_create_or_replace is True

        diff = MagicMock()
        diff.missing_views = []
        diff.extra_views = []
        mod_diff = MagicMock()
        mod_diff.object_name = "v3"
        diff.modified_views = [mod_diff]

        obj = MagicMock()
        obj.name = "v3"
        expected = {"v3": obj}

        stmts = self.gen._generate_statements_for_type(spec, diff, expected, self.options)

        assert len(stmts) == 1
        assert stmts[0].statement_type == "CREATE"
        assert "OR REPLACE" in stmts[0].sql

    def test_generate_statements_modified_not_in_expected_logs_warning(self):
        """Modified object absent from expected_objects should log a warning (M2 fix)."""
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        diff = MagicMock()
        diff.missing_views = []
        diff.extra_views = []
        mod_diff = MagicMock()
        mod_diff.object_name = "v_missing"
        diff.modified_views = [mod_diff]

        stmts = self.gen._generate_statements_for_type(spec, diff, {}, self.options)

        assert stmts == []
        self.gen.logger.warning.assert_called_once()
        warning_msg = self.gen.logger.warning.call_args[0][0]
        assert "v_missing" in warning_msg


# ── _generate_create_or_replace_for_type ─────────────────────────────────


@pytest.mark.unit
class TestGenerateCreateOrReplaceForType:
    def setup_method(self):
        self.gen = _make_generator()

    def test_plain_create_becomes_create_or_replace(self):
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        obj = MagicMock()
        obj.name = "v1"
        self.gen.sql_generator.generate_create_statement.return_value = "CREATE VIEW v1 AS SELECT 1"
        stmt = self.gen._generate_create_or_replace_for_type(spec, obj, MagicMock())
        assert stmt is not None
        assert stmt.sql.startswith("CREATE OR REPLACE VIEW")
        assert "OR REPLACE OR REPLACE" not in stmt.sql

    def test_already_create_or_replace_not_doubled(self):
        """M1 fix: sql already containing 'CREATE OR REPLACE' must not be doubled."""
        spec = _OBJECT_TYPE_SPECS_BY_TYPE["VIEW"]  # VIEW
        obj = MagicMock()
        obj.name = "v2"
        self.gen.sql_generator.generate_create_statement.return_value = (
            "CREATE OR REPLACE VIEW v2 AS SELECT 1"
        )
        stmt = self.gen._generate_create_or_replace_for_type(spec, obj, MagicMock())
        assert stmt is not None
        assert (
            stmt.sql.count("OR REPLACE") == 1
        ), f"Expected exactly one 'OR REPLACE', got: {stmt.sql}"


# ── AC#14 — End-to-end generate_from_diff ────────────────────────────────


@pytest.mark.unit
class TestGenerateFromDiffDataDriven:
    def test_generate_from_diff_processes_all_spec_types(self):
        gen = _make_generator()
        gen.sql_generator.generate_create_statement.return_value = "CREATE DUMMY obj"
        gen.sql_generator._generate_drop_statement.return_value = "DROP DUMMY obj"

        diff = MagicMock()
        # Tables: no changes
        diff.modified_tables = []
        diff.missing_tables = []
        diff.extra_tables = []

        # Set one missing object per type
        context_kwargs = {}
        for spec in _OBJECT_TYPE_SPECS:
            obj = MagicMock()
            obj.name = f"test_{spec.expected_attr}"
            setattr(diff, spec.diff_missing_attr, [obj.name])
            setattr(diff, spec.diff_modified_attr, [])
            setattr(diff, spec.diff_extra_attr, [])
            context_kwargs[f"expected_{spec.expected_attr}"] = {obj.name: obj}

        ctx = DiffGenerationContext(**context_kwargs)
        stmts = gen.generate_from_diff(diff, context=ctx)

        create_stmts = [s for s in stmts if s.statement_type == "CREATE"]
        assert (
            len(create_stmts) == 16
        ), f"Expected 16 CREATE statements (one per type), got {len(create_stmts)}"

        # Verify each spec type has a CREATE statement
        created_types = {s.object_type for s in create_stmts}
        expected_types = {spec.object_type for spec in _OBJECT_TYPE_SPECS}
        assert created_types == expected_types
