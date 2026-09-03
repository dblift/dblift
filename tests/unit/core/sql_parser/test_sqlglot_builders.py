"""Tests for ``core/sql_parser/_sqlglot_builders.py`` (PR-D3 / PR-F2).

The mixin was extracted from ``HybridParser`` in PR-D3 and the
trigger-building section was decomposed into typed helpers in PR-F2.
The pre-existing ``test_hybrid_parser*`` files exercise the builders
indirectly through ``HybridParser.parse_sql``; this file targets the
mixin's surface **directly** so:

- The trigger helpers (``_parse_trigger_match``,
  ``_extract_trigger_definition``, ``_find_matching_trigger``,
  ``_merge_trigger_metadata``, ``_build_trigger_from_header``) have
  their contracts pinned independently of the regex parser front-end.
- The table / view / index builders are exercised against a freshly
  parsed sqlglot AST without going through the full ``HybridParser``
  routing.

Composing the mixin onto a minimal test harness lets the suite run
without booting the full provider stack.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import pytest
from sqlglot import exp, parse_one

from dblift.core.sql_model.base import ConstraintType
from dblift.core.sql_model.trigger import Trigger
from dblift.core.sql_parser._sqlglot_builders import _SqlglotBuildersMixin, _TriggerHeader

pytestmark = [pytest.mark.unit]


class _Harness(_SqlglotBuildersMixin):
    """Minimal composing class so the mixin's ``self.*`` resolve correctly."""

    def __init__(self, dialect: str = "postgresql") -> None:
        from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
        from dblift.db.provider_registry import ProviderRegistry

        self.dialect = dialect
        self._quirks = ProviderRegistry.get_quirks(dialect)
        try:
            self.sqlglot_parser: Any = SqlGlotParser(dialect)
        except Exception:
            self.sqlglot_parser = None

    def _normalize_identifier(self, identifier: Optional[str], preserve_case: bool) -> str:
        if identifier is None:
            return ""
        trimmed = identifier.strip().strip('"').strip("`")
        if trimmed.startswith("[") and trimmed.endswith("]"):
            trimmed = trimmed[1:-1]
        if "." in trimmed:
            trimmed = trimmed.split(".")[-1]
        return trimmed if preserve_case else trimmed.upper()


# --------------------------------------------------------------------- #
# Trigger helpers (PR-F2 decomposition)
# --------------------------------------------------------------------- #


class TestParseTriggerMatch:
    def _match(self, sql: str) -> re.Match:
        match = _Harness()._parse_trigger_header(sql)
        assert match is not None
        return match

    def test_full_qualified_trigger_header(self):
        match = self._match(
            "CREATE TRIGGER app.tr_audit BEFORE UPDATE ON public.users "
            "FOR EACH ROW UPDATE audit SET ts=NOW();"
        )
        header = _Harness()._parse_trigger_match(match, default_schema="dbo")
        assert header == _TriggerHeader(
            schema="app",
            name="tr_audit",
            timing="BEFORE",
            event="UPDATE",
            table_name="users",
        )

    def test_default_schema_used_when_trigger_unqualified(self):
        match = self._match(
            "CREATE TRIGGER tr_audit AFTER INSERT ON public.users "
            "FOR EACH ROW UPDATE audit SET ts=NOW();"
        )
        header = _Harness()._parse_trigger_match(match, default_schema="dbo")
        assert header.schema == "dbo"
        assert header.name == "tr_audit"
        assert header.timing == "AFTER"
        assert header.event == "INSERT"
        assert header.table_name == "users"

    def test_timing_and_event_are_uppercased(self):
        # Input intentionally lowercase so the test actually exercises the
        # ``.upper()`` calls inside ``_parse_trigger_match``. With uppercase
        # input the test would pass even if the normalization were removed.
        match = re.match(
            r"CREATE\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?TRIGGER\s+"
            r"(?:([a-zA-Z_][a-zA-Z0-9_]*)\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s+"
            r"(BEFORE|AFTER)\s+"
            r"(INSERT|UPDATE|DELETE)\s+"
            r"ON\s+"
            r"([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)",
            "create trigger tr before delete on s.t for each row select 1;",
            re.IGNORECASE,
        )
        assert match is not None
        header = _Harness()._parse_trigger_match(match, None)
        assert header.timing == "BEFORE"
        assert header.event == "DELETE"


