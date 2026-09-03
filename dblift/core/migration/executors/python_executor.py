"""
Python migration executor.

Executes Python-based migration scripts (.py files) that follow the
convention: def migrate(context: MigrationContext).
"""

import importlib.util
import inspect
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.migration import Migration

from .base_executor import BaseMigrationExecutor, MigrationExecutionResult

if TYPE_CHECKING:
    from dblift.core.migration.placeholders.placeholder_service import PlaceholderService

# B10-BUG-09: prefixes that return a result set on every supported
# dialect. Keep this list narrow — ``CALL`` / ``EXEC`` / ``EXECUTE`` may
# or may not return rows depending on the routine, and there is no safe
# static way to tell, so they stay on the DML path where drivers that
# do return a result set silently ignore it.
_QUERY_PREFIXES = ("SELECT", "WITH", "VALUES", "SHOW", "EXPLAIN", "TABLE")


def _is_query_statement(sql: Any) -> bool:
    """Return True if ``sql`` starts with a result-set-returning keyword.

    Strips leading whitespace, opening parentheses (for ``(SELECT ...)``
    style queries) and SQL block comments so that a query prefixed with
    ``-- header`` or ``/* ... */`` still classifies correctly.
    """
    if not isinstance(sql, str):
        raise TypeError(
            f"context.execute() expects a SQL string, got {type(sql).__name__}. "
            "For document-store DDL/data operations, use the context.db or "
            "context.raw_client SDK methods directly."
        )
    if not sql:
        return False
    stripped = sql.lstrip()
    # Skip SQL line comments and block comments that may precede the
    # first keyword. This mirrors what database drivers do internally when
    # classifying the statement type.
    while stripped.startswith("--") or stripped.startswith("/*"):
        if stripped.startswith("--"):
            newline = stripped.find("\n")
            if newline == -1:
                return False
            stripped = stripped[newline + 1 :].lstrip()
        else:  # /* ... */
            end = stripped.find("*/")
            if end == -1:
                return False
            stripped = stripped[end + 2 :].lstrip()
    # Allow a leading ``(`` for parenthesised queries.
    stripped = stripped.lstrip("(").lstrip()
    head = stripped[:8].upper()
    return any(head.startswith(p) for p in _QUERY_PREFIXES)


