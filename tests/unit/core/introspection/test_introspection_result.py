"""Tests for db/introspection/result.py."""

import unittest
from unittest.mock import MagicMock


class TestResultSeverity(unittest.TestCase):
    def test_enum_values(self):
        from core.introspection.result import ResultSeverity

        self.assertEqual(ResultSeverity.INFO.value, "info")
        self.assertEqual(ResultSeverity.WARNING.value, "warning")
        self.assertEqual(ResultSeverity.ERROR.value, "error")
        self.assertEqual(ResultSeverity.CRITICAL.value, "critical")


class TestIntrospectionIssue(unittest.TestCase):
    def test_str_basic(self):
        from core.introspection.result import IntrospectionIssue, ResultSeverity

        issue = IntrospectionIssue(severity=ResultSeverity.WARNING, message="test warning")
        s = str(issue)
        self.assertIn("WARNING", s)
        self.assertIn("test warning", s)

    def test_str_with_object_type_and_name(self):
        from core.introspection.result import IntrospectionIssue, ResultSeverity

        issue = IntrospectionIssue(
            severity=ResultSeverity.ERROR,
            message="err",
            object_type="table",
            object_name="users",
        )
        s = str(issue)
        self.assertIn("table.users", s)

    def test_str_with_property(self):
        from core.introspection.result import IntrospectionIssue, ResultSeverity

        issue = IntrospectionIssue(
            severity=ResultSeverity.INFO,
            message="msg",
            property_name="columns",
        )
        s = str(issue)
        self.assertIn("Property: columns", s)

    def test_str_with_exception(self):
        from core.introspection.result import IntrospectionIssue, ResultSeverity

        exc = ValueError("bad value")
        issue = IntrospectionIssue(severity=ResultSeverity.ERROR, message="err", exception=exc)
        s = str(issue)
        self.assertIn("ValueError", s)


class TestObjectCaptureStatus(unittest.TestCase):
    def test_completeness_no_properties(self):
        from core.introspection.result import ObjectCaptureStatus

        s = ObjectCaptureStatus(object_type="table", object_name="users")
        self.assertEqual(s.get_completeness_score(), 1.0)

    def test_completeness_not_captured(self):
        from core.introspection.result import ObjectCaptureStatus

        s = ObjectCaptureStatus(object_type="table", object_name="users", captured=False)
        self.assertEqual(s.get_completeness_score(), 0.0)

    def test_completeness_all_captured(self):
        from core.introspection.result import ObjectCaptureStatus

        s = ObjectCaptureStatus(object_type="table", object_name="users")
        s.add_property_status("columns", True)
        s.add_property_status("indexes", True)
        self.assertEqual(s.get_completeness_score(), 1.0)

    def test_completeness_partial(self):
        from core.introspection.result import ObjectCaptureStatus

        s = ObjectCaptureStatus(object_type="table", object_name="users")
        s.add_property_status("columns", True)
        s.add_property_status("indexes", False)
        self.assertEqual(s.get_completeness_score(), 0.5)

    def test_add_property_status_with_issue(self):
        from core.introspection.result import (
            IntrospectionIssue,
            ObjectCaptureStatus,
            ResultSeverity,
        )

        s = ObjectCaptureStatus(object_type="table", object_name="users")
        issue = IntrospectionIssue(severity=ResultSeverity.WARNING, message="warn")
        s.add_property_status("columns", False, issue=issue)
        self.assertEqual(len(s.issues), 1)


class TestIntrospectionResult(unittest.TestCase):
    def _make(self):
        from core.introspection.result import IntrospectionResult

        return IntrospectionResult()

    def test_default_success(self):
        r = self._make()
        self.assertTrue(r.success)

    def test_add_warning(self):
        r = self._make()
        r.add_warning("test warning", object_type="table", object_name="t")
        self.assertEqual(len(r.warnings), 1)
        # add_warning does NOT set success = False (only add_error does)
        self.assertTrue(r.success)

    def test_add_error(self):
        r = self._make()
        r.add_error("test error")
        self.assertEqual(len(r.errors), 1)
        self.assertFalse(r.success)

    def test_add_object_status(self):
        from core.introspection.result import ObjectCaptureStatus

        r = self._make()
        status = ObjectCaptureStatus("table", "users")
        r.object_statuses.append(status)
        self.assertEqual(len(r.object_statuses), 1)
        self.assertEqual(r.object_statuses[0].object_type, "table")

    def test_to_dict_success(self):
        r = self._make()
        d = r.to_dict()
        self.assertIn("success", d)
        self.assertTrue(d["success"])

    def test_to_dict_with_errors(self):
        r = self._make()
        r.add_error("DB error")
        d = r.to_dict()
        self.assertFalse(d["success"])
        self.assertGreater(len(d["errors"]), 0)

    def test_error_count(self):
        r = self._make()
        r.add_error("e1")
        r.add_error("e2")
        self.assertEqual(len(r.errors), 2)

    def test_warning_count(self):
        r = self._make()
        r.add_warning("w1")
        r.add_warning("w2")
        self.assertEqual(len(r.warnings), 2)
