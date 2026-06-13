"""Introspection / verification / schema-lifecycle phases of ``RoundTripTester``.

Hosts:
  * Source + test introspection (``_introspect_source`` / ``_introspect_test``).
  * Test-schema lifecycle (ensure, clean, commit) wrapped by ``_execute_on_test``.
  * The captured-vs-live comparison loop (``_compare_and_verify``).

The drop+create DDL loop itself lives in ``_drop_phase.py`` and is
invoked from ``_execute_on_test`` via ``self._execute_ddl_statements``.

Logger name is hardcoded to ``core.validation.round_trip_tester`` so unit
tests using ``assertLogs("core.validation.round_trip_tester", ...)`` still
observe records emitted from this module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.exceptions import SchemaCreationError
from core.sql_model.index import Index

if TYPE_CHECKING:
    from core.introspection.schema_introspector import SchemaIntrospector
    from core.validation._round_trip_comparator import RoundTripComparator
    from db.base_provider import BaseProvider
    from db.base_quirks import BaseQuirks

# Preserve the historical logger name so `assertLogs("core.validation.round_trip_tester", ...)`
# in the unit tests keeps capturing records emitted from this mixin.
logger = logging.getLogger("core.validation.round_trip_tester")


class _IntrospectionVerifierMixin:
    """Introspection + schema-lifecycle + verification helpers for ``RoundTripTester``.

    Requires the composing class to expose: ``dialect``, ``source_provider``,
    ``test_provider``, ``source_schema``, ``test_schema``, ``test_object_types``,
    ``introspector``, ``results``, ``_quirks``, ``_rt_comparator``, and the
    ``_execute_ddl_statements`` method (provided by ``_DropPhaseMixin``).
    ``_execute_ddl_statements`` is intentionally not declared on this mixin
    so MRO resolves it to ``_DropPhaseMixin``'s real implementation.
    """

    # Attributes supplied by the composing class (declared for mypy clarity).
    dialect: str
    source_provider: "BaseProvider"
    test_provider: "BaseProvider"
    source_schema: str
    test_schema: str
    test_object_types: List[str]
    introspector: Optional["SchemaIntrospector"]
    results: Dict[str, Any]
    _quirks: "BaseQuirks"
    _rt_comparator: "RoundTripComparator"

    def _execute_on_test(self, statements: List[str]) -> None:
        """Execute CREATE statements on test database."""
        try:
            self._ensure_test_schema()
            self._clean_test_schema()
            # ``_execute_ddl_statements`` is supplied by ``_DropPhaseMixin`` on
            # the composing class; declared abstract on this mixin would shadow
            # that implementation via MRO.
            self._execute_ddl_statements(statements)  # type: ignore[attr-defined]
            self._commit_test_execution()
        except Exception as e:
            self.results["errors"].append(
                f"Failed to execute statements on test database: {str(e)}"
            )
            raise

    def _ensure_test_schema(self) -> None:
        """Ensure the test schema exists, handling Oracle autocommit and DB2/Oracle post-creation commit."""
        # Type ignore: test_provider is BaseProvider but we know it has schema_operations
        logger.debug(f"Ensuring test schema exists: {self.test_schema}")
        # Some dialects (Oracle) require autocommit=False for DDL like CREATE USER.
        if self._quirks.ddl_requires_autocommit_off and hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
            try:
                auto_commit = self.test_provider.connection.getAutoCommit()  # type: ignore[attr-defined]
                if auto_commit:
                    logger.warning(
                        f"[{self.dialect.upper()}] autocommit is True before schema creation. "
                        "Setting to False (DDL requires autocommit=False on this dialect)."
                    )
                    if hasattr(self.test_provider.connection, "setAutoCommit"):  # type: ignore[attr-defined]
                        self.test_provider.connection.setAutoCommit(False)  # type: ignore[attr-defined]
                        logger.debug(
                            f"[{self.dialect.upper()}] Set autocommit to False before schema creation"
                        )
            except Exception as auto_commit_check_err:
                logger.debug(
                    f"[{self.dialect.upper()}] Could not check/set autocommit before schema creation: {auto_commit_check_err}"
                )

        try:
            self.test_provider.schema_operations.create_schema_if_not_exists(  # type: ignore[attr-defined]
                self.test_provider.connection, self.test_schema  # type: ignore[attr-defined]
            )
            # For DB2 and Oracle, commit schema creation (Oracle requires commit after CREATE USER)
            # BUT: Oracle doesn't allow commit when autocommit is enabled (ORA-17273)
            # So we only commit if autocommit is False
            if self._quirks.requires_explicit_commit_after_ddl and hasattr(self.test_provider.connection, "commit"):  # type: ignore[attr-defined]
                # Check if connection is still valid before committing
                connection_valid = True
                if hasattr(self.test_provider.connection, "isClosed"):  # type: ignore[attr-defined]
                    try:
                        connection_valid = not self.test_provider.connection.isClosed()  # type: ignore[attr-defined]
                    except Exception as e:
                        logger.debug(f"Could not check connection validity, assuming valid: {e}")
                        connection_valid = True

                if connection_valid:
                    # Skip commit when the dialect raises on commit-with-autocommit (Oracle ORA-17273).
                    should_commit = True
                    if self._quirks.commit_with_autocommit_raises and hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                        try:
                            auto_commit = self.test_provider.connection.getAutoCommit()  # type: ignore[attr-defined]
                            if auto_commit:
                                logger.debug(
                                    f"[{self.dialect.upper()}] autocommit is True, skipping commit "
                                    "(dialect raises on commit-with-autocommit). "
                                    "Schema creation should already be committed."
                                )
                                should_commit = False
                        except Exception as e:
                            # If we can't check autocommit, try to commit anyway
                            logger.debug(
                                f"[{self.dialect.upper()}] Could not check autoCommit before schema commit (non-critical): {e}"
                            )

                    if should_commit:
                        try:
                            self.test_provider.connection.commit()  # type: ignore[attr-defined]
                            logger.debug(f"Committed schema creation for {self.dialect}")
                        except Exception as commit_err:
                            # If commit fails due to closed connection or autocommit, log and continue
                            # The schema might have been created successfully before connection closed
                            error_msg = str(commit_err).lower()
                            if "closed" in error_msg or "17008" in str(commit_err):
                                logger.warning(
                                    f"Connection closed before commit for {self.dialect}. "
                                    f"Schema creation may have succeeded. Error: {commit_err}"
                                )
                            elif "17273" in str(commit_err) or "autocommit" in error_msg:
                                logger.warning(
                                    f"[{self.dialect.upper()}] Cannot commit while autocommit is "
                                    "enabled (e.g. Oracle ORA-17273). "
                                    f"Schema creation should already be committed. Error: {commit_err}"
                                )
                            else:
                                # Re-raise other commit errors
                                raise
                else:
                    logger.warning(
                        f"Connection is closed after schema creation for {self.dialect}. "
                        "Schema creation may have succeeded before connection closed."
                    )
        except Exception as schema_err:
            logger.warning(f"Could not ensure schema exists: {schema_err}")
            # Dialects with strict schema creation (Oracle CREATE USER cannot
            # be silently retried) re-raise; others continue because CREATE
            # SCHEMA IF NOT EXISTS handles the "already exists" case.
            if self._quirks.strict_schema_creation_errors:
                raise SchemaCreationError(
                    f"Failed to create {self.dialect} schema '{self.test_schema}': {schema_err}"
                ) from schema_err
            # Continue anyway - schema might already exist

    def _clean_test_schema(self) -> None:
        """Clean up all existing objects in test schema before creating new ones."""
        # Use the built-in clean_schema method which handles all database-specific logic,
        # transaction management, and error handling
        try:
            # CRITICAL: Commit any pending transaction from previous steps (like introspection)
            # This ensures clean_schema operates on a fresh transaction state
            # Without this, the same connection used for introspection might hang during cleanup
            # BUT: Oracle doesn't allow commit when autocommit is enabled (ORA-17273)
            try:
                if hasattr(self.test_provider.connection, "commit"):  # type: ignore[attr-defined]
                    # Skip commit when the dialect raises on commit-with-autocommit (Oracle ORA-17273).
                    should_commit = True
                    if self._quirks.commit_with_autocommit_raises and hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                        try:
                            auto_commit = self.test_provider.connection.getAutoCommit()  # type: ignore[attr-defined]
                            if auto_commit:
                                logger.debug(
                                    f"[{self.dialect.upper()}] autocommit is True, skipping commit "
                                    "before cleanup (dialect raises on commit-with-autocommit)."
                                )
                                should_commit = False
                        except Exception as e:
                            # If we can't check autocommit, try to commit anyway
                            logger.debug(
                                f"[{self.dialect.upper()}] Could not check autoCommit before cleanup commit (non-critical): {e}"
                            )

                    if should_commit:
                        self.test_provider.connection.commit()  # type: ignore[attr-defined]
                        logger.debug(
                            f"[{self.dialect.upper()}] Committed pending transaction before cleanup"
                        )
            except Exception as commit_err:
                error_msg = str(commit_err).lower()
                if "17273" in str(commit_err) or (
                    "autocommit" in error_msg and self._quirks.commit_with_autocommit_raises
                ):
                    logger.debug(
                        f"[{self.dialect.upper()}] Cannot commit while autocommit is enabled "
                        "(e.g. Oracle ORA-17273). Skipping commit before cleanup."
                    )
                else:
                    logger.debug(
                        f"[{self.dialect.upper()}] Commit before cleanup failed (trying rollback): {commit_err}"
                    )
                    try:
                        if hasattr(self.test_provider.connection, "rollback"):  # type: ignore[attr-defined]
                            self.test_provider.connection.rollback()  # type: ignore[attr-defined]
                    except Exception as e:
                        logger.debug(
                            f"[{self.dialect.upper()}] Rollback before cleanup failed (non-critical): {e}"
                        )

            logger.info(
                f"[{self.dialect.upper()}] Starting cleanup of test schema '{self.test_schema}' before creating objects"
            )
            if hasattr(self.test_provider, "clean_schema"):
                logger.debug(
                    f"[{self.dialect.upper()}] Calling clean_schema for schema: {self.test_schema}"
                )
                clean_response = self.test_provider.clean_schema(self.test_schema)  # type: ignore[attr-defined]
                logger.info(
                    f"[{self.dialect.upper()}] Schema cleanup completed: {len(clean_response.statements) if hasattr(clean_response, 'statements') else 'N/A'} statements executed"
                )
                # CRITICAL: dialects that auto-commit DDL during clean_schema
                # (MySQL/DB2) have already committed, so don't rollback. Just
                # ensure autoCommit is set correctly for the next operations.
                if self._quirks.clean_schema_auto_commits:
                    try:
                        if hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                            auto_commit = self.test_provider.connection.getAutoCommit()  # type: ignore[attr-defined]
                            logger.debug(
                                f"[{self.dialect.upper()}] cleanup committed, autoCommit={auto_commit}"
                            )
                    except Exception as e:
                        logger.debug(
                            f"[{self.dialect.upper()}] post-cleanup autoCommit check failed (non-critical): {e}"
                        )
            else:
                logger.warning("Provider does not support clean_schema, skipping cleanup")
        except Exception as cleanup_err:
            # Log but don't fail - cleanup is best effort
            logger.warning(
                f"[{self.dialect.upper()}] Cleanup warning (non-fatal): {cleanup_err}",
                exc_info=True,
            )
            try:
                if hasattr(self.test_provider.connection, "rollback"):  # type: ignore[attr-defined]
                    self.test_provider.connection.rollback()  # type: ignore[attr-defined]
                    logger.debug(
                        f"[{self.dialect.upper()}] Rolled back transaction after cleanup error"
                    )
            except Exception as rollback_err:
                logger.debug(
                    f"[{self.dialect.upper()}] Rollback after cleanup error failed: {rollback_err}"
                )

    def _commit_test_execution(self) -> None:
        """Commit the transaction after executing CREATE statements.

        - Dialects requiring explicit commit after DDL (Oracle/DB2): always commit.
        - Dialects auto-committing DDL during clean_schema (MySQL/DB2): commit
          only when autoCommit is False (safe no-op otherwise).
        - Other dialects: commit if autoCommit is False; commit anyway when
          autoCommit cannot be determined.
        """
        if not hasattr(self.test_provider.connection, "commit"):  # type: ignore[attr-defined]
            return
        try:
            if self._quirks.requires_explicit_commit_after_ddl:
                # Even for dialects requiring explicit commit (Oracle, DB2),
                # commit() raises if autoCommit is True (DB2 JCC, Oracle ORA-17273).
                # When autoCommit cannot be determined, commit anyway (best-effort).
                should_commit = True
                if hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                    try:
                        if self.test_provider.connection.getAutoCommit():  # type: ignore[attr-defined]
                            should_commit = False
                            logger.debug(
                                f"[{self.dialect.upper()}] AutoCommit is True; skipping explicit commit"
                            )
                    except Exception as e:
                        logger.debug(f"Could not check autoCommit: {e}; will attempt commit")
                if should_commit:
                    self.test_provider.connection.commit()  # type: ignore[attr-defined]
                    logger.debug(
                        f"[{self.dialect.upper()}] Committed transaction after executing CREATE statements"
                    )
            elif hasattr(self.test_provider.connection, "getAutoCommit"):  # type: ignore[attr-defined]
                auto_commit = self.test_provider.connection.getAutoCommit()  # type: ignore[attr-defined]
                if not auto_commit:
                    self.test_provider.connection.commit()  # type: ignore[attr-defined]
                    logger.debug("Committed transaction after executing CREATE statements")
                else:
                    logger.debug("AutoCommit is True, DDL already auto-committed")
            elif self._quirks.clean_schema_auto_commits:
                # Can't check, but DDL is auto-committed for this dialect.
                logger.debug(
                    f"Could not check autoCommit, assuming DDL is auto-committed for {self.dialect}"
                )
            else:
                # Can't check, commit anyway for safety.
                self.test_provider.connection.commit()  # type: ignore[attr-defined]
                logger.debug("Committed transaction (could not check autoCommit)")
        except Exception as e:
            logger.warning(f"Could not commit transaction: {e}")
            # For dialects that auto-commit DDL during clean_schema, rollback
            # after a failed commit can hang the connection (the DDL was
            # already committed). Only attempt rollback when it's safe.
            if not self._quirks.clean_schema_auto_commits:
                if hasattr(self.test_provider.connection, "rollback"):  # type: ignore[attr-defined]
                    try:
                        self.test_provider.connection.rollback()  # type: ignore[attr-defined]
                    except Exception as e:
                        logger.debug(
                            f"[{self.dialect.upper()}] Rollback after failed commit failed (non-critical): {e}"
                        )

    def _introspect_source(self) -> Dict[str, List[Any]]:
        """Introspect schema from source database."""
        if not self.introspector:
            from core.introspection.schema_introspector import SchemaIntrospector

            self.introspector = SchemaIntrospector(self.source_provider)

        objects: Dict[str, List[Any]] = {}

        # Introspect based on test_object_types
        if "tables" in self.test_object_types:
            tables = self.introspector.get_tables(self.source_schema)
            objects["tables"] = tables if tables else []
            logger.debug(
                f"Introspected {len(tables) if tables else 0} tables from schema {self.source_schema}"
            )

        if "views" in self.test_object_types:
            logger.debug(f"Introspecting views from schema {self.source_schema}")
            objects["views"] = self.introspector.get_views(self.source_schema)
            logger.debug(
                f"Introspected {len(objects.get('views', []))} views from schema {self.source_schema}"
            )

        if "indexes" in self.test_object_types:
            all_indexes: List[Index] = []
            tables = objects.get("tables", [])
            if tables:
                for table in tables:
                    # Use the exact table name as stored in the database
                    table_name = table.name
                    # get_indexes signature is (schema, table) not (schema, table=...)
                    table_indexes = self.introspector.get_indexes(self.source_schema, table_name)
                    all_indexes.extend(table_indexes)
                    logger.debug(
                        f"Found {len(table_indexes)} indexes for table '{table_name}' in schema {self.source_schema}"
                    )
            else:
                # If no tables found but indexes are requested, we need to find tables first
                logger.warning(
                    f"No tables found in schema {self.source_schema}, cannot get indexes. "
                    f"Consider including 'tables' in test_object_types."
                )
            objects["indexes"] = all_indexes
            logger.debug(f"Total indexes found: {len(all_indexes)} in schema {self.source_schema}")

        if "sequences" in self.test_object_types:
            objects["sequences"] = self.introspector.get_sequences(self.source_schema)

        if "procedures" in self.test_object_types:
            objects["procedures"] = self.introspector.get_procedures(self.source_schema)

        if "functions" in self.test_object_types:
            objects["functions"] = self.introspector.get_functions(self.source_schema)

        if "triggers" in self.test_object_types:
            objects["triggers"] = self.introspector.get_triggers(self.source_schema)

        if "user_defined_types" in self.test_object_types:
            objects["user_defined_types"] = self.introspector.get_user_defined_types(
                self.source_schema
            )

        if "synonyms" in self.test_object_types:
            objects["synonyms"] = self.introspector.get_synonyms(self.source_schema)

        if "packages" in self.test_object_types:
            objects["packages"] = self.introspector.get_packages(self.source_schema)

        if "events" in self.test_object_types:
            objects["events"] = self.introspector.get_events(self.source_schema)

        if "extensions" in self.test_object_types:
            objects["extensions"] = self.introspector.get_extensions()

        if "materialized_views" in self.test_object_types:
            # Get materialized views directly (not from regular views)
            materialized_views = self.introspector.get_materialized_views(self.source_schema)
            objects["materialized_views"] = materialized_views if materialized_views else []

        return objects

    def _introspect_test(self) -> Dict[str, List[Any]]:
        """Re-introspect schema from test database."""
        # Use IntrospectorFactory to get the correct introspector for the dialect
        from core.introspection.introspector_factory import IntrospectorFactory
        from core.introspection.schema_introspector import SchemaIntrospector

        # Use the same introspector type as source, or create a new one
        if self.introspector and hasattr(self.introspector, "provider"):
            # Use factory to create test introspector of the same type
            test_introspector = IntrospectorFactory.create(
                self.test_provider, log=getattr(self.introspector, "log", None)
            )
        else:
            test_introspector = SchemaIntrospector(self.test_provider)
        objects: Dict[str, List[Any]] = {}

        # Re-introspect based on test_object_types
        if "tables" in self.test_object_types:
            tables = test_introspector.get_tables(self.test_schema)
            objects["tables"] = tables if tables else []
            logger.debug(
                f"Re-introspected {len(tables) if tables else 0} tables from test schema {self.test_schema}"
            )

        if "views" in self.test_object_types:
            objects["views"] = test_introspector.get_views(self.test_schema)

        if "indexes" in self.test_object_types:
            all_indexes: List[Index] = []
            tables = objects.get("tables", [])
            for table in tables:
                # get_indexes signature is (schema, table) not (schema, table=...)
                table_indexes = test_introspector.get_indexes(self.test_schema, table.name)
                all_indexes.extend(table_indexes)
            objects["indexes"] = all_indexes

        if "sequences" in self.test_object_types:
            objects["sequences"] = test_introspector.get_sequences(self.test_schema)

        if "procedures" in self.test_object_types:
            objects["procedures"] = test_introspector.get_procedures(self.test_schema)

        if "functions" in self.test_object_types:
            objects["functions"] = test_introspector.get_functions(self.test_schema)

        if "triggers" in self.test_object_types:
            objects["triggers"] = test_introspector.get_triggers(self.test_schema)

        if "user_defined_types" in self.test_object_types:
            objects["user_defined_types"] = test_introspector.get_user_defined_types(
                self.test_schema
            )

        if "synonyms" in self.test_object_types:
            objects["synonyms"] = test_introspector.get_synonyms(self.test_schema)

        if "packages" in self.test_object_types:
            objects["packages"] = test_introspector.get_packages(self.test_schema)

        if "events" in self.test_object_types:
            objects["events"] = test_introspector.get_events(self.test_schema)

        if "extensions" in self.test_object_types:
            objects["extensions"] = test_introspector.get_extensions()

        if "materialized_views" in self.test_object_types:
            # Get materialized views directly (not from regular views)
            materialized_views = test_introspector.get_materialized_views(self.test_schema)
            objects["materialized_views"] = materialized_views if materialized_views else []

        return objects

    def _compare_and_verify(
        self,
        original_objects: Dict[str, List[Any]],
        reintrospected_objects: Dict[str, List[Any]],
    ) -> None:
        """Compare original and re-introspected objects."""
        # Compare tables
        if "tables" in self.test_object_types:
            self._rt_comparator.compare_tables(
                original_objects.get("tables", []),
                reintrospected_objects.get("tables", []),
                self.results,
            )

        # Compare views
        if "views" in self.test_object_types:
            self._rt_comparator.compare_views(
                original_objects.get("views", []),
                reintrospected_objects.get("views", []),
                self.results,
            )

        # Compare indexes
        if "indexes" in self.test_object_types:
            self._rt_comparator.compare_indexes(
                original_objects.get("indexes", []),
                reintrospected_objects.get("indexes", []),
                self.results,
            )

        # For other object types, we do basic count and name matching
        for obj_type in [
            "sequences",
            "procedures",
            "functions",
            "triggers",
            "user_defined_types",
            "synonyms",
            "packages",
            "events",
            "extensions",
            "materialized_views",
        ]:
            if obj_type in self.test_object_types:
                self._rt_comparator.compare_objects_by_name(
                    obj_type,
                    original_objects.get(obj_type, []),
                    reintrospected_objects.get(obj_type, []),
                    self.results,
                )
