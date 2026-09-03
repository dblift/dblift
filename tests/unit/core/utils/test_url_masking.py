"""Tests for core.utils.url_masking module."""

import pytest

from dblift.core.utils.url_masking import mask_database_url


@pytest.mark.unit
class TestMaskDatabaseUrl:
    """Test mask_database_url function."""

    def test_masks_standard_authority_format(self):
        """Standard //user:password@host format must mask password."""
        url = "postgresql+psycopg://admin:secret@host:5432/db"
        masked = mask_database_url(url)
        assert "secret" not in masked
        assert "admin" in masked
        assert "***" in masked
        assert "//admin:***@host" in masked

    def test_masks_password_param(self):
        """password= query param must be masked."""
        url = "postgresql+psycopg://localhost/db?user=admin&password=secret123"
        masked = mask_database_url(url)
        assert "password=***" in masked
        assert "secret123" not in masked

    def test_masks_pwd_param(self):
        """pwd= query param must be masked."""
        url = "postgresql+psycopg://localhost/db?user=admin&pwd=secret123"
        masked = mask_database_url(url)
        assert "pwd=***" in masked
        assert "secret123" not in masked

    def test_masks_cosmosdb_account_key(self):
        """CosmosDB AccountKey= must be masked."""
        url = "AccountEndpoint=https://account.documents.azure.com/;AccountKey=abc123;"
        masked = mask_database_url(url)
        assert "abc123" not in masked
        assert "AccountKey=***" in masked

    def test_masks_leading_password_param(self):
        """password= at the very start of a connection string must be masked.

        ODBC/DB2-style strings have no ``?``/``&``/``;`` before the first
        parameter, so the delimiter-anchored patterns must not be the only
        ones that match.
        """
        conn = "password=secret123;server=host;database=db"
        masked = mask_database_url(conn)
        assert "secret123" not in masked
        assert "password=***" in masked

    def test_masks_semicolon_password_param(self):
        """password= after a ';' separator must be masked."""
        conn = "server=host;password=secret123;database=db"
        masked = mask_database_url(conn)
        assert "secret123" not in masked

    def test_no_password_url_unchanged(self):
        """URL without credentials remains unchanged."""
        url = "postgresql+psycopg://localhost/db?user=admin"
        assert mask_database_url(url) == url

    @pytest.mark.parametrize(
        "value",
        [
            # "password=" / "pwd=" as the tail of a longer token: not the
            # parameter, so masking it corrupts an operator-visible value.
            "DATABASE=db;oldpassword=keepme;UID=u",
            "Server=s;old_password=keepme;",
            "Server=s;custom_pwd_hint=keepme;",
            # A filesystem path that merely contains the letters.
            "sqlite:////home/pwd=keepme/app.db",
        ],
    )
    def test_does_not_mask_password_lookalikes(self, value):
        """Only a real parameter may be masked, never a substring of one."""
        assert mask_database_url(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "password=secret123;server=host",
            "server=host;password=secret123",
            "server=host?password=secret123",
            "server=host&password=secret123",
            "server=host;pwd=secret123",
            "PWD=secret123;server=host",
        ],
    )
    def test_masks_real_password_parameters(self, value):
        """Every delimiter — and the start of the string — still masks."""
        assert "secret123" not in mask_database_url(value)
