"""Tests for Trigger and View sql model classes."""

import unittest
from unittest.mock import MagicMock

from dblift.core.sql_model.view_options import MySqlViewOptions, ViewOptions


class TestTriggerInit(unittest.TestCase):
    def _make(self, **kwargs):
        from dblift.core.sql_model.trigger import Trigger

        defaults = {"name": "trg_test", "table_name": "users"}
        defaults.update(kwargs)
        return Trigger(**defaults)

    def test_basic_init(self):
        t = self._make()
        self.assertEqual(t.name, "trg_test")
        self.assertEqual(t.table_name, "users")

    def test_timing_and_events(self):
        t = self._make(timing="BEFORE", events=["INSERT", "UPDATE"])
        self.assertEqual(t.timing, "BEFORE")
        self.assertEqual(t.events, ["INSERT", "UPDATE"])

    def test_definition_stored(self):
        t = self._make(definition="FOR EACH ROW BEGIN END")
        self.assertEqual(t.definition, "FOR EACH ROW BEGIN END")


class TestTriggerQualifiedTableName(unittest.TestCase):
    def test_with_schema(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger(name="t", table_name="orders", schema="public")
        self.assertIn("orders", t.qualified_table_name)

    def test_without_schema(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger(name="t", table_name="orders")
        self.assertIn("orders", t.qualified_table_name)


class TestTriggerEventStr(unittest.TestCase):
    def test_single_event(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger(name="t", table_name="u", events=["INSERT"])
        self.assertEqual(t.event_str, "INSERT")

    def test_multiple_events(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger(name="t", table_name="u", events=["INSERT", "UPDATE"])
        self.assertIn("INSERT", t.event_str)
        self.assertIn("UPDATE", t.event_str)

    def test_no_events(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger(name="t", table_name="u")
        self.assertIsInstance(t.event_str, str)


class TestTriggerEquality(unittest.TestCase):
    def test_equal_triggers(self):
        from dblift.core.sql_model.trigger import Trigger

        t1 = Trigger(
            "t",
            "users",
            timing="AFTER",
            events=["INSERT"],
            definition="BEGIN END",
            dialect="postgresql",
        )
        t2 = Trigger(
            "t",
            "users",
            timing="AFTER",
            events=["INSERT"],
            definition="BEGIN END",
            dialect="postgresql",
        )
        self.assertEqual(t1, t2)

    def test_different_name_not_equal(self):
        from dblift.core.sql_model.trigger import Trigger

        t1 = Trigger("t1", "users")
        t2 = Trigger("t2", "users")
        self.assertNotEqual(t1, t2)

    def test_different_timing_not_equal(self):
        from dblift.core.sql_model.trigger import Trigger

        t1 = Trigger("t", "users", timing="BEFORE")
        t2 = Trigger("t", "users", timing="AFTER")
        self.assertNotEqual(t1, t2)

    def test_not_equal_to_non_trigger(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger("t", "users")
        self.assertNotEqual(t, "not a trigger")


class TestTriggerFromDict(unittest.TestCase):
    def test_basic_from_dict(self):
        from dblift.core.sql_model.trigger import Trigger

        data = {
            "name": "trg_users",
            "table_name": "users",
            "schema": "public",
            "timing": "AFTER",
            "events": ["INSERT"],
            "definition": "FOR EACH ROW BEGIN END",
            "dialect": "postgresql",
            "enabled": True,
        }
        t = Trigger.from_dict(data)
        self.assertEqual(t.name, "trg_users")
        self.assertEqual(t.timing, "AFTER")

    def test_from_dict_to_dict_roundtrip(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger(
            "t1",
            "users",
            schema="public",
            timing="BEFORE",
            events=["UPDATE"],
            definition="BEGIN END",
            dialect="mysql",
        )
        d = t.to_dict()
        t2 = Trigger.from_dict(d)
        self.assertEqual(t, t2)


class TestTriggerToDict(unittest.TestCase):
    def test_to_dict_contains_key_fields(self):
        from dblift.core.sql_model.trigger import Trigger

        t = Trigger("trg1", "users", timing="AFTER", events=["DELETE"])
        d = t.to_dict()
        self.assertEqual(d["name"], "trg1")
        self.assertEqual(d["table_name"], "users")
        self.assertIn("timing", d)
        self.assertIn("events", d)


class TestTriggerFormatMysqlDefiner(unittest.TestCase):
    def test_formats_definer(self):
        from dblift.core.sql_model.trigger import Trigger

        result = Trigger._format_mysql_definer("root@localhost")
        self.assertIsNotNone(result)


class TestViewInit(unittest.TestCase):
    def test_basic_init(self):
        from dblift.core.sql_model.view import View

        v = View(name="v_users", schema="public", query="SELECT * FROM users")
        self.assertEqual(v.name, "v_users")
        self.assertEqual(v.query, "SELECT * FROM users")

    def test_materialized(self):
        from dblift.core.sql_model.view import View

        v = View(name="mv", materialized=True)
        self.assertTrue(v.materialized)

    def test_mysql_properties(self):
        from dblift.core.sql_model.view import View

        v = View.from_options(
            name="v",
            options=ViewOptions(
                mysql=MySqlViewOptions(
                    algorithm="MERGE", sql_security="DEFINER", definer="root@localhost"
                )
            ),
        )
        self.assertEqual(v.algorithm, "MERGE")
        self.assertEqual(v.sql_security, "DEFINER")


class TestViewEquality(unittest.TestCase):
    def test_equal(self):
        from dblift.core.sql_model.view import View

        v1 = View("v1", schema="public", query="SELECT 1", dialect="postgresql")
        v2 = View("v1", schema="public", query="SELECT 1", dialect="postgresql")
        self.assertEqual(v1, v2)

    def test_different_query_not_equal(self):
        from dblift.core.sql_model.view import View

        v1 = View("v1", query="SELECT 1")
        v2 = View("v1", query="SELECT 2")
        self.assertNotEqual(v1, v2)

    def test_not_equal_to_non_view(self):
        from dblift.core.sql_model.view import View

        v = View("v1")
        self.assertNotEqual(v, "not a view")


class TestViewFromDict(unittest.TestCase):
    def test_roundtrip(self):
        from dblift.core.sql_model.view import View

        v = View(
            "v1", schema="dbo", query="SELECT * FROM t", materialized=False, dialect="sqlserver"
        )
        d = v.to_dict()
        v2 = View.from_dict(d)
        self.assertEqual(v.name, v2.name)
        self.assertEqual(v.query, v2.query)


class TestViewDropStatement(unittest.TestCase):
    def test_regular_view_drop(self):
        from dblift.core.sql_model.view import View

        v = View("v1", schema="public", dialect="postgresql")
        drop = v.drop_statement
        self.assertIn("DROP", drop.upper())
        self.assertIn("v1", drop)

    def test_materialized_view_drop(self):
        from dblift.core.sql_model.view import View

        v = View("mv1", schema="public", materialized=True, dialect="postgresql")
        drop = v.drop_statement
        self.assertIn("MATERIALIZED", drop.upper())


class TestViewFormatMysqlDefiner(unittest.TestCase):
    def test_formats_definer(self):
        from dblift.core.sql_model.view import View

        result = View._format_mysql_definer("root@localhost")
        self.assertIsNotNone(result)
