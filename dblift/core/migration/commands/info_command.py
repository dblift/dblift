"""
Info command implementation.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, cast

if TYPE_CHECKING:
    pass
from dblift.core.logger.results import InfoResult, MigrationInfo
from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, MigrationType
from dblift.core.migration.state.migration_state import MigrationState
from dblift.core.utils.url_masking import mask_database_url
from dblift.db.provider_capabilities import get_provider_display_url, get_provider_driver_display

from .base_command import BaseCommand


def normalize_migration_info_status(ui_state: Optional[str]) -> str:
    """Map UI migration state to canonical MigrationInfo.status (uppercase).

    UI may emit title case (e.g. "Success", "Baseline") or uppercase.
    """
    status_upper = ui_state.upper() if ui_state else "UNKNOWN"
    if status_upper in ("SUCCESS", "APPLIED"):
        return "SUCCESS"
    if status_upper == "FAILED":
        return "FAILED"
    if status_upper == "PENDING":
        return "PENDING"
    if status_upper == "UNDONE":
        return "UNDONE"
    if status_upper == "BASELINE":
        return "BASELINE"
    return status_upper


def _migration_type_name(migration_type: object) -> str:
    if isinstance(migration_type, MigrationType):
        return migration_type.value
    return str(migration_type or "").upper()


def _normalize_filter(value: Optional[str]) -> Optional[List[str]]:
    """Split a comma-separated CLI filter value into a clean list."""
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


class InfoCommand(BaseCommand):
    """Handles the 'info' command execution."""

    def execute(
        self,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        display_human: bool = True,
    ) -> InfoResult:
        """Get information about migrations using migration rules for state determination."""
        result = InfoResult()
        result.target_schema = self.config.database.schema
        if target_version is None:
            target_version = getattr(self.config, "target_version", None)

        normalized_tags = _normalize_filter(tags)
        normalized_exclude_tags = _normalize_filter(exclude_tags)
        normalized_versions = _normalize_filter(versions)
        normalized_exclude_versions = _normalize_filter(exclude_versions)

        def _body() -> None:
            # Use MigrationStateManager to get centralized migration state
            try:
                migration_state = self.state_manager.build_state(
                    scripts_dir,
                    recursive=recursive,
                    additional_dirs=additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                    target_version=target_version,
                )
            except Exception as e:
                # If build_state fails, create empty state
                self.log.debug(f"Could not build migration state: {e}")
                migration_state = MigrationState()

            # Warn if duplicate version numbers exist across filesystem scripts.
            # Synthetic history rows, such as baseline command markers, are not
            # resolved script files and must not participate in this check.
            try:
                all_script_objects = self.script_manager.get_migration_scripts(
                    scripts_dir,
                    recursive=recursive,
                    additional_dirs=additional_dirs or [],
                    dir_recursive_map=dir_recursive_map,
                )
            except Exception as e:
                self.log.debug(f"Could not scan scripts for duplicate version warning: {e}")
                all_script_objects = []

            _seen_versions: Dict[str, str] = {}
            for _script in all_script_objects:
                if (
                    _migration_type_name(getattr(_script, "type", None))
                    not in VERSIONED_SCRIPT_TYPES
                ):
                    continue
                _ver = getattr(_script, "version", None)
                _name = getattr(_script, "script_name", None) or getattr(_script, "script", None)
                if _ver is None or not _name:
                    continue
                if _ver in _seen_versions:
                    self.log.warning(
                        f"Duplicate version {_ver}: '{_seen_versions[_ver]}' and '{_name}' "
                        f"— running migrate will fail. Remove one of these scripts."
                    )
                else:
                    _seen_versions[_ver] = _name

            # Get ALL migrations from history (not filtered) to show complete sequential history
            # The state's applied_objects is filtered to exclude undone migrations,
            # but for info command we need to show ALL migrations in chronological order
            all_applied_migrations = migration_state.all_applied_objects

            # Populate current schema version from applied (non-undone) migrations
            applied_migrations = migration_state.applied_objects
            current_version = self.state_manager.get_current_version(applied_migrations)
            if current_version:
                result.current_schema_version = current_version

            # Use the migration UI to display the information properly
            # Pass the full state so UI can access undone_versions and other state info
            if display_human:
                self.migration_ui.display_migration_info(
                    migration_state=migration_state,
                    all_applied_migrations=all_applied_migrations,
                    scripts_dir=scripts_dir,
                    target_version=None,
                    tags=normalized_tags,
                    exclude_tags=normalized_exclude_tags,
                    versions=normalized_versions,
                    exclude_versions=normalized_exclude_versions,
                )

            # Use the same data processing pipeline as the console output
            # Get structured migration data using the UI data collector
            migrations_data = self.migration_ui.get_migration_data(
                migration_state=migration_state,
                all_applied_migrations=all_applied_migrations,
                scripts_dir=scripts_dir,
                target_version=None,
                tags=normalized_tags,
                exclude_tags=normalized_exclude_tags,
                versions=normalized_versions,
                exclude_versions=normalized_exclude_versions,
            )

            # Convert the UI data to MigrationInfo objects for the HTML formatter
            all_migration_infos = []
            # Handle case where migrations_data might be a Mock or not iterable
            if not hasattr(migrations_data, "__iter__"):
                migrations_data = []
            else:
                try:
                    migrations_data = list(migrations_data)
                except (TypeError, AttributeError):
                    migrations_data = []

            for migration_data in migrations_data:
                # Map UI data format to MigrationInfo format
                status = normalize_migration_info_status(migration_data.get("state", "UNKNOWN"))

                info = MigrationInfo(
                    script=migration_data.get("script", ""),
                    version=migration_data.get("version", ""),
                    description=migration_data.get("description", ""),
                    type=migration_data.get("type", "UNKNOWN"),
                    status=status,
                    checksum=migration_data.get("checksum"),
                    installed_on=migration_data.get("installed_on"),
                    execution_time=migration_data.get("execution_time") or 0,
                    installed_by=migration_data.get("installed_by"),
                )
                all_migration_infos.append(info)

            result.migrations = all_migration_infos

            # Add database connection information to the result
            # (This is already done by _populate_database_info, but keeping for compatibility)
            try:
                # Get database version
                if hasattr(self.provider, "get_database_version"):
                    result.db_version = self.provider.get_database_version()

                # Get provider display URL (masked for security)
                display_url = get_provider_display_url(self.provider, self.config)
                if display_url:
                    result.database_url_masked = mask_database_url(display_url)
                    self.log.debug(f"Database URL: {result.database_url_masked}")

                # Get driver info from plugin-declared quirks.
                try:
                    result.native_driver = get_provider_driver_display(self.provider, self.config)
                except Exception as e:
                    self.log.debug(f"Could not determine native driver info: {e}")
                    result.native_driver = None  # Don't set "Unknown Native Driver"

            except Exception as e:
                self.log.debug(f"Could not retrieve database connection info: {e}")

        # Canonical lifecycle: preflight/header/schema-version/body/footer.
        return cast(
            InfoResult,
            self._run_command_lifecycle(
                "info",
                result,
                _body,
                preflight=lambda: self._run_preflight(result, ensure_history=True),
                before_body=self._log_current_schema_version,
                error_message_prefix="Info operation failed",
            ),
        )
