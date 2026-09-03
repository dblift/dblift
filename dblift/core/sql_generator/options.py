"""Configuration options for SQL script generation."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set


class OrganizationStrategy(Enum):
    """File organization strategies for generated SQL scripts."""

    SINGLE_FILE = "single_file"
    """All objects in one file"""

    BY_TYPE = "by_type"
    """One file per object type (tables.sql, views.sql, etc.)"""

    BY_OBJECT = "by_object"
    """One file per object (users_table.sql, orders_table.sql)"""

    BY_SCHEMA = "by_schema"
    """Organized by schema (public/schema.sql, sales/schema.sql)"""

    BY_DEPENDENCY = "by_dependency"
    """Grouped by dependency chains"""


class OutputFormat(Enum):
    """Output format for generated SQL."""

    SQL = "sql"
    """Standard SQL script files"""

    SQL_WITH_COMMENTS = "sql_comments"
    """SQL with header comments and documentation"""


@dataclass
class ScriptOptions:
    """Configuration options for SQL script generation.

    Attributes:
        organization: How to organize generated files
        format: Output format for SQL
        include_comments: Include comments and documentation
        include_drops: Include DROP statements
        format_sql: Apply SQL formatting (pretty print)
        indent_width: Number of spaces for indentation
        include_object_types: Set of object types to include (None = all)
        exclude_object_types: Set of object types to exclude
    """

    organization: OrganizationStrategy = OrganizationStrategy.BY_TYPE
    format: OutputFormat = OutputFormat.SQL_WITH_COMMENTS
    include_comments: bool = True
    include_drops: bool = False
    format_sql: bool = True
    indent_width: int = 2
    include_object_types: Optional[Set[str]] = None
    exclude_object_types: Optional[Set[str]] = field(default_factory=set)
