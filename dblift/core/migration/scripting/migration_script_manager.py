"""Migration script manager — discovers, parses, and orders migration scripts on disk."""

import os
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, Optional, Set, Tuple

from dblift.core.logger import Log
from dblift.core.migration._type_match import is_migration_type
from dblift.core.migration.encoding import MigrationEncodingError, read_migration_text
from dblift.core.migration.migration import (
    Migration,
    MigrationResource,
    MigrationType,
    ResolvedMigration,
    calculate_migration_script_checksum,
    normalize_migration_checksum,
)
from dblift.core.migration.scripting.filename_parser import (
    _CALLBACK_PREFIXES,
    _callback_prefix_missing_separator,
    _looks_like_migration,
    _matches_callback_event,
    parse_migration_filename,
)
from dblift.core.migration.version_utils import compare_versions as _compare_versions_shared
from dblift.core.migration.version_utils import is_migration_success


class _DiscoveredScript(NamedTuple):
    """File and filename metadata retained only for the current catalog load."""

    path: Path
    resolved_path: Path
    filename_metadata: Tuple[MigrationType, Optional[str], str, List[str]]


def _successful_non_delete_records(migrations: Iterable[Migration]) -> Iterator[Migration]:
    """Yield successful non-audit rows in the supplied history order."""
    for migration in migrations:
        migration_type = getattr(migration, "type", None)
        if (
            not is_migration_type(migration_type, "DELETE")
            and not is_migration_type(migration_type, "UNDO_SQL")
            and is_migration_success(getattr(migration, "success", False))
        ):
            yield migration


def _last_successful_non_delete_record(
    applied_migrations: List[Migration], script_name: str
) -> Optional[Migration]:
    """Find the last successful non-audit row in the supplied history order."""
    return next(
        (
            migration
            for migration in _successful_non_delete_records(reversed(applied_migrations))
            if getattr(migration, "script_name", None) == script_name
        ),
        None,
    )


def _current_script_checksum(
    manager: "MigrationScriptManager",
    script_path: Optional[Path],
    script: Optional[Migration] = None,
) -> Optional[int]:
    """Reuse resolved content's checksum, or read a legacy/standalone script once."""
    if script is not None and isinstance(getattr(script, "content", None), str):
        checksum = normalize_migration_checksum(getattr(script, "checksum", None))
        if checksum is not None:
            return checksum
    if script_path and script_path.exists():
        raw_text = read_migration_text(
            script_path,
            configured_encoding=manager.script_encoding,
            detect_encoding=manager.detect_encoding,
        )
        checksum = normalize_migration_checksum(manager.calculate_checksum(raw_text))
        if checksum is None:
            checksum = calculate_migration_script_checksum(raw_text)
        return checksum
    return None


