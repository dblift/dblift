"""Tests for db/introspection/core/utils.py."""

import unittest


class TestGetRowValue(unittest.TestCase):
    def _get(self, row, key):
        from core.introspection._utils import get_row_value

        return get_row_value(row, key)

    def test_lowercase_key(self):
        self.assertEqual(self._get({"table_name": "users"}, "table_name"), "users")

    def test_uppercase_key_fallback(self):
        self.assertEqual(self._get({"TABLE_NAME": "users"}, "table_name"), "users")

    def test_none_when_not_found(self):
        self.assertIsNone(self._get({}, "table_name"))

    def test_compact_key_fallback(self):
        self.assertEqual(self._get({"tablename": "users"}, "table_name"), "users")

    def test_db2_sequence_abbreviation(self):
        result = self._get({"seqname": "my_seq"}, "sequence_name")
        self.assertIsNotNone(result)

    def test_db2_constraint_abbreviation(self):
        result = self._get({"constname": "pk1"}, "constraint_name")
        self.assertIsNotNone(result)

    def test_db2_table_abbreviation(self):
        result = self._get({"tabname": "users"}, "table_name")
        self.assertIsNotNone(result)

    def test_db2_column_abbreviation(self):
        result = self._get({"colname": "id"}, "column_name")
        self.assertIsNotNone(result)

    def test_db2_index_abbreviation(self):
        result = self._get({"indname": "idx_users"}, "index_name")
        self.assertIsNotNone(result)

    def test_returns_zero_value(self):
        self.assertEqual(self._get({"count": 0}, "count"), 0)


class TestParseJsonArray(unittest.TestCase):
    def _parse(self, val):
        from core.introspection._utils import parse_json_array

        return parse_json_array(val)

    def test_none_returns_empty(self):
        self.assertEqual(self._parse(None), [])

    def test_valid_json_array(self):
        import json

        result = self._parse(json.dumps([{"a": 1}]))
        self.assertEqual(len(result), 1)

    def test_invalid_json_returns_empty(self):
        result = self._parse("not-json")
        self.assertEqual(result, [])

    def test_list_returned_as_is(self):
        result = self._parse([{"a": 1}])
        self.assertEqual(len(result), 1)

    def test_empty_string_returns_empty(self):
        result = self._parse("")
        self.assertEqual(result, [])


class TestToInt(unittest.TestCase):
    def _to_int(self, val):
        from core.introspection._utils import to_int

        return to_int(val)

    def test_integer(self):
        self.assertEqual(self._to_int(42), 42)

    def test_string_int(self):
        self.assertEqual(self._to_int("10"), 10)

    def test_none_returns_none(self):
        self.assertIsNone(self._to_int(None))

    def test_invalid_string_returns_none(self):
        self.assertIsNone(self._to_int("abc"))

    def test_float_string(self):
        self.assertEqual(self._to_int("3.7"), 3)


class TestStripLeadingComments(unittest.TestCase):
    def _strip(self, text):
        from core.introspection._utils import strip_leading_comments

        return strip_leading_comments(text)

    def test_strips_single_line_comment(self):
        result = self._strip("-- This is a comment\nCREATE TABLE t ()")
        self.assertNotIn("-- This is a comment", result)
        self.assertIn("CREATE TABLE", result)

    def test_strips_block_comment(self):
        result = self._strip("/* comment */\nCREATE TABLE t ()")
        self.assertNotIn("/* comment */", result)

    def test_no_comment_unchanged(self):
        result = self._strip("CREATE TABLE t ()")
        self.assertIn("CREATE TABLE", result)

    def test_none_returns_empty(self):
        result = self._strip(None)
        self.assertIn(result, ("", None))
