"""Migration script manager — discovers, parses, and orders migration scripts on disk."""

import os
import re
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dblift.core.logger import Log
from dblift.core.migration.encoding import read_migration_text
from dblift.core.migration.migration import (
    _CALLBACK_PREFIXES,
    Migration,
    MigrationResource,
    MigrationType,
    ResolvedMigration,
    _callback_event_prefix,
    _callback_prefix_missing_separator,
    calculate_migration_script_checksum,
    normalize_migration_checksum,
    strip_migration_tags,
)
from dblift.core.migration.version_utils import compare_versions as _compare_versions_shared
from dblift.core.migration.version_utils import is_migration_success

# A version must start with a digit. Later segments may mix letters and
# digits (``V3.2A``, ``V1.2.3RC1``) — dblift is deliberately looser than
# Flyway there, which stores versions as integers and rejects any
# non-numeric token. The leading digit is what makes the grammar decidable:
# without it ``VA__create.sql`` (version "A") and ``Users__seed.sql``
# (version "sers") are the same shape, and there is no rule that keeps the
# second from being loaded as a migration. ``Migration._determine_type``
# applies the same rule — keep the two in step.
_VERSION_BODY = r"\d[A-Za-z0-9]*(?:[._][A-Za-z0-9]+)*"


def _versioned_pattern(prefix: str, extension_escaped: str) -> str:
    """Build the ``<prefix>{version}__{description}<ext>`` filename pattern."""
    return rf"^{prefix}({_VERSION_BODY})__(.+){extension_escaped}$"


def _normalize_version(version_str: str) -> str:
    """Return the version with ``_`` separators rendered as ``.``.

    ``V1_2_3`` and ``V1.2.3`` name the same version, so they must not produce
    two different history rows.

    Applied to all-digit versions only, matching long-standing behaviour. A
    version carrying letters is returned verbatim: rewriting ``1_2A`` to
    ``1.2A`` would not match the ``1_2A`` already written to existing history
    rows, and the raw-string set lookups against ``undone_versions`` in
    ``MigrationStateManager`` compare versions as text, not through the
    comparator.
    """
    if version_str.replace(".", "").replace("_", "").isdigit():
        return version_str.replace("_", ".")
    return version_str


# A near-miss is a file that visibly reached for the convention and missed:
# a prefix letter followed by a version-ish character (``V2.1_create.sql``,
# ``R_repeat.sql``), or a prefix plus a one-letter version and the separator
# (``VA__create.sql``). Both halves are deliberately tight, because this fires
# on every single run:
#
#   * the prefix letter alone is far too weak — ``backup_old.sql``,
#     ``routines.sql`` and ``users.sql`` all start with one;
#   * allowing any run of letters before ``__`` is also too weak, because
#     ordinary words then qualify: ``util__helpers.py``,
#     ``report__daily.sql``, ``views__all.sql``. Capping it at a single
#     letter keeps ``VA``/``UB``-style attempts and lets words through.
#
# Baseline (``B``) is deliberately absent: a well-formed ``B1__x.sql`` is
# excluded by design, not by malformation, so warning about it would be wrong.
_NEAR_MISS_RE = re.compile(r"^[VUR](?:[0-9_]|[A-Za-z]?[0-9.]*__)", re.IGNORECASE)


def _looks_like_migration(script_name: str) -> bool:
    """True if *script_name* looks like a failed attempt at the convention."""
    return _NEAR_MISS_RE.match(script_name) is not None


