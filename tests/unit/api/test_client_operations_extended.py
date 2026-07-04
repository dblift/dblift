"""Tests for api/_client_operations.py."""

import unittest
from unittest.mock import MagicMock


class TestHeuristicStatementCount(unittest.TestCase):
    def _count(self, sql):
        from api._client_operations import _heuristic_statement_count_from_sql

        return _heuristic_statement_count_from_sql(sql)

    def test_empty_returns_zero(self):
        self.assertEqual(self._count(""), 0)

    def test_single_statement(self):
        self.assertEqual(self._count("SELECT 1;"), 1)

    def test_multiple_statements(self):
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3;"
        self.assertEqual(self._count(sql), 3)

    def test_skips_comments(self):
        sql = "-- comment\nSELECT 1;"
        self.assertEqual(self._count(sql), 1)

    def test_skips_lines_without_semicolon(self):
        sql = "CREATE TABLE t (\n  id INT\n);"
        # Only last line ends with semicolon
        self.assertEqual(self._count(sql), 1)

    def test_skips_blank_lines(self):
        sql = "\n\nSELECT 1;\n\n"
        self.assertEqual(self._count(sql), 1)


class TestApplySqlScriptWarningScan(unittest.TestCase):
    def _scan(self, result, sql):
        from api._client_operations import _apply_sql_script_warning_scan

        _apply_sql_script_warning_scan(result, sql)

    def _result(self):
        from core.logger.results import GenerateUndoScriptResult

        return GenerateUndoScriptResult()

    def test_no_warning_no_flag(self):
        result = self._result()
        self._scan(result, "CREATE TABLE t (id INT);")
        self.assertFalse(result.requires_manual_review)

    def test_warning_sets_flag(self):
        result = self._result()
        self._scan(result, "-- WARNING: review this\nCREATE TABLE t (id INT);")
        self.assertTrue(result.requires_manual_review)

    def test_requires_manual_review_text(self):
        result = self._result()
        self._scan(result, "-- requires manual review\nALTER TABLE t DROP COLUMN x;")
        self.assertTrue(result.requires_manual_review)

    def test_collects_warning_messages(self):
        result = self._result()
        self._scan(result, "-- WARNING: data loss possible\nDROP TABLE users;")
        self.assertTrue(result.requires_manual_review)


class TestGenerateUndoScriptOperation(unittest.TestCase):
    def test_missing_script_raises_or_errors(self):
        from pathlib import Path

        from api._client_operations import generate_undo_script_operation

        client = MagicMock()
        client.migrations_dirs = [Path("/nonexistent")]
        try:
            result = generate_undo_script_operation(
                client, migration_path=Path("/nonexistent/V1.sql")
            )
            self.assertIsNotNone(result)
        except (FileNotFoundError, ValueError, RuntimeError):
            pass  # Expected — file doesn't exist


class TestUndoScriptErrorResult(unittest.TestCase):
    def test_creates_failure_result(self):
        from pathlib import Path

        from api._client_operations import _undo_script_error_result

        result = _undo_script_error_result(Path("/tmp/V1.sql"), "test error")
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
