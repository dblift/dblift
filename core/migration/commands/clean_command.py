"""
Clean command implementation.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass
from core.logger.results import CleanResult
from core.migration.clean_summary import CleanedObjectInfo, CleanExecutionSummary
from db.provider_capabilities import get_clean_preview

from .base_command import BaseCommand


class CleanCommand(BaseCommand):
    """Handles the 'clean' command execution."""

    def execute(
        self,
        dry_run: bool = False,
        scripts_dir: Optional[Path] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        snapshot_model_path: Optional[Path] = None,
        **kwargs: Any,
    ) -> CleanResult:
        """Clean the database by dropping all objects in the schema.

        Args:
            dry_run: If True, simulate the clean without executing.
            scripts_dir: Directory containing migration scripts.
            recursive: If True, search scripts recursively.
            additional_dirs: Additional directories to search for scripts.
            dir_recursive_map: Map of directories to their recursive setting.
            snapshot_model_path: Path to snapshot model file.
            **kwargs: Reserved for forward compatibility; passed through from API/executor.
        """
        result = CleanResult()
        clean_enabled = kwargs.pop("clean_enabled", False) is True
        # BUG-10: CosmosDB has no SQL schema, so ``config.database.schema`` is
        # empty and the summary line rendered as "Cleaned N object(s) from
        # schema '':". Fall back to the database-scope name when schema is
        # unset so the label is meaningful across dialects. For SQL dialects
        # ``schema`` is always populated, so the fallback never triggers.
        result.target_schema = (
            self.config.database.schema
            or getattr(self.config.database, "database_name", None)
            or getattr(self.config.database, "database", None)
            or ""
        )

        if (
            getattr(self.config, "clean_disabled", True) is True
            and not dry_run
            and not clean_enabled
        ):
            error_message = (
                "Clean is disabled by configuration. Set clean_disabled: false "
                "or pass --clean-enabled to allow destructive clean execution."
            )
            self.log.error(error_message)
            result.set_error(error_message)
            result.complete()
            return result

        try:
            # Establish connection (needed for both dry-run enumeration and actual clean).
            # In dry-run mode the connection is the sole source of truth for what
            # would be dropped — a failed connection must be reported, not hidden,
            # otherwise the user sees "(schema appears empty)" when the schema may
            # be full.  Re-raising lets the outer except handler set result.set_error.
            # In non-dry-run mode, swallowing is acceptable because the subsequent
            # clean_schema() call will raise a clear error if the connection is broken.
            try:
                self._ensure_connected()
            except Exception as e:
                if dry_run:
                    raise
                self.log.debug(f"_ensure_connection skipped: {e}")
            if hasattr(self.provider, "set_current_schema"):
                try:
                    self.provider.set_current_schema(self.config.database.schema)
                except Exception as e:
                    self.log.debug(f"set_current_schema skipped: {e}")

            # Populate database connection information (requires an active connection)
            self._populate_database_info(result)

            try:
                self._log_command_header_update("clean", dry_run=dry_run)
            except Exception as e:
                self.log.debug(f"_log_command_header_update skipped: {e}")

            if dry_run:
                self.log.info(f"DRY RUN: Would clean schema '{self.config.database.schema}'")

                schema = self.config.database.schema
                objects_found = False
                preview_succeeded = False

                # Preferred path: the provider's own discovery (same code a real
                # clean would use), so dry-run can't drift from reality.
                try:
                    preview = get_clean_preview(self.provider, schema)
                    if preview is not None:
                        for obj in preview.objects:
                            self.log.info(f"  Would drop {obj.object_type}: {obj.name}")
                            objects_found = True
                        preview_succeeded = True
                except Exception as e:
                    # Fall through to the introspector fallback below — a failing
                    # get_clean_preview should not silently produce an empty listing.
                    self.log.debug(
                        f"Provider get_clean_preview failed, falling back to introspector: {e}"
                    )

                # Fallback for providers that have not implemented get_clean_preview
                # *or* whose get_clean_preview raised — best-effort enumeration via
                # SchemaIntrospector.
                if not preview_succeeded:

                    def _safe_introspect(fn: Any, schema: Any) -> List[Any]:
                        try:
                            return fn(schema) or []
                        except Exception:
                            return []

                    try:
                        from core.introspection.schema_introspector import SchemaIntrospector

                        introspector = SchemaIntrospector(self.provider, self.log)
                        for obj in _safe_introspect(introspector.get_tables, schema):
                            self.log.info(f"  Would drop table: {obj.name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_views, schema):
                            self.log.info(f"  Would drop view: {obj.name}")
                            objects_found = True
                        # Batch-5 BUG-04: dialect-specific object types that a
                        # real clean drops but the minimal fallback used to
                        # skip. Oracle matview/package/procedure/synonym are
                        # the confirmed-broken case; each getter returns ``[]``
                        # on dialects that do not expose that object kind, so
                        # these extra loops are safe cross-dialect.
                        for obj in _safe_introspect(introspector.get_materialized_views, schema):
                            self.log.info(f"  Would drop materialized view: {obj.name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_sequences, schema):
                            self.log.info(f"  Would drop sequence: {obj.name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_functions, schema):
                            self.log.info(f"  Would drop function: {obj.name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_procedures, schema):
                            name = getattr(obj, "name", None) or str(obj)
                            self.log.info(f"  Would drop procedure: {name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_packages, schema):
                            name = getattr(obj, "name", None) or str(obj)
                            self.log.info(f"  Would drop package: {name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_synonyms, schema):
                            name = getattr(obj, "name", None) or str(obj)
                            self.log.info(f"  Would drop synonym: {name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_triggers, schema):
                            self.log.info(f"  Would drop trigger: {obj.name}")
                            objects_found = True
                        for obj in _safe_introspect(introspector.get_user_defined_types, schema):
                            name = getattr(obj, "name", None) or str(obj)
                            self.log.info(f"  Would drop type: {name}")
                            objects_found = True
                    except Exception as e:
                        self.log.warning(
                            f"Could not enumerate schema objects for dry-run preview: {e}"
                        )

                if not objects_found:
                    self.log.info("  (schema appears empty or objects could not be enumerated)")
                # Note: Callbacks are NOT executed in dry-run mode
                self._log_command_completion("clean", result)
                return result

            # Execute beforeClean callbacks if scripts_dir is provided
            if scripts_dir:
                try:
                    self._execute_callbacks(
                        scripts_dir, "beforeClean", recursive, additional_dirs, dir_recursive_map
                    )
                except Exception as e:
                    self.log.error(f"beforeClean callback failed: {e}")
                    result.set_error(f"beforeClean callback failed: {e}")
                    if scripts_dir:
                        self._execute_callbacks(
                            scripts_dir,
                            "afterCleanError",
                            recursive,
                            additional_dirs,
                            dir_recursive_map,
                        )
                    result.complete()
                    return result

            self.log.info(f"Cleaning schema '{self.config.database.schema}'")

            # Use provider's clean_schema method which returns executed statements
            executed_statements: List[str] = []
            if hasattr(self.provider, "clean_schema"):
                clean_response = self.provider.clean_schema(self.config.database.schema)

                cleaned_objects: List[CleanedObjectInfo] = []

                if isinstance(clean_response, CleanExecutionSummary):
                    executed_statements = clean_response.statements
                    cleaned_objects = clean_response.objects
                    # Check for errors in clean response
                    if hasattr(clean_response, "errors") and clean_response.errors:
                        for error in clean_response.errors:
                            result.add_warning(error)
                else:
                    executed_statements = clean_response or []

                if cleaned_objects:
                    for cleaned_obj in cleaned_objects:
                        result.add_cleaned_object(
                            object_type=cleaned_obj.object_type,
                            name=cleaned_obj.name,
                            schema=cleaned_obj.schema,
                            details=cleaned_obj.details,
                        )
                # Parse statements only if provider didn't supply structured metadata
                elif executed_statements:
                    for statement in executed_statements:
                        self._parse_drop_statement_for_result(statement, result)

                # Check if there were errors - if so, don't mark as successful
                has_errors = (
                    isinstance(clean_response, CleanExecutionSummary)
                    and hasattr(clean_response, "errors")
                    and len(clean_response.errors) > 0
                )

                if has_errors:
                    result.success = False
                    result.set_error(
                        f"Clean operation completed with {len(clean_response.errors)} error(s). "
                        f"Some objects could not be dropped."
                    )
            else:
                # Fallback: This should not happen with modern providers, but kept for safety
                self.log.warning("Provider does not support clean_schema method, using fallback")
                fallback_sql1 = f"DROP SCHEMA IF EXISTS {self.config.database.schema} CASCADE"
                fallback_sql2 = f"CREATE SCHEMA {self.config.database.schema}"
                self.provider.execute_statement(fallback_sql1)
                self.provider.execute_statement(fallback_sql2)
                executed_statements = [fallback_sql1, fallback_sql2]
                result.add_schema_dropped(self.config.database.schema)

            # Commit only when DDL was actually issued — committing on an autoCommit
            # connection that issued no DML raises PSQLException on PostgreSQL.
            if executed_statements:
                try:
                    self.provider.commit_transaction()
                    self.log.debug("Committed clean operation changes")
                except Exception as commit_err:
                    self.log.error(f"Failed to commit clean operation: {commit_err}")
                    raise

            # Execute afterClean callbacks if scripts_dir is provided
            if scripts_dir:
                self._execute_callbacks(
                    scripts_dir, "afterClean", recursive, additional_dirs, dir_recursive_map
                )

            # Log summary of cleaned objects grouped by type
            self._log_clean_summary(result)

            # Log final status summary only (errors are already logged individually)
            if result.success:
                if result.warnings:
                    self.log.info(
                        f"Schema cleaned successfully (executed {len(executed_statements)} statements, "
                        f"{len(result.warnings)} warning(s))"
                    )
                else:
                    self.log.info(
                        f"Schema cleaned successfully (executed {len(executed_statements)} statements)"
                    )
            else:
                error_count = len(result.warnings) if result.warnings else 0
                self.log.error(
                    f"Schema clean failed (executed {len(executed_statements)} statements, "
                    f"{error_count} error(s))"
                )

            self._log_command_completion("clean", result)
            return result

        except Exception as e:
            self.log.error(f"Clean operation failed: {e}")
            result.set_error(f"Clean operation failed: {e}")
            # Execute afterCleanError callbacks on exception if scripts_dir is provided
            if scripts_dir:
                try:
                    self._execute_callbacks(
                        scripts_dir,
                        "afterCleanError",
                        recursive,
                        additional_dirs,
                        dir_recursive_map,
                    )
                except Exception as cb_e:
                    self.log.debug(
                        f"afterCleanError callback skipped: {cb_e}"
                    )  # Ignore errors in error callbacks during exception handling
            self._log_command_completion("clean", result)
            return result

    def _parse_drop_statement_for_result(self, statement: str, result: CleanResult) -> None:
        """Parse a DROP statement to track what objects were dropped.

        Args:
            statement: SQL DROP statement
            result: CleanResult to update with dropped objects
        """
        # Normalize statement for parsing
        stmt = statement.upper().strip()

        # Parse DROP VIEW statements
        view_match = re.search(
            r'DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?(?:"?[^"]*"?\.)?"?([^"\s]+)"?', stmt
        )
        if view_match:
            view_name = view_match.group(1)
            result.add_view_dropped(view_name)
            return

        # Parse DROP TABLE statements
        table_match = re.search(
            r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:"?[^"]*"?\.)?"?([^"\s]+)"?', stmt
        )
        if table_match:
            table_name = table_match.group(1)
            result.add_table_dropped(table_name)
            return

        # Parse DROP SEQUENCE statements
        sequence_match = re.search(
            r'DROP\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?(?:"?[^"]*"?\.)?"?([^"\s]+)"?', stmt
        )
        if sequence_match:
            sequence_name = sequence_match.group(1)
            result.add_sequence_dropped(sequence_name)
            return

        # Parse DROP FUNCTION statements
        function_match = re.search(
            r'DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(?:"?[^"]*"?\.)?"?([^"\s(]+)', stmt
        )
        if function_match:
            function_name = function_match.group(1)
            result.add_function_dropped(function_name)
            return

        # Parse DROP PROCEDURE statements
        procedure_match = re.search(
            r'DROP\s+PROCEDURE\s+(?:IF\s+EXISTS\s+)?(?:"?[^"]*"?\.)?"?([^"\s(]+)', stmt
        )
        if procedure_match:
            procedure_name = procedure_match.group(1)
            result.add_procedure_dropped(procedure_name)
            return

        # Parse DROP TRIGGER statements
        trigger_match = re.search(
            r'DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?(?:"?[^"]*"?\.)?"?([^"\s]+)"?', stmt
        )
        if trigger_match:
            trigger_name = trigger_match.group(1)
            result.add_trigger_dropped(trigger_name)
            return

    def _log_clean_summary(self, result: CleanResult) -> None:
        """Log summary of cleaned objects grouped by type."""
        from rich.tree import Tree

        from core.logger.console import render_tree_to_str

        objects_map = result.get_objects_by_type()
        total_objects = sum(len(names) for names in objects_map.values())

        if total_objects == 0:
            self.log.info("No objects were cleaned")
            return

        preferred_order = [
            "schema",
            "table",
            "view",
            "materialized_view",
            "materialized_query_table",
            "function",
            "procedure",
            "sequence",
            "trigger",
            "extension",
            "domain",
            "type",
            "index",
            "foreign_key",
            "synonym",
            "alias",
            "module",
            "event",
            "global_temporary_table",
        ]

        def _label(object_type: str, count: int) -> str:
            label = object_type.replace("_", " ").title()
            if count == 1:
                return label
            if label.endswith(("s", "x", "z", "ch", "sh")):
                return f"{label}es"
            if label.endswith("y") and label[-2:] not in ("ay", "ey", "iy", "oy", "uy"):
                return f"{label[:-1]}ies"
            return f"{label}s"

        root = Tree(f"Cleaned {total_objects} object(s) from schema '{result.target_schema}'")

        handled = set()
        ordered = list(preferred_order) + sorted(t for t in objects_map if t not in preferred_order)
        for object_type in ordered:
            names = sorted(objects_map.get(object_type, []))
            if not names:
                continue
            handled.add(object_type)
            branch = root.add(f"{_label(object_type, len(names))} ({len(names)})")
            for name in names:
                branch.add(name)

        self.log.console_print(root)
        self.log.file_only_info(render_tree_to_str(root))
