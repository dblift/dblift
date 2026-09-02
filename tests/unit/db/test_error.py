"""Tests for db.error — error classification and connection error formatting."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.db.error import (
    DatabaseErrorClassifier,
    ErrorCategory,
    _extract_sqlstate,
    _is_auth_error,
    format_connection_error,
)

# ---------------------------------------------------------------------------
# ErrorCategory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorCategory:
    """Test ErrorCategory enum values and string compatibility."""

    def test_all_expected_values_exist(self):
        expected = {
            "NETWORK",
            "TIMEOUT",
            "LOCKING",
            "AUTHENTICATION",
            "AUTHORIZATION",
            "SCHEMA",
            "CONSTRAINT",
            "SQL_SYNTAX",
            "RESOURCE",
            "INTERNAL",
            "UNKNOWN",
        }
        assert {e.name for e in ErrorCategory} == expected

    def test_string_compatibility(self):
        """ErrorCategory(str, Enum) should compare with plain strings."""
        assert ErrorCategory.NETWORK == "network"
        assert ErrorCategory.UNKNOWN == "unknown"
        assert ErrorCategory.TIMEOUT == "timeout"

    def test_value_attribute(self):
        assert ErrorCategory.NETWORK.value == "network"
        assert ErrorCategory.SQL_SYNTAX.value == "sql_syntax"


# ---------------------------------------------------------------------------
# DatabaseErrorClassifier
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDatabaseErrorClassifier:
    """Test pattern-based error classification."""

    # -- Oracle --

    def test_oracle_ora17800_network(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-17800: Got minus one from a read call"))
            == ErrorCategory.NETWORK
        )

    def test_oracle_ora17002_network(self):
        c = DatabaseErrorClassifier("oracle")
        assert c.categorize_error(Exception("ORA-17002: I/O error")) == ErrorCategory.NETWORK

    def test_oracle_ora12541_network(self):
        c = DatabaseErrorClassifier("oracle")
        assert c.categorize_error(Exception("ORA-12541: TNS:no listener")) == ErrorCategory.NETWORK

    def test_oracle_ora00060_locking(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-00060: deadlock detected")) == ErrorCategory.LOCKING
        )

    def test_oracle_ora01017_authentication(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-01017: invalid username/password"))
            == ErrorCategory.AUTHENTICATION
        )

    def test_oracle_ora01031_authorization(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-01031: insufficient privileges"))
            == ErrorCategory.AUTHORIZATION
        )

    def test_oracle_ora00942_schema(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-00942: table or view does not exist"))
            == ErrorCategory.SCHEMA
        )

    def test_oracle_ora00001_constraint(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-00001: unique constraint violated"))
            == ErrorCategory.CONSTRAINT
        )

    def test_oracle_ora00900_sql_syntax(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-00900: invalid SQL statement"))
            == ErrorCategory.SQL_SYNTAX
        )

    def test_oracle_ora04031_resource(self):
        c = DatabaseErrorClassifier("oracle")
        assert (
            c.categorize_error(Exception("ORA-04031: unable to allocate memory"))
            == ErrorCategory.RESOURCE
        )

    # -- PostgreSQL --

    def test_postgresql_sqlstate_08001_network(self):
        c = DatabaseErrorClassifier("postgresql")
        assert (
            c.categorize_error(Exception("SQLSTATE 08001: connection failure"))
            == ErrorCategory.NETWORK
        )

    def test_postgresql_sqlstate_40001_locking(self):
        c = DatabaseErrorClassifier("postgresql")
        assert (
            c.categorize_error(Exception("SQLSTATE 40001: serialization failure"))
            == ErrorCategory.LOCKING
        )

    def test_postgresql_sqlstate_23505_constraint(self):
        c = DatabaseErrorClassifier("postgresql")
        assert (
            c.categorize_error(Exception("SQLSTATE 23505: unique violation"))
            == ErrorCategory.CONSTRAINT
        )

    def test_postgresql_sqlstate_42601_sql_syntax(self):
        c = DatabaseErrorClassifier("postgresql")
        assert (
            c.categorize_error(Exception("SQLSTATE 42601: syntax error"))
            == ErrorCategory.SQL_SYNTAX
        )

    def test_postgresql_sqlstate_28000_authentication(self):
        c = DatabaseErrorClassifier("postgresql")
        assert (
            c.categorize_error(Exception("SQLSTATE 28000: invalid authorization"))
            == ErrorCategory.AUTHENTICATION
        )

    # -- DB2 --

    def test_db2_errorcode_minus4499_network(self):
        c = DatabaseErrorClassifier("db2")
        assert (
            c.categorize_error(Exception("errorcode=-4499, sqlstate=08001"))
            == ErrorCategory.NETWORK
        )

    def test_db2_sql0911n_locking(self):
        c = DatabaseErrorClassifier("db2")
        assert (
            c.categorize_error(Exception("SQL0911N: The current transaction has been rolled back"))
            == ErrorCategory.LOCKING
        )

    def test_db2_disconnect_exception_network(self):
        c = DatabaseErrorClassifier("db2")
        assert (
            c.categorize_error(Exception("DisconnectNonTransientConnectionException"))
            == ErrorCategory.NETWORK
        )

    # -- MySQL --

    def test_mysql_2003_network(self):
        c = DatabaseErrorClassifier("mysql")
        assert (
            c.categorize_error(Exception("2003 Can't connect to MySQL server"))
            == ErrorCategory.NETWORK
        )

    def test_mysql_2013_network(self):
        c = DatabaseErrorClassifier("mysql")
        assert (
            c.categorize_error(Exception("2013 Lost connection to MySQL server"))
            == ErrorCategory.NETWORK
        )

    def test_mysql_1205_locking(self):
        c = DatabaseErrorClassifier("mysql")
        assert (
            c.categorize_error(Exception("1205 Lock wait timeout exceeded"))
            == ErrorCategory.LOCKING
        )

    def test_mysql_1045_authentication(self):
        c = DatabaseErrorClassifier("mysql")
        assert (
            c.categorize_error(Exception("1045 Access denied for user 'root'"))
            == ErrorCategory.AUTHENTICATION
        )

    # -- Generic fallback --

    def test_generic_connection_reset(self):
        c = DatabaseErrorClassifier("generic")
        assert c.categorize_error(Exception("connection reset by peer")) == ErrorCategory.NETWORK

    def test_generic_broken_pipe(self):
        c = DatabaseErrorClassifier("generic")
        assert c.categorize_error(Exception("broken pipe")) == ErrorCategory.NETWORK

    def test_generic_deadlock(self):
        c = DatabaseErrorClassifier("generic")
        assert c.categorize_error(Exception("deadlock detected")) == ErrorCategory.LOCKING

    def test_generic_timeout(self):
        c = DatabaseErrorClassifier("generic")
        assert c.categorize_error(Exception("query timed out")) == ErrorCategory.TIMEOUT

    def test_unknown_error(self):
        c = DatabaseErrorClassifier("generic")
        assert (
            c.categorize_error(Exception("something unexpected happened")) == ErrorCategory.UNKNOWN
        )


# ---------------------------------------------------------------------------
# format_connection_error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatConnectionError:
    """Test the shared connection-error formatter's remaining branches."""

    def test_unknown_host_returns_host_not_found(self):
        """No auth markers, no SQLState, no refused/timeout substring: the
        'unknown host' substring branch is reached."""
        err = Exception("could not translate host name: unknown host db.example.invalid")
        out = format_connection_error(err, "generic")
        assert out == "Connection failed: host not found"

    def test_name_or_service_not_known_returns_host_not_found(self):
        err = Exception("Temporary failure: name or service not known")
        out = format_connection_error(err, "generic")
        assert out == "Connection failed: host not found"

    def test_pymssql_tuple_error_is_unwrapped(self):
        """pymssql raises errors as a raw tuple; its str() must not leak
        the byte-string literal or error-code tuple wrapper verbatim."""
        raw = (
            "(20009, b'DB-Lib error message 20009, severity 9: "
            "Unable to connect: Adaptive Server is unavailable or does not exist')"
        )
        result = format_connection_error(Exception(raw), "sqlserver")
        assert "20009" not in result or "b'" not in result
        assert "Unable to connect" in result

    def test_sqlite_filesystem_permission_error_is_not_invalid_credentials(self):
        """A PermissionError raised while SQLite tries to open/create its
        database file (e.g. an unwritable parent directory) is an OS-level
        filesystem error, not a database authentication failure. SQLite has
        no credentials concept, so the message must reflect the actual OS
        error rather than the generic 'invalid credentials' wording."""
        err = PermissionError(13, "Permission denied")
        # Match the real message shape raised by Path.mkdir() on a read-only
        # parent directory: "[Errno 13] Permission denied: '/tmp/ro/sub'"
        err.filename = "/tmp/ro/sub"
        result = format_connection_error(err, "sqlite")
        assert result != "Connection failed: invalid credentials"
        assert "Permission denied" in result
        assert "/tmp/ro/sub" in result


