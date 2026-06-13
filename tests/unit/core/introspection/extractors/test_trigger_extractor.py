"""
Unit tests for TriggerExtractor.
Covers: get_triggers() with rows, empty results, event deduplication,
event splitting (comma/space/"OR"), dialect-specific properties,
enabled/disabled detection, missing name/table, error handling.
"""

import unittest
from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.trigger_extractor import TriggerExtractor, _to_bool

pytestmark = [pytest.mark.unit]


def _make_extractor(dialect="postgresql", vendor_queries=None):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    extractor = TriggerExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


def _vq(rows, sql="SELECT 1"):
    vq = MagicMock()
    vq.supports_triggers.return_value = True
    vq.get_triggers_query.return_value = (sql, ["public"])
    return vq


class TestToBool(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(_to_bool(None))

    def test_bool_true(self):
        self.assertTrue(_to_bool(True))

    def test_bool_false(self):
        self.assertFalse(_to_bool(False))

    def test_string_true_variants(self):
        for v in ("TRUE", "T", "YES", "Y", "1"):
            self.assertTrue(_to_bool(v), f"Expected True for '{v}'")

    def test_string_false_variants(self):
        for v in ("FALSE", "F", "NO", "N", "0"):
            self.assertFalse(_to_bool(v), f"Expected False for '{v}'")

    def test_unknown_string_returns_none(self):
        self.assertIsNone(_to_bool("MAYBE"))

    def test_case_insensitive(self):
        self.assertTrue(_to_bool("yes"))
        self.assertFalse(_to_bool("no"))


class TestTriggerExtractorNoVendorQueries(unittest.TestCase):
    def test_returns_empty_when_no_vendor_queries(self):
        extractor = _make_extractor()
        result = extractor.get_triggers("public")
        self.assertEqual(result, [])

    def test_returns_empty_when_triggers_not_supported(self):
        vq = MagicMock()
        vq.supports_triggers.return_value = False
        extractor = _make_extractor(vendor_queries=vq)
        result = extractor.get_triggers("public")
        self.assertEqual(result, [])

    def test_returns_empty_when_sql_is_none(self):
        vq = MagicMock()
        vq.supports_triggers.return_value = True
        vq.get_triggers_query.return_value = (None, [])
        extractor = _make_extractor(vendor_queries=vq)
        result = extractor.get_triggers("public")
        self.assertEqual(result, [])


class TestTriggerExtractorBasicExtraction(unittest.TestCase):
    def test_single_trigger_basic_fields(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "trig_audit",
                "table_name": "users",
                "action_timing": "AFTER",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "EXECUTE FUNCTION audit_fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": "public",
                "function_name": "audit_fn",
                "function_arguments": "",
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("public")
        self.assertEqual(len(trigs), 1)
        self.assertEqual(trigs[0].name, "trig_audit")
        self.assertEqual(trigs[0].table_name, "users")
        self.assertEqual(trigs[0].timing, "AFTER")
        self.assertEqual(trigs[0].events, ["INSERT"])
        self.assertEqual(trigs[0].orientation, "ROW")
        self.assertEqual(trigs[0].definition, "EXECUTE FUNCTION audit_fn()")
        self.assertTrue(trigs[0].enabled)

    def test_empty_results_returns_empty_list(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = []
        trigs = extractor.get_triggers("public")
        self.assertEqual(trigs, [])

    def test_table_filter_passed_to_query(self):
        vq = MagicMock()
        vq.supports_triggers.return_value = True
        vq.get_triggers_query.return_value = ("SELECT 1", ["public", "users"])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = []
        extractor.get_triggers("public", "users")
        vq.get_triggers_query.assert_called_once_with("public", "users")


class TestTriggerExtractorEventParsing(unittest.TestCase):
    def test_multiple_events_in_single_row(self):
        """Multiple event rows for same trigger get merged."""
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "trig1",
                "table_name": "orders",
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "EXECUTE FUNCTION fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            },
            {
                "trigger_name": "trig1",
                "table_name": "orders",
                "action_timing": "BEFORE",
                "event_manipulation": "UPDATE",
                "action_orientation": "ROW",
                "trigger_definition": "EXECUTE FUNCTION fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            },
        ]
        trigs = extractor.get_triggers("public")
        self.assertEqual(len(trigs), 1)
        self.assertIn("INSERT", trigs[0].events)
        self.assertIn("UPDATE", trigs[0].events)

    def test_oracle_or_separated_events(self):
        """Oracle uses 'INSERT OR UPDATE' format."""
        vq = _vq([])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "trig_ora",
                "table_name": "ORDERS",
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT OR UPDATE",
                "action_orientation": "ROW",
                "trigger_definition": None,
                "action_statement": "BEGIN NULL; END;",
                "tgenabled": None,
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("MYSCHEMA")
        self.assertEqual(len(trigs), 1)
        self.assertIn("INSERT", trigs[0].events)
        self.assertIn("UPDATE", trigs[0].events)
        self.assertNotIn("OR", trigs[0].events)

    def test_no_duplicate_events(self):
        """Same event in two rows is only added once."""
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "t",
                "table_name": "x",
                "action_timing": "AFTER",
                "event_manipulation": "DELETE",
                "action_orientation": "ROW",
                "trigger_definition": "EXECUTE FUNCTION fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            },
            {
                "trigger_name": "t",
                "table_name": "x",
                "action_timing": "AFTER",
                "event_manipulation": "DELETE",  # duplicate
                "action_orientation": "ROW",
                "trigger_definition": "EXECUTE FUNCTION fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            },
        ]
        trigs = extractor.get_triggers("public")
        self.assertEqual(trigs[0].events.count("DELETE"), 1)


class TestTriggerExtractorEnabledFlag(unittest.TestCase):
    def test_enabled_when_tgenabled_is_O(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "t",
                "table_name": "x",
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("public")
        self.assertTrue(trigs[0].enabled)

    def test_disabled_when_tgenabled_is_D(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "t",
                "table_name": "x",
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "fn()",
                "action_statement": None,
                "tgenabled": "D",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("public")
        self.assertFalse(trigs[0].enabled)

    def test_enabled_true_when_tgenabled_is_none(self):
        """When no tgenabled column, trigger defaults to enabled=True."""
        vq = _vq([])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "t",
                "table_name": "x",
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": None,
                "action_statement": "BEGIN NULL; END;",
                "tgenabled": None,
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("MYSCHEMA")
        self.assertTrue(trigs[0].enabled)


class TestTriggerExtractorSkipsInvalidRows(unittest.TestCase):
    def test_skips_row_with_missing_trigger_name(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": None,
                "table_name": "users",
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("public")
        self.assertEqual(trigs, [])

    def test_skips_row_with_missing_table_name(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "my_trig",
                "table_name": None,
                "action_timing": "BEFORE",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("public")
        self.assertEqual(trigs, [])


class TestTriggerExtractorDB2ColumnNames(unittest.TestCase):
    def test_db2_returns_trigname_and_tabname(self):
        """DB2 may return original column names instead of aliases."""
        vq = _vq([])
        extractor = _make_extractor(dialect="db2", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "TRIGNAME": "T1",
                "TABNAME": "ORDERS",
                "action_timing": "BEFORE",
                "event_manipulation": "UPDATE",
                "action_orientation": "ROW",
                "trigger_definition": None,
                "action_statement": "BEGIN ATOMIC END",
                "tgenabled": None,
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
            }
        ]
        trigs = extractor.get_triggers("MYSCHEMA")
        self.assertEqual(len(trigs), 1)
        self.assertEqual(trigs[0].name, "T1")
        self.assertEqual(trigs[0].table_name, "ORDERS")


class TestTriggerExtractorMysqlDefiner(unittest.TestCase):
    def test_mysql_definer_attribute(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "mysql_trig",
                "table_name": "products",
                "action_timing": "AFTER",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "BEGIN INSERT INTO log VALUES(NEW.id); END",
                "action_statement": None,
                "tgenabled": None,
                "function_schema": None,
                "function_name": None,
                "function_arguments": None,
                "when_clause": None,
                "is_constraint_trigger": None,
                "tgdeferrable": None,
                "tginitdeferred": None,
                "definer": "root@localhost",
            }
        ]
        trigs = extractor.get_triggers("mydb")
        self.assertEqual(len(trigs), 1)
        self.assertEqual(trigs[0].definer, "root@localhost")


class TestTriggerExtractorConstraintAttributes(unittest.TestCase):
    def test_constraint_trigger_attributes(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "trigger_name": "trig_const",
                "table_name": "orders",
                "action_timing": "AFTER",
                "event_manipulation": "INSERT",
                "action_orientation": "ROW",
                "trigger_definition": "EXECUTE FUNCTION fn()",
                "action_statement": None,
                "tgenabled": "O",
                "function_schema": "public",
                "function_name": "fn",
                "function_arguments": "",
                "when_clause": "NEW.id IS NOT NULL",
                "is_constraint_trigger": "YES",
                "tgdeferrable": "YES",
                "tginitdeferred": "NO",
            }
        ]
        trigs = extractor.get_triggers("public")
        self.assertEqual(len(trigs), 1)
        self.assertTrue(trigs[0].is_constraint_trigger)
        self.assertTrue(trigs[0].constraint_deferrable)
        self.assertFalse(trigs[0].constraint_initially_deferred)
        self.assertEqual(trigs[0].when_clause, "NEW.id IS NOT NULL")


class TestTriggerExtractorErrorHandling(unittest.TestCase):
    def test_query_exception_returns_empty_list(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("DB error")
        trigs = extractor.get_triggers("public")
        self.assertEqual(trigs, [])

    def test_error_tracked_when_result_tracker_set(self):
        vq = _vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        tracker = MagicMock()
        extractor.result_tracker = tracker
        trigs = extractor.get_triggers("public")
        self.assertEqual(trigs, [])
        tracker._track_error.assert_called_once()
