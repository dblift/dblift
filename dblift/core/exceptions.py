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


class UnsupportedMetaCommandError(ParserError):
    """Raised for a client meta-command line with no safe no-op interpretation."""


class TransactionStatementError(UnsupportedMetaCommandError):
    """Raised when a script holds a transaction statement dblift cannot run or drop.

    dblift runs each script in a transaction of its own; a ``COMMIT``, ``ROLLBACK`` or
    ``BEGIN`` inside it would end or fail against that transaction. The message names
    the script, the statement and its line.
    """


class UnsafeStatementSplitError(ParserError):
    """Raised when a SQL script cannot be split without changing its meaning."""


# --- Execution exceptions ---


class ExecutionError(DbliftError):
    """Base exception for migration execution errors."""


class StatementVerdictError(ExecutionError):
    """A verdict the server deferred past its statement, attributed to a statement of the script."""

    def __init__(self, message: str, statement_index: int) -> None:
        """Keep the 0-based index of the statement the failure belongs to."""
        super().__init__(message)
        self.statement_index = statement_index


class FixedDboSchemaError(ExecutionError):
    """A SQL Server login mapped to ``dbo`` cannot honor the configured schema.

    Raised only when ``fail_on_fixed_dbo`` is set. ``set_current_schema``
    raises it before any migration or callback statement executes, so no
    history row is written.
    """


class TransactionAbortedError(ExecutionError):
    """Raised when a database transaction is in an aborted state."""


class CallbackExecutionError(ExecutionError):
    """Raised when a migration callback fails."""


class NoSqlWriteNotSupportedError(ExecutionError):
    """Raised when a write statement is sent to a document store's query API.

    NoSQL backends expose a read-only query language (Cosmos DB's SQL API,
    and the equivalents in other document stores). Schema and data changes
    go through the vendor SDK from a Python migration, so a write statement
    arriving at the query executor is surfaced rather than translated.
    """


class NoSqlQueryLanguageUnsupportedError(ExecutionError):
    """Raised when a string statement reaches a store with no query language.

    Sibling of :class:`NoSqlWriteNotSupportedError`, not a subclass. That
    one means a *write* was sent to a read-only query API — Cosmos DB
    executes ``SELECT`` and rejects the rest. This one means there is no
    string language to execute at all: MongoDB reads are ``find()`` calls,
    not statements, so a string arriving at the query executor is an error
    whatever it says.

    The remedy is always the same and belongs in the message: reach the
    driver through ``context.db`` (a ``pymongo.database.Database``) or
    ``context.raw_client``.
    """

    #: Stable diagnostic code quoted in the message and in the docs.
    code = "DBLIFT-NOSQL-002"


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


class InvalidTargetVersionError(ValidationError, ValueError):
    """Raised when ``target_version`` is not a version of any migration script."""

    def __init__(self, target_version: str, available: "list[str]") -> None:
        """Record the rejected value and the versions a caller could have used."""
        self.target_version = target_version
        self.available_versions = list(available)
        listed = ", ".join(available) if available else "(no versioned migration scripts found)"
        super().__init__(
            f"Invalid target version {target_version!r}: it is not the version of a migration "
            f"script. Available versions: {listed}"
        )
