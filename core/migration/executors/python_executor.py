"""
Python migration executor.

Executes Python-based migration scripts (.py files) that follow the
convention: def migrate(context: MigrationContext).
"""

import importlib.util
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional

from core.migration.formats import MigrationFormat
from core.migration.migration import Migration

from .base_executor import BaseMigrationExecutor, MigrationExecutionResult

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
            "For CosmosDB DDL/data operations, use context.database or "
            "context.client SDK methods directly."
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

    To support undo, add an ``undo`` function with the same signature::

        def undo(context: MigrationContext) -> None:
            context.execute("DELETE FROM t WHERE id = 1")

    Public interface:

    * ``execute(sql, params=None)`` — run SQL via the active provider connection.
      Automatically routes SELECT to ``execute_query`` and DML/DDL to
      ``execute_statement``, so a single call works for both. For CosmosDB
      SDK operations, use ``context.database`` or ``context.client`` directly.
    * ``log`` — logger with ``.info()``, ``.debug()``, ``.warning()``, ``.error()``.
    * ``dry_run`` (bool) — True when called with ``--dry-run``; skip writes.
    * ``database`` — CosmosDB ``DatabaseProxy`` (``None`` for SQL dialects).
    * ``client``   — CosmosDB ``CosmosClient`` (``None`` for SQL dialects).

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
    def database(self) -> Optional[Any]:
        """Cosmos DB DatabaseProxy (None for non-SDK providers)."""
        cm = getattr(self.provider, "connection_manager", None)
        return getattr(cm, "database", None) if cm else None

    @property
    def client(self) -> Optional[Any]:
        """Cosmos DB client (None for non-SDK providers)."""
        cm = getattr(self.provider, "connection_manager", None)
        return getattr(cm, "client", None) if cm else None

    def __getitem__(self, key: Any) -> Any:
        """Reject dict-style access with an actionable error (B9-NOTE-01).

        Earlier CosmosDB Python migration samples passed a raw ``dict`` to
        ``migrate(client_config)`` with keys like ``account_endpoint`` and
        ``account_key``. The API now injects a typed ``MigrationContext``
        exposing ``context.database`` / ``context.client`` / ``context.provider``
        / ``context.log`` / ``context.dry_run``. Without this guard, old
        scripts crashed with the opaque ``TypeError: 'MigrationContext' object
        is not subscriptable`` and callers had no hint about the new API.
        """
        raise TypeError(
            f"MigrationContext is not a dict (tried context[{key!r}]). "
            "The dblift Python migration API injects a typed MigrationContext "
            "instead of the legacy dict. Replace 'client_config[\"account_endpoint\"]' "
            "with 'context.client' (azure.cosmos.CosmosClient) or "
            "'context.database' (DatabaseProxy). Available attributes: "
            "provider, log, dry_run, database, client. "
            "Run 'context.execute(sql)' for raw statements."
        )


class PythonMigrationExecutor(BaseMigrationExecutor):
    """
    Executor for Python-based migration scripts.

    Loads and executes .py migration files that define a `migrate(context)` function.
    """

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
            placeholders=dict(
                getattr(self, "config", None) and getattr(self.config, "placeholders", {}) or {}
            ),
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

    def supports_rollback(self, migration: Migration) -> bool:
        """Check if this migration has an undo function."""
        return bool(migration.content and "def undo(" in migration.content)

    def rollback_migration(
        self, migration: Migration, dry_run: bool = False, **kwargs: Any
    ) -> MigrationExecutionResult:
        """Rollback a Python migration by calling its undo(context) function."""
        if not self.supports_rollback(migration):
            return MigrationExecutionResult(
                success=False,
                migration=migration,
                execution_time_ms=0,
                error=f"Script {migration.script_name} does not define an 'undo' function",
            )

        start = time.time()

        if migration.path is None:
            elapsed_ms = int((time.time() - start) * 1000)
            return MigrationExecutionResult(
                success=False,
                migration=migration,
                execution_time_ms=elapsed_ms,
                error=f"Python script has no file path: {migration.script_name}.",
            )

        context = MigrationContext(
            provider=self.provider,
            log=self.log,
            dry_run=dry_run,
            config=getattr(self, "config", None),
            placeholders=dict(
                getattr(self, "config", None) and getattr(self.config, "placeholders", {}) or {}
            ),
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
            mod.undo(context)
            elapsed_ms = int((time.time() - start) * 1000)
            return MigrationExecutionResult(
                success=True,
                migration=migration,
                execution_time_ms=elapsed_ms,
                statements_executed=1,
            )
        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            error_msg = f"{type(e).__name__}: {e}"
            self.log.error(f"Python rollback failed {migration.script_name}: {error_msg}")
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