class TestExtractTriggerDefinition:
    def _extract(self, sql: str) -> Optional[str]:
        return _Harness()._extract_trigger_definition(sql)

    def test_returns_body_after_for_each_row(self):
        sql = "CREATE TRIGGER t BEFORE INSERT ON s.u FOR EACH ROW INSERT INTO log VALUES (1);"
        assert self._extract(sql) == "INSERT INTO log VALUES (1)"

    def test_returns_none_when_no_for_each_row(self):
        sql = "CREATE TRIGGER t BEFORE INSERT ON s.u BEGIN SELECT 1; END;"
        assert self._extract(sql) is None

    def test_handles_multiline_body(self):
        sql = (
            "CREATE TRIGGER t BEFORE INSERT ON s.u\n"
            "FOR EACH ROW\n"
            "  UPDATE counters SET n = n + 1\n"
            "  WHERE id = NEW.id;"
        )
        body = self._extract(sql)
        assert body is not None
        assert "UPDATE counters" in body
        assert body.endswith("WHERE id = NEW.id")


class TestFindMatchingTrigger:
    def _trigger(self, **kwargs):
        defaults = dict(
            name="tr",
            table_name="t",
            schema=None,
            timing=None,
            events=[],
            orientation="ROW",
            definition=None,
            dialect="postgresql",
            definer=None,
        )
        defaults.update(kwargs)
        return Trigger(**defaults)

    def test_returns_none_when_triggers_empty(self):
        header = _TriggerHeader("s", "n", None, None, "t")
        assert _Harness()._find_matching_trigger([], header) is None

    def test_returns_none_when_triggers_is_none(self):
        header = _TriggerHeader("s", "n", None, None, "t")
        assert _Harness()._find_matching_trigger(None, header) is None

    def test_match_is_case_insensitive_on_all_three_keys(self):
        existing = self._trigger(name="TR_audit", table_name="USERS", schema="App")
        header = _TriggerHeader("app", "tr_audit", None, None, "users")
        assert _Harness()._find_matching_trigger([existing], header) is existing

    def test_distinct_table_yields_no_match(self):
        existing = self._trigger(name="tr", table_name="users", schema="app")
        header = _TriggerHeader("app", "tr", None, None, "orders")
        assert _Harness()._find_matching_trigger([existing], header) is None

    def test_distinct_schema_yields_no_match(self):
        existing = self._trigger(name="tr", table_name="users", schema="app")
        header = _TriggerHeader("admin", "tr", None, None, "users")
        assert _Harness()._find_matching_trigger([existing], header) is None

    def test_treats_none_schema_as_empty_string(self):
        existing = self._trigger(name="tr", table_name="users", schema=None)
        header = _TriggerHeader(None, "tr", None, None, "users")
        assert _Harness()._find_matching_trigger([existing], header) is existing


class TestMergeTriggerMetadata:
    def _existing(self, **kwargs):
        defaults = dict(
            name="tr",
            table_name="users",
            schema="app",
            timing=None,
            events=[],
            orientation="ROW",
            definition=None,
            dialect="postgresql",
            definer=None,
        )
        defaults.update(kwargs)
        return Trigger(**defaults)

    def _header(self):
        return _TriggerHeader(
            schema="app",
            name="tr",
            timing="BEFORE",
            event="UPDATE",
            table_name="users",
        )

    def test_fills_missing_fields_only(self):
        existing = self._existing()  # all None / empty
        _Harness()._merge_trigger_metadata(existing, self._header(), "BODY", "u@h")
        assert existing.timing == "BEFORE"
        assert existing.events == ["UPDATE"]
        assert existing.definition == "BODY"
        assert existing.definer == "u@h"

    def test_does_not_overwrite_existing_timing(self):
        existing = self._existing(timing="AFTER")
        _Harness()._merge_trigger_metadata(existing, self._header(), None, None)
        assert existing.timing == "AFTER"

    def test_does_not_overwrite_existing_events(self):
        existing = self._existing(events=["INSERT"])
        _Harness()._merge_trigger_metadata(existing, self._header(), None, None)
        assert existing.events == ["INSERT"]

    def test_does_not_overwrite_existing_definition(self):
        existing = self._existing(definition="prior body")
        _Harness()._merge_trigger_metadata(existing, self._header(), "new body", None)
        assert existing.definition == "prior body"


