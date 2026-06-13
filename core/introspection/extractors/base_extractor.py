"""Base class for object extractors."""

from abc import ABC
from typing import Any, Dict, List, Optional

from core.introspection._utils import get_row_value, parse_json_array, to_int
from core.logger import NullLog
from db.value_utils import to_python_string


class BaseExtractor(ABC):
    """
    Base class for extracting database objects.

    This class provides common functionality for all extractors, including:
    - Row value extraction
    - Database-specific override hooks
    - Connection and metadata management

    Subclasses should implement database-specific logic by overriding
    the appropriate hook methods.
    """

    dialect: str

    def __init__(
        self,
        provider: Any,
        connection: Any = None,
        metadata: Any = None,
        vendor_queries: Any = None,
        dialect: str = "unknown",
        log: Any = None,
        result_tracker: Any = None,
    ) -> None:
        """
        Initialize the base extractor.

        Args:
            provider: Database provider
            connection: Optional database connection
            metadata: Optional database metadata object
            vendor_queries: Optional vendor-specific queries instance
            dialect: Database dialect name
            log: Optional logger instance
            result_tracker: Optional result tracking instance (BaseIntrospector)
        """
        self.provider = provider
        self.connection = connection
        self.metadata = metadata
        self.vendor_queries = vendor_queries
        self.dialect = dialect
        self.log = log if log is not None else NullLog()
        self.result_tracker = result_tracker

    def ensure_metadata(self) -> None:
        """Ensure an active provider connection is available."""
        if self.connection is None or getattr(self.connection, "closed", False):
            provider_declares_connection = "connection" in vars(self.provider) or isinstance(
                getattr(type(self.provider), "connection", None), property
            )
            provider_connection = (
                getattr(self.provider, "connection", None) if provider_declares_connection else None
            )
            if provider_connection is not None and not getattr(
                provider_connection, "closed", False
            ):
                self.connection = provider_connection
                return
            self.connection = self.provider.create_connection()

    def get_row_value(self, row: Dict[str, Any], key: str) -> Any:
        """
        Get value from row dictionary.

        This method can be overridden by database-specific extractors
        to handle dialect-specific column name variations.

        Args:
            row: Dictionary from query result
            key: Column name to look up

        Returns:
            Value from the row, or None if not found
        """
        return get_row_value(row, key)

    def parse_json_array(self, raw_value: Any) -> List[Any]:
        """Parse a JSON array payload."""
        return parse_json_array(raw_value)

    def to_int(self, value: Any) -> Optional[int]:
        """Convert value to integer."""
        return to_int(value)

    def to_python_string(self, value: Any) -> Optional[str]:
        """Convert driver value to Python string."""
        return to_python_string(value)

    def track_warning(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Track a warning if result tracking is enabled."""
        if self.result_tracker:
            self.result_tracker._track_warning(
                message, object_type, object_name, property_name, exception
            )

    def track_error(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Track an error if result tracking is enabled."""
        if self.result_tracker:
            self.result_tracker._track_error(
                message, object_type, object_name, property_name, exception
            )

    def track_object_status(
        self,
        object_type: str,
        object_name: str,
        schema: Optional[str] = None,
        captured: bool = True,
    ) -> Any:
        """Track object capture status if result tracking is enabled."""
        if self.result_tracker:
            return self.result_tracker._track_object_status(
                object_type, object_name, schema, captured
            )
        return None

    # Database-specific override hooks live in concrete extractors.
