"""
Tests for system-generated constraint name detection.

This module tests that user-defined constraint names are not incorrectly
classified as system-generated, which would cause them to be ignored during
schema comparison.
"""

import pytest

from core.comparison.comparison_utils import is_system_generated_constraint_name

pytestmark = [pytest.mark.unit]


class TestSystemGeneratedConstraintNames:
    """Test system-generated constraint name detection."""

    def test_postgresql_pkey_always_system_generated(self):
        """Test that _pkey suffix is always considered system-generated."""
        assert is_system_generated_constraint_name("users_pkey") is True
        assert is_system_generated_constraint_name("products_pkey") is True
        assert is_system_generated_constraint_name("orders_pkey") is True

    def test_postgresql_fkey_always_system_generated(self):
        """Test that _fkey suffix is always considered system-generated."""
        assert is_system_generated_constraint_name("users_user_id_fkey") is True
        assert is_system_generated_constraint_name("orders_customer_id_fkey") is True

    def test_postgresql_key_with_underscore_is_system_generated(self):
        """Test that tablename_columnname_key pattern is system-generated."""
        assert is_system_generated_constraint_name("users_email_key") is True
        assert is_system_generated_constraint_name("products_sku_key") is True
        assert is_system_generated_constraint_name("orders_order_number_key") is True

    def test_postgresql_check_with_underscore_is_system_generated(self):
        """Test that tablename_columnname_check pattern is system-generated."""
        assert is_system_generated_constraint_name("users_age_check") is True
        assert is_system_generated_constraint_name("products_price_check") is True

    def test_user_defined_key_not_system_generated(self):
        """Test that user-defined constraint names ending in _key are NOT system-generated."""
        # These should NOT be considered system-generated
        assert is_system_generated_constraint_name("my_api_key") is False
        assert is_system_generated_constraint_name("primary_key_override") is False
        assert is_system_generated_constraint_name("foreign_key_constraint") is False
        assert is_system_generated_constraint_name("unique_key_constraint") is False
        # Single word ending in _key (no underscore before)
        assert is_system_generated_constraint_name("apikey") is False

    def test_user_defined_check_not_system_generated(self):
        """Test that user-defined constraint names ending in _check are NOT system-generated."""
        # These should NOT be considered system-generated
        assert is_system_generated_constraint_name("health_check") is False
        assert is_system_generated_constraint_name("data_check_validation") is False
        # Single word ending in _check (no underscore before)
        assert is_system_generated_constraint_name("check") is False

    def test_oracle_sys_c_pattern(self):
        """Test Oracle SYS_C pattern detection."""
        assert is_system_generated_constraint_name("SYS_C0013220") is True
        assert is_system_generated_constraint_name("SYS_C123456") is True
        assert is_system_generated_constraint_name("SYS_CUSTOM") is False  # Not all numeric
        assert is_system_generated_constraint_name("sys_c0013220") is True  # Case insensitive

    def test_sqlserver_pattern(self):
        """Test SQL Server auto-generated pattern detection."""
        assert is_system_generated_constraint_name("PK__users__3213E83F") is True
        assert is_system_generated_constraint_name("FK__orders__customer_id__123456") is True
        assert is_system_generated_constraint_name("PK_users") is False  # No double underscore
        assert is_system_generated_constraint_name("users_PK") is False  # Wrong position

    def test_unnamed_pattern(self):
        """Test unnamed constraint pattern."""
        assert is_system_generated_constraint_name("unnamed_1") is True
        assert is_system_generated_constraint_name("unnamed_123") is True
        assert is_system_generated_constraint_name("named_constraint") is False

    def test_user_defined_names_not_system_generated(self):
        """Test that clearly user-defined names are not system-generated."""
        assert is_system_generated_constraint_name("pk_users_id") is False
        assert is_system_generated_constraint_name("fk_user_orders") is False
        assert is_system_generated_constraint_name("ck_age_positive") is False
        assert is_system_generated_constraint_name("uq_email") is False
        assert is_system_generated_constraint_name("custom_constraint_name") is False

    def test_edge_cases(self):
        """Test edge cases."""
        assert is_system_generated_constraint_name("") is False
        assert is_system_generated_constraint_name(None) is False
        assert is_system_generated_constraint_name("key") is False  # Just "key"
        assert is_system_generated_constraint_name("check") is False  # Just "check"
        assert is_system_generated_constraint_name("_key") is False  # Just "_key" (no prefix)
        assert is_system_generated_constraint_name("_check") is False  # Just "_check" (no prefix)

    def test_false_positive_prevention(self):
        """Test that legitimate user-defined constraint names are not incorrectly marked as system-generated."""
        # These should NOT be system-generated (user-defined names)
        assert (
            is_system_generated_constraint_name("customer_key") is False
        )  # Single word, no underscore
        assert (
            is_system_generated_constraint_name("order_check") is False
        )  # Single word, no underscore
        assert (
            is_system_generated_constraint_name("payment_status_key") is True
        )  # Could be auto-generated (table=payment, column=status)
        assert (
            is_system_generated_constraint_name("user_profile_key") is True
        )  # Could be auto-generated (table=user, column=profile)
        assert (
            is_system_generated_constraint_name("product_category_check") is True
        )  # Could be auto-generated
        # These should be correctly identified as user-defined
        assert (
            is_system_generated_constraint_name("my_api_key") is False
        )  # Starts with "my", contains "api"
        assert (
            is_system_generated_constraint_name("primary_key_override") is False
        )  # Starts with "primary"
        assert (
            is_system_generated_constraint_name("foreign_key_constraint") is False
        )  # Starts with "foreign"
        assert (
            is_system_generated_constraint_name("unique_key_constraint") is False
        )  # Starts with "unique"
        assert (
            is_system_generated_constraint_name("constraint_key") is False
        )  # Starts with "constraint"
        assert is_system_generated_constraint_name("health_check") is False  # Starts with "health"
        assert (
            is_system_generated_constraint_name("data_check_validation") is False
        )  # Starts with "data"
        assert (
            is_system_generated_constraint_name("validation_check") is False
        )  # Starts with "validation"
        assert (
            is_system_generated_constraint_name("override_check") is False
        )  # Starts with "override"
