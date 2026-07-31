"""
Clean command implementation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger.results import CleanResult

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
        **kwargs: Any,
    ) -> CleanResult:
        """Clean the database by dropping all objects in the schema.

        Args:
            dry_run: If True, simulate the clean without executing.
            scripts_dir: Directory containing migration scripts.
            recursive: If True, search scripts recursively.
            additional_dirs: Additional directories to search for scripts.
            dir_recursive_map: Map of directories to their recursive setting.
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

                for obj in self.provider.list_droppable_objects(schema):
                    if not obj.record_result:
                        continue
                    self.log.info(f"  Would drop {obj.object_type}: {obj.name}")
                    objects_found = True

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

            executed_statements: List[str] = []
            drop_errors: List[str] = []
            for obj in self.provider.list_droppable_objects(self.config.database.schema):
                try:
                    self.provider.drop_object(obj)
                    executed_statements.append(obj.drop_sql)
                    if obj.record_result:
                        result.add_cleaned_object(
                            object_type=obj.object_type,
                            name=obj.name,
                            schema=self.config.database.schema,
                        )
                except Exception as e:
                    error = f"Failed to drop {obj.object_type} {obj.name}: {e}"
                    self.log.warning(error)
                    result.add_warning(error)
                    drop_errors.append(error)

            if drop_errors:
                result.success = False
                result.set_error(
                    f"Clean operation completed with {len(drop_errors)} error(s). "
                    f"Some objects could not be dropped."
                )

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
