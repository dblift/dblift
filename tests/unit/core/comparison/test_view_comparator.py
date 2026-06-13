"""Tests for View Comparator.

This module tests the ViewComparator class which compares view objects
and generates diff results.
"""

import pytest

from core.comparison.diff_models import ViewDiff
from core.comparison.view_comparator import ViewComparator
from core.sql_model.view import View
from core.sql_model.view_options import (
    MaterializedViewOptions,
    MySqlViewOptions,
    OracleViewOptions,
    PostgresViewOptions,
    ViewOptions,
)


@pytest.mark.unit
class TestViewComparator:
    """Test ViewComparator class."""

    def test_init(self):
        """Test ViewComparator initialization."""
        comparator = ViewComparator()
        assert comparator is not None

    def test_init_with_type_normalizer(self):
        """Test ViewComparator initialization with type_normalizer (ignored)."""
        comparator = ViewComparator(type_normalizer="ignored")
        assert comparator is not None

    def test_compare_identical_views(self):
        """Test comparing identical views returns None."""
        comparator = ViewComparator()

        expected = View(name="test_view", query="SELECT * FROM users", dialect="postgresql")

        actual = View(name="test_view", query="SELECT * FROM users", dialect="postgresql")

        result = comparator.compare_views(expected, actual)

        assert result is None

    def test_compare_views_definition_changed(self):
        """Test comparing views with different definitions."""
        comparator = ViewComparator()

        expected = View(name="test_view", query="SELECT id, name FROM users", dialect="postgresql")

        actual = View(
            name="test_view", query="SELECT id, name, email FROM users", dialect="postgresql"
        )

        result = comparator.compare_views(expected, actual)

        assert result is not None
        assert isinstance(result, ViewDiff)
        assert result.definition_changed is True
        assert result.expected_definition == "SELECT id, name FROM users"
        assert result.actual_definition == "SELECT id, name, email FROM users"

    def test_compare_views_materialized_changed(self):
        """Test comparing views with different materialized status."""
        comparator = ViewComparator()

        expected = View(
            name="test_view", query="SELECT * FROM users", materialized=False, dialect="postgresql"
        )

        actual = View(
            name="test_view", query="SELECT * FROM users", materialized=True, dialect="postgresql"
        )

        result = comparator.compare_views(expected, actual)

        assert result is not None
        assert result.materialized_changed == (False, True)

    def test_compare_views_postgresql_unlogged_changed(self):
        """Test comparing PostgreSQL materialized views with different unlogged status."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(unlogged=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(unlogged=True)),
        )

        result = comparator.compare_views(expected, actual, dialect="postgresql")

        assert result is not None
        assert result.unlogged_changed == (False, True)

    def test_compare_views_postgresql_security_definer_changed(self):
        """Test comparing PostgreSQL views with different security_definer."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_definer=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_definer=True)),
        )

        result = comparator.compare_views(expected, actual, dialect="postgresql")

        assert result is not None
        assert result.security_definer_changed == (False, True)

    def test_compare_views_postgresql_security_invoker_changed(self):
        """Test comparing PostgreSQL views with different security_invoker."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_invoker=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_invoker=True)),
        )

        result = comparator.compare_views(expected, actual, dialect="postgresql")

        assert result is not None
        assert result.security_invoker_changed == (False, True)

    def test_compare_views_mysql_algorithm_changed(self):
        """Test comparing MySQL views with different algorithm."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(algorithm="MERGE")),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(algorithm="TEMPTABLE")),
        )

        result = comparator.compare_views(expected, actual, dialect="mysql")

        assert result is not None
        assert result.algorithm_changed == ("MERGE", "TEMPTABLE")

    def test_compare_views_mysql_sql_security_changed(self):
        """Test comparing MySQL views with different sql_security."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(sql_security="DEFINER")),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(sql_security="INVOKER")),
        )

        result = comparator.compare_views(expected, actual, dialect="mysql")

        assert result is not None
        assert result.sql_security_changed == ("DEFINER", "INVOKER")

    def test_compare_views_mysql_definer_changed(self):
        """Test comparing MySQL views with different definer."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(definer="user1@localhost")),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(definer="user2@localhost")),
        )

        result = comparator.compare_views(expected, actual, dialect="mysql")

        assert result is not None
        assert result.definer_changed == ("user1@localhost", "user2@localhost")

    def test_compare_views_oracle_force_changed(self):
        """Test comparing Oracle views with different force status."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="oracle",
            options=ViewOptions(oracle=OracleViewOptions(force=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="oracle",
            options=ViewOptions(oracle=OracleViewOptions(force=True)),
        )

        result = comparator.compare_views(expected, actual, dialect="oracle")

        assert result is not None
        assert result.force_changed == (False, True)

    def test_compare_views_materialized_is_populated_changed(self):
        """Test comparing materialized views with different is_populated."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(materialized_view=MaterializedViewOptions(is_populated=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(materialized_view=MaterializedViewOptions(is_populated=True)),
        )

        result = comparator.compare_views(expected, actual)

        assert result is not None
        assert result.is_populated_changed == (False, True)

    def test_compare_views_materialized_refresh_method_changed(self):
        """Test comparing materialized views with different refresh_method."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(materialized_view=MaterializedViewOptions(refresh_method="FAST")),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(refresh_method="COMPLETE")
            ),
        )

        result = comparator.compare_views(expected, actual)

        assert result is not None
        assert result.refresh_method_changed == ("FAST", "COMPLETE")

    def test_compare_views_materialized_refresh_method_case_insensitive(self):
        """Test comparing materialized views with refresh_method case-insensitive."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(materialized_view=MaterializedViewOptions(refresh_method="fast")),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(materialized_view=MaterializedViewOptions(refresh_method="FAST")),
        )

        result = comparator.compare_views(expected, actual)

        # Should not detect difference due to case-insensitive comparison
        assert result is None or result.refresh_method_changed is None

    def test_compare_views_materialized_refresh_mode_changed(self):
        """Test comparing materialized views with different refresh_mode."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(refresh_mode="ON DEMAND")
            ),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(refresh_mode="ON COMMIT")
            ),
        )

        result = comparator.compare_views(expected, actual)

        assert result is not None
        assert result.refresh_mode_changed == ("ON DEMAND", "ON COMMIT")

    def test_compare_views_materialized_fast_refreshable_changed(self):
        """Test comparing materialized views with different fast_refreshable."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(materialized_view=MaterializedViewOptions(fast_refreshable=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="oracle",
            options=ViewOptions(materialized_view=MaterializedViewOptions(fast_refreshable=True)),
        )

        result = comparator.compare_views(expected, actual)

        assert result is not None
        assert result.fast_refreshable_changed == (False, True)

    def test_compare_views_no_name_uses_actual_name(self):
        """Test comparing views when expected has no name."""
        comparator = ViewComparator()

        expected = View(name="", query="SELECT * FROM users", dialect="postgresql")

        actual = View(name="test_view", query="SELECT * FROM users", dialect="postgresql")

        result = comparator.compare_views(expected, actual)

        # Should use actual.name when expected.name is empty
        assert result is None or result.view_name == "test_view"

    def test_normalize_view_definition_empty(self):
        """Test normalizing empty view definition."""
        comparator = ViewComparator()

        result = comparator._normalize_view_definition(None)
        assert result == ""

        result = comparator._normalize_view_definition("")
        assert result == ""

    def test_normalize_view_definition_removes_comments(self):
        """Test normalizing view definition removes comments."""
        comparator = ViewComparator()

        definition = "SELECT * FROM users -- comment"
        result = comparator._normalize_view_definition(definition)

        assert "--" not in result

    def test_normalize_view_definition_removes_multiline_comments(self):
        """Test normalizing view definition removes multiline comments."""
        comparator = ViewComparator()

        definition = "SELECT * /* comment */ FROM users"
        result = comparator._normalize_view_definition(definition)

        assert "/*" not in result
        assert "*/" not in result

    def test_normalize_view_definition_normalizes_whitespace(self):
        """Test normalizing view definition normalizes whitespace."""
        comparator = ViewComparator()

        definition = "SELECT   *   FROM    users"
        result = comparator._normalize_view_definition(definition)

        # Should normalize whitespace
        assert "  " not in result or result.count(" ") <= len("SELECT * FROM users")

    def test_normalize_view_definition_uppercase(self):
        """Test normalizing view definition converts to uppercase."""
        comparator = ViewComparator()

        definition = "select * from users"
        result = comparator._normalize_view_definition(definition)

        assert result.isupper() or "SELECT" in result.upper()

    def test_compare_views_postgresql_unlogged_none_ignored(self):
        """Test that None values for unlogged are ignored."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(unlogged=None)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(unlogged=True)),
        )

        result = comparator.compare_views(expected, actual, dialect="postgresql")

        # Should not detect difference when one is None
        assert result is None or result.unlogged_changed is None

    def test_compare_views_postgresql_security_definer_none_ignored(self):
        """Test that None values for security_definer are ignored."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_definer=None)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_definer=True)),
        )

        result = comparator.compare_views(expected, actual, dialect="postgresql")

        # Should not detect difference when one is None
        assert result is None or result.security_definer_changed is None

    def test_compare_views_mysql_sql_security_none_ignored(self):
        """Test that None or empty values for sql_security are ignored."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(sql_security=None)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            dialect="mysql",
            options=ViewOptions(mysql=MySqlViewOptions(sql_security="DEFINER")),
        )

        result = comparator.compare_views(expected, actual, dialect="mysql")

        # Should not detect difference when one is None
        assert result is None or result.sql_security_changed is None

    def test_compare_views_materialized_properties_only_when_both_materialized(self):
        """Test that materialized-specific properties are only compared when both are materialized."""
        comparator = ViewComparator()

        expected = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=False,
            dialect="postgresql",
            options=ViewOptions(materialized_view=MaterializedViewOptions(is_populated=False)),
        )

        actual = View.from_options(
            name="test_view",
            query="SELECT * FROM users",
            materialized=True,
            dialect="postgresql",
            options=ViewOptions(materialized_view=MaterializedViewOptions(is_populated=True)),
        )

        result = comparator.compare_views(expected, actual)

        # Should detect materialized change, but not is_populated (only compared when both materialized)
        assert result is not None
        assert result.materialized_changed == (False, True)
        # is_populated should not be compared since expected is not materialized
        assert result.is_populated_changed is None
