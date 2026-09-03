"""``ParseResult`` — rich result container for SQL parsing operations.

This module is part of the ``dblift.core.sql_model.base`` split (PR-H13). Public
import paths should continue to use ``from core.sql_model.base import ...``;
this module is re-exported by the ``base`` façade.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from dblift.core.sql_model._base_sql_object import SqlObject
from dblift.core.sql_model._base_sql_statement import SqlStatement

if TYPE_CHECKING:
    from dblift.core.sql_model.database_link import DatabaseLink
    from dblift.core.sql_model.event import Event
    from dblift.core.sql_model.extension import Extension
    from dblift.core.sql_model.foreign_data_wrapper import ForeignDataWrapper
    from dblift.core.sql_model.foreign_server import ForeignServer
    from dblift.core.sql_model.index import Index
    from dblift.core.sql_model.package import Package
    from dblift.core.sql_model.partition import Partition
    from dblift.core.sql_model.procedure import Procedure
    from dblift.core.sql_model.sequence import Sequence
    from dblift.core.sql_model.synonym import Synonym
    from dblift.core.sql_model.table import Table
    from dblift.core.sql_model.trigger import Trigger
    from dblift.core.sql_model.user_defined_type import UserDefinedType
    from dblift.core.sql_model.view import View


@dataclass
class ParseResult:
    """Result of SQL parsing operation.

    This class provides comprehensive parsing results including:
    - Basic statements list (existing)
    - Rich SQL Model objects (tables, views, indexes, etc.)
    - Dependency information between objects
    - Enhanced metadata for validation and analysis
    """

    success: bool
    statements: Optional[List[SqlStatement]] = None
    errors: Optional[List[str]] = None

    # Enhanced: Rich SQL Model objects
    tables: Optional[List["Table"]] = None
    views: Optional[List["View"]] = None
    indexes: Optional[List["Index"]] = None
    sequences: Optional[List["Sequence"]] = None
    procedures: Optional[List["Procedure"]] = None
    triggers: Optional[List["Trigger"]] = None
    functions: Optional[List["Procedure"]] = None  # Functions are stored as procedures
    synonyms: Optional[List["Synonym"]] = None
    user_defined_types: Optional[List["UserDefinedType"]] = None
    packages: Optional[List["Package"]] = None
    events: Optional[List["Event"]] = None
    extensions: Optional[List["Extension"]] = None
    foreign_data_wrappers: Optional[List["ForeignDataWrapper"]] = None
    foreign_servers: Optional[List["ForeignServer"]] = None
    partitions: Optional[List["Partition"]] = None
    database_links: Optional[List["DatabaseLink"]] = None

    # Enhanced: Dependency tracking
    dependencies: Optional[Dict[str, List[str]]] = None

    def __init__(
        self,
        success: bool,
        statements: Optional[List[SqlStatement]] = None,
        errors: Optional[List[str]] = None,
    ):
        """Initialize a parse result.

        Args:
            success: Whether parsing was successful
            statements: Parsed statements (if successful)
            errors: Error messages (if unsuccessful)
        """
        self.success = success
        self.statements = statements or []
        self.errors = errors or []

        # Initialize rich SQL Model collections
        self.tables = []
        self.views = []
        self.indexes = []
        self.sequences = []
        self.procedures = []
        self.triggers = []
        self.functions = []
        self.synonyms = []
        self.user_defined_types = []
        self.packages = []
        self.events = []
        self.extensions = []
        self.foreign_data_wrappers = []
        self.foreign_servers = []
        self.database_links = []

        # Initialize dependency tracking
        self.dependencies = {}

    def __bool__(self) -> bool:
        """Return success status."""
        return self.success

    # Enhanced: Methods to add SQL Model objects

    def add_table(self, table: "Table") -> None:
        """Add a table to the parse result.

        Args:
            table: Table object to add
        """
        if self.tables is None:
            self.tables = []
        self.tables.append(table)

    def add_view(self, view: "View") -> None:
        """Add a view to the parse result.

        Args:
            view: View object to add
        """
        if self.views is None:
            self.views = []
        self.views.append(view)

    def add_index(self, index: "Index") -> None:
        """Add an index to the parse result.

        Args:
            index: Index object to add
        """
        if self.indexes is None:
            self.indexes = []
        self.indexes.append(index)

    def add_sequence(self, sequence: "Sequence") -> None:
        """Add a sequence to the parse result.

        Args:
            sequence: Sequence object to add
        """
        if self.sequences is None:
            self.sequences = []
        self.sequences.append(sequence)

    def add_procedure(self, procedure: "Procedure") -> None:
        """Add a procedure to the parse result.

        Args:
            procedure: Procedure object to add
        """
        if self.procedures is None:
            self.procedures = []
        self.procedures.append(procedure)

    def add_trigger(self, trigger: "Trigger") -> None:
        """Add a trigger to the parse result.

        Args:
            trigger: Trigger object to add
        """
        if self.triggers is None:
            self.triggers = []

        # Check for duplicates based on name and table
        for existing in self.triggers:
            if existing.name == trigger.name and existing.table_name == trigger.table_name:
                return  # Trigger already exists, don't add duplicate

        self.triggers.append(trigger)

    def add_function(self, function: "Procedure") -> None:
        """Add a function to the parse result.

        Args:
            function: Function object to add (stored as Procedure)
        """
        if self.functions is None:
            self.functions = []

        # Check for duplicates based on name and schema
        for existing in self.functions:
            if existing.name == function.name and existing.schema == function.schema:
                return  # Function already exists, don't add duplicate

        self.functions.append(function)

    def add_synonym(self, synonym: "Synonym") -> None:
        """Add a synonym to the parse result.

        Args:
            synonym: Synonym object to add
        """
        if self.synonyms is None:
            self.synonyms = []
        self.synonyms.append(synonym)

    def add_user_defined_type(self, user_type: "UserDefinedType") -> None:
        """Add a user-defined type to the parse result.

        Args:
            user_type: UserDefinedType object to add
        """
        if self.user_defined_types is None:
            self.user_defined_types = []
        self.user_defined_types.append(user_type)

    def add_package(self, package: "Package") -> None:
        """Add a package to the parse result.

        Args:
            package: Package object to add
        """
        if self.packages is None:
            self.packages = []

        normalized_name = package.name.lower() if package.name else ""
        normalized_schema = (package.schema or "").lower()

        for existing in self.packages:
            existing_name = existing.name.lower() if existing.name else ""
            existing_schema = (existing.schema or "").lower()

            if existing_name == normalized_name and existing_schema == normalized_schema:
                if package.spec:
                    existing.spec = package.spec
                if package.body:
                    existing.body = package.body
                return

        self.packages.append(package)

    def add_event(self, event: "Event") -> None:
        """Add an event to the parse result.

        Args:
            event: Event object to add
        """
        if self.events is None:
            self.events = []
        self.events.append(event)

    def add_extension(self, extension: "Extension") -> None:
        """Add an extension to the parse result.

        Args:
            extension: Extension object to add
        """
        if self.extensions is None:
            self.extensions = []
        self.extensions.append(extension)

    def add_foreign_data_wrapper(self, fdw: "ForeignDataWrapper") -> None:
        """Add a foreign data wrapper to the parse result.

        Args:
            fdw: ForeignDataWrapper object to add
        """
        if self.foreign_data_wrappers is None:
            self.foreign_data_wrappers = []
        self.foreign_data_wrappers.append(fdw)

    def add_foreign_server(self, foreign_server: "ForeignServer") -> None:
        """Add a foreign server to the parse result.

        Args:
            foreign_server: ForeignServer object to add
        """
        if self.foreign_servers is None:
            self.foreign_servers = []
        self.foreign_servers.append(foreign_server)

    def add_database_link(self, database_link: "DatabaseLink") -> None:
        """Add a database link to the parse result.

        Args:
            database_link: DatabaseLink object to add
        """
        if self.database_links is None:
            self.database_links = []
        self.database_links.append(database_link)

    def add_partition(self, partition: "Partition") -> None:
        """Add a partition to the parse result.

        Args:
            partition: Partition object to add
        """
        if self.partitions is None:
            self.partitions = []
        self.partitions.append(partition)

    def add_dependency(self, obj_name: str, depends_on: str) -> None:
        """Add a dependency relationship between objects.

        Args:
            obj_name: Name of the dependent object
            depends_on: Name of the object it depends on
        """
        if self.dependencies is None:
            self.dependencies = {}

        if obj_name not in self.dependencies:
            self.dependencies[obj_name] = []

        if depends_on not in self.dependencies[obj_name]:
            self.dependencies[obj_name].append(depends_on)

    def get_table(self, name: str) -> Optional["Table"]:
        """Get a table by name (case-insensitive).

        Args:
            name: Table name to search for

        Returns:
            Table object if found, None otherwise
        """
        if not self.tables:
            return None

        name_lower = name.lower()
        for table in self.tables:
            if table.name.lower() == name_lower:
                return table
        return None

    def get_view(self, name: str) -> Optional["View"]:
        """Get a view by name (case-insensitive).

        Args:
            name: View name to search for

        Returns:
            View object if found, None otherwise
        """
        if not self.views:
            return None

        name_lower = name.lower()
        for view in self.views:
            if view.name.lower() == name_lower:
                return view
        return None

    def get_all_objects(self) -> List[SqlObject]:
        """Get all SQL objects from this parse result.

        Returns:
            Combined list of all SQL objects (tables, views, indexes, etc.)
        """
        objects: List[SqlObject] = []

        if self.tables:
            objects.extend(self.tables)
        if self.views:
            objects.extend(self.views)
        if self.indexes:
            objects.extend(self.indexes)
        if self.sequences:
            objects.extend(self.sequences)
        if self.procedures:
            objects.extend(self.procedures)
        if self.triggers:
            objects.extend(self.triggers)
        if self.functions:
            objects.extend(self.functions)
        if self.synonyms:
            objects.extend(self.synonyms)
        if self.user_defined_types:
            objects.extend(self.user_defined_types)
        if self.packages:
            objects.extend(self.packages)
        if self.events:
            objects.extend(self.events)
        if self.extensions:
            objects.extend(self.extensions)

        return objects

    def get_dependencies_for(self, obj_name: str) -> List[str]:
        """Get all objects that the specified object depends on.

        Args:
            obj_name: Name of the object

        Returns:
            List of object names that obj_name depends on
        """
        if not self.dependencies:
            return []

        return self.dependencies.get(obj_name, [])

    def has_circular_dependencies(self) -> bool:
        """Check if there are circular dependencies in the parsed SQL.

        Returns:
            True if circular dependencies exist, False otherwise
        """
        if not self.dependencies:
            return False

        # Use depth-first search to detect cycles
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            # Type guard for mypy
            deps = self.dependencies
            if deps is not None:
                for neighbor in deps.get(node, []):
                    if neighbor not in visited:
                        if has_cycle(neighbor):
                            return True
                    elif neighbor in rec_stack:
                        return True

            rec_stack.remove(node)
            return False

        for node in self.dependencies.keys():
            if node not in visited:
                if has_cycle(node):
                    return True

        return False

    def get_summary(self) -> str:
        """Get a summary of the parse result.

        Returns:
            Human-readable summary string
        """
        summary_parts = []

        if self.statements:
            summary_parts.append(f"{len(self.statements)} statements")

        if self.tables:
            summary_parts.append(f"{len(self.tables)} tables")

        if self.views:
            summary_parts.append(f"{len(self.views)} views")

        if self.indexes:
            summary_parts.append(f"{len(self.indexes)} indexes")

        if self.sequences:
            summary_parts.append(f"{len(self.sequences)} sequences")

        if self.procedures:
            summary_parts.append(f"{len(self.procedures)} procedures")

        if self.triggers:
            summary_parts.append(f"{len(self.triggers)} triggers")

        if self.functions:
            summary_parts.append(f"{len(self.functions)} functions")

        if self.synonyms:
            summary_parts.append(f"{len(self.synonyms)} synonyms")

        if self.user_defined_types:
            summary_parts.append(f"{len(self.user_defined_types)} user-defined types")

        if self.packages:
            summary_parts.append(f"{len(self.packages)} packages")

        if self.events:
            summary_parts.append(f"{len(self.events)} events")

        if self.extensions:
            summary_parts.append(f"{len(self.extensions)} extensions")

        if self.dependencies:
            summary_parts.append(f"{len(self.dependencies)} dependencies")

        if self.errors:
            summary_parts.append(f"{len(self.errors)} errors")

        return ", ".join(summary_parts) if summary_parts else "Empty result"
