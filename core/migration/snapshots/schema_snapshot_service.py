"""Schema snapshot service — builds, persists, and loads schema snapshots from live providers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from config import DbliftConfig
from core.introspection import IntrospectorFactory
from core.logger import Log, NullLog
from core.migration._type_match import is_versioned, migration_type_name
from core.migration.migration import MigrationType
from core.migration.snapshots.schema_snapshot import (
    SchemaSnapshot,
    SchemaSnapshotPayload,
    decode_payload,
)
from core.migration.snapshots.schema_snapshot_repository import (
    SchemaSnapshotRepository,
)
from core.sql_model.base import ConstraintType
from core.sql_model.table_canonicalizer import TableCanonicalizer
from db.base_provider import BaseProvider
from db.provider_capabilities import ensure_provider_connection


class SnapshotConnectionContext:
    """Context manager to ensure a single connection is used throughout snapshot operations."""

    def __init__(
        self, provider: BaseProvider, log: Optional[Union[logging.Logger, Log]] = None
    ) -> None:
        """Bind the context to a provider so the same connection is reused inside the ``with`` block."""
        self.provider = provider
        self.log = log if log is not None else NullLog()
        self.original_connection = None
        self.snapshot_connection = None

    def __enter__(self) -> "SnapshotConnectionContext":
        """Establish a dedicated connection for snapshot operations."""
        try:
            # Store the original connection state
            if hasattr(self.provider, "connection"):
                self.original_connection = self.provider.connection
            elif hasattr(self.provider, "query_executor") and hasattr(
                self.provider.query_executor, "connection"
            ):
                self.original_connection = self.provider.query_executor.connection

            # Create a fresh connection for snapshot operations
            if not self.provider.is_connected():
                self.provider.create_connection()

            # Store the snapshot connection
            if hasattr(self.provider, "connection"):
                self.snapshot_connection = self.provider.connection
            elif hasattr(self.provider, "query_executor") and hasattr(
                self.provider.query_executor, "connection"
            ):
                self.snapshot_connection = self.provider.query_executor.connection

            self.log.debug("Established dedicated connection for snapshot operations")

        except Exception as e:
            self.log.debug(f"Could not establish snapshot connection: {e}")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Clean up the snapshot connection."""
        try:
            # The connection will be managed by the provider's lifecycle
            # We don't explicitly close it here to avoid breaking the provider state
            self.log.debug("Snapshot connection context completed")
        except Exception as e:
            self.log.debug(f"Error during snapshot connection cleanup: {e}")


