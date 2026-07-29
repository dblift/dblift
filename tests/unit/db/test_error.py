"""Tests for db.error — error classification, retry logic, and data classes."""

from unittest.mock import MagicMock, patch

import pytest

from db.error import (
    DatabaseErrorClassifier,
    DatabaseErrorInfo,
    ErrorCategory,
    RetryManager,
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
# DatabaseErrorInfo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDatabaseErrorInfo:
    """Test DatabaseErrorInfo dataclass."""

    def test_defaults(self):
        info = DatabaseErrorInfo(exception=ValueError("boom"))
        assert info.category == ErrorCategory.UNKNOWN
        assert info.retry_count == 0
        assert info.context == {}
        assert info.sql is None
        assert info.params is None
        assert info.schema is None

    def test_str_basic(self):
        info = DatabaseErrorInfo(exception=RuntimeError("oops"))
        result = str(info)
        assert "[UNKNOWN]" in result
        assert "oops" in result

    def test_str_with_sql_and_schema(self):
        info = DatabaseErrorInfo(
            exception=RuntimeError("fail"),
            sql="SELECT 1",
            schema="public",
            category=ErrorCategory.NETWORK,
            retry_count=2,
        )
        result = str(info)
        assert "[NETWORK]" in result
        assert "SELECT 1" in result
        assert "public" in result
        assert "Retry: 2" in result

    def test_str_truncates_long_sql(self):
        long_sql = "SELECT " + "x" * 200
        info = DatabaseErrorInfo(exception=RuntimeError("e"), sql=long_sql)
        result = str(info)
        assert "..." in result


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

    # -- is_retryable --

    def test_is_retryable_network(self):
        c = DatabaseErrorClassifier("generic")
        assert c.is_retryable(ErrorCategory.NETWORK, retry_count=0, max_retries=3) is True

    def test_is_retryable_timeout(self):
        c = DatabaseErrorClassifier("generic")
        assert c.is_retryable(ErrorCategory.TIMEOUT, retry_count=0, max_retries=3) is True

    def test_is_retryable_locking(self):
        c = DatabaseErrorClassifier("generic")
        assert c.is_retryable(ErrorCategory.LOCKING, retry_count=0, max_retries=3) is True

    def test_not_retryable_authentication(self):
        c = DatabaseErrorClassifier("generic")
        assert c.is_retryable(ErrorCategory.AUTHENTICATION) is False

    def test_not_retryable_unknown(self):
        c = DatabaseErrorClassifier("generic")
        assert c.is_retryable(ErrorCategory.UNKNOWN) is False

    def test_not_retryable_when_max_retries_reached(self):
        c = DatabaseErrorClassifier("generic")
        assert c.is_retryable(ErrorCategory.NETWORK, retry_count=3, max_retries=3) is False


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
        with patch("db.error.DatabaseErrorClassifier", side_effect=RuntimeError("boom")):
            result = _is_auth_error(
                Exception("some odd driver failure"), "some odd driver failure", "generic"
            )
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


# ---------------------------------------------------------------------------
# RetryManager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetryManager:
    """Test RetryManager retry logic."""

    @pytest.fixture
    def classifier(self):
        return DatabaseErrorClassifier("generic")

    @pytest.fixture
    def manager(self, classifier):
        return RetryManager(
            classifier, log=None, max_retries=3, base_delay=0.01, max_delay=0.1, jitter=0.0
        )

    def test_success_on_first_try(self, manager):
        result = manager.execute_with_retry(lambda: "ok")
        assert result == "ok"

    def test_retry_on_transient_error_then_succeed(self, manager):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("connection reset by peer")
            return "recovered"

        result = manager.execute_with_retry(flaky)
        assert result == "recovered"
        assert call_count == 3

    def test_raise_after_max_retries(self, manager):
        def always_fail():
            raise Exception("connection reset by peer")

        with pytest.raises(Exception, match="connection reset"):
            manager.execute_with_retry(always_fail)

    def test_no_retry_on_non_retryable_error(self, manager):
        call_count = 0

        def bad_sql():
            nonlocal call_count
            call_count += 1
            raise Exception("something unexpected happened")

        with pytest.raises(Exception, match="something unexpected"):
            manager.execute_with_retry(bad_sql)
        assert call_count == 1

    def test_args_and_kwargs_forwarded(self, manager):
        def add(a, b, extra=0):
            return a + b + extra

        result = manager.execute_with_retry(add, 1, 2, extra=10)
        assert result == 13

    def test_exponential_backoff(self, classifier):
        mgr = RetryManager(
            classifier,
            log=None,
            max_retries=3,
            base_delay=1.0,
            max_delay=100.0,
            backoff_multiplier=2.0,
            jitter=0.0,
        )
        assert mgr._compute_delay(0) == pytest.approx(1.0)
        assert mgr._compute_delay(1) == pytest.approx(2.0)
        assert mgr._compute_delay(2) == pytest.approx(4.0)

    def test_max_delay_cap(self, classifier):
        mgr = RetryManager(
            classifier,
            log=None,
            max_retries=10,
            base_delay=1.0,
            max_delay=5.0,
            backoff_multiplier=10.0,
            jitter=0.0,
        )
        assert mgr._compute_delay(5) == pytest.approx(5.0)

    def test_jitter_applied(self, classifier):
        mgr = RetryManager(
            classifier,
            log=None,
            max_retries=3,
            base_delay=1.0,
            max_delay=100.0,
            backoff_multiplier=2.0,
            jitter=0.5,
        )
        delays = {mgr._compute_delay(0) for _ in range(20)}
        # With 50% jitter on a 1.0 base, values should vary
        assert len(delays) > 1

    # -- Decorator --

    def test_decorator_success(self, manager):
        @manager.retry_on_db_error()
        def good_func():
            return 42

        assert good_func() == 42

    def test_decorator_retries(self, classifier):
        mgr = RetryManager(
            classifier,
            log=None,
            max_retries=2,
            base_delay=0.01,
            max_delay=0.1,
            jitter=0.0,
        )
        call_count = 0

        @mgr.retry_on_db_error()
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("connection reset by peer")
            return "done"

        assert flaky_func() == "done"
        assert call_count == 2

    def test_custom_exception_types(self, manager):
        """Only specified exception types trigger retry."""
        call_count = 0

        def fails_with_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("connection reset by peer")

        with pytest.raises(ValueError):
            manager.execute_with_retry(
                fails_with_value_error,
                exception_types=ValueError,
            )
        # Should retry because it's retryable + matches exception_types
        assert call_count > 1
