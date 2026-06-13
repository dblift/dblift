"""Synonym Comparator for Drift Detection.

This module provides the SynonymComparator class which compares synonym objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.diff_models import SynonymDiff
from core.sql_model.synonym import Synonym

logger = logging.getLogger(__name__)


class SynonymComparator:
    """Compares synonym objects and generates diff results.

    This class provides methods to compare synonym objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_synonyms(
        self,
        expected: Synonym,
        actual: Synonym,
        dialect: str = "",
    ) -> Optional[SynonymDiff]:
        """Compare two synonym objects.

        Args:
            expected: Expected synonym from migrations
            actual: Actual synonym from database
            dialect: SQL dialect

        Returns:
            SynonymDiff if differences found, None otherwise
        """
        syn_name = expected.name or actual.name
        diff = SynonymDiff(object_name=syn_name, synonym_name=syn_name)

        # Normalize target object names for comparison
        def _normalize_target(target: Optional[str]) -> str:
            """Normalize target object name for comparison.

            Handles quoted and unquoted identifiers:
            - Quoted identifiers (e.g. "name", [name], `name`): Strip quotes, preserve case
            - Unquoted identifiers: Apply dialect-specific case normalization
              - Oracle/DB2: uppercase
              - PostgreSQL/MySQL/SQL Server: lowercase
            """
            if not target:
                return ""

            cleaned = target.strip()
            is_quoted = False

            # Check for and remove dialect-specific quoting
            if cleaned.startswith('"') and cleaned.endswith('"'):
                cleaned = cleaned[1:-1]
                is_quoted = True
            elif cleaned.startswith("[") and cleaned.endswith("]"):
                cleaned = cleaned[1:-1]
                is_quoted = True
            elif cleaned.startswith("`") and cleaned.endswith("`"):
                cleaned = cleaned[1:-1]
                is_quoted = True

            # For quoted identifiers, preserve case (case-sensitive)
            # For unquoted identifiers, apply dialect-specific normalization
            if not is_quoted:
                # Ensure we have a Python string to handle driver-returned objects
                cleaned = str(cleaned)
                from db.provider_registry import ProviderRegistry

                quirks = ProviderRegistry.get_quirks(dialect.lower())
                return cleaned.upper() if quirks.uppercase_identifiers else cleaned.lower()

            return str(cleaned)

        # Compare target object
        expected_target = _normalize_target(expected.target_object)
        actual_target = _normalize_target(actual.target_object)
        if expected_target != actual_target:
            diff.target_changed = (expected.target_object, actual.target_object)
            diff.expected_target = expected.target_full_name
            diff.actual_target = actual.target_full_name
            logger.info(
                f"Synonym '{syn_name}': target changed from {expected.target_object} to {actual.target_object}"
            )

        # Compare target schema
        expected_schema = _normalize_target(expected.target_schema)
        actual_schema = _normalize_target(actual.target_schema)
        if expected_schema != actual_schema:
            diff.target_schema_changed = (expected.target_schema, actual.target_schema)
            logger.info(
                f"Synonym '{syn_name}': target schema changed from {expected.target_schema} to {actual.target_schema}"
            )

        # Compare target database (SQL Server)
        expected_db = _normalize_target(expected.target_database)
        actual_db = _normalize_target(actual.target_database)
        if expected_db != actual_db:
            diff.target_database_changed = (expected.target_database, actual.target_database)
            logger.info(
                f"Synonym '{syn_name}': target database changed from {expected.target_database} to {actual.target_database}"
            )

        # Compare database link (Oracle)
        expected_link = _normalize_target(expected.db_link)
        actual_link = _normalize_target(actual.db_link)
        if expected_link != actual_link:
            diff.db_link_changed = (expected.db_link, actual.db_link)
            logger.info(
                f"Synonym '{syn_name}': database link changed from {expected.db_link} to {actual.db_link}"
            )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