class SchemaSnapshotService:
    """Build and persist schema snapshots based on live database state."""

    def __init__(
        self,
        config: DbliftConfig,
        provider: BaseProvider,
        history_manager: Any,
        log: Optional[Union[logging.Logger, Log]] = None,
    ) -> None:
        """Wire dependencies — config, provider, history manager — needed to capture snapshots."""
        self.config = config
        self.provider = provider
        self.history_manager = history_manager
        self.log = log if log is not None else NullLog()
        self._logger = logging.getLogger(__name__)
        schema = getattr(self.config.database, "schema", None)
        schema_name = schema if isinstance(schema, str) and schema is not None else ""
        self.repository = SchemaSnapshotRepository(
            provider=provider,
            schema=schema_name,
            table_name=getattr(config, "snapshot_table", None),
            logger=self._logger,
        )

    def capture_snapshot(
        self,
        reason: str = "",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> SchemaSnapshot:
        """Capture and persist a schema snapshot."""
        # Ensure clean connection state before snapshot creation (for DB2)
        # This prevents locking issues from uncommitted transactions after migration
        self._ensure_clean_connection_state()

        # Use a single connection for the entire snapshot process; the context
        # manager binds the connection but the body uses self.connection / self.provider.
        with self._get_snapshot_connection():
            payload = self._build_payload()
            return self.save_payload(payload, reason=reason, extra_metadata=extra_metadata)

    def load_latest_snapshot(self) -> Optional[SchemaSnapshot]:
        """Fetch the most recent snapshot if available."""
        return self.repository.get_latest_snapshot()

    def build_live_payload(self) -> SchemaSnapshotPayload:
        """Construct a schema snapshot payload of the current database without persisting it."""
        # Ensure clean connection state before introspection (critical for DB2)
        self._ensure_clean_connection_state()
        return self._build_payload()

    def save_payload(
        self,
        payload: SchemaSnapshotPayload,
        reason: str = "",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> SchemaSnapshot:
        """Persist an existing snapshot payload to the repository."""
        snapshot_meta = payload.metadata.setdefault("snapshot", {})
        if reason:
            snapshot_meta["reason"] = reason
        snapshot_meta["captured_at"] = datetime.now(timezone.utc).isoformat()
        if extra_metadata:
            self._deep_update(payload.metadata, extra_metadata)

        migration_meta = payload.metadata.get("migration", {})
        last_version = migration_meta.get("last_version")
        installed_rank = migration_meta.get("installed_rank")

        # Get max_snapshots from config (default to 1 if not set)
        max_snapshots = getattr(self.config, "max_snapshots", 1)

        snapshot = self.repository.save_snapshot_with_limit(
            payload,
            max_snapshots=max_snapshots,
            migration_version=last_version,
            installed_rank=installed_rank,
        )

        self.log.debug(
            f"Persisted schema snapshot {snapshot.snapshot_id} (last_version={last_version})"
        )
        return snapshot

    def load_snapshot_payload_from_path(self, snapshot_path: Path) -> SchemaSnapshotPayload:
        """Load a snapshot payload from a model file on disk."""
        path = Path(snapshot_path)
        data = path.read_text(encoding="utf-8").strip()
        if not data:
            raise ValueError(f"Snapshot model file '{path}' is empty")

        try:
            if data.startswith("{"):
                payload_dict = json.loads(data)
                return SchemaSnapshotPayload.from_dict(payload_dict)
            return decode_payload(data)
        except Exception as exc:
            raise ValueError(f"Could not parse snapshot model file '{path}': {exc}") from exc

    def validate_snapshot_quality(self, snapshot: SchemaSnapshot) -> Dict[str, Any]:
        """Validate snapshot quality and completeness.

        Args:
            snapshot: SchemaSnapshot instance to validate

        Returns:
            Dictionary with quality metrics and validation results
        """
        if not snapshot:
            return {
                "valid": False,
                "error": "Snapshot is None",
            }

        quality_report: Dict[str, Any] = {
            "valid": True,
            "completeness": {},
            "quality_metrics": {},
            "issues": [],
        }

        # Get snapshot payload
        snapshot_payload = snapshot.payload

        # Build live payload for comparison
        try:
            live_payload = self.build_live_payload()
        except Exception as e:
            quality_report["valid"] = False
            quality_report["error"] = f"Failed to build live payload: {e}"
            return quality_report

        # Compare object counts
        quality_report["completeness"] = {
            "tables": {
                "snapshot": len(snapshot_payload.tables),
                "live": len(live_payload.tables),
                "match": len(snapshot_payload.tables) == len(live_payload.tables),
            },
            "views": {
                "snapshot": len(snapshot_payload.views),
                "live": len(live_payload.views),
                "match": len(snapshot_payload.views) == len(live_payload.views),
            },
            "indexes": {
                "snapshot": len(snapshot_payload.indexes),
                "live": len(live_payload.indexes),
                "match": len(snapshot_payload.indexes) == len(live_payload.indexes),
            },
            "sequences": {
                "snapshot": len(snapshot_payload.sequences),
                "live": len(live_payload.sequences),
                "match": len(snapshot_payload.sequences) == len(live_payload.sequences),
            },
        }

        # Check for mismatches
        for obj_type, counts in quality_report["completeness"].items():
            if not counts["match"]:
                quality_report["issues"].append(
                    f"{obj_type}: snapshot has {counts['snapshot']} but live has {counts['live']}"
                )
                quality_report["valid"] = False

        # Get quality metrics from metadata
        validation_meta = snapshot.metadata.get("validation", {})
        introspection_quality = validation_meta.get("introspection_quality", {})

        if introspection_quality:
            quality_report["quality_metrics"] = {
                "completeness_score": introspection_quality.get("completeness_score"),
                "confidence_level": introspection_quality.get("confidence_level"),
                "error_count": introspection_quality.get("error_count", 0),
                "warning_count": introspection_quality.get("warning_count", 0),
            }

            # Check if quality is acceptable
            if introspection_quality.get("error_count", 0) > 0:
                quality_report["issues"].append(
                    f"Introspection had {introspection_quality['error_count']} errors"
                )
                quality_report["valid"] = False

            completeness_score = introspection_quality.get("completeness_score")
            if completeness_score is not None and completeness_score < 1.0:
                quality_report["issues"].append(
                    f"Completeness score is {completeness_score} (expected 1.0)"
                )

        return quality_report

    # Internal helpers -----------------------------------------------------

    def _build_payload(self) -> SchemaSnapshotPayload:
        schema_name = getattr(self.config.database, "schema", None)
        dialect = getattr(self.config.database, "type", None)

        introspector = IntrospectorFactory.create(provider=self.provider, log=self.log)

        try:
            # Always enable result tracking for introspection quality validation
            introspection_result = None
            if hasattr(introspector, "enable_result_tracking"):
                introspection_result = introspector.enable_result_tracking()
            else:
                # Log warning if result tracking is not available
                self.log.warning(
                    "Introspector does not support result tracking - quality metrics will not be available"
                )

            tables_raw = self._safe_introspect(introspector.get_tables, schema_name)
            tables, table_keys = self._filter_tables(tables_raw, schema_name)
            TableCanonicalizer().canonicalize_tables(tables)

            views = self._filter_views(
                self._safe_introspect(introspector.get_views, schema_name),
                schema_name,
            )
            materialized_views = self._call_optional(
                introspector, "get_materialized_views", schema_name
            )
            materialized_views_filtered = []
            if materialized_views:
                materialized_views_filtered = self._filter_views(materialized_views, schema_name)
                views.extend(materialized_views_filtered)

            # Try bulk index retrieval; fall back to per-table loop
            indexes_raw = self._try_bulk_indexes(introspector, schema_name, tables)
            index_parent_keys = set(table_keys)
            for view in materialized_views_filtered:
                view_schema = getattr(view, "schema", None) or schema_name
                index_parent_keys.add(
                    self._make_table_key(view_schema, getattr(view, "name", None))
                )
            indexes = self._filter_indexes(indexes_raw, index_parent_keys, tables)

            sequences = self._filter_sequences(
                self._safe_introspect(introspector.get_sequences, schema_name),
                tables,
            )
            triggers = self._filter_triggers(
                self._safe_introspect(introspector.get_triggers, schema_name),
                table_keys,
            )
            events = self._call_optional(introspector, "get_events", schema_name)
            procedures = self._call_optional(introspector, "get_procedures", schema_name)
            functions = self._call_optional(introspector, "get_functions", schema_name)
            packages = self._call_optional(introspector, "get_packages", schema_name)
            synonyms = self._call_optional(introspector, "get_synonyms", schema_name)
            user_defined_types = self._filter_user_defined_types(
                self._call_optional(
                    introspector,
                    "get_user_defined_types",
                    schema_name,
                ),
                tables,
                views,
            )
            extensions = self._call_optional(introspector, "get_extensions")
            foreign_data_wrappers = self._call_optional(introspector, "get_foreign_data_wrappers")
            foreign_servers = self._call_optional(introspector, "get_foreign_servers")
            database_links = self._call_optional(introspector, "get_database_links", schema_name)
            linked_servers = self._call_optional(introspector, "get_linked_servers")
            modules = self._call_optional(introspector, "get_modules", schema_name)

            validation_metadata = {}
            if introspection_result:
                validation_metadata = {
                    "introspection_quality": {
                        "completeness_score": introspection_result.get_completeness_score(),
                        "confidence_level": introspection_result.get_confidence_level(),
                        "error_count": len(introspection_result.errors),
                        "warning_count": len(introspection_result.warnings),
                        "object_statuses": [
                            {
                                "object_type": status.object_type,
                                "object_name": status.object_name,
                                "schema": status.schema,
                                "captured": status.captured,
                            }
                            for status in introspection_result.object_statuses
                        ],
                    },
                }

                # Log quality metrics if there are issues
                if introspection_result.errors or introspection_result.warnings:
                    error_msg = f"Snapshot capture had {len(introspection_result.errors)} errors and {len(introspection_result.warnings)} warnings"
                    self.log.warning(error_msg)

            metadata: Dict[str, Any] = {
                "dialect": dialect,
                "schema": schema_name,
                "history_table": self.history_manager.history_table,
                "migration": self._collect_migration_metadata(),
            }
            metadata.update(validation_metadata)

            payload = SchemaSnapshotPayload(
                tables=tables,
                views=views,
                indexes=indexes,
                sequences=sequences,
                triggers=triggers,
                events=events,
                procedures=procedures,
                functions=functions,
                packages=packages,
                synonyms=synonyms,
                user_defined_types=user_defined_types,
                extensions=extensions,
                foreign_data_wrappers=foreign_data_wrappers,
                foreign_servers=foreign_servers,
                database_links=database_links,
                linked_servers=linked_servers,
                modules=modules,
                metadata=metadata,
            )

            return payload
        finally:
            # CRITICAL: Ensure proper cleanup after introspection to prevent hanging.
            # DB2 leaves implicit transactions open that block subsequent queries;
            # MySQL InnoDB consistent-snapshot mode locks the snapshot until
            # commit/rollback. The capability flag identifies these dialects.
            # The quirks lookup itself is guarded: a failure to resolve quirks
            # must not mask an in-flight exception from the ``try`` body.
            dialect_lower = (dialect or "").lower()
            needs_rollback = False
            try:
                from db.provider_registry import ProviderRegistry

                needs_rollback = ProviderRegistry.get_quirks(
                    dialect_lower
                ).requires_rollback_after_introspection
            except Exception as exc:
                self.log.debug(f"Could not resolve quirks for rollback gating ({dialect}): {exc}")
            if needs_rollback:
                try:
                    # Rollback any pending transactions via provider
                    if hasattr(self.provider, "rollback_transaction"):
                        self.provider.rollback_transaction()
                        self.log.debug(
                            f"Rolled back transaction after snapshot introspection ({dialect})"
                        )
                    # Also try direct connection rollback as fallback
                    elif hasattr(self.provider, "connection") and self.provider.connection:
                        connection = self.provider.connection
                        if hasattr(connection, "getAutoCommit"):
                            if not connection.getAutoCommit():
                                try:
                                    connection.rollback()
                                    self.log.debug(
                                        f"Rolled back transaction after snapshot introspection ({dialect})"
                                    )
                                except Exception:
                                    # Intentional: rollback on a dead connection is non-fatal
                                    pass
                except Exception as e:
                    # Non-fatal - log but don't fail
                    self.log.debug(
                        f"Could not rollback transaction after snapshot introspection: {e}"
                    )

    def _collect_migration_metadata(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        try:
            applied = self.history_manager.get_applied_migrations()
        except Exception as exc:
            self.log.debug(f"Could not collect applied migrations for snapshot: {exc}")
            return metadata

        versioned = [m for m in applied if is_versioned(getattr(m, "type", None))]
        versioned.sort(
            key=lambda m: (
                m.installed_rank if getattr(m, "installed_rank", None) is not None else -1,
                m.version or "",
            )
        )
        last_version = versioned[-1].version if versioned else None
        last_rank = versioned[-1].installed_rank if versioned else None

        applied_records = []
        for m in versioned:
            success = self._migration_success_value(m)
            if success is False:
                continue
            installed_on = self._serialize_metadata_datetime(getattr(m, "installed_on", None))
            applied_records.append(
                {
                    "script": getattr(m, "script_name", None),
                    "version": getattr(m, "version", None),
                    "description": getattr(m, "description", None),
                    "type": migration_type_name(getattr(m, "type", None)),
                    "checksum": getattr(m, "checksum", None),
                    "success": True if success is None else success,
                    "installed_rank": getattr(m, "installed_rank", None),
                    "installed_on": installed_on,
                    "installed_by": getattr(m, "installed_by", None),
                }
            )

        repeatables = []
        for m in applied:
            if getattr(m, "type", None) != MigrationType.REPEATABLE:
                continue
            if self._migration_success_value(m) is False:
                # Skip failed repeatables: including them would make a later plan
                # treat the checksum as already applied and never retry them.
                continue
            installed_on = self._serialize_metadata_datetime(getattr(m, "installed_on", None))
            repeatables.append(
                {
                    "script": m.script_name,
                    "checksum": m.checksum,
                    "installed_rank": m.installed_rank,
                    "installed_on": installed_on,
                }
            )

        metadata.update(
            {
                "last_version": last_version,
                "installed_rank": last_rank,
                "applied_versions": [
                    record["version"] for record in applied_records if record.get("version")
                ],
                "applied": applied_records,
                "repeatables": repeatables,
            }
        )
        return metadata

    @staticmethod
    def _serialize_metadata_datetime(value: Any) -> Any:
        """Serialize datetime values for snapshot metadata."""
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _migration_success_value(migration: Any) -> Optional[bool]:
        """Normalize an optional migration success marker."""
        from core.migration.version_utils import is_migration_failure, is_migration_success

        value = getattr(migration, "success", None)
        applied_record = getattr(migration, "applied_migration", None)
        if value is None and applied_record is not None:
            value = getattr(applied_record, "success", None)
        if value is None:
            return None
        if is_migration_success(value):
            return True
        if is_migration_failure(value):
            return False
        return None

    def _validate_snapshot_accuracy(
        self,
        payload: SchemaSnapshotPayload,
        introspector: Any,
        schema_name: str,
        live_tables: List[Any],
        live_views: List[Any],
        live_indexes: List[Any],
    ) -> None:
        """Compatibility no-op retained for older internal callers."""
        return None

    def _filter_tables(
        self, tables: List[Any], default_schema: Optional[str]
    ) -> tuple[List[Any], Set[str]]:
        internal_names = {
            self._normalize_name(self.history_manager.history_table),
            self._normalize_name(getattr(self.provider, "MIGRATION_LOCK_TABLE", "")),
            self._normalize_name(getattr(self.config, "snapshot_table", "")),
        }
        internal_keys = {
            self._make_table_key(default_schema, self.history_manager.history_table),
            self._make_table_key(
                default_schema, getattr(self.provider, "MIGRATION_LOCK_TABLE", "")
            ),
            self._make_table_key(default_schema, getattr(self.config, "snapshot_table", "")),
        }
        table_keys = set()
        filtered: List[Any] = []
        for table in tables or []:
            table_schema = getattr(table, "schema", None) or default_schema
            table_name = getattr(table, "name", None)
            name_norm = self._normalize_name(table_name)
            key = self._make_table_key(table_schema, table_name)
            if name_norm in internal_names or key in internal_keys:
                continue
            filtered.append(table)
            table_keys.add(key)
        return filtered, table_keys

    def _filter_views(self, views: List[Any], default_schema: Optional[str]) -> List[Any]:
        internal = {
            self._normalize_name(getattr(self.config, "snapshot_table", "")),
            self._normalize_name(self.history_manager.history_table),
        }
        filtered: List[Any] = []
        for view in views or []:
            name = getattr(view, "name", None)
            if self._normalize_name(name) in internal:
                continue
            filtered.append(view)
        return filtered

    def _filter_indexes(
        self, indexes: List[Any], allowed_table_keys: Set[str], tables: List[Any]
    ) -> List[Any]:
        constraint_names: set[str] = set()
        for table in tables or []:
            for constraint in getattr(table, "constraints", []) or []:
                constraint_type = getattr(constraint, "constraint_type", None)
                if constraint_type in (ConstraintType.PRIMARY_KEY, ConstraintType.UNIQUE):
                    name = self._normalize_name(getattr(constraint, "name", None))
                    if name:
                        constraint_names.add(name)

        filtered: List[Any] = []
        for index in indexes or []:
            table_schema = getattr(index, "schema", None) or getattr(index, "table_schema", None)
            table_name = getattr(index, "table_name", None)
            if self._make_table_key(table_schema, table_name) not in allowed_table_keys:
                continue
            index_name = self._normalize_name(getattr(index, "name", None))
            if index_name in constraint_names:
                continue
            filtered.append(index)
        return filtered

    def _filter_triggers(self, triggers: List[Any], allowed_table_keys: Set[str]) -> List[Any]:
        filtered: List[Any] = []
        for trigger in triggers or []:
            table_schema = getattr(trigger, "schema", None) or getattr(
                trigger, "table_schema", None
            )
            table_name = getattr(trigger, "table_name", None)
            if self._make_table_key(table_schema, table_name) not in allowed_table_keys:
                continue
            filtered.append(trigger)
        return filtered

    def _filter_user_defined_types(
        self, udts: List[Any], tables: List[Any], views: List[Any]
    ) -> List[Any]:
        table_names = {self._normalize_name(getattr(table, "name", None)) for table in tables or []}
        view_names = {self._normalize_name(getattr(view, "name", None)) for view in views or []}
        internal_names = {
            self._normalize_name(self.history_manager.history_table),
            self._normalize_name(getattr(self.config, "snapshot_table", "")),
        }
        reserved_names = table_names | view_names | internal_names

        filtered: List[Any] = []
        for udt in udts or []:
            name = self._normalize_name(getattr(udt, "name", None))
            if name in reserved_names:
                continue
            filtered.append(udt)
        return filtered

    def _filter_sequences(self, sequences: List[Any], tables: List[Any]) -> List[Any]:
        table_names = {self._normalize_name(getattr(table, "name", None)) for table in tables or []}
        internal_prefixes = [
            self._normalize_name(self.history_manager.history_table),
            self._normalize_name(getattr(self.config, "snapshot_table", "")),
        ]

        filtered: List[Any] = []
        for seq in sequences or []:
            name = self._normalize_name(getattr(seq, "name", None))
            if not name:
                continue
            if any(prefix and name.startswith(prefix) for prefix in internal_prefixes):
                continue
            if name.startswith("iseq$$_"):
                # Oracle system-generated identity sequence
                continue
            if name.endswith("_id_seq"):
                base_name = name[: -len("_id_seq")]
                if base_name in table_names:
                    continue
            filtered.append(seq)
        return filtered

    def _is_connection_error(self, error: Exception) -> bool:
        """Check if an exception represents a connection-level failure."""
        if hasattr(self.provider, "error_handler") and self.provider.error_handler is not None:
            handler = self.provider.error_handler
            category = handler.categorize_error(error)
            return category in (
                handler.ErrorCategory.NETWORK,
                handler.ErrorCategory.TIMEOUT,
                handler.ErrorCategory.AUTHENTICATION,
            )
        # Fallback patterns if error handler is unavailable
        error_str = str(error).lower()
        return any(
            ind in error_str
            for ind in [
                "ora-17800",
                "ora-17002",
                "ora-03113",
                "connection reset",
                "broken pipe",
                "socket",
                "connection closed",
                "sqlstate=08",
                "errorcode=-4499",
            ]
        )

    def _safe_introspect(self, func: Any, *args: Any) -> Any:
        try:
            self.log.debug(
                f"_safe_introspect calling {func.__name__ if hasattr(func, '__name__') else func} with args: {args}"
            )
            result = func(*args) if args else func()
            self.log.debug(f"_safe_introspect result: {len(result) if result else 0} items")
            return result or []
        except AttributeError as e:
            self.log.debug(f"_safe_introspect AttributeError: {e}")
            # Dialect does not support this object type
            return []
        except Exception as exc:
            if self._is_connection_error(exc):
                raise  # Propagate connection errors to the user
            self.log.debug(f"_safe_introspect Exception: {exc}")
            self.log.debug(f"Snapshot introspection call failed: {exc}")
            return []

    def _try_bulk_indexes(
        self, introspector: Any, schema_name: Optional[str], tables: Any
    ) -> List[Any]:
        """Try bulk get_all_indexes; fall back to per-table loop on failure."""
        func = getattr(introspector, "get_all_indexes", None)
        if callable(func):
            try:
                result = func(schema_name)
                if isinstance(result, list):
                    self.log.debug(f"Bulk get_all_indexes returned {len(result)} items")
                    return result
                else:
                    self.log.debug(
                        f"get_all_indexes returned non-list ({type(result).__name__}), falling back to per-table loop"
                    )
            except Exception as exc:
                if self._is_connection_error(exc):
                    raise
                self.log.debug(f"get_all_indexes failed ({exc}), falling back to per-table loop")

        # Fallback: per-table N+1 loop
        indexes_raw: List[Any] = []
        for table in tables:
            table_name = getattr(table, "name", None)
            if not table_name:
                continue
            indexes_raw.extend(
                self._safe_introspect(introspector.get_indexes, schema_name, table_name)
            )
        return indexes_raw

    def _call_optional(self, obj: Any, attr: str, *args: Any) -> Any:
        func = getattr(obj, attr, None)
        if not callable(func):
            self.log.debug(f"Method {attr} not callable or not found")
            return []
        self.log.debug(f"Calling {attr} with args: {args}")
        result = self._safe_introspect(func, *args)
        self.log.debug(f"Method {attr} returned {len(result) if result else 0} items")
        return result

    @staticmethod
    def _normalize_name(value: Optional[str]) -> str:
        # Convert to Python string to handle driver-returned objects
        text = str(value or "").strip()
        if len(text) >= 2 and (
            (text.startswith('"') and text.endswith('"'))
            or (text.startswith("'") and text.endswith("'"))
            or (text.startswith("`") and text.endswith("`"))
        ):
            text = text[1:-1]
        if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return text.lower()

    def _make_table_key(self, schema: Optional[str], name: Optional[str]) -> str:
        schema_part = self._normalize_name(schema or getattr(self.config.database, "schema", ""))
        name_part = self._normalize_name(name)
        return f"{schema_part}.{name_part}"

    def _deep_update(self, target: Dict[str, Any], updates: Dict[str, Any]) -> None:
        for key, value in updates.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def _ensure_clean_connection_state(self) -> None:
        """Ensure connection is in a clean state before snapshot operations.

        This is critical for DB2 which holds row-level locks until transactions
        are committed or rolled back. After migration, there may be uncommitted
        transactions or locks that prevent introspection queries from running.

        This method:
        1. Ensures the connection is valid and open
        2. Rolls back any pending transaction to release locks
        3. Allows introspection to manage its own connection state
        """
        try:
            # First, ensure we have a valid connection
            self._ensure_valid_connection()

            # Use provider's transaction management if available
            if hasattr(self.provider, "rollback_transaction"):
                try:
                    self.provider.rollback_transaction()
                    self.log.debug("Rolled back existing transaction before snapshot creation")
                except Exception as e:
                    self.log.debug(f"Could not rollback transaction via provider: {e}")

            # Also try direct connection access as fallback (for DB2)
            connection = None
            if hasattr(self.provider, "connection") and self.provider.connection:
                connection = self.provider.connection
            elif hasattr(self.provider, "query_executor") and hasattr(
                self.provider.query_executor, "connection"
            ):
                connection = self.provider.query_executor.connection

            if connection:
                # Check if connection is still valid
                try:
                    if connection.isClosed():
                        self.log.debug("Connection is closed, attempting to reconnect")
                        # Try to get a fresh connection
                        self._ensure_valid_connection()
                        return
                except Exception as e:
                    self.log.debug(f"Could not check connection state: {e}")
                    # Try to get a fresh connection
                    self._ensure_valid_connection()
                    return

                # Check if there's an uncommitted transaction and rollback
                try:
                    if hasattr(connection, "getAutoCommit") and not connection.getAutoCommit():
                        # Rollback any existing uncommitted transaction
                        # This releases any row-level locks that might block introspection
                        connection.rollback()
                        self.log.debug(
                            "Rolled back existing transaction via direct connection access"
                        )
                except Exception as e:
                    self.log.debug(f"Could not check/rollback transaction: {e}")
        except Exception as e:
            # Non-fatal - some providers may not expose connection directly
            self.log.debug(f"Could not ensure clean connection state: {e}")

    def _ensure_valid_connection(self) -> None:
        """Ensure the provider has a valid, open database connection."""
        try:
            # Try to ensure connection via provider hook if available.
            if ensure_provider_connection(self.provider):
                self.log.debug("Ensured valid connection via provider")
            elif hasattr(self.provider, "query_executor") and hasattr(
                self.provider.query_executor, "_ensure_connection"
            ):
                self.provider.query_executor._ensure_connection()
                self.log.debug("Ensured valid connection via query executor")
        except Exception as e:
            self.log.debug(f"Could not ensure valid connection: {e}")

    def _get_snapshot_connection(self) -> "SnapshotConnectionContext":
        """Get a connection context manager for the entire snapshot process."""
        return SnapshotConnectionContext(self.provider, self.log)