@dataclass
class MigrationContext:
    """Context injected into each Python migration script.

    Every Python migration must define a top-level ``migrate`` function that
    accepts exactly one argument — this context object::

        def migrate(context: MigrationContext) -> None:
            context.execute("INSERT INTO t VALUES (1)")
            context.log.info("Row inserted")

    A ``U<version>__*.py`` undo script also defines a top-level ``migrate``
    function — the same entry point as any other migration — describing the
    action to perform when undoing::

        def migrate(context: MigrationContext) -> None:
            context.execute("DELETE FROM t WHERE id = 1")

    Public interface:

    * ``execute(sql, params=None)`` — run SQL via the active provider connection.
      Automatically routes SELECT to ``execute_query`` and DML/DDL to
      ``execute_statement``, so a single call works for both. On a document
      store only SELECT is executable; everything else is an SDK call
      through ``context.db``.
    * ``log`` — logger with ``.info()``, ``.debug()``, ``.warning()``, ``.error()``.
    * ``dry_run`` (bool) — True when called with ``--dry-run``; skip writes.
    * ``db`` — native database handle of an SDK-backed provider, e.g. Cosmos
      DB's ``DatabaseProxy`` (``None`` for SQL dialects).
    * ``raw_client`` — the underlying SDK client, e.g. Cosmos DB's
      ``CosmosClient`` (``None`` for SQL dialects).
    * ``placeholders`` — the effective placeholder mapping, identical to the
      one substituted into SQL migrations: the ``dblift_*`` system
      placeholders, then the configured placeholders, then the per-call
      ones passed to ``migrate()`` / ``undo()``, each overriding the former.

    Attributes:
        provider: Database provider instance (BaseProvider)
        log: Logger instance (core.logger.Log)
        dry_run: If True, the script should simulate execution without writes
    """

    provider: Any
    log: Any
    dry_run: bool = False
    config: Optional[Any] = None
    placeholders: Mapping[str, str] = field(default_factory=dict)

    @property
    def schema(self) -> Optional[str]:
        """Target schema from config (or None)."""
        if self.config is None:
            return None
        return getattr(self.config.database, "schema", None)

    @property
    def connection(self) -> Optional[Any]:
        """Active provider connection (if exposed)."""
        return getattr(self.provider, "connection", None)

    @property
    def engine(self) -> Optional[Any]:
        """SQLAlchemy Engine (if provider is SQLAlchemy-backed and exposed)."""
        eng = getattr(self.provider, "engine", None)
        return eng if eng is not None else None

    def execute(self, sql: str, params: Optional[Any] = None) -> Any:
        """Execute a SQL statement via the underlying provider.

        Convenience shortcut so migration scripts can write
        ``context.execute("ALTER TABLE ...")`` instead of
        ``context.provider.execute_statement(...)``.

        ``params`` uses dblift's ``?`` (qmark) placeholder convention,
        positionally matched against a list — the same syntax used in SQL
        migration files — regardless of the target dialect's native
        paramstyle::

            context.execute(
                "INSERT INTO t (a, b) VALUES (?, ?)", [1, 2]
            )

        Each ``?`` is translated internally to the connection's DBAPI
        paramstyle (e.g. ``%s`` for pymysql, ``:1`` for cx_Oracle), so
        dialect-specific placeholder syntax such as ``%s`` should not be
        written directly in ``sql``.

        B10-BUG-09: ``provider.execute_statement`` routes through the provider
        ``Statement.executeUpdate()``, which PostgreSQL and DB2 drivers
        reject for result-set-returning SQL ("A result was returned when
        none was expected"). Migration scripts often read data before
        writing (e.g. ``SELECT COUNT(*) ...`` to decide whether to seed),
        and forcing them to know the provider API was a footgun. Detect
        result-set-returning statements and dispatch to ``execute_query``
        so both styles work on every dialect.
        """
        if _is_query_statement(sql):
            if params is None:
                return self.provider.execute_query(sql)
            return self.provider.execute_query(sql, params=params)
        if params is None:
            return self.provider.execute_statement(sql)
        return self.provider.execute_statement(sql, params=params)

    def cursor(self) -> "MigrationContext":
        """DBAPI-compat shim so scripts written as ``conn.cursor().execute(sql)`` work.

        Classic Python migration guides (Flyway-style, SQLAlchemy, plain DBAPI)
        call ``connection.cursor()`` before ``execute``. The MigrationContext
        already owns the executing provider, so returning ``self`` lets the
        DBAPI idiom resolve without a second object.
        """
        return self

    def commit(self) -> None:
        """DBAPI-compat no-op: dblift's ExecutionEngine owns the transaction."""
        return None

    def rollback(self) -> None:
        """DBAPI-compat no-op: dblift's ExecutionEngine owns the transaction."""
        return None

    def close(self) -> None:
        """DBAPI-compat no-op so ``cursor().close()`` in migration scripts works.

        Batch-6 BUG-01: the ``cursor()`` shim returns ``self`` so callers can
        use the classic DBAPI pattern ``cur = conn.cursor(); cur.execute(...);
        cur.close()``. Before this shim the final ``close()`` raised
        ``AttributeError`` because MigrationContext only implemented
        ``cursor``/``commit``/``rollback``. MigrationContext is stateless from
        the script's perspective — the ExecutionEngine owns the underlying
        connection — so ``close()`` is a no-op.
        """
        return None

    @property
    def db(self) -> Optional[Any]:
        """Native database handle of an SDK-backed provider, else ``None``.

        Provider-neutral by design: Cosmos DB yields an
        ``azure.cosmos.DatabaseProxy``, and a future document store yields
        whatever its driver calls a database. Relational providers have no
        SDK handle and return ``None`` — they use :meth:`execute`.
        """
        cm = getattr(self.provider, "connection_manager", None)
        return getattr(cm, "database", None) if cm else None

    @property
    def raw_client(self) -> Optional[Any]:
        """Underlying SDK client of an SDK-backed provider, else ``None``.

        Cosmos DB yields an ``azure.cosmos.CosmosClient``. Reach for this
        only when the operation lives above the database handle (account
        level), otherwise prefer :attr:`db`.
        """
        cm = getattr(self.provider, "connection_manager", None)
        return getattr(cm, "client", None) if cm else None

    def __getitem__(self, key: Any) -> Any:
        """Reject dict-style access with an actionable error (B9-NOTE-01).

        Earlier CosmosDB Python migration samples passed a raw ``dict`` to
        ``migrate(client_config)`` with keys like ``account_endpoint`` and
        ``account_key``. The API now injects a typed ``MigrationContext``
        exposing ``context.db`` / ``context.raw_client`` / ``context.provider``
        / ``context.log`` / ``context.dry_run``. Without this guard, old
        scripts crashed with the opaque ``TypeError: 'MigrationContext' object
        is not subscriptable`` and callers had no hint about the new API.
        """
        raise TypeError(
            f"MigrationContext is not a dict (tried context[{key!r}]). "
            "The dblift Python migration API injects a typed MigrationContext "
            "instead of the legacy dict. Replace 'client_config[\"account_endpoint\"]' "
            "with 'context.raw_client' (azure.cosmos.CosmosClient) or "
            "'context.db' (DatabaseProxy). Available attributes: "
            "provider, log, dry_run, db, raw_client. "
            "Run 'context.execute(sql)' for raw SELECT statements."
        )


