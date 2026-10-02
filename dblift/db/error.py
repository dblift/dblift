"""
Database error classification.

Provides pattern-based error classification. Dialect-specific error patterns
are supplied by each dialect's quirks (``error_patterns()``); this module owns
only the generic, dialect-agnostic fallback patterns.
"""

import re
from enum import Enum
from typing import Any, List, Optional, Tuple, Union

from dblift.core.logger import NullLog


class ErrorCategory(str, Enum):
    """Classification categories for database errors."""

    NETWORK = "network"
    TIMEOUT = "timeout"
    LOCKING = "locking"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SCHEMA = "schema"
    CONSTRAINT = "constraint"
    SQL_SYNTAX = "sql_syntax"
    RESOURCE = "resource"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Generic (dialect-agnostic) error patterns
# ---------------------------------------------------------------------------
# Dialect-specific patterns now live in each plugin's quirks
# (``db/plugins/<X>/quirks.py`` ``error_patterns()``) and are sourced at
# classifier construction via ``ProviderRegistry.get_quirks`` (ADR-26 A2).

# Some DBAPI drivers render an error as its (errno, message) args tuple, e.g.
# PyMySQL '(1054, "Unknown column \'x\' in \'where clause\'")' or pymssql
# "(20009, b'DB-Lib error message 20009, severity 9: Unable to connect: ...')".
# clean_driver_error_message() unwraps it to the message text.
_DBAPI_ERROR_TUPLE_RE = re.compile(r"\A\(\d+,\s*b?(['\"])(.*?)\1\)", re.DOTALL)

# SQLAlchemy appends the failing statement to statement-bound errors, e.g.
# '...\n[SQL: CREATE TABLE dblift_schema_history (...)]\n[parameters: ...]'.
# strip_sql_statement_block() removes this trailing block so a schema/table
# setup failure never leaks internal DDL to the user.
_SQL_STATEMENT_BLOCK_RE = re.compile(r"\s*\[SQL:.*", re.IGNORECASE | re.DOTALL)

_DRIVER_EXCEPTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+Exception:\s*"  # Java/JDBC: dotted.path.Exception:
    r"|"
    r"\([a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)+\)\s*"  # SQLAlchemy: (dotted.path.ExceptionClass)
    r")+"
    r"(?:ERROR:\s*)?",
    re.IGNORECASE,
)
# SQLAlchemy appends a doc-link pointer for every wrapped DBAPI error, e.g.
# '(Background on this error at: https://sqlalche.me/e/20/e3q8)'.
_SQLALCHEMY_DOC_LINK_RE = re.compile(
    r"\s*\(Background on this error at:.*\)\s*\Z", re.IGNORECASE | re.DOTALL
)


def clean_driver_error_message(message: str) -> str:
    """Strip driver and SQLAlchemy wrapping from a database error message.

    Shared by every place that shows a database error to the user, so a
    failure reads the same in the command error, the logs and the run report.
    The ``[SQL: ...]`` block of a failing statement is kept: in a migration
    error it tells the user which statement broke. Use
    :func:`strip_sql_statement_block` where the statement is dblift's own.

    e.g. 'org.postgresql.util.PSQLException: ERROR: column "x" already exists'
         → 'column "x" already exists'
    e.g. '(_duckdb.IOException) IO Error: Cannot open file "x": No such file or directory
         (Background on this error at: https://sqlalche.me/e/20/e3q8)'
         → 'IO Error: Cannot open file "x": No such file or directory'
    e.g. '(pymysql.err.OperationalError) (1054, "Unknown column 'x' in 'where clause'")'
         → "Unknown column 'x' in 'where clause'"
    """
    text = _DRIVER_EXCEPTION_PREFIX_RE.sub("", str(message).strip()).strip()
    text = _SQLALCHEMY_DOC_LINK_RE.sub("", text).strip()
    errno_tuple = _DBAPI_ERROR_TUPLE_RE.match(text)
    if errno_tuple:
        text = (errno_tuple.group(2) + text[errno_tuple.end() :]).strip()
    return text


def strip_sql_statement_block(message: str) -> str:
    """Remove the ``[SQL: ...]`` block SQLAlchemy appends to statement-bound errors.

    For connection and schema-history setup errors, where the statement is
    dblift's own DDL rather than the user's migration.
    """
    return _SQL_STATEMENT_BLOCK_RE.sub("", message).strip()


