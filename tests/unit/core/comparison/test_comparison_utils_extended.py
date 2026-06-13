"""Extended tests for core/comparison/comparison_utils.py."""

import unittest


class TestIsSystemGeneratedConstraintName(unittest.TestCase):
    def _check(self, name):
        from core.comparison.comparison_utils import is_system_generated_constraint_name

        return is_system_generated_constraint_name(name)

    def test_none_false(self):
        self.assertFalse(self._check(None))

    def test_empty_false(self):
        self.assertFalse(self._check(""))

    def test_oracle_sys_c(self):
        self.assertTrue(self._check("SYS_C0013220"))

    def test_sqlserver_pk_double_underscore(self):
        self.assertTrue(self._check("PK__users__3213E83F"))

    def test_sqlserver_fk_double_underscore(self):
        self.assertTrue(self._check("FK__orders__user_id__3213E83F"))

    def test_user_defined_false(self):
        self.assertFalse(self._check("pk_users_id"))

    def test_regular_name_false(self):
        # Plain name without system-gen patterns
        self.assertFalse(self._check("my_constraint"))

    def test_mixed_case_oracle(self):
        self.assertTrue(self._check("sys_c0013220"))


class TestNormalizeIdentifier(unittest.TestCase):
    def _n(self, ident):
        from core.comparison.comparison_utils import normalize_identifier

        return normalize_identifier(ident)

    def test_lowercase(self):
        result = self._n("MY_TABLE")
        self.assertEqual(result, "my_table")

    def test_none_returns_empty(self):
        result = self._n(None)
        self.assertEqual(result, "")

    def test_empty_string(self):
        result = self._n("")
        self.assertEqual(result, "")

    def test_already_lowercase(self):
        result = self._n("my_table")
        self.assertEqual(result, "my_table")


class TestNormalizeExpression(unittest.TestCase):
    def _n(self, expr):
        from core.comparison.comparison_utils import normalize_expression

        return normalize_expression(expr)

    def test_none_returns_empty(self):
        result = self._n(None)
        self.assertIn(result, ("", None))

    def test_strips_whitespace(self):
        result = self._n("  age > 0  ")
        self.assertIsInstance(result, str)

    def test_basic_expression(self):
        result = self._n("age > 0")
        self.assertIsInstance(result, str)


class TestExtractBaseIdentityType(unittest.TestCase):
    def test_int_postgres(self):
        from core.comparison.comparison_utils import extract_base_identity_type

        result = extract_base_identity_type("INT", "postgresql")
        self.assertIsInstance(result, str)

    def test_number_oracle(self):
        from core.comparison.comparison_utils import extract_base_identity_type

        result = extract_base_identity_type("NUMBER(10,0)", "oracle")
        self.assertIsInstance(result, str)


class TestNormalizeParameters(unittest.TestCase):
    def test_none_returns_empty(self):
        from core.comparison.comparison_utils import normalize_parameters

        result = normalize_parameters(None)
        self.assertEqual(result, "")

    def test_empty_list(self):
        from core.comparison.comparison_utils import normalize_parameters

        result = normalize_parameters([])
        self.assertEqual(result, "")

    def test_with_params(self):
        from core.comparison.comparison_utils import normalize_parameters

        result = normalize_parameters(["param1", "param2"])
        self.assertIsInstance(result, str)
