"""
Round-trip testing framework for schema introspection.

Tests the complete cycle: introspect → generate → execute → verify
to ensure all properties are preserved correctly.

This module is the public façade. The heavy-lifting implementation is
split across sibling modules and composed onto ``RoundTripTester`` via
mixins to keep file sizes manageable while preserving the public class
surface (every helper used by ``tests/unit/core/validation/`` —
including private ones like ``_build_drop_sql`` and
``_retry_drop_and_create`` — remains an instance method of
``RoundTripTester``):

* ``_drop_phase._DropPhaseMixin`` — autocommit handling, transaction
  state probing, per-statement drop+execute loop, dialect-specific
  ``DROP TABLE`` SQL builder, and the error-recovery dispatcher.
* ``_retry_strategy._RetryStrategyMixin`` — Oracle/DB2 "already exists"
  retry: candidate identifier enumeration + drop+create replay.
* ``_introspection_verifier._IntrospectionVerifierMixin`` — source +
  test introspection, schema-lifecycle (ensure/clean/commit), and the
  captured-vs-live comparison loop.

Module-level ``DependencyAnalyzer`` stays on this module so existing
test patches against ``core.validation.round_trip_tester.DependencyAnalyzer``
keep working.

OCP-01 is closed: dialect-specific branches that previously lived in
this module (DROP-strategy candidate building, schema-rewrite forms)
have been lifted into ``BaseQuirks.build_retry_drop_strategies`` and
``BaseQuirks.replace_round_trip_schema_in_sql`` with Oracle / DB2 /
SQL Server overrides (Y-1, Y-2).
"""

import logging
import traceback
from typing import Any, Dict, List, Optional

