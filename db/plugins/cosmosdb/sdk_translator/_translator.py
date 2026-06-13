"""CosmosDB SDK Translator — main CosmosDbSdkTranslator class.

This module contains the CosmosDbSdkTranslator class, which composes the
translation and execution mixins into a single coherent API.
"""

import logging
from typing import Any, Dict, List, Optional, cast

from core.sql_generator.sql_statement import SqlStatement
from db.plugins.cosmosdb.sdk_translator._executors import _CosmosDbExecutorMixin
from db.plugins.cosmosdb.sdk_translator._script_generation import _CosmosDbScriptGenerationMixin
from db.plugins.cosmosdb.sdk_translator._translators import _CosmosDbTranslatorMixin

logger = logging.getLogger(__name__)


class CosmosDbSdkTranslator(
    _CosmosDbTranslatorMixin,
    _CosmosDbExecutorMixin,
    _CosmosDbScriptGenerationMixin,
):
    """
    Translates pseudo-SQL statements to Azure SDK operations for CosmosDB.

    This translator enables operations that require Azure SDK (like DROP CONTAINER,
    ALTER CONTAINER properties, throughput management, index management) to be
    represented as pseudo-SQL and then executed via the SDK.

    This provides a DBA-friendly SQL-like interface while handling the SDK complexity
    internally.
    """

    # Patterns that require SDK translation (not native SQL API)
    SDK_PATTERNS = [
        "DROP CONTAINER",
        "ALTER CONTAINER",
        "UPDATE CONTAINER",
        "SET CONTAINER",
        "SET THROUGHPUT",
        "SET AUTOSCALE",
        "SHOW THROUGHPUT",
        "CREATE INDEX",
        "DROP INDEX",
        "EXCLUDE INDEX",
        "INCLUDE INDEX",
        "SET TTL",
    ]

    def __init__(self, connection_manager: Any = None, log: Optional[logging.Logger] = None):
        """Initialize the translator.

        Args:
            connection_manager: CosmosDbConnectionManager instance (optional, needed for execution)
            log: Optional logger
        """
        self.connection_manager = connection_manager
        self.log = log or logger
        # Cache for storing previous state (used for undo generation)
        self._state_cache: Dict[str, Any] = {}

    def can_translate(self, statement: SqlStatement) -> bool:
        """Check if a statement can be translated to SDK operations.

        Args:
            statement: SQL statement to check

        Returns:
            True if statement can be translated
        """
        if statement.dialect.lower() != "cosmosdb":  # lint: allow-dialect-string: dialect dispatch
            return False

        sql_upper = statement.sql.upper().strip()
        # Check for pseudo-SQL patterns that need SDK translation
        return any(sql_upper.startswith(pattern) for pattern in self.SDK_PATTERNS)

    # Dispatch table mapping SQL prefix → translator method name.
    # Entries are checked in order; the first matching prefix wins.
    _TRANSLATION_DISPATCH: List[tuple[str, str]] = [
        # Container operations
        ("DROP CONTAINER", "_translate_drop_container"),
        ("ALTER CONTAINER", "_translate_alter_container"),
        ("UPDATE CONTAINER", "_translate_alter_container"),
        ("SET CONTAINER", "_translate_set_container"),
        # Throughput operations
        ("SET THROUGHPUT", "_translate_set_throughput"),
        ("SET AUTOSCALE", "_translate_set_autoscale"),
        ("SHOW THROUGHPUT", "_translate_show_throughput"),
        # Index operations
        ("CREATE INDEX", "_translate_create_index"),
        ("DROP INDEX", "_translate_drop_index"),
        ("EXCLUDE INDEX", "_translate_exclude_index_path"),
        ("INCLUDE INDEX", "_translate_include_index_path"),
        # TTL operations
        ("SET TTL", "_translate_set_ttl"),
    ]

    def translate_to_sdk_operation(self, statement: SqlStatement) -> Optional[Dict[str, Any]]:
        """Translate a pseudo-SQL statement to an SDK operation.

        Args:
            statement: SQL statement to translate

        Returns:
            Dictionary with SDK operation details, or None if not translatable
            Format:
            {
                "operation": str,  # Operation type
                "container_name": str,
                "parameters": dict,  # SDK-specific parameters
                "python_code": str,  # Python code snippet for execution
                "description": str,  # Human-readable description
                "warning": Optional[str],  # Warning message if destructive
                "note": Optional[str],  # Additional notes
                "undo_sql": Optional[str],  # SQL to undo this operation
            }
        """
        if not self.can_translate(statement):
            return None

        sql_upper = statement.sql.upper().strip()

        for prefix, method_name in self._TRANSLATION_DISPATCH:
            if sql_upper.startswith(prefix):
                handler = getattr(self, method_name)
                return cast(Optional[Dict[str, Any]], handler(statement))

        return None
