"""
Migration format detection.

Automatically detects the format of a migration file based on its extension
and optionally its content.
"""

import logging
from pathlib import Path

from .migration_format import MigrationFormat

logger = logging.getLogger(__name__)


class MigrationFormatDetector:
    """
    Detects the format of migration files.

    Uses file extension as the primary detection method, with content analysis
    as a fallback for ambiguous cases.

    Examples:
        >>> detector = MigrationFormatDetector()
        >>> format = detector.detect_from_path(Path("V1_0_0__create_table.sql"))
        >>> print(format)  # MigrationFormat.SQL

        >>> format = detector.detect_from_path(Path("V1_0_0__setup.py"))
        >>> print(format)  # MigrationFormat.PYTHON
    """

    # Map file extensions to migration formats
    EXTENSION_MAP = {
        ".sql": MigrationFormat.SQL,
        ".py": MigrationFormat.PYTHON,
        ".js": MigrationFormat.JAVASCRIPT,
        ".cypher": MigrationFormat.CYPHER,
        ".cql": MigrationFormat.CQL,
        ".gremlin": MigrationFormat.GREMLIN,
        ".json": MigrationFormat.JSON,
        ".yaml": MigrationFormat.YAML,
        ".yml": MigrationFormat.YAML,
    }

    @classmethod
    def detect_from_path(cls, file_path: Path) -> MigrationFormat:
        """
        Detect migration format from file path.

        Args:
            file_path: Path to the migration file

        Returns:
            Detected MigrationFormat

        Examples:
            >>> MigrationFormatDetector.detect_from_path(Path("migration.sql"))
            MigrationFormat.SQL

            >>> MigrationFormatDetector.detect_from_path(Path("migration.py"))
            MigrationFormat.PYTHON
        """
        extension = file_path.suffix.lower()
        detected_format = cls.EXTENSION_MAP.get(extension, MigrationFormat.UNKNOWN)

        if detected_format == MigrationFormat.UNKNOWN:
            logger.warning(
                f"Unknown migration file extension '{extension}' for file: {file_path.name}. "
                f"Supported extensions: {', '.join(cls.EXTENSION_MAP.keys())}"
            )

        return detected_format

    @classmethod
    def detect_from_filename(cls, filename: str) -> MigrationFormat:
        """
        Detect migration format from filename string.

        Args:
            filename: Name of the migration file

        Returns:
            Detected MigrationFormat

        Examples:
            >>> MigrationFormatDetector.detect_from_filename("V1__create.sql")
            MigrationFormat.SQL
        """
        return cls.detect_from_path(Path(filename))

    @classmethod
    def is_migration_file(cls, file_path: Path) -> bool:
        """
        Check if a file is a recognized migration file based on extension.

        Args:
            file_path: Path to check

        Returns:
            True if the file has a recognized migration format extension

        Examples:
            >>> MigrationFormatDetector.is_migration_file(Path("V1__test.sql"))
            True

            >>> MigrationFormatDetector.is_migration_file(Path("README.md"))
            False
        """
        extension = file_path.suffix.lower()
        return extension in cls.EXTENSION_MAP