def _matches_callback_event(base_name: str, event_prefix: str) -> bool:
    """Return True if ``base_name`` is a callback file for ``event_prefix``.

    Delegates the boundary rule to :func:`_callback_event_prefix`, so a file
    resolves to exactly one event and never also to a shorter prefix of it.
    Both arguments are compared case-insensitively.
    """
    matched = _callback_event_prefix(base_name)
    return matched is not None and matched.lower() == event_prefix.lower()


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
        # Extract tags if present - they can be in any valid filename.
        # Shared with the callback event helpers so classification and event
        # matching normalize a name identically; see strip_migration_tags.
        filename_without_tags, tags = strip_migration_tags(filename)

        # MULTI-FORMAT SUPPORT: Get the file extension to support multiple formats
        from pathlib import Path

        from dblift.core.migration.formats import MigrationFormatDetector

        file_path = Path(filename_without_tags)
        file_extension = file_path.suffix.lower()

        # Check if this is a valid migration file extension
        if not MigrationFormatDetector.is_migration_file(file_path):
            # Not a recognized migration format - return UNKNOWN
            description = filename_without_tags
            return MigrationType.UNKNOWN, None, description, tags

        # Escape the extension for use in regex patterns
        extension_escaped = re.escape(file_extension)

        # Check for callback scripts first (before the generic baseline catch-all).
        # Case-insensitive, and the "__" separator is mandatory: a name without it
        # is not a callback and falls through to the UNKNOWN catch-all below.
        if _callback_event_prefix(filename_without_tags) is not None:
            description = filename_without_tags.replace(file_extension, "")
            return MigrationType.CALLBACK, None, description, tags

        # Versioned migration: V{version}__{description}[tag1,tag2].<extension>
        versioned_match = re.match(
            _versioned_pattern("V", extension_escaped), filename_without_tags
        )
        if versioned_match:
            return (
                MigrationType.SQL,
                _normalize_version(versioned_match.group(1)),
                versioned_match.group(2),
                tags,
            )

        # Undo migration: U{version}__{description}[tag1,tag2].<extension>
        undo_match = re.match(_versioned_pattern("U", extension_escaped), filename_without_tags)
        if undo_match:
            return (
                MigrationType.UNDO_SQL,
                _normalize_version(undo_match.group(1)),
                undo_match.group(2),
                tags,
            )

        # Repeatable migration: R__{description}[tag1,tag2].<extension>
        repeatable_pattern = rf"^R__(.+){extension_escaped}$"
        repeatable_match = re.match(repeatable_pattern, filename_without_tags)
        if repeatable_match:
            return MigrationType.REPEATABLE, None, repeatable_match.group(1), tags

        # Handle malformed versioned migration: V__.<extension> (no version, no description)
        malformed_versioned = f"V__{file_extension}"
        if filename_without_tags == malformed_versioned or filename_without_tags == "V__.sql":
            return MigrationType.SQL, None, "", tags

        # Any other file is unrecognized/invalid (baselines don't exist as script files)
        # For malformed script names, return the filename for debugging/logging purposes
        description = filename_without_tags.replace(file_extension, "").replace(".sql", "")
        return MigrationType.UNKNOWN, None, description, tags

    def is_versioned_script_name(self, filename: str) -> bool:
        """True if *filename* is a Flyway versioned migration (V*__), any registered extension.

        Uses :meth:`parse_filename` (canonical), not :meth:`Migration._determine_type`,
        so non-.sql extensions match consistently. The two agree on the version
        grammar itself — both require a leading digit.
        """
        migration_type, version, _, _ = self.parse_filename(filename)
        return migration_type == MigrationType.SQL and bool(version)

    def compare_versions(self, version1: Optional[str], version2: Optional[str]) -> int:
        """Compare two version strings (e.g. '1.0.0' vs '1.0.1', '1_2_3' vs '1_2_4', '3.2A' vs '3.2B'). Handles None as empty string."""
        return _compare_versions_shared(version1, version2)

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
        def _cmp_migration(a: Migration, b: Migration) -> int:
            return self.compare_versions(a.version, b.version)

        all_migrations.extend(
            sorted(
                migrations[MigrationType.SQL],
                key=cmp_to_key(_cmp_migration),
            )
        )

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

        # Find the last applied version of this script (excluding DELETE entries)
        applied_script = None
        for migration in reversed(applied_migrations):
            # All applied_migrations should now be Migration objects
            migration_script_name = getattr(migration, "script_name", None)
            migration_success = getattr(migration, "success", False)
            migration_type = getattr(migration, "type", None)

            # Skip audit rows when looking for the original applied migration.
            is_audit_type = self._is_migration_type_equal(
                migration_type, "DELETE"
            ) or self._is_migration_type_equal(migration_type, "UNDO_SQL")
            if (
                migration_script_name == script_name
                and is_migration_success(migration_success)
                and not is_audit_type
            ):
                applied_script = migration
                break

        # If script has never been successfully applied, consider it changed
        if not applied_script:
            self.logger.debug(f"Script {script_name} has not been applied yet")
            return True

        # Get applied checksum (normalize driver unsigned 32-bit vs signed Flyway CRC32)
        applied_checksum = normalize_migration_checksum(getattr(applied_script, "checksum", None))

        # Get current checksum
        current_checksum = None
        if script_path and script_path.exists():
            # Calculate checksum from the same decoded text used for migration execution.
            raw_text = read_migration_text(
                script_path,
                configured_encoding=self.script_encoding,
                detect_encoding=self.detect_encoding,
            )
            current_checksum = normalize_migration_checksum(self.calculate_checksum(raw_text))
            # Legacy: calculate_checksum once returned MD5 hex (non-numeric); Flyway CRC32 is authoritative
            if current_checksum is None:
                current_checksum = calculate_migration_script_checksum(raw_text)
        else:
            # We need to find the script file
            # This could be improved by allowing script_dir to be passed in
            self.logger.debug(
                f"No script path provided for {script_name}, checksum comparison not possible"
            )
            return True

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
            # Exclude symlinks early: file symlinks pass is_file() but are rejected later by not is_symlink()
            search_method = (
                f
                for f in all_files
                if f.is_file()
                and not f.is_symlink()
                and MigrationFormatDetector.is_migration_file(f)
            )

            for script_path in search_method:
                # Only include regular files, not symlinks or non-regular files
                if script_path.is_file() and not script_path.is_symlink():
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
                    if self.is_valid_script_name(script_path.name):
                        # Store the script with its source directory information
                        # For additional directories, prefix with the directory name to track the source
                        # Compare resolved paths to handle different path representations
                        try:
                            is_additional_dir = resolved_dir_path != resolved_migrations_dir
                        except (OSError, RuntimeError):
                            is_additional_dir = dir_path != migrations_dir

                        if is_additional_dir:
                            # Store as "dir_name/relative_path" (which may include
                            # subdirectory components) to track which directory it
                            # came from while preserving its location within that
                            # directory.
                            rel_path = script_path.relative_to(dir_path)
                            scripts.append(f"{dir_path}/{rel_path.as_posix()}")
                        else:
                            # For the primary directory, use the relative path as-is
                            rel_path = script_path.relative_to(dir_path)
                            scripts.append(str(rel_path))
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

        # Get all scripts from the directory and its subdirectories
        script_paths = self.get_all_scripts(
            scripts_directory,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
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

            # Resolve the path to detect duplicates even if paths are represented differently
            try:
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
                # Check if it's a callback script (case-insensitive matching)
                script_name = script_path.name
                if _callback_event_prefix(script_name) is not None:
                    # Create Migration object with the logger and encoding
                    migration = Migration(
                        script_path,
                        logger=self.logger,
                        script_encoding=self.script_encoding,
                        detect_encoding=self.detect_encoding,
                    )
                    callbacks.append(migration)
                    continue

                migration_type, version, description, _ = self.parse_filename(script_name)
                # Exclude files that are classified as BASELINE but do not match the naming convention
                if migration_type == MigrationType.BASELINE and not any(
                    script_name.startswith(prefix) for prefix in _CALLBACK_PREFIXES
                ):
                    excluded_files.append(rel_script_path)
                    continue
                # Create Migration object with the logger and encoding
                migration = Migration(
                    script_path,
                    logger=self.logger,
                    script_encoding=self.script_encoding,
                    detect_encoding=self.detect_encoding,
                )
                migrations[migration_type].append(migration)
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
    ) -> List[Migration]:
        """Get callbacks for a specific event (e.g., 'beforeMigrate', 'afterMigrateError').

        Args:
            scripts_dir: Directory containing migration scripts
            event_prefix: Callback event prefix to filter by (case-insensitive)
            recursive: Whether to search subdirectories recursively
            additional_dirs: Optional list of additional directories to search

        Returns:
            List of Migration objects for the specified callback event, sorted alphabetically
        """
        migrations = self.load_migration_scripts(
            scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

        callbacks = migrations[MigrationType.CALLBACK]

        # Filter callbacks by event prefix (case-insensitive, delimiter-aware matching)
        filtered_callbacks: List[Migration] = []
        for cb in callbacks:
            base_name = Path(cb.script_name).name
            if _matches_callback_event(base_name, event_prefix):
                filtered_callbacks.append(cb)

        # Sort alphabetically (case-insensitive) to ensure consistent execution order
        filtered_callbacks.sort(key=lambda m: m.script_name.lower())

        return filtered_callbacks
