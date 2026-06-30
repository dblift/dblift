"""Core migration domain model.

Defines :class:`Migration` together with its immutable companion dataclasses
:class:`MigrationResource` (filesystem source), :class:`ResolvedMigration`
(parsed/validated form) and :class:`AppliedMigration` (history-table view),
plus helpers for checksum calculation and dict <-> object conversion.
"""

import logging as _logging
import os
import re
import zlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from core.logger import Log
from core.migration.encoding import read_migration_text
from core.migration.formats import MigrationFormat, MigrationFormatDetector

# Forward declare MigrationScriptManager to avoid circular imports
MigrationScriptManager = None


def _default_splitter_dialect() -> str:
    """Registry-derived generic dialect for statement splitting (ADR-26 E5).

    Used only on the no-dialect fallback path where no dialect could be
    resolved from explicit args, config, or environment. The statement
    splitter still needs *a* relational dialect for its regex tokenizer;
    we take the first relational native dialect the plugin registry
    advertises (sorted by name) so no dialect-name literal is hardcoded.
    """
    from db.provider_registry import ProviderRegistry

    relational = sorted(
        p.name
        for p in ProviderRegistry.list_plugins()
        if ProviderRegistry.is_native_dialect(p.name)
        and ProviderRegistry.get_quirks(p.name).sqlglot_dialect
    )
    return relational[0] if relational else ""


# Canonical list of callback event prefixes (camelCase).
# Must stay in sync with MigrationScriptManager.callback_prefixes
# (core/migration/scripting/migration_script_manager.py).
_CALLBACK_PREFIXES = [
    "beforeMigrate",
    "afterMigrate",
    "afterMigrateError",
    "beforeEach",
    "afterEach",
    "beforeValidate",
    "afterValidate",
    "beforeClean",
    "afterClean",
    "afterCleanError",
    "beforeUndo",
    "afterUndo",
    "afterUndoError",
    "beforeEachMigrate",
    "afterEachMigrate",
    "beforeVersioned",
    "afterVersioned",
    "beforeRepeatable",
    "afterRepeatable",
]


class MigrationType(Enum):
    """Enum for migration types."""

    # Flyway-style versioned scripts (V*__description.*); parse_filename uses SQL for
    # every supported extension (.sql, .py, …), not "SQL format only".
    SQL = "SQL"
    PYTHON = "PYTHON"  # non-SQL versioned script migrations (.py, .js, etc.)
    REPEATABLE = "REPEATABLE"  # Repeatable migrations (R*.sql)
    UNDO_SQL = "UNDO_SQL"  # Undo migrations (U*.sql)
    BASELINE = "BASELINE"  # Baseline command entries (not actual script files)
    CALLBACK = "CALLBACK"  # Callback scripts
    DELETE = "DELETE"  # Delete operation entries (for audit trail when scripts are removed)
    UNKNOWN = "UNKNOWN"  # Unknown migration type


@dataclass(frozen=True)
class MigrationResource:
    """Filesystem resource for a migration script before resolution/history state."""

    path: Path
    script_name: str
    content: str
    encoding: str = "utf-8"

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        script_name: Optional[str] = None,
        encoding: str = "utf-8",
        detect_encoding: bool = False,
    ) -> "MigrationResource":
        """Build a :class:`MigrationResource` by reading ``path`` with the requested encoding."""
        return cls(
            path=path,
            script_name=script_name or path.name,
            content=read_migration_text(
                path, configured_encoding=encoding, detect_encoding=detect_encoding
            ),
            encoding=encoding,
        )


@dataclass(frozen=True)
class ResolvedMigration:
    """Migration resolved from script resources and ready for validation/execution."""

    script_name: str
    content: str
    version: Optional[str]
    description: Optional[str]
    type: MigrationType
    checksum: int
    tags: List[str] = field(default_factory=list)
    resource: Optional[MigrationResource] = None

    @classmethod
    def from_migration(cls, migration: "Migration") -> "ResolvedMigration":
        """Project a mutable :class:`Migration` into its immutable resolved snapshot."""
        resource = None
        if getattr(migration, "path", None):
            assert migration.path is not None
            resource = MigrationResource(
                path=migration.path,
                script_name=migration.script_name,
                content=migration.content,
                encoding=getattr(migration, "script_encoding", "utf-8"),
            )
        return cls(
            script_name=migration.script_name,
            content=migration.content,
            version=migration.version,
            description=migration.description,
            type=migration.type,
            checksum=migration.checksum or 0,
            tags=list(getattr(migration, "tags", []) or []),
            resource=resource,
        )

    def to_migration(
        self, *, logger: Optional[Union[Log, _logging.Logger]] = None, dialect: Optional[str] = None
    ) -> "Migration":
        """Materialize a mutable :class:`Migration` from this resolved snapshot."""
        migration = Migration(
            script_name=self.script_name,
            content=self.content,
            version=self.version,
            description=self.description,
            type=self.type,
            tags=list(self.tags),
            logger=logger,
            dialect=dialect,
        )
        migration.checksum = self.checksum
        migration.resolved_migration = self
        return migration


