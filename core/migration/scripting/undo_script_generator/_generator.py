"""Undo Script Generator — main UndoScriptGenerator class.

This module contains the UndoScriptGenerator class which composes the
reversers and extractors mixins into a coherent generator.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.logger import DbliftLogger, Log
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.scripting.undo_script_generator._extractors import _UndoExtractorsMixin
from core.migration.scripting.undo_script_generator._models import UndoStatement
from core.migration.scripting.undo_script_generator._reversers import _UndoReversersMixin
from core.migration.sql.sql_analyzer import SqlAnalyzer
from core.sql_parser.parser_factory import SqlParserFactory


class UndoScriptGenerator(_UndoReversersMixin, _UndoExtractorsMixin):
    """Generates undo scripts from versioned migration files."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Log] = None,
    ):
        """Initialize the undo script generator.

        Args:
            dialect: SQL dialect (postgresql, oracle, mysql, sqlserver)
            logger: Optional logger instance
        """
        self.dialect = dialect
        self.logger = logger
        self.sql_analyzer = SqlAnalyzer(dialect=dialect, logger=logger)
        # Use parser factory to get the appropriate parser for this dialect
        parser_factory = SqlParserFactory(dialect=dialect, parser_type="hybrid")
        self.parser = parser_factory.get_parser(dialect)

    def generate_undo_script(
        self,
        migration_path: Path,
        output_dir: Optional[Path] = None,
        overwrite: bool = False,
    ) -> Path:
        """Generate an undo script for a versioned migration.

        Args:
            migration_path: Path to the versioned SQL migration file (V*__.sql)
            output_dir: Directory to write undo script (default: same as migration file)
            overwrite: Whether to overwrite existing undo script

        Returns:
            Path to the generated undo script

        Raises:
            ValueError: If migration_path is not a versioned migration
            FileExistsError: If undo script exists and overwrite=False
        """
        # Validate migration file
        if not migration_path.exists():
            raise FileNotFoundError(f"Migration file not found: {migration_path}")

        script_manager = MigrationScriptManager(self.logger or DbliftLogger())
        if not script_manager.is_versioned_script_name(migration_path.name):
            raise ValueError(
                f"File is not a versioned migration: {migration_path.name}. "
                "Expected a versioned migration filename (V*__description.<ext>)."
            )

        # Parse migration to get version and description
        migration = Migration(script_path=migration_path, logger=self.logger)
        if migration.format != MigrationFormat.SQL:
            raise ValueError(
                f"Cannot auto-generate undo for {migration_path.name}: only SQL versioned "
                f"migrations (V*__.sql) are supported. For Python or other formats, add a "
                f"manual U*__.sql undo script."
            )

        if not migration.version:
            raise ValueError(f"Could not extract version from: {migration_path.name}")

        # Extract original version format from filename (preserve underscores/dots)
        # Migration.version is normalized (underscores -> dots), but we want original format
        original_version = self._extract_version_from_filename(migration_path.name)
        if not original_version:
            # Fallback to normalized version if extraction fails
            original_version = migration.version

        # Determine output path
        if output_dir is None:
            output_dir = migration_path.parent
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Generate undo filename: U{version}__{description} with same extension as original
        # Use original version format to preserve underscores/dots
        # Preserve the file extension from the original migration
        original_extension = migration.path.suffix if migration.path else ".sql"
        undo_filename = f"U{original_version}__{migration.description}{original_extension}"
        undo_path = output_dir / undo_filename

        # Check if file exists
        if undo_path.exists() and not overwrite:
            raise FileExistsError(
                f"Undo script already exists: {undo_path}. Use overwrite=True to replace."
            )

        # Generate undo statements
        undo_statements = self._generate_undo_statements(migration)

        # Write undo script
        self._write_undo_script(undo_path, migration, undo_statements)

        if self.logger:
            self.logger.info(f"Generated undo script: {undo_path}")

        return undo_path

    def generate_undo_script_for_migration(
        self,
        migration: Migration,
        output_dir: Optional[Path] = None,
        overwrite: bool = False,
    ) -> Path:
        """Generate an undo script for an already parsed and validated migration."""
        migration_path = migration.path
        if migration_path is None:
            raise ValueError("Migration must have a script path to generate an undo script.")
        if migration.format != MigrationFormat.SQL:
            raise ValueError(
                f"Cannot auto-generate undo for {migration.script_name}: only SQL versioned "
                f"migrations (V*__.sql) are supported. For Python or other formats, add a "
                f"manual U*__.sql undo script."
            )
        if not migration.version:
            raise ValueError(f"Could not extract version from: {migration.script_name}")

        undo_path = self.get_undo_script_path_for_migration(migration, output_dir)

        if undo_path.exists() and not overwrite:
            raise FileExistsError(
                f"Undo script already exists: {undo_path}. Use overwrite=True to replace."
            )

        undo_statements = self._generate_undo_statements(migration)
        self._write_undo_script(undo_path, migration, undo_statements)

        if self.logger:
            self.logger.info(f"Generated undo script: {undo_path}")

        return undo_path

    def get_undo_script_path_for_migration(
        self, migration: Migration, output_dir: Optional[Path] = None
    ) -> Path:
        """Return the exact undo script path this generator will write."""
        migration_path = migration.path
        if migration_path is None:
            raise ValueError("Migration must have a script path to generate an undo script.")

        original_version = self._extract_version_from_filename(migration.script_name)
        if not original_version:
            original_version = migration.version

        if output_dir is None:
            output_dir = migration_path.parent
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        original_extension = migration_path.suffix
        undo_filename = f"U{original_version}__{migration.description}{original_extension}"
        return output_dir / undo_filename

    def _generate_undo_statements(self, migration: Migration) -> List[UndoStatement]:
        """Generate reverse statements for all operations in migration.

        Args:
            migration: Migration object to reverse

        Returns:
            List of undo statements (in reverse order)
        """
        # Parse SQL using the parser to get structured statements with types
        parse_result = self.parser.parse_sql(migration.content, default_schema=None)

        if not parse_result.success or not parse_result.statements:
            # Fallback to simple statement splitting
            statements = migration.parse_sql_statements(dialect=self.dialect)
            undo_statements = []
            for statement in reversed(statements):
                undo_stmt = self._reverse_statement(statement)
                if undo_stmt:
                    undo_statements.append(undo_stmt)
            return undo_statements

        # First pass: generate all undo statements
        undo_statements = []
        for stmt in reversed(parse_result.statements):
            undo_stmt = self._reverse_statement_from_parsed(stmt)
            if undo_stmt:
                undo_statements.append(undo_stmt)

        # Second pass: filter out COMMENT reversals for tables that are being dropped
        # (DROP TABLE automatically removes comments, so COMMENT ... IS NULL is unnecessary)
        tables_being_dropped = set()
        for undo_stmt in undo_statements:
            if undo_stmt.sql.strip().upper().startswith("DROP TABLE"):
                # Extract table name from DROP TABLE statement
                table_name = self._extract_table_name_from_drop(undo_stmt.sql)
                if table_name:
                    tables_being_dropped.add(table_name.lower())

        # Filter out COMMENT and INDEX statements for tables that will be dropped
        filtered_statements = []
        for undo_stmt in undo_statements:
            sql_upper = undo_stmt.sql.strip().upper()

            # Skip COMMENT ON TABLE for tables that will be dropped
            if sql_upper.startswith("COMMENT ON TABLE"):
                table_name = self._extract_table_name_from_comment(undo_stmt.sql)
                if table_name and table_name.lower() in tables_being_dropped:
                    if self.logger:
                        self.logger.debug(
                            f"Skipping COMMENT reversal for {table_name} - table will be dropped"
                        )
                    continue

            # Skip DROP INDEX for indexes on tables that will be dropped
            elif sql_upper.startswith("DROP INDEX"):
                # Extract table name from the original CREATE INDEX statement
                table_name = self._extract_table_name_from_create_index(
                    undo_stmt.original_statement
                )
                if table_name and table_name.lower() in tables_being_dropped:
                    if self.logger:
                        self.logger.debug(
                            f"Skipping DROP INDEX - table {table_name} will be dropped"
                        )
                    continue

            # Skip INSERT/DELETE reversals for tables that will be dropped
            elif undo_stmt.operation_type == "INSERT":
                # Extract table name from original INSERT statement
                table_name = self._extract_table_name_from_insert(undo_stmt.original_statement)
                if table_name and table_name.lower() in tables_being_dropped:
                    if self.logger:
                        self.logger.debug(
                            f"Skipping INSERT reversal for {table_name} - table will be dropped"
                        )
                    continue
            elif sql_upper.startswith("DELETE FROM"):
                # Extract table name from DELETE statement
                table_name = self._extract_table_name_from_delete(undo_stmt.sql)
                if table_name and table_name.lower() in tables_being_dropped:
                    if self.logger:
                        self.logger.debug(
                            f"Skipping DELETE reversal for {table_name} - table will be dropped"
                        )
                    continue

            filtered_statements.append(undo_stmt)

        return filtered_statements

    def _write_undo_script(
        self,
        undo_path: Path,
        migration: Migration,
        undo_statements: List[UndoStatement],
    ) -> None:
        """Write undo script to file.

        Args:
            undo_path: Path to write undo script
            migration: Original migration object
            undo_statements: List of undo statements
        """
        lines = []

        # Header
        lines.append(f"-- Undo script for {migration.script_name}")
        lines.append("-- Generated automatically - review before use")
        lines.append(f"-- Generated: {datetime.now().isoformat()}")
        lines.append("")

        # Count warnings
        warnings_count = sum(1 for stmt in undo_statements if stmt.warning)
        if warnings_count > 0:
            lines.append(f"-- WARNING: {warnings_count} statement(s) require manual review")
            lines.append("")

        # Write statements
        for stmt in undo_statements:
            if stmt.warning:
                lines.append(f"-- {stmt.warning}")
            if stmt.requires_manual_review:
                lines.append("-- Original statement:")
                # Indent original statement
                for line in stmt.original_statement.split("\n"):
                    lines.append(f"--   {line}")
                lines.append("")
            lines.append(stmt.sql)
            lines.append("")

        # Write to file
        undo_path.write_text("\n".join(lines), encoding="utf-8")
