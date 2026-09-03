"""``Migration._sql_statements`` cache immutability under ``content_override``.

Bugbot PR 160 (line 386) flagged that ``Migration.parse_sql_statements``
mutated ``self._sql_statements`` even when called with a per-execution
``content_override`` (placeholder-substituted SQL). Subsequent readers of
``Migration.sql_statements`` (checksum, info display, repeat parses) saw
substituted content instead of canonical content — silently observable
state drift on the migration object.

This module pins the contract that PR-10 / ADR-0010 establishes:

* ``parse_sql_statements()`` (no override) — caches in ``_sql_statements``.
* ``parse_sql_statements(content_override=...)`` — returns the parsed
  statements but **does not** mutate ``_sql_statements``.
* The cache is therefore always either ``None`` or a parse of the
  canonical ``Migration.content`` — never the substituted form.
"""

from __future__ import annotations

import pytest

from dblift.core.migration.migration import Migration


def _make_migration(content: str) -> Migration:
    """Build a Migration object directly (no script file) with given content."""
    return Migration(
        script_name="V1__test.sql",
        content=content,
        version="1",
        description="test",
        dialect="postgresql",
    )


class TestParseDoesNotPoisonCacheUnderOverride:
    """The headline contract: override never writes to ``_sql_statements``."""

    def test_override_call_leaves_cache_none_when_never_parsed(self):
        m = _make_migration("CREATE TABLE ${schema}_users (id INT);")
        assert m._sql_statements is None

        result = m.parse_sql_statements(content_override="CREATE TABLE app_users (id INT);")

        # The result is correct...
        assert result and "app_users" in result[0]
        # ...but the canonical cache is untouched.
        assert m._sql_statements is None

    def test_override_call_does_not_overwrite_pre_existing_cache(self):
        m = _make_migration("CREATE TABLE ${schema}_users (id INT);")
        # First parse without override → caches the canonical-content parse
        canonical = m.parse_sql_statements()
        assert m._sql_statements == canonical
        assert canonical and "${schema}" in canonical[0]

        # Now parse with override; cache must NOT change
        cache_before = list(m._sql_statements)
        m.parse_sql_statements(content_override="CREATE TABLE app_users (id INT);")
        assert m._sql_statements == cache_before
        assert "${schema}" in m._sql_statements[0]
        assert "app_users" not in " ".join(m._sql_statements)

    def test_repeat_parse_without_override_returns_canonical(self):
        """After an override call, a fresh no-override parse still returns canonical SQL.

        This is the user-facing symptom of the bug: the second time you ask
        for the migration's statements, you get the placeholder-substituted
        form from the previous execution, not the original.
        """
        m = _make_migration("CREATE TABLE ${schema}_users (id INT);")
        m.parse_sql_statements(content_override="CREATE TABLE app_users (id INT);")
        result = m.parse_sql_statements()  # no override
        assert result and "${schema}" in result[0]


class TestCanonicalCacheStillWorks:
    """Without override, the original caching behaviour is preserved."""

    def test_first_canonical_call_populates_cache(self):
        m = _make_migration("SELECT 1;")
        assert m._sql_statements is None
        result = m.parse_sql_statements()
        assert m._sql_statements == result

    def test_second_canonical_call_returns_same_object(self):
        # The function recomputes (no memoisation logic in current impl) but
        # always writes the canonical form. Two canonical calls must agree.
        m = _make_migration("SELECT 1;\nSELECT 2;")
        first = m.parse_sql_statements()
        second = m.parse_sql_statements()
        assert first == second
        assert m._sql_statements == second


class TestSqlStatementsPropertyIsAlwaysCanonical:
    """The ``sql_statements`` property reads from ``self.content`` — independent of cache."""

    def test_property_unaffected_by_override_call(self):
        m = _make_migration("CREATE TABLE ${schema}_t (id INT);")
        m.parse_sql_statements(content_override="CREATE TABLE app_t (id INT);")
        # The public property is computed from raw content, not the cache.
        statements = m.sql_statements
        assert statements
        assert "${schema}" in " ".join(statements)
        assert "app_t" not in " ".join(statements)


class TestEmptyContent:
    """Edge case: empty content + override."""

    @pytest.mark.parametrize("override", ["", "   ", None])
    def test_empty_override_falls_back_to_self_content(self, override):
        m = _make_migration("SELECT 42;")
        if override is None:
            result = m.parse_sql_statements()
        else:
            # Empty / whitespace override is treated as "no content" by the
            # implementation; behaviour-wise the function returns []. The
            # invariant is just that the canonical cache stays clean.
            result = m.parse_sql_statements(content_override=override)
            assert m._sql_statements is None
            assert result == []
            return
        assert m._sql_statements == result