# ---------------------------------------------------------------------------
# _is_auth_error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsAuthError:
    """Test the classifier fallback used by _is_auth_error."""

    def test_returns_false_when_classifier_construction_raises(self):
        """If DatabaseErrorClassifier(db_type) or categorize_error() raises for
        any reason, _is_auth_error must swallow it and report 'not an auth
        error' rather than propagating."""
        with patch("dblift.db.error.DatabaseErrorClassifier", side_effect=RuntimeError("boom")):
            result = _is_auth_error(
                Exception("some odd driver failure"), "some odd driver failure", "generic"
            )
        assert result is False

    def test_returns_false_for_os_level_permission_error(self):
        """A raw PermissionError/OSError (e.g. from SQLite failing to open a
        file on an unwritable path) must not be classified as an auth error
        just because its message contains 'Permission denied' — the generic
        AUTHORIZATION pattern is meant for database-level permission errors,
        not filesystem errors from embedded drivers."""
        err = PermissionError(13, "Permission denied", "/tmp/ro/sub")
        result = _is_auth_error(err, str(err).lower(), "sqlite")
        assert result is False


# ---------------------------------------------------------------------------
# _extract_sqlstate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSqlstate:
    """Test SQLState extraction edge cases."""

    def test_returns_none_when_getSQLState_raises(self):
        err = Exception("driver error")
        err.getSQLState = MagicMock(side_effect=RuntimeError("driver crashed"))  # type: ignore[attr-defined]
        assert _extract_sqlstate(err) is None

    def test_reads_plain_sqlstate_attribute(self):
        """Drivers that expose sqlstate as a plain attribute instead of a
        getSQLState() method are also supported."""
        err = Exception("driver error")
        err.sqlstate = "28000"  # type: ignore[attr-defined]
        assert _extract_sqlstate(err) == "28000"