class MigrationScriptManager:
    """Resolves on-disk migration scripts, computes checksums, and orders them by version."""

    def __init__(self, logger: Log, script_encoding: str = "utf-8", detect_encoding: bool = False):
        """Configure script encoding and (optional) auto-detection used when reading migration files."""
        self.logger = logger
        self.script_encoding = script_encoding
        self.detect_encoding = detect_encoding
        # Filenames already reported by _report_callback_naming_violation.
        self._reported_naming_violations: Set[str] = set()

    def _get_migration_type_string(self, migration_type: Any) -> str:
        """Safely get migration type as string, handling both enum and string types.

        Delegates to the shared helper in ``dblift.core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from dblift.core.migration._type_match import migration_type_name

        return migration_type_name(migration_type)

    def _is_migration_type_equal(self, migration_type: Any, target_type: str) -> bool:
        """Check if migration type matches target type, handling both enum and string types.

        Delegates to the shared helper in ``dblift.core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from dblift.core.migration._type_match import is_migration_type

        return is_migration_type(migration_type, target_type)

    def calculate_checksum(self, content: str) -> int:
        """Calculate the Flyway-compatible CRC32 checksum for script content (see Migration)."""
        return calculate_migration_script_checksum(content)

    def parse_filename(self, filename: str) -> Tuple[MigrationType, Optional[str], str, List[str]]:
        """Parse Flyway-style filename (e.g., 'V1.0.0__create_table.sql', 'R__update_data.sql').

        Now also supports tags in the format V1.0.0__description[tag1,tag2].sql

        Supports multiple file formats: .sql, .py, .js, .cypher, .cql, .json, .yaml

        Returns:
            Tuple of (MigrationType, version, description, tags)
        """
        metadata = parse_migration_filename(filename)
        return metadata.migration_type, metadata.version, metadata.description, list(metadata.tags)

    def load_migration_script(
        self,
        script_path: Path,
        *,
        filename_metadata: Optional[Tuple[MigrationType, Optional[str], str, List[str]]] = None,
        require_versioned: bool = False,
    ) -> Migration:
        """Read one resource with configured encoding and construct a resolved migration."""
        from dblift.core.migration.formats import MigrationFormat

        if require_versioned and not script_path.exists():
            raise FileNotFoundError(f"Migration file not found: {script_path}")

        metadata = (
            filename_metadata
            if filename_metadata is not None
            else self.parse_filename(script_path.name)
        )
        if require_versioned and (metadata[0] != MigrationType.SQL or not metadata[1]):
            raise ValueError(
                f"File is not a versioned migration: {script_path.name}. "
                "Expected a versioned migration filename (V*__description.<ext>)."
            )
        content = read_migration_text(
            script_path,
            configured_encoding=self.script_encoding,
            detect_encoding=self.detect_encoding,
        )
        migration = Migration(
            script_name=script_path.name,
            content=content,
            logger=self.logger,
            script_encoding=self.script_encoding,
            detect_encoding=self.detect_encoding,
            _filename_metadata=metadata,
        )
        migration.path = script_path
        if migration.type == MigrationType.SQL and migration.format not in (
            MigrationFormat.SQL,
            MigrationFormat.UNKNOWN,
        ):
            migration.type = MigrationType.PYTHON
        return migration

    def find_undo_candidates(self, scripts_directory: Path, recursive: bool = True) -> List[Path]:
        """Discover the undo API's loose V* candidates in filesystem order."""
        from dblift.core.migration.formats import MigrationFormatDetector

        pattern = "**/V*" if recursive else "V*"
        return [
            path
            for path in scripts_directory.glob(pattern)
            if path.is_file() and MigrationFormatDetector.is_migration_file(path)
        ]

    def is_versioned_script_name(self, filename: str) -> bool:
        """True if *filename* is a Flyway versioned migration (V*__), any registered extension.

        Uses the canonical parser for every registered extension. Versions must
        start with a digit.
        """
        migration_type, version, _, _ = self.parse_filename(filename)
        return migration_type == MigrationType.SQL and bool(version)

    def compare_versions(self, version1: Optional[str], version2: Optional[str]) -> int:
        """Compare two version strings (e.g. '1.0.0' vs '1.0.1', '1_2_3' vs '1_2_4', '3.2A' vs '3.2B'). Handles None as empty string."""
        return _compare_versions_shared(version1, version2)

    @staticmethod
    def migration_directory_exists(path: Path) -> bool:
        """Report filesystem status for migration input collection."""
        return path.exists()

    def get_migration_scripts(
        self,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> List[Migration]:
        """Get all migration scripts from the directory and its subdirectories.

        Args:
            scripts_dir: The primary directory containing migration scripts
            recursive: Whether to search subdirectories recursively (default for all dirs)
            additional_dirs: Optional list of additional directories to search
            dir_recursive_map: Optional mapping of directory paths to their recursive settings

        Returns:
            List of Migration objects
        """
        migrations = self.load_migration_scripts(
            scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

        # Return all migrations with versioned migrations first
        all_migrations = []

        # Add versioned migrations first (already sorted by version in load_migration_scripts)
        all_migrations.extend(migrations[MigrationType.SQL])

        # Then add repeatable migrations
        all_migrations.extend(migrations[MigrationType.REPEATABLE])

        # Then add undo migrations
        all_migrations.extend(migrations[MigrationType.UNDO_SQL])

        # Then add baseline migrations
        all_migrations.extend(migrations[MigrationType.BASELINE])

        # Finally add callbacks (kept separate from baseline for semantic clarity)
        all_migrations.extend(migrations[MigrationType.CALLBACK])

        return all_migrations

    def get_migration_resources(
        self,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> List[MigrationResource]:
        """Return script resources without history/execution fields."""
        migrations = self.get_migration_scripts(
            scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )
        resources: List[MigrationResource] = []
        for migration in migrations:
            path = getattr(migration, "path", None)
            if path is None:
                continue
            resources.append(
                MigrationResource(
                    path=path,
                    script_name=migration.script_name,
                    content=migration.content,
                    encoding=getattr(migration, "script_encoding", self.script_encoding),
                )
            )
        return resources

    def get_resolved_migrations(
        self,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> List[ResolvedMigration]:
        """Return resolved script migrations as first-class metadata objects."""
        return [
            ResolvedMigration.from_migration(migration)
            for migration in self.get_migration_scripts(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
        ]

    def extract_version(self, script_name: str) -> Optional[str]:
        """Extract version from script name if present."""
        # Use the parse_filename method for consistency
        migration_type, version, _, _ = self.parse_filename(script_name)
        return version

    def extract_description(self, script_name: str) -> str:
        """Extract description from script name."""
        # Use the parse_filename method for consistency
        _, _, description, _ = self.parse_filename(script_name)
        return description

    def extract_tags(self, script_name: str) -> List[str]:
        """Extract tags from script name."""
        # Use the parse_filename method for consistency
        _, _, _, tags = self.parse_filename(script_name)
        return tags

    def has_script_changed(
        self,
        script_name: str,
        applied_migrations: Optional[List[Migration]] = None,
        script_path: Optional[Path] = None,
    ) -> bool:
        """Check if a script has changed by comparing its checksum with the stored one.

        Args:
            script_name: Name of the script
            applied_migrations: List of applied Migration objects from history manager (optional)
            script_path: Path to the script file (optional, if not provided will try to find it)

        Returns:
            bool: True if the script has changed or hasn't been applied yet, False otherwise
        """
        # If no applied migrations provided, we can't check if script has changed
        if not applied_migrations:
            self.logger.debug(
                f"No applied migrations provided, assuming script {script_name} has changed"
            )
            return True

        applied_script = _last_successful_non_delete_record(applied_migrations, script_name)

        # If script has never been successfully applied, consider it changed
        if not applied_script:
            self.logger.debug(f"Script {script_name} has not been applied yet")
            return True

        # Get applied checksum (normalize driver unsigned 32-bit vs signed Flyway CRC32)
        applied_checksum = normalize_migration_checksum(getattr(applied_script, "checksum", None))

        # Standalone callers always read the current file, without a resolved snapshot.
        current_checksum = _current_script_checksum(self, script_path)

        if applied_checksum is None:
            self.logger.debug(
                f"No stored checksum for {script_name}; cannot verify if script changed"
            )
            return True

        if current_checksum is None:
            self.logger.debug(
                f"Could not compute normalized filesystem checksum for {script_name}; "
                "treating as possibly changed"
            )
            return True

        # Compare only signed 32-bit ints — never str vs int (always "changed" in Python).
        is_changed: bool = current_checksum != applied_checksum
        if is_changed:
            self.logger.debug(
                f"Script {script_name} has changed. Database checksum: {applied_checksum}, Filesystem checksum: {current_checksum}"
            )
        else:
            self.logger.debug(f"Script {script_name} has not changed")

        return is_changed

    def get_all_scripts(
        self,
        migrations_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        _discovery_metadata: Optional[Dict[str, _DiscoveredScript]] = None,
    ) -> List[str]:
        """Return a list of all migration script filenames in the directory and its subdirectories.

        Args:
            migrations_dir: The base directory to search for migration scripts
            recursive: Whether to search subdirectories recursively (default for all dirs)
            additional_dirs: Optional list of additional directories to search
            dir_recursive_map: Optional mapping of directory paths to their recursive settings
                             (overrides the global recursive flag for specific directories)

        Returns:
            List of relative paths to migration scripts
        """
        scripts = []
        dirs_to_search = [migrations_dir]

        # Add additional directories if provided
        if additional_dirs:
            dirs_to_search.extend(additional_dirs)

        # Normalize and deduplicate directories to avoid processing the same directory twice
        # Use resolved paths to handle symlinks and relative paths correctly
        seen_dirs: Set[Path] = set()
        normalized_dirs = []
        # Resolve migrations_dir for comparison
        try:
            resolved_migrations_dir = migrations_dir.resolve()
        except (OSError, RuntimeError):
            resolved_migrations_dir = migrations_dir

        # Build a mapping of resolved paths to their recursive settings
        recursive_map: Dict[Path, bool] = {}
        if dir_recursive_map:
            for dir_path, rec_setting in dir_recursive_map.items():
                try:
                    resolved = dir_path.resolve()
                    recursive_map[resolved] = rec_setting
                except (OSError, RuntimeError):
                    recursive_map[dir_path] = rec_setting

        for dir_path in dirs_to_search:
            # Resolve the path to handle symlinks and relative paths
            try:
                resolved_dir = dir_path.resolve()
                if resolved_dir not in seen_dirs:
                    seen_dirs.add(resolved_dir)
                    normalized_dirs.append((dir_path, resolved_dir))
            except (OSError, RuntimeError):
                # If resolution fails, use the original path
                if dir_path not in seen_dirs:
                    seen_dirs.add(dir_path)
                    normalized_dirs.append((dir_path, dir_path))

        for dir_path, resolved_dir_path in normalized_dirs:
            # Validate the directory exists
            if not dir_path.exists() or not dir_path.is_dir():
                self.logger.debug(
                    f"Migration directory does not exist or is not a directory: {dir_path}"
                )
                continue

            if not os.access(dir_path, os.R_OK | os.X_OK):
                raise PermissionError(
                    f"Cannot read migrations directory: {dir_path} (permission denied)"
                )

            # Determine recursive setting for this directory
            # Check dir_recursive_map first, then fall back to global recursive flag
            dir_recursive = recursive_map.get(
                resolved_dir_path, recursive_map.get(dir_path, recursive)
            )

            # Choose the appropriate search method based on recursive flag
            # Support multiple migration formats
            from dblift.core.migration.formats import MigrationFormatDetector

            if dir_recursive:
                # Recursively find all migration files in the directory and subdirectories
                # Use glob to find files with any extension, then filter by supported formats
                all_files = dir_path.rglob("*")
            else:
                # Only search in the top-level directory
                all_files = dir_path.glob("*")

            # Filter to only supported migration file formats
            # File symlinks pass is_file(), so explicitly exclude them here.
            search_method = (
                f
                for f in all_files
                if f.is_file()
                and not f.is_symlink()
                and MigrationFormatDetector.is_migration_file(f)
            )

            for script_path in search_method:
                # Path traversal guard: ensure resolved path is within the configured dir
                try:
                    resolved_script_path = script_path.resolve()
                    resolved_script_path.relative_to(resolved_dir_path)
                except OSError as e:
                    self.logger.warning(
                        f"Security: skipping '{script_path}' — path inaccessible or "
                        f"invalid: {e}"
                    )
                    continue
                except ValueError:
                    self.logger.warning(
                        f"Security: skipping '{script_path}' — resolved path "
                        f"'{resolved_script_path}' is outside configured migrations "
                        f"directory '{dir_path}'"
                    )
                    continue
                filename_metadata = self.parse_filename(script_path.name)
                if filename_metadata[0] in (
                    MigrationType.SQL,
                    MigrationType.REPEATABLE,
                    MigrationType.UNDO_SQL,
                    MigrationType.CALLBACK,
                ):
                    # Store the script with its source directory information
                    # For additional directories, prefix with the directory name to track the source
                    # Compare resolved paths to handle different path representations
                    is_additional_dir = resolved_dir_path != resolved_migrations_dir

                    if is_additional_dir:
                        # Store as "dir_name/relative_path" (which may include
                        # subdirectory components) to track which directory it
                        # came from while preserving its location within that
                        # directory.
                        rel_path = script_path.relative_to(dir_path)
                        script_reference = f"{dir_path}/{rel_path.as_posix()}"
                    else:
                        # For the primary directory, use the relative path as-is
                        rel_path = script_path.relative_to(dir_path)
                        script_reference = str(rel_path)
                    scripts.append(script_reference)
                    if _discovery_metadata is not None:
                        _discovery_metadata[script_reference] = _DiscoveredScript(
                            script_path, resolved_script_path, filename_metadata
                        )
                else:
                    self._report_callback_naming_violation(script_path.name)

        return scripts

    def _report_callback_naming_violation(self, script_name: str) -> None:
        """Warn once when a rejected file was plainly meant to be a migration.

        A rejected file is simply absent from the run, so a near-miss reads as
        "nothing to apply" rather than as an error. Files that were obviously
        intended as migrations are therefore called out; anything else in the
        directory (``helpers.py``, ``notes.sql``) is somebody's supporting file
        and stays silent. Reported once per manager because
        ``get_callbacks_by_event`` re-scans the directory for each of the
        dozen-odd events a command dispatches.
        """
        if script_name in self._reported_naming_violations:
            return

        callback_prefix = _callback_prefix_missing_separator(script_name)
        if callback_prefix is not None:
            self._reported_naming_violations.add(script_name)
            self.logger.warning(
                f"Script '{script_name}' is named for the '{callback_prefix}' callback event "
                f"but does not follow the Dblift naming convention "
                f"'{callback_prefix}__<description>' — the '__' separator is missing. "
                f"It will be excluded from migration."
            )
            return

        if _looks_like_migration(script_name):
            self._reported_naming_violations.add(script_name)
            self.logger.warning(
                f"Script '{script_name}' starts with a migration prefix but does not follow "
                f"the Dblift naming convention. Expected V<version>__<description>, "
                f"U<version>__<description> or R__<description>, where <version> starts with "
                f"a digit (e.g. V1__init.sql, V2.1__add_index.sql) and '__' is a double "
                f"underscore. It will be excluded from migration."
            )

    def load_migration_scripts(
        self,
        scripts_directory: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> Dict[MigrationType, List[Migration]]:
        """Load all SQL migration scripts from the directory and its subdirectories.

        Args:
            scripts_directory: The primary directory containing migration scripts
            recursive: Whether to search subdirectories recursively (default for all dirs)
            additional_dirs: Optional list of additional directories to search
            dir_recursive_map: Optional mapping of directory paths to their recursive settings
                             (overrides the global recursive flag for specific directories)

        Returns:
            Dictionary mapping migration types to lists of Migration objects
        """
        migrations: Dict[MigrationType, List[Migration]] = {
            MigrationType.SQL: [],
            MigrationType.UNDO_SQL: [],
            MigrationType.REPEATABLE: [],
            MigrationType.BASELINE: [],
            MigrationType.CALLBACK: [],
        }

        # Retain guarded filesystem and parsed filename metadata for this load only.
        discovery_metadata: Dict[str, _DiscoveredScript] = {}
        script_paths = self.get_all_scripts(
            scripts_directory,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
            _discovery_metadata=discovery_metadata,
        )

        # First pass: collect all scripts
        callbacks = []
        invalid_files = []
        excluded_files = []
        # Track seen files by their resolved path to avoid processing duplicates
        seen_files: Set[Path] = set()

        for rel_script_path in script_paths:
            # Handle paths from additional directories - format is
            # "full_dir_path/relative_path", where relative_path may itself
            # contain subdirectory components.
            if additional_dirs and "/" in rel_script_path:
                # Try to match the directory path with one of the additional_dirs,
                # keeping whatever comes after it (including subdirectories) intact.
                matching_dir = None
                matching_rel_part = None
                for add_dir in additional_dirs:
                    add_dir_prefix = f"{add_dir}/"
                    if rel_script_path.startswith(add_dir_prefix):
                        matching_dir = add_dir
                        matching_rel_part = rel_script_path[len(add_dir_prefix) :]
                        break

                if matching_dir and matching_rel_part is not None:
                    script_path = matching_dir / matching_rel_part
                else:
                    # Fallback: try as path from scripts_directory
                    script_path = scripts_directory / rel_script_path
            else:
                # Primary directory - use as-is
                script_path = scripts_directory / rel_script_path

            discovered = discovery_metadata.get(rel_script_path)
            # Keep legacy reference routing when a primary subdirectory name also
            # prefixes an additional directory. Only reuse the path we guarded.
            try:
                if discovered is not None and script_path == discovered.path:
                    script_path = discovered.path
                    resolved_path = discovered.resolved_path
                else:
                    resolved_path = script_path.resolve()
                if resolved_path in seen_files:
                    # Skip this file as we've already processed it
                    self.logger.debug(
                        f"Skipping duplicate file {script_path} (already processed as {resolved_path})"
                    )
                    continue
                seen_files.add(resolved_path)
            except (OSError, RuntimeError):
                # If resolution fails, use the original path
                if script_path in seen_files:
                    self.logger.debug(f"Skipping duplicate file {script_path}")
                    continue
                seen_files.add(script_path)

            try:
                script_name = script_path.name
                parsed_metadata = discovered.filename_metadata if discovered is not None else None
                if parsed_metadata is None:
                    parsed_metadata = self.parse_filename(script_name)
                migration_type = parsed_metadata[0]
                # Exclude files that are classified as BASELINE but do not match the naming convention
                if migration_type == MigrationType.BASELINE and not any(
                    script_name.startswith(prefix) for prefix in _CALLBACK_PREFIXES
                ):
                    excluded_files.append(rel_script_path)
                    continue
                # Create Migration object with the logger and encoding
                migration = self.load_migration_script(
                    script_path, filename_metadata=parsed_metadata
                )
                if migration_type == MigrationType.CALLBACK:
                    callbacks.append(migration)
                else:
                    migrations[migration_type].append(migration)
            except MigrationEncodingError:
                # Deliberately not collected as an "invalid script". That branch
                # exists for files which are not migrations at all — a stray
                # README, a wrong filename — and downgrades them to a warning.
                # This file IS a migration; we simply cannot read it. Skipping it
                # let `migrate` report "No pending migrations found" and exit 0,
                # so a latin-1 script produced a green deploy that applied
                # nothing. Let it reach the command.
                raise
            except ValueError as e:
                invalid_files.append((rel_script_path, str(e)))
                continue

        # Sort callbacks alphabetically by their name
        callbacks.sort(key=lambda m: m.script_name)

        # Add callbacks to their own category (they will be executed but not recorded in history)
        migrations[MigrationType.CALLBACK].extend(callbacks)

        # Sort versioned migrations by semantic version (numeric components compared as integers)
        def _cmp_migration_sort(a: Migration, b: Migration) -> int:
            return self.compare_versions(a.version, b.version)

        migrations[MigrationType.SQL].sort(key=cmp_to_key(_cmp_migration_sort))
        migrations[MigrationType.REPEATABLE].sort(key=lambda m: m.script_name.lower())

        # Log any invalid files
        if invalid_files:
            for file_name, error in invalid_files:
                self.logger.warning(f"Invalid migration script {file_name}: {error}")

        # Log excluded files
        if excluded_files:
            self.logger.info(
                f"Found {len(excluded_files)} script(s) not following Dblift naming convention. These will be excluded from migration: {excluded_files}"
            )

        return migrations

    def is_valid_script_name(self, filename: str) -> bool:
        """Return True if the filename is a valid migration or callback script name, False otherwise."""
        migration_type, _, _, _ = self.parse_filename(filename)
        # Accept versioned, repeatable, undo, and callback scripts
        return migration_type in (
            MigrationType.SQL,
            MigrationType.REPEATABLE,
            MigrationType.UNDO_SQL,
            MigrationType.CALLBACK,
        )

    def get_callbacks_by_event(
        self,
        scripts_dir: Path,
        event_prefix: str,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        callback_catalog: Optional[List[Migration]] = None,
    ) -> List[Migration]:
        """Get callbacks for a specific event (e.g., 'beforeMigrate', 'afterMigrateError').

        Args:
            scripts_dir: Directory containing migration scripts
            event_prefix: Callback event prefix to filter by (case-insensitive)
            recursive: Whether to search subdirectories recursively
            additional_dirs: Optional list of additional directories to search
            dir_recursive_map: Optional mapping of directories to recursive settings
            callback_catalog: Optional command-scoped callback list to filter

        Returns:
            List of Migration objects for the specified callback event, sorted alphabetically
        """
        if callback_catalog is None:
            migrations = self.load_migration_scripts(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
            callbacks = migrations[MigrationType.CALLBACK]
        else:
            callbacks = callback_catalog

        # Filter callbacks by event prefix (case-insensitive, delimiter-aware matching)
        filtered_callbacks: List[Migration] = []
        for cb in callbacks:
            base_name = Path(cb.script_name).name
            if _matches_callback_event(base_name, event_prefix):
                filtered_callbacks.append(cb)

        # Sort alphabetically (case-insensitive) to ensure consistent execution order
        filtered_callbacks.sort(key=lambda m: m.script_name.lower())

        return filtered_callbacks
