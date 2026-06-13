"""ForeignServer Comparator for Drift Detection.

This module provides the ForeignServerComparator class which compares foreign server objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_identifier
from core.comparison.diff_models import ForeignServerDiff
from core.sql_model.foreign_server import ForeignServer

logger = logging.getLogger(__name__)


class ForeignServerComparator:
    """Compares foreign server objects and generates diff results.

    This class provides methods to compare foreign server objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_foreign_servers(
        self,
        expected: ForeignServer,
        actual: ForeignServer,
        dialect: str = "",
    ) -> Optional[ForeignServerDiff]:
        """Compare two foreign server objects (PostgreSQL).

        Args:
            expected: Expected foreign server from migrations
            actual: Actual foreign server from database
            dialect: SQL dialect (typically postgresql)

        Returns:
            ForeignServerDiff if differences found, None otherwise
        """
        server_name = expected.name or actual.name
        diff = ForeignServerDiff(object_name=server_name, server_name=server_name)

        # Compare FDW name
        expected_fdw = normalize_identifier(expected.fdw_name)
        actual_fdw = normalize_identifier(actual.fdw_name)
        if expected_fdw != actual_fdw:
            diff.fdw_changed = (expected.fdw_name, actual.fdw_name)
            logger.info(
                f"Foreign server '{server_name}': FDW changed from {expected.fdw_name} to {actual.fdw_name}"
            )

        # Compare host
        expected_host = normalize_identifier(expected.host)
        actual_host = normalize_identifier(actual.host)
        if expected_host != actual_host:
            diff.host_changed = (expected.host, actual.host)
            logger.info(
                f"Foreign server '{server_name}': host changed from {expected.host} to {actual.host}"
            )

        # Compare port
        if expected.port != actual.port:
            diff.port_changed = (expected.port, actual.port)
            logger.info(
                f"Foreign server '{server_name}': port changed from {expected.port} to {actual.port}"
            )

        # Compare database name
        expected_dbname = normalize_identifier(expected.dbname)
        actual_dbname = normalize_identifier(actual.dbname)
        if expected_dbname != actual_dbname:
            diff.dbname_changed = (expected.dbname, actual.dbname)
            logger.info(
                f"Foreign server '{server_name}': dbname changed from {expected.dbname} to {actual.dbname}"
            )

        # Compare options (excluding host, port, dbname which are tracked separately)
        expected_opts = {
            k: v for k, v in expected.options.items() if k not in ["host", "port", "dbname"]
        }
        actual_opts = {
            k: v for k, v in actual.options.items() if k not in ["host", "port", "dbname"]
        }
        if expected_opts != actual_opts:
            diff.options_changed = (expected_opts, actual_opts)
            logger.info(f"Foreign server '{server_name}': options changed")

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
