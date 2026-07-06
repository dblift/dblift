"""``View`` must carry plugin-owned ``dialect_options`` through serialization
and equality, exactly like ``Table``.

Regression: ``View.to_dict``/``from_dict`` dropped ``dialect_options`` and
``__eq__`` ignored them, so anything a plugin stashed on a view under its
dialect namespace was lost across a schema-snapshot round-trip — a reloaded
snapshot compared against a live introspection would then falsely report a
change (or miss one).
"""

import pytest

from core.sql_model.view import View


@pytest.mark.unit
class TestViewDialectOptions:
    def test_round_trip_via_dict_preserves_dialect_options(self):
        v = View(name="v", schema="s", query="SELECT 1", dialect="snowflake")
        v.set_dialect_option("snowflake", "secure", True)
        v.set_dialect_option("snowflake", "cluster_by", ["created_at"])

        restored = View.from_dict(v.to_dict())

        assert restored.get_dialect_option("snowflake", "secure") is True
        assert restored.get_dialect_option("snowflake", "cluster_by") == ["created_at"]

    def test_round_trip_is_equal(self):
        v = View(name="v", schema="s", query="SELECT 1", dialect="snowflake")
        v.set_dialect_option("snowflake", "opts", {"a": 1, "b": "x"})

        assert View.from_dict(v.to_dict()) == v

    def test_equality_considers_dialect_options(self):
        a = View(name="v", schema="s", query="SELECT 1", dialect="snowflake")
        b = View(name="v", schema="s", query="SELECT 1", dialect="snowflake")
        assert a == b

        a.set_dialect_option("snowflake", "secure", True)
        assert a != b

        b.set_dialect_option("snowflake", "secure", True)
        assert a == b

    def test_to_dict_omits_empty_dialect_options(self):
        v = View(name="v", schema="s", query="SELECT 1", dialect="postgresql")
        assert "dialect_options" not in v.to_dict()
