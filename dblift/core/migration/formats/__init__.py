"""
Migration format detection and handling.

This module provides format detection for migration files to support
both SQL and future non-SQL migration formats.
"""

from .format_detector import MigrationFormatDetector
from .migration_format import MigrationFormat

__all__ = [
    "MigrationFormat",
    "MigrationFormatDetector",
]