class TestBuildTriggerFromHeader:
    def test_constructs_trigger_with_full_metadata(self):
        header = _TriggerHeader("app", "tr", "BEFORE", "UPDATE", "users")
        trigger = _Harness()._build_trigger_from_header(header, "BODY", "u@h")
        assert trigger.name == "tr"
        assert trigger.table_name == "users"
        assert trigger.schema == "app"
        assert trigger.timing == "BEFORE"
        assert trigger.events == ["UPDATE"]
        assert trigger.definition == "BODY"
        assert trigger.dialect == "postgresql"
        assert trigger.definer == "u@h"

    def test_no_event_yields_empty_events_list(self):
        header = _TriggerHeader("app", "tr", "BEFORE", None, "users")
        trigger = _Harness()._build_trigger_from_header(header, None, None)
        assert trigger.events == []
        assert trigger.timing == "BEFORE"
        assert trigger.definition is None
        assert trigger.definer is None


# --------------------------------------------------------------------- #
# Table / view / index builders (PR-D3 extraction surface)
# --------------------------------------------------------------------- #


class TestBuildTableModelFromSqlglot:
    def test_extracts_columns_constraints_and_pk(self):
        ast = parse_one(
            "CREATE TABLE app.users (id INT PRIMARY KEY, email TEXT NOT NULL UNIQUE);",
            read="postgres",
        )
        assert isinstance(ast, exp.Create)
        # ``_build_table_model_from_sqlglot`` itself takes the SQL text
        # because it re-parses internally; mirroring the production call
        # path keeps the assertion grounded in real behavior.
        table = _Harness("postgresql")._build_table_model_from_sqlglot(
            "CREATE TABLE app.users (id INT PRIMARY KEY, email TEXT NOT NULL UNIQUE);",
            default_schema=None,
        )
        assert table is not None
        assert table.name == "users"
        assert table.schema == "app"
        assert [c.name for c in table.columns] == ["id", "email"]
        assert any(c.constraint_type == ConstraintType.PRIMARY_KEY for c in table.constraints)
        assert any(c.constraint_type == ConstraintType.UNIQUE for c in table.constraints)

    def test_returns_none_for_non_create_table_statement(self):
        table = _Harness("postgresql")._build_table_model_from_sqlglot(
            "SELECT 1;", default_schema=None
        )
        assert table is None

    def test_returns_none_when_sqlglot_parser_not_available(self):
        h = _Harness("postgresql")
        h.sqlglot_parser = None  # simulate plugins without sqlglot_dialect
        assert (
            h._build_table_model_from_sqlglot("CREATE TABLE x (id INT);", default_schema=None)
            is None
        )


class TestBuildViewFromSqlglot:
    def test_extracts_view_name_schema_and_query(self):
        view = _Harness("postgresql")._build_view_from_sqlglot(
            "CREATE VIEW app.active_users AS SELECT id FROM users WHERE active = TRUE;",
            default_schema=None,
        )
        assert view is not None
        assert view.name == "active_users"
        assert view.schema == "app"
        assert view.query is not None and "SELECT" in view.query.upper()

    def test_detects_materialized_view(self):
        view = _Harness("postgresql")._build_view_from_sqlglot(
            "CREATE MATERIALIZED VIEW app.totals AS SELECT count(*) FROM orders;",
            default_schema=None,
        )
        assert view is not None
        assert view.materialized is True

    def test_default_schema_when_view_unqualified(self):
        view = _Harness("postgresql")._build_view_from_sqlglot(
            "CREATE VIEW v AS SELECT 1;", default_schema="public"
        )
        assert view is not None
        assert view.schema == "public"


class TestBuildIndexFromSqlglot:
    def test_extracts_unique_index_name_table_columns(self):
        index = _Harness("postgresql")._build_index_from_sqlglot(
            "CREATE UNIQUE INDEX idx_users_email ON app.users (email);",
            default_schema=None,
        )
        assert index is not None
        assert index.name == "idx_users_email"
        assert index.table_name == "users"
        assert index.table_schema == "app"
        assert index.columns == ["email"]
        assert index.unique is True

    def test_non_unique_index(self):
        index = _Harness("postgresql")._build_index_from_sqlglot(
            "CREATE INDEX idx_t_x ON s.t (x);", default_schema=None
        )
        assert index is not None
        assert index.unique is False

    def test_returns_none_on_non_index_statement(self):
        index = _Harness("postgresql")._build_index_from_sqlglot(
            "CREATE TABLE t (id INT);", default_schema=None
        )
        assert index is None
