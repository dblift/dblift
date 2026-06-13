"""Tests for _ensure_semicolon() module-level helper in diff_sql_generator."""

import unittest

import pytest

from core.sql_generator.diff_sql_generator import _ensure_semicolon

pytestmark = [pytest.mark.unit]


class TestEnsureSemicolon(unittest.TestCase):
    """Tests for _ensure_semicolon()."""

    def test_already_ends_with_semicolon(self):
        result = _ensure_semicolon("SELECT 1;")
        self.assertEqual(result, "SELECT 1;")

    def test_without_semicolon(self):
        result = _ensure_semicolon("SELECT 1")
        self.assertEqual(result, "SELECT 1;")

    def test_empty_string(self):
        result = _ensure_semicolon("")
        self.assertEqual(result, ";")

    def test_trailing_spaces_no_semicolon(self):
        result = _ensure_semicolon("SELECT 1  ")
        self.assertEqual(result, "SELECT 1  ;")

    def test_double_semicolon(self):
        result = _ensure_semicolon("SELECT 1;;")
        self.assertEqual(result, "SELECT 1;;")

    def test_multiline_sql(self):
        sql = "CREATE TABLE foo (\n    id INT\n)"
        result = _ensure_semicolon(sql)
        self.assertEqual(result, sql + ";")

    def test_multiline_sql_already_terminated(self):
        sql = "CREATE TABLE foo (\n    id INT\n);"
        result = _ensure_semicolon(sql)
        self.assertEqual(result, sql)

    def test_semicolon_only(self):
        result = _ensure_semicolon(";")
        self.assertEqual(result, ";")


if __name__ == "__main__":
    unittest.main()
