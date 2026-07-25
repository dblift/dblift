"""Custom exception hierarchy for dblift core modules.

Replaces generic Exception/RuntimeError usage with specific, descriptive
exception types that improve debuggability and allow callers to catch
specific failure modes.
"""


class DbliftError(Exception):
    """Base exception for all dblift errors."""


# --- Parser exceptions ---


class ParserError(DbliftError):
    """Base exception for SQL parser errors."""


class UnsupportedDialectError(ParserError):
    """Raised when a requested SQL dialect is not supported."""


class ParserNotAvailableError(ParserError):
    """Raised when a parser cannot be loaded for a dialect."""


# --- Execution exceptions ---


class ExecutionError(DbliftError):
    """Base exception for migration execution errors."""


class TransactionAbortedError(ExecutionError):
    """Raised when a database transaction is in an aborted state."""


class CallbackExecutionError(ExecutionError):
    """Raised when a migration callback fails."""


# --- Validation exceptions ---


class ValidationError(DbliftError):
    """Base exception for validation errors."""


class ConnectionClosedError(ValidationError):
    """Raised when a database connection is unexpectedly closed."""


class UnsupportedMigrationFormatError(ValidationError):
    """Raised when a migration's format cannot run on the target dialect.

    The concrete case is a ``.sql`` migration aimed at a NoSQL dialect —
    one whose quirks declare ``supports_sql_migrations = False``. Document
    stores such as Cosmos DB have no SQL DDL, so their migrations are
    written as Python scripts driving the vendor SDK.
    """

    #: Stable diagnostic code quoted in the message and in the docs.
    code = "DBLIFT-NOSQL-001"


class SchemaCreationError(ValidationError):
    """Raised when a test schema cannot be created."""