class PythonMigrationExecutor(BaseMigrationExecutor):
    """
    Executor for Python-based migration scripts.

    Loads and executes .py migration files that define a `migrate(context)` function.

    Attributes:
        placeholder_service: Optional placeholder service shared with the SQL
            path. When injected, ``context.placeholders`` is resolved from it at
            execution time so per-call placeholders are visible; without it the
            executor falls back to the placeholders baked into the config.
    """

    def __init__(
        self,
        provider: Any,
        config: Any,
        log: Any,
        placeholder_service: Optional["PlaceholderService"] = None,
    ):
        """Initialize the Python executor.

        Args:
            provider: Database provider instance
            config: DBLIFT configuration
            log: Logger instance
            placeholder_service: Optional placeholder service holding the
                effective placeholder set (system + config + per-call)
        """
        super().__init__(provider, config, log)
        self.placeholder_service = placeholder_service

    def _resolve_placeholders(self) -> Dict[str, Any]:
        """Return the placeholder mapping to expose on the migration context.

        Read at execution time rather than at construction: per-call
        placeholders from ``migrate(placeholders=...)`` / ``undo(placeholders=...)``
        are added to the shared service after the executor tree is built, so a
        value cached in ``__init__`` would miss them. ``config.placeholders`` is
        only a fallback for executors constructed without the service.
        """
        if self.placeholder_service is not None:
            return dict(self.placeholder_service.placeholders)
        return dict(getattr(getattr(self, "config", None), "placeholders", None) or {})

    def can_execute(self, migration: Migration) -> bool:
        """Check if this executor can handle the given migration."""
        return migration.format == MigrationFormat.PYTHON

    def validate_migration(self, migration: Migration) -> tuple[bool, list[str]]:
        """Validate a Python migration before execution."""
        errors = []
        # V1: non-empty content
        if not migration.content or not migration.content.strip():
            errors.append(f"Python script is empty or not loaded: {migration.script_name}")
            return False, errors
        # V2: presence of def migrate(
        if "def migrate(" not in migration.content:
            errors.append(f"Missing 'migrate' function in script {migration.script_name}")
        # V3: valid Python syntax
        try:
            compile(migration.content, migration.script_name, "exec")
        except SyntaxError as e:
            errors.append(f"Python syntax error in {migration.script_name}: {e}")
        return len(errors) == 0, errors

    def execute_migration(
        self, migration: Migration, dry_run: bool = False, **kwargs: Any
    ) -> MigrationExecutionResult:
        """Execute a Python migration script."""
        start = time.time()

        # Defensive validation: script_path is required for importlib
        if migration.path is None:
            elapsed_ms = int((time.time() - start) * 1000)
            return MigrationExecutionResult(
                success=False,
                migration=migration,
                execution_time_ms=elapsed_ms,
                error=(
                    f"Python script has no file path: {migration.script_name}. "
                    f"Use Migration(script_path=Path('...')) for Python scripts."
                ),
            )

        context = MigrationContext(
            provider=self.provider,
            log=self.log,
            dry_run=dry_run,
            config=getattr(self, "config", None),
            placeholders=self._resolve_placeholders(),
        )
        try:
            spec = importlib.util.spec_from_file_location(
                migration.script_name, str(migration.path)
            )
            if spec is None or spec.loader is None:
                raise RuntimeError(
                    f"Cannot load module spec for migration script: {migration.path}"
                )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            migrate_fn = getattr(mod, "migrate", None)
            if not callable(migrate_fn):
                raise RuntimeError(
                    f"Python migration {migration.script_name}: no callable `migrate` function found."
                )
            try:
                sig = inspect.signature(migrate_fn)
                sig.bind(context)
            except TypeError as e:
                raise RuntimeError(
                    f"Python migration {migration.script_name}: incorrect signature. "
                    f"Expected `def migrate(context)` — got: {e}. "
                    "The migration function must accept exactly one "
                    "argument (MigrationContext)."
                ) from e
            migrate_fn(context)
            elapsed_ms = int((time.time() - start) * 1000)
            return MigrationExecutionResult(
                success=True,
                migration=migration,
                execution_time_ms=elapsed_ms,
                statements_executed=1,
                output="[DRY-RUN] Script executed in simulation mode" if dry_run else None,
            )
        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            error_msg = f"{type(e).__name__}: {e}"
            self.log.error(f"Python migration failed {migration.script_name}: {error_msg}")
            return MigrationExecutionResult(
                success=False,
                migration=migration,
                execution_time_ms=elapsed_ms,
                statements_executed=0,
                error=error_msg,
            )

    def get_supported_formats(self) -> List[MigrationFormat]:
        """Get list of supported formats."""
        return [MigrationFormat.PYTHON]