# Generic fallback patterns (checked for all database types)
_GENERIC_PATTERNS: List[Tuple[re.Pattern[str], ErrorCategory]] = [
    (
        re.compile(r"connection\s+(reset|refused|closed|lost|timed\s*out)", re.IGNORECASE),
        ErrorCategory.NETWORK,
    ),
    (re.compile(r"broken\s+pipe", re.IGNORECASE), ErrorCategory.NETWORK),
    (
        re.compile(r"socket\s+(error|closed|timeout|exception)", re.IGNORECASE),
        ErrorCategory.NETWORK,
    ),
    (re.compile(r"network\s+(error|unreachable)", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"insufficient\s+data", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"timeout|timed\s*out", re.IGNORECASE), ErrorCategory.TIMEOUT),
    (re.compile(r"deadlock", re.IGNORECASE), ErrorCategory.LOCKING),
    (re.compile(r"authentication\s+fail", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    (re.compile(r"permission\s+denied", re.IGNORECASE), ErrorCategory.AUTHORIZATION),
]


class DatabaseErrorClassifier:
    """Pattern-based database error classifier."""

    def __init__(self, db_type: str = "generic", log: Optional[Any] = None):
        """Initialize the classifier for *db_type*.

        ``db_type`` selects the dialect-specific pattern table from that
        dialect's quirks (``error_patterns()``); generic patterns are always
        appended afterwards. Unknown / missing ``db_type`` resolves to the
        ``BaseQuirks`` default (no dialect patterns), i.e. the generic-only
        ordering.
        """
        self.db_type = db_type.lower() if db_type else "generic"
        self.log = log if log is not None else NullLog()
        # Source dialect-specific patterns from the dialect's quirks (lazy
        # import avoids any import cycle through the plugin registry).
        from dblift.db.provider_registry import ProviderRegistry

        dialect_patterns = ProviderRegistry.get_quirks(self.db_type).error_patterns()
        # Build ordered pattern list: db-specific first, then generic
        self._patterns: List[Tuple[re.Pattern[str], ErrorCategory]] = list(dialect_patterns) + list(
            _GENERIC_PATTERNS
        )

    def categorize_error(self, error: Exception, sql: Optional[str] = None) -> ErrorCategory:
        """Classify a database exception into an ErrorCategory."""
        error_str = str(error)
        error_type = type(error).__name__

        # Also check the type name (e.g. "DisconnectException")
        text_to_search = f"{error_str} {error_type}"

        for pattern, category in self._patterns:
            if pattern.search(text_to_search):
                return category

        return ErrorCategory.UNKNOWN


def format_connection_error(error: Exception, db_type: str = "") -> str:
    """Map common database connection errors to a one-line user-facing message.

    Shared by ``db check-connection`` and every other command's own
    connection-establishment step (see ``BaseCommand._ensure_connected``), so a
    connection failure is reported identically no matter which command
    triggered it.

    Before falling back to substring matching, consult SQLState when available:
    the 5-character code is set by many drivers and is identical across locales.
    Auth-error detection also consults ``DatabaseErrorClassifier`` (dialect
    quirks ``error_patterns()`` + the generic patterns above), so vendor codes
    such as Oracle's ORA-01017 are recognized without hardcoding vendor-specific
    substrings here. The substring fallback remains for wrappers and drivers
    that do not populate SQLState or match a quirks pattern.

    SQLState references:
        08001 ``sqlclient_unable_to_establish_sqlconnection``
        08006 ``connection_failure``
        08S01 ``communication_link_failure`` (MS / TDS)
        28000 / 28P01 ``invalid_authorization_specification``
        3D000 ``invalid_catalog_name``
        08004 ``sqlserver_rejected_establishment_of_sqlconnection``
    """
    message = strip_sql_statement_block(clean_driver_error_message(str(error)))
    lowered = message.lower()
    # SQL Server can report login failures with SQLState 08001, so inspect
    # explicit auth markers before classifying broad connection SQLStates.
    if _is_auth_error(error, lowered, db_type):
        return "Connection failed: invalid credentials"

    sqlstate = extract_sqlstate(error)
    if sqlstate in ("08001", "08006", "08S01"):
        return "Connection failed: host unreachable or connection timed out"
    if sqlstate in ("28000", "28P01"):
        return "Connection failed: invalid credentials"
    if sqlstate in ("3D000", "08004"):
        return "Connection failed: database not found or connection rejected"

    if "refused" in lowered or "timed out" in lowered or "timeout" in lowered:
        return "Connection failed: host unreachable"
    if "unknown host" in lowered or "name or service not known" in lowered:
        return "Connection failed: host not found"

    return f"Connection failed: {message}"


def _is_auth_error(error: Exception, lowered_message: str, db_type: str) -> bool:
    """Return True when *error* clearly describes an authentication failure.

    Checks cheap substring markers first, then falls back to the dialect's
    quirks-based ``DatabaseErrorClassifier`` so vendor error codes (e.g.
    Oracle's ORA-01017) are recognized generically across every dialect that
    declares ``error_patterns()``, not just the ones with a hardcoded marker
    below. An AUTHORIZATION error (the role connected but lacks a privilege)
    is not an auth failure: it keeps the engine's own text so the operator
    sees which privilege is missing, instead of being told the credentials
    are wrong.
    """
    auth_markers = (
        "authentication",
        "login failed",
        "password",
        "error 18456",
        "18456",
    )
    if any(marker in lowered_message for marker in auth_markers):
        return True
    if isinstance(error, OSError):
        # A raw PermissionError/OSError (e.g. SQLite failing to open or
        # create its database file on an unwritable path) is a filesystem
        # error, not a database credential failure. The generic
        # "permission denied" pattern below is meant for DB-level
        # authorization errors, so skip it here rather than misreport an
        # OS error as "invalid credentials".
        return False
    try:
        category = DatabaseErrorClassifier(db_type).categorize_error(error)
    except Exception:
        return False
    return category == ErrorCategory.AUTHENTICATION


def extract_sqlstate(error: BaseException) -> Optional[str]:
    """Return the 5-character SQLState of *error*, or None.

    Some driver exceptions expose ``getSQLState()``. ``sqlstate`` is also
    sometimes attached as a plain attribute — check both.
    """
    get_ss = getattr(error, "getSQLState", None)
    if callable(get_ss):
        try:
            value = get_ss()
        except Exception:
            value = None
        if value:
            return str(value).strip() or None
    attr = getattr(error, "sqlstate", None) or getattr(error, "SQLState", None)
    if attr:
        return str(attr).strip() or None
    return None


def extract_error_code(error: BaseException) -> Optional[Union[int, str]]:
    """Return the vendor error code of *error*, or None.

    Read from ``getErrorCode()`` when the driver exposes it, else from an
    ``errorcode`` / ``errorCode`` attribute.
    """
    code: Optional[Union[int, str]] = None
    get_code = getattr(error, "getErrorCode", None)
    if callable(get_code):
        try:
            code = get_code()
        except Exception:
            code = None
    if code is None:
        code = getattr(error, "errorcode", None)
    if code is None:
        code = getattr(error, "errorCode", None)
    return code