from core.comparison.comparator import ObjectComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.introspection.schema_introspector import SchemaIntrospector
from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.dependency_analyzer import DependencyAnalyzer
from core.sql_generator.generator_factory import SqlGeneratorFactory
from core.validation._drop_phase import _DropPhaseMixin
from core.validation._introspection_verifier import _IntrospectionVerifierMixin
from core.validation._retry_strategy import _RetryStrategyMixin
from core.validation._round_trip_comparator import RoundTripComparator
from db.base_provider import BaseProvider
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class RoundTripTester(
    _DropPhaseMixin,
    _RetryStrategyMixin,
    _IntrospectionVerifierMixin,
):
    """
    Tests round-trip accuracy of schema introspection and SQL generation.

    Process:
    1. Introspect schema from source database
    2. Generate CREATE statements
    3. Execute on test database
    4. Re-introspect from test database
    5. Compare original vs re-introspected
    6. Verify all properties preserved
    """

    def __init__(
        self,
        source_provider: BaseProvider,
        test_provider: BaseProvider,
        source_schema: str,
        test_schema: str,
        introspector: Optional[SchemaIntrospector] = None,
        sql_generator: Optional[BaseSqlGenerator] = None,
        comparator: Optional[ObjectComparator] = None,
        test_object_types: Optional[List[str]] = None,
    ):
        """
        Initialize the round-trip tester.

        Args:
            source_provider: Provider for source database
            test_provider: Provider for test database (can be same as source)
            source_schema: Schema name in source database
            test_schema: Schema name in test database
            introspector: Optional introspector instance
            sql_generator: Optional SQL generator instance
            comparator: Optional comparator instance
            test_object_types: Optional list of object types to test.
                If None, tests all supported types for the dialect.
                Supported: tables, views, indexes, sequences, procedures,
                functions, triggers, user_defined_types, synonyms, packages,
                events, extensions, materialized_views
        """
        self.source_provider = source_provider
        self.test_provider = test_provider
        self.source_schema = source_schema
        self.test_schema = test_schema
        self.introspector = introspector
        self.sql_generator = sql_generator
        type_normalizer = DataTypeNormalizer()
        self.comparator = comparator or ObjectComparator(type_normalizer)
        # Determine dialect
        self.dialect = (
            source_provider.config.database.type
            if hasattr(source_provider, "config") and hasattr(source_provider.config, "database")
            else ""
        )
        self._quirks = ProviderRegistry.get_quirks((self.dialect or "").lower())
        self._rt_comparator = RoundTripComparator(self.dialect, logger, self.comparator)

        # Determine which object types to test
        if test_object_types is None:
            # Test all supported types for the dialect
            self.test_object_types = self._get_supported_object_types()
        else:
            self.test_object_types = [t.lower() for t in test_object_types]

        # Initialize results structure for all object types
        self.results: Dict[str, Any] = {
            "success": False,
            "tables": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "views": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "indexes": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "sequences": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "procedures": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "functions": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "triggers": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "user_defined_types": {
                "original_count": 0,
                "reintrospected_count": 0,
                "differences": [],
            },
            "synonyms": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "packages": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "events": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "extensions": {"original_count": 0, "reintrospected_count": 0, "differences": []},
            "materialized_views": {
                "original_count": 0,
                "reintrospected_count": 0,
                "differences": [],
            },
            "errors": [],
            "warnings": [],
        }

    def _get_supported_object_types(self) -> List[str]:
        """Get list of object types supported for the current dialect."""
        base_types = [
            "tables",
            "views",
            "indexes",
            "sequences",
            "procedures",
            "functions",
            "triggers",
        ]
        supported = base_types.copy()
        supported.extend(self._quirks.round_trip_extra_object_types())
        return supported

    def _safe_rollback(self, provider, context_msg: str) -> None:
        """Rollback transaction for dialects that auto-commit DDL during clean_schema.

        No-op for other dialects. Failures are logged at debug level
        and swallowed because rollback is non-critical cleanup.
        """
        if not self._quirks.clean_schema_auto_commits:
            return
        try:
            if hasattr(provider, "connection") and hasattr(provider.connection, "rollback"):
                try:
                    provider.connection.rollback()  # type: ignore[attr-defined]
                    logger.debug(
                        f"[{self.dialect.upper()}] Rolled back transaction after {context_msg}"
                    )
                except Exception as e:
                    logger.debug(
                        f"[{self.dialect.upper()}] Rollback after {context_msg} failed (non-critical): {e}"
                    )
        except Exception as e:
            logger.debug(f"{context_msg} cleanup check failed (non-critical): {e}")

    def run_round_trip_test(self) -> Dict[str, Any]:
        """
        Run the complete round-trip test.

        Returns:
            Dictionary with test results
        """
        try:
            # Step 1: Introspect from source
            logger.info(f"Step 1: Introspecting schema '{self.source_schema}' from source database")
            introspected_objects = self._introspect_source()

            # CRITICAL: Rollback after source introspection for MySQL/DB2 to prevent hanging
            self._safe_rollback(self.source_provider, "source introspection")

            # Update counts first
            for obj_type, objects in introspected_objects.items():
                if obj_type in self.results and isinstance(objects, list):
                    self.results[obj_type]["original_count"] = len(objects)
                    logger.debug(
                        f"Set {obj_type} original_count to {len(objects)} for schema {self.source_schema}"
                    )

            # Check if we have any objects to test
            total_objects = sum(
                len(objects) if objects else 0
                for objects in introspected_objects.values()
                if isinstance(objects, list)
            )
            if total_objects == 0:
                self.results["errors"].append("No objects found in source schema")
                return self.results

            # Step 2: Generate CREATE statements
            logger.info("Step 2: Generating CREATE statements")
            create_statements = self._generate_create_statements(introspected_objects)

            if not create_statements:
                self.results["errors"].append("No CREATE statements generated")
                return self.results

            # Step 3: Execute on test database
            logger.info(f"Step 3: Executing CREATE statements on test schema '{self.test_schema}'")
            logger.debug(f"Generated {len(create_statements)} CREATE statements")
            self._execute_on_test(create_statements)

            # Step 4: Re-introspect from test database
            logger.info(f"Step 4: Re-introspecting schema '{self.test_schema}' from test database")

            reintrospected_objects = self._introspect_test()

            # CRITICAL: Rollback after test introspection for MySQL/DB2 to prevent hanging
            self._safe_rollback(self.test_provider, "test introspection")

            # Update reintrospected counts
            for obj_type, objects in reintrospected_objects.items():
                if obj_type in self.results and isinstance(objects, list):
                    self.results[obj_type]["reintrospected_count"] = len(objects)

            # Step 5: Compare and verify
            logger.info("Step 5: Comparing original vs re-introspected")
            self._compare_and_verify(introspected_objects, reintrospected_objects)

            # Determine overall success
            # CRITICAL: SQL execution failures are now added as errors, not warnings
            # This ensures tests fail when generated SQL is invalid
            has_errors = len(self.results["errors"]) > 0
            # All differences (errors, warnings, info) are considered failures
            # Perfect SQL reproduction requires no differences at all
            has_differences = any(
                len(self.results[obj_type]["differences"]) > 0
                for obj_type in self.test_object_types
                if obj_type in self.results
            )
            self.results["success"] = not has_errors and not has_differences

            # CRITICAL: For dialects that auto-commit DDL during clean_schema
            # (MySQL/DB2), all operations are already committed. Rolling back
            # after commits can cause hangs, so we skip rollback for those
            # dialects.
            try:
                if self._quirks.clean_schema_auto_commits:
                    # All operations are committed, just ensure connection state is clean
                    # Don't rollback as it can cause hangs on already-committed transactions
                    logger.debug(
                        f"[{self.dialect.upper()}] transactions already committed, skipping rollback"
                    )
            except Exception as cleanup_err:
                logger.debug(f"Transaction cleanup error (non-critical): {cleanup_err}")

            return self.results

        except Exception as e:
            logger.error(f"Round-trip test failed: {e}", exc_info=True)
            self.results["errors"].append(f"Test execution failed: {str(e)}")
            # CRITICAL: Rollback on error to prevent hanging (both providers)
            self._safe_rollback(self.test_provider, "test_provider error")
            self._safe_rollback(self.source_provider, "source_provider error")
            return self.results

    def _generate_create_statements(self, objects: Dict[str, List[Any]]) -> List[str]:
        """Orchestrator: generate CREATE statements from introspected objects."""
        if not self.sql_generator:
            self.sql_generator = SqlGeneratorFactory.create(self.dialect)  # type: ignore[assignment]

        # Order tables by dependencies (parent before child)
        if "tables" in objects and objects["tables"]:
            try:
                analyzer = DependencyAnalyzer()
                objects["tables"] = analyzer.get_create_order(objects["tables"])
                logger.debug(f"Ordered {len(objects['tables'])} tables by dependencies")
            except Exception as e:
                logger.warning(f"Failed to order tables by dependencies: {e}, using original order")
                self.results["warnings"].append(f"Failed to order tables by dependencies: {e}")

        statements: List[str] = []
        for obj_type, obj_list in objects.items():
            if obj_list:
                statements.extend(self._generate_statements_for_objects(obj_list, obj_type))
        return statements

    def _generate_statements_for_objects(self, obj_list: List[Any], obj_type: str) -> List[str]:
        """Generate CREATE + additional statements for a list of objects of one type."""
        results: List[str] = []
        for obj in obj_list:
            try:
                if not self.sql_generator:
                    continue
                create_sql = self.sql_generator.generate_create_statement(obj)
                if not create_sql or not create_sql.strip():
                    obj_name = getattr(obj, "name", "unknown")
                    warning_msg = f"Empty CREATE statement generated for {obj_type} '{obj_name}'"
                    self.results["warnings"].append(warning_msg)
                    logger.warning(warning_msg)
                    continue

                obj_name = getattr(obj, "name", "unknown")
                logger.info(f"[{self.dialect.upper()}] Generated SQL for {obj_type} '{obj_name}':")
                logger.info(f"SQL: {create_sql[:500]}")

                if self.source_schema != self.test_schema:
                    create_sql = self._replace_schema_in_sql(create_sql)
                results.append(create_sql)
                logger.debug(f"Generated CREATE statement: {create_sql[:200]}...")

                # Additional statements (e.g., ALTER TABLE for DB2 CHECK constraints)
                rt_dialect = self.dialect or ""
                additional_statements = self.sql_generator._generate_additional_statements(
                    obj, rt_dialect
                )
                for additional_stmt in additional_statements:
                    if additional_stmt and additional_stmt.strip():
                        if self.source_schema != self.test_schema:
                            additional_stmt = self._replace_schema_in_sql(additional_stmt)
                        results.append(additional_stmt)
                        logger.debug(f"Generated additional statement: {additional_stmt[:200]}...")
            except Exception as e:
                error_msg = (
                    f"Failed to generate CREATE for {obj_type} "
                    f"{getattr(obj, 'name', 'unknown')}: {e}"
                )
                self.results["warnings"].append(error_msg)
                logger.error(error_msg)
                logger.error(f"Traceback: {traceback.format_exc()}")
        return results

    def _replace_schema_in_sql(self, sql: str) -> str:
        """Replace source schema name with test schema name in generated SQL.

        Delegates to ``self._quirks.replace_round_trip_schema_in_sql`` so
        each dialect owns its own identifier-quoting and REFERENCES /
        FROM-JOIN rewriting rules.
        """
        rewritten = self._quirks.replace_round_trip_schema_in_sql(
            sql, self.source_schema, self.test_schema
        )
        logger.debug(
            f"Replaced schema {self.source_schema} with {self.test_schema} in generated SQL"
        )
        return rewritten

    def get_summary(self) -> str:
        """Get a human-readable summary of test results."""
        return RoundTripComparator.get_summary(self.results, self.test_object_types)