@dataclass(frozen=True)
class AppliedMigration:
    """History-table record for an already applied migration."""

    script_name: str
    version: Optional[str]
    description: Optional[str]
    type: MigrationType
    checksum: Optional[int]
    success: Optional[Any] = None
    execution_time: Optional[int] = None
    installed_on: Optional[Any] = None
    installed_by: Optional[str] = None
    installed_rank: Optional[int] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_history_row(cls, row: Dict[str, Any]) -> "AppliedMigration":
        """Construct an :class:`AppliedMigration` from a history-table row (case-insensitive keys)."""
        normalized = {k.lower() if isinstance(k, str) else k: v for k, v in row.items()}
        type_str = normalized.get("type")
        type_enum = (
            MigrationType[type_str]
            if type_str and type_str in MigrationType.__members__
            else MigrationType.UNKNOWN
        )
        checksum = normalized.get("checksum")
        if checksum is not None:
            checksum = normalize_migration_checksum(checksum)
        return cls(
            script_name=str(normalized.get("script") or ""),
            version=normalized.get("version"),
            description=normalized.get("description"),
            type=type_enum,
            checksum=checksum,
            success=normalized.get("success"),
            execution_time=normalized.get("execution_time"),
            installed_on=normalized.get("installed_on"),
            installed_by=normalized.get("installed_by"),
            installed_rank=normalized.get("installed_rank"),
            status=normalized.get("status"),
            error_message=normalized.get("error_message"),
            raw=normalized,
        )

    def to_migration(
        self,
        *,
        logger: Optional[Union[Log, _logging.Logger]] = None,
        dialect: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> "Migration":
        """Build a mutable :class:`Migration` from this applied record (empty content, raw fields copied)."""
        migration = Migration(
            script_name=self.script_name,
            content="",
            version=self.version,
            description=self.description,
            type=self.type,
            tags=tags or [],
            logger=logger,
            dialect=dialect,
        )
        migration.checksum = self.checksum
        for key, value in self.raw.items():
            if not hasattr(migration, key) or key in {
                "success",
                "execution_time",
                "installed_on",
                "installed_by",
                "installed_rank",
                "status",
                "error_message",
                "deleted_at",
                "deleted_by",
                "deletion_reason",
            }:
                setattr(migration, key, value)
        migration.applied_migration = self
        return migration


# Subset of MigrationType names that behave like versioned, ordered, run-once
# scripts. Consulted from state/command modules to decide whether a migration
# should participate in version-based pending/applied/undone accounting.
# Extend when a new scripted format is implemented — this is the single source
# of truth (the former duplicated copies in core/migration/state/*.py and the
# hardcoded literal in base_command.py have been removed).
VERSIONED_SCRIPT_TYPES: frozenset[str] = frozenset(
    {MigrationType.SQL.value, MigrationType.PYTHON.value}
)


def calculate_migration_script_checksum(content: str) -> int:
    """CRC32 checksum (signed 32-bit int), line-by-line.
    Returns a signed 32-bit integer (can be negative, like Java int).
    """
    crc = 0
    for line in content.splitlines():
        crc = zlib.crc32(line.encode("utf-8"), crc)
    return crc if crc < 2**31 else crc - 2**32


def normalize_migration_checksum(value: Optional[Any]) -> Optional[int]:
    """Convert a database checksum to signed 32-bit int.

    Some drivers return CRC32 as unsigned 32-bit (e.g. 3272252829) while Python uses
    signed -1022714467; this aligns both for comparison.
    Returns a signed 32-bit integer (can be negative, like Java int).
    """
    if value is None:
        return None
    try:
        val = int(value)
    except (TypeError, ValueError):
        try:
            val = int(float(value))
        except (TypeError, ValueError):
            return None
    val &= 0xFFFFFFFF
    if val >= 2**31:
        val -= 2**32
    return val


class Migration:
    """Represents a migration script."""

    def __init__(
        self,
        script: Optional[Path] = None,
        script_path: Optional[Path] = None,
        script_name: Optional[str] = None,
        content: Optional[str] = None,
        version: Optional[str] = None,
        description: Optional[str] = None,
        type: Optional[MigrationType] = None,
        sql_statements: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        logger: Optional[Union[Log, _logging.Logger]] = None,
        dialect: Optional[str] = None,
        script_encoding: str = "utf-8",
        detect_encoding: bool = False,
        config: Any = None,
    ) -> None:
        """
        Initialize a Migration object.

        Args:
            script: Path to the migration script file (deprecated, use script_path instead)
            script_path: Path to the migration script file (optional if other parameters provided)
            script_name: Name of the migration script (optional if script_path provided)
            content: Content of the migration script (optional if script_path provided)
            version: Version of the migration (optional if script_path provided)
            description: Description of the migration (optional if script_path provided)
            type: Type of the migration (optional if script_path provided)
            sql_statements: SQL statements in the migration (optional)
            tags: Migration tags for organizing migrations by groups/features
            logger: Optional logger to use instead of creating a new one
            dialect: Optional SQL dialect to use for parsing
            config: Optional application configuration for dialect fallback
        """
        self.logger = logger
        self.dialect = dialect
        self.config = config
        # Typed slots for back-references set by ResolvedMigration/AppliedMigration.to_migration
        self.resolved_migration: Optional["ResolvedMigration"] = None
        self.applied_migration: Optional["AppliedMigration"] = None
        self.resolved: bool = False

        # Store script encoding for file reading operations
        self.script_encoding = script_encoding
        self.detect_encoding = detect_encoding

        # Handle deprecated script parameter
        if script is not None:
            script_path = script

        # If a script path is provided, read from file
        if script_path:
            self.path: Optional[Path] = script_path
            self.script_name = script_path.name
            # Use configured encoding explicitly to handle accented characters properly
            self.content = read_migration_text(
                script_path,
                configured_encoding=self.script_encoding,
                detect_encoding=self.detect_encoding,
            )
            self.version = self._extract_version()
            self.description = self._extract_description()
            self.type = self._determine_type()
            self.tags = self._extract_tags()
            self._sql_statements = None
            # Detect migration format from file extension
            self.format = MigrationFormatDetector.detect_from_path(script_path)
            # Override type for non-SQL scripted formats
            if self.type == MigrationType.SQL and self.format not in (
                MigrationFormat.SQL,
                MigrationFormat.UNKNOWN,
            ):
                self.type = MigrationType.PYTHON
        # Otherwise use the provided values
        else:
            if not script_name:
                raise ValueError("Either script_path or script_name must be provided")

            self.path = None
            self.script_name = script_name
            self.content = content or ""
            self.version = version or self._extract_version()
            self.description = description or self._extract_description()

            # Validate migration type
            if type is not None and not isinstance(type, MigrationType):
                raise ValueError(
                    f"Invalid migration type: {type}. Must be a MigrationType enum value."
                )
            self.type = type or self._determine_type()

            self.tags = tags or self._extract_tags()
            self._sql_statements = sql_statements
            # Detect format from script name extension (handles DB-loaded migrations where
            # script_path is not available but the extension encodes the format).
            self.format = MigrationFormatDetector.detect_from_filename(self.script_name)

        self.checksum: Optional[int] = self._calculate_checksum()

        # Add attributes expected by migration_ui.py
        self.name = self.script_name  # Alias for script_name
        self.status = "PENDING"  # Default status
        self.success: Optional[bool] = None  # Will be set for applied migrations
        self.installed_on: Optional[str] = None  # Will be set for applied migrations
        self.installed_rank: Optional[int] = None  # Will be set for applied migrations
        self.execution_time: Optional[int] = None  # Will be set for applied migrations
        self.dependencies: Optional[List[str]] = None
        self.rollback_script: Optional[str] = None
        self.target_version: Optional[str] = None
        self.installed_by: Optional[str] = None
        self.callback_script: Optional[str] = None
        self.callback_status: Optional[str] = None
        self.callback_output: Optional[str] = None
        self.undo_script: Optional[str] = None
        self.undo_status: Optional[str] = None
        self.dependency_status: Optional[Dict[str, Any]] = None
        self.error_message: Optional[str] = None
        self.deleted_at: Optional[str] = None
        self.deleted_by: Optional[str] = None
        self.deletion_reason: Optional[str] = None
        self.can_be_restored: Optional[bool] = None
        self.restore_requirements: Optional[List[str]] = None
        self.execution_history: Optional[List[Any]] = None
        self.script_exists: Optional[bool] = None
        self.script_missing_since: Optional[str] = None
        self.undo_script_exists: Optional[bool] = None
        self.undo_script_missing_since: Optional[str] = None
        self.callback_script_exists: Optional[bool] = None
        self.callback_script_missing_since: Optional[str] = None

    @staticmethod
    def create_baseline_migration(content: str, version: str, description: str) -> "Migration":
        """Create a baseline migration entry.

        Args:
            content: Content of the migration script (typically a comment about the baseline)
            version: Version to baseline at
            description: Description of the baseline operation

        Returns:
            A Migration object representing a baseline migration
        """
        # For baselines, use a simpler script name format like Flyway
        baseline_name = "Base Migration"
        return Migration(
            script_name=baseline_name,
            content=content,
            version=version,
            description=description,
            type=MigrationType.BASELINE,
            tags=[],
        )

    @staticmethod
    def create_delete_migration(
        script_name: str,
        version: Optional[str] = None,
        reason: str = "Marked as deleted via repair command",
    ) -> "Migration":
        """Create a delete migration entry for audit trail.

        Args:
            script_name: Name of the original script that was deleted
            version: Version of the script (optional, extracted from script_name if not provided)
            reason: Reason for the deletion

        Returns:
            A Migration object representing a delete operation
        """
        return Migration(
            script_name=script_name,
            content=f"-- Delete operation: {reason}",
            version=version,
            description=reason,
            type=MigrationType.DELETE,
            tags=[],
        )

    def load_content(self, scripts_dir: Optional[Path] = None) -> None:
        """Populate self.content from disk when it is empty (e.g. for DB-loaded migrations).

        Does nothing if content is already present or if the script file cannot be located.
        """
        if self.content:
            return
        candidates = []
        if self.path and self.path.exists():
            candidates.append(self.path)
        if scripts_dir and self.script_name:
            candidates.append(scripts_dir / self.script_name)
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                self.content = read_migration_text(
                    candidate,
                    configured_encoding=self.script_encoding,
                    detect_encoding=self.detect_encoding,
                )
                self.path = candidate
                return
            except OSError:
                continue

    @property
    def sql_statements(self) -> List[str]:
        """Get the SQL statements from the script content."""
        if not self.content:
            return []

        # Split on GO statements and semicolons
        statements: List[str] = []
        current_statement: List[str] = []

        for line in self.content.split("\n"):
            line = line.strip()
            if not line:
                continue

            if line.upper() == "GO":
                if current_statement:
                    statements.append(" ".join(current_statement))
                    current_statement = []
            else:
                current_statement.append(line)

        # Add any remaining statement
        if current_statement:
            statements.append(" ".join(current_statement))

        # Split any remaining statements on semicolons
        final_statements: List[str] = []
        for stmt in statements:
            if ";" in stmt:
                parts = stmt.split(";")
                final_statements.extend(p.strip() for p in parts if p.strip())
            else:
                final_statements.append(stmt)

        return final_statements

    def parse_sql_statements(
        self, dialect: Optional[str] = None, content_override: Optional[str] = None
    ) -> List[str]:
        """Parse SQL statements from the migration content.

        Args:
            dialect: The SQL dialect to use for parsing (e.g., 'sqlserver', 'oracle')
            content_override: If provided, parse this text instead of self.content.
                Used by the execution engine to pass placeholder-substituted content so
                that the tokeniser never sees raw ``${...}`` fragments embedded in
                identifiers (which would otherwise cause it to insert whitespace and
                produce un-executable SQL like ``app _config``).

                **Immutability contract** (Bugbot PR 160 line 386, ADR-0010): when
                ``content_override`` is provided, the parsed statements are returned
                but **not cached** in ``self._sql_statements``. Caching the
                placeholder-substituted form would poison every later reader (checksum,
                info display, second parse without override) with content that no
                longer reflects the canonical migration source. Callers that need the
                canonical statements call ``parse_sql_statements()`` without override.

        Returns:
            List of SQL statements. Cached on ``self._sql_statements`` only when
            no ``content_override`` was supplied.
        """
        # Prefer the caller-supplied content (e.g. post-placeholder substitution).
        content = content_override if content_override is not None else self.content
        # When override was supplied, the result is for THIS execution only — do
        # not let it overwrite the canonical cache.
        cache_result = content_override is None

        # No SQL statements provided, parse from content
        if not content:
            return []

        # Use the provided logger or create a standard logger
        from core.logger import DbliftLogger

        logger = self.logger
        if logger is None:
            logger = DbliftLogger()
        log = cast(Log, logger)

        # Use dialect if provided, otherwise try to determine
        if dialect:
            self.dialect = dialect
        elif self.dialect:
            dialect = self.dialect
        else:
            # If no dialect provided, try to determine from config
            config = self.config
            if config and hasattr(config, "database") and config.database.type:
                dialect = config.database.type.lower()
                log.info(f"Using dialect '{dialect}' from config")

            # If still no dialect, check for environment variables
            if not dialect:
                db_type = os.environ.get("DBLIFT_DATABASE_TYPE")
                if db_type:
                    dialect = db_type.lower()
                    log.info(f"Using dialect '{dialect}' from environment variable")

        # If no dialect determined from any source, we can't proceed properly.
        # Statement splitting still needs *a* dialect for its regex splitter;
        # resolve a generic relational dialect from the plugin registry rather
        # than hardcoding one (ADR-26 E5).
        if not dialect:
            log.warning("No dialect available from config, defaulting to simple parser")
            from core.migration.sql.sql_analyzer import SqlAnalyzer

            sql_analyzer = SqlAnalyzer(dialect=_default_splitter_dialect(), logger=log)
            statements = sql_analyzer.split_statements(content)
            if cache_result:
                self._sql_statements = statements
            return statements

        # Use SqlAnalyzer to handle dialect-specific statement parsing
        # This will follow the cascading approach defined in the architecture:
        # 1. ANTLR with Visitors (primary method)
        # 2. ANTLR with Regex Fallback
        # 3. Regex (fallback)
        try:
            from core.migration.sql.sql_analyzer import SqlAnalyzer

            sql_analyzer = SqlAnalyzer(dialect=dialect, logger=log)
            statements = sql_analyzer.split_statements(content)
            log.debug(f"SqlAnalyzer split returned {len(statements)} statements")
        except Exception as e:
            log.warning(
                f"Error using SqlAnalyzer: {str(e)}. Falling back to simple semicolon-based parser."
            )
            # Fallback: split on semicolons, filter empty statements
            raw = content or ""
            statements = [s.strip() for s in raw.split(";") if s.strip()]
            log.debug(f"Fallback parser produced {len(statements)} statements")

        # Final pass: ensure we don't have any empty statements
        if statements:
            statements = [stmt for stmt in statements if stmt.strip()]

        # Cache only when the parse used canonical content. When called with
        # content_override (placeholder-substituted), the result is per-execution
        # and must not poison the canonical cache (Bugbot PR 160, ADR-0010).
        if cache_result:
            self._sql_statements = statements
        return statements

    @property
    def type_str(self) -> str:
        """Get the migration type as a string."""
        return self.type.value

    def _extract_version(self) -> Optional[str]:
        """Extract version from script name.

        Uses MigrationScriptManager's parsing for consistency.
        """
        # Import here to avoid circular imports
        # Use provided logger or create a new one
        from core.logger import DbliftLogger

        # Import here to avoid circular imports
        from .scripting.migration_script_manager import MigrationScriptManager

        logger = self.logger
        if logger is None:
            logger = DbliftLogger()
        script_manager = MigrationScriptManager(
            cast(Log, logger), self.script_encoding, self.detect_encoding
        )

        return script_manager.extract_version(self.script_name)

    def _extract_description(self) -> str:
        """Extract description from script name.

        Uses MigrationScriptManager's parsing for consistency.
        """
        # Import here to avoid circular imports
        # Use provided logger or create a new one
        from core.logger import DbliftLogger

        # Import here to avoid circular imports
        from .scripting.migration_script_manager import MigrationScriptManager

        logger = self.logger
        if logger is None:
            logger = DbliftLogger()
        script_manager = MigrationScriptManager(
            cast(Log, logger), self.script_encoding, self.detect_encoding
        )

        return script_manager.extract_description(self.script_name)

    def _determine_type(self) -> MigrationType:
        """Determine the type of migration based on the script name."""
        if not self.script_name:
            return MigrationType.UNKNOWN

        script_name = self.script_name.lower()

        # Check for callback scripts first — use module-level _CALLBACK_PREFIXES constant
        if any(script_name.startswith(prefix.lower()) for prefix in _CALLBACK_PREFIXES):
            return MigrationType.CALLBACK

        # Check for versioned migrations — Flyway convention: V<version>__<desc>
        # NOTE: Uses \d (digit-only) rather than [a-z0-9] to avoid false positives:
        # "validate.sql" starts with "va" — 'a' would match [a-z0-9] and be misclassified.
        # This is intentionally stricter than parse_filename() which accepts letter-based
        # versions (e.g. "Va__create.sql"). _determine_type() is a fast pre-check; full
        # validation with version extraction is done later by MigrationScriptManager.
        if re.match(r"^v\d", script_name):
            return MigrationType.SQL

        # Check for repeatable migrations — Flyway convention: R__<desc> (no version number)
        # "R1__setup.sql" (versioned repeatable) is intentionally rejected (not standard Flyway).
        if script_name.startswith("r__"):
            return MigrationType.REPEATABLE

        # Check for baseline migrations — convention: B<version>__<desc>
        # Uses \d for same reason as versioned: avoids "backup.sql" false positive.
        if re.match(r"^b\d", script_name):
            return MigrationType.BASELINE

        # Check for undo migrations — Flyway convention: U<version>__<desc>
        # Uses \d for same reason: avoids "undo.sql", "update.sql" false positives.
        if re.match(r"^u\d", script_name):
            return MigrationType.UNDO_SQL

        return MigrationType.UNKNOWN

    def _extract_tags(self) -> List[str]:
        """Extract tags from script name.

        Uses MigrationScriptManager's parsing for consistency.
        """
        # Import here to avoid circular imports
        # Use provided logger or create a new one
        from core.logger import DbliftLogger

        # Import here to avoid circular imports
        from .scripting.migration_script_manager import MigrationScriptManager

        logger = self.logger
        if logger is None:
            logger = DbliftLogger()
        script_manager = MigrationScriptManager(
            cast(Log, logger), self.script_encoding, self.detect_encoding
        )

        return script_manager.extract_tags(self.script_name)

    def _calculate_checksum(self) -> int:
        """Calculate a CRC32 checksum compatible with Flyway.

        Uses CRC32 line-by-line (line separators excluded), identical to
        org.flywaydb.core.internal.resource.ResourceName in Flyway Java.
        Returns a signed 32-bit integer (can be negative, like Java int).
        """
        return calculate_migration_script_checksum(self.content)

    def __repr__(self) -> str:
        # Deferred import: _type_match imports MigrationType from this module.
        from core.migration._type_match import migration_type_name

        type_str = migration_type_name(self.type)
        return f"<Migration script_name='{self.script_name}' type='{type_str}' version='{self.version}'>"

    def __str__(self) -> str:
        from core.migration._type_match import migration_type_name

        type_str = migration_type_name(self.type)
        return f"Migration: {self.script_name} ({type_str}, version={self.version})"


def dict_to_migration(
    migration_dict: Dict[str, Any], logger: Any = None, dialect: Optional[str] = None
) -> "Migration":
    """Convert a migration dict (from DB) to a Migration object, mapping all relevant fields."""
    # Normalize dictionary keys to lowercase for case-insensitive access
    # (DB2 returns uppercase column names by default)
    normalized_dict = {k.lower() if isinstance(k, str) else k: v for k, v in migration_dict.items()}

    script_name = normalized_dict.get("script")
    tags = normalized_dict.get("tags")
    # If tags not in dict, extract from script_name (tags are in brackets in filename)
    if not tags and script_name:
        # Import here to avoid circular imports
        from core.logger import DbliftLogger

        from .scripting.migration_script_manager import MigrationScriptManager

        script_logger = logger or DbliftLogger()
        script_manager = MigrationScriptManager(script_logger)
        tags = script_manager.extract_tags(script_name)

    applied = AppliedMigration.from_history_row(normalized_dict)
    return applied.to_migration(logger=logger, dialect=dialect, tags=tags or [])
