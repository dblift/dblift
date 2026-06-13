"""Simple per-pattern diffs.

Extracted from ``diff_models.py`` (PR-G4). Each class here follows the
homogeneous "field-set ⇒ fixed severity" pattern via
``DiffResult._set_severity_from_pairs``. Subclasses with bespoke severity
logic (TableDiff, ConstraintDiff, IndexDiff, ViewDiff, ProcedureDiff,
FunctionDiff) live in their own modules.
"""

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from core.comparison._diff_base import DiffResult, DiffSeverity


@dataclass
class SequenceDiff(DiffResult):
    """Represents differences in a sequence definition.

    Attributes:
        sequence_name: Name of the sequence
        start_value_changed: Whether start value changed
        increment_changed: Whether increment changed
        min_value_changed: Whether minimum value changed
        max_value_changed: Whether maximum value changed
        cycle_changed: Whether cycle option changed
        temp_changed: Whether TEMPORARY status changed (PostgreSQL grammar-based)
    """

    _name_field: ClassVar[str] = "sequence_name"
    _object_type_label: ClassVar[str] = "sequence"

    sequence_name: str = ""
    start_value_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    increment_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    min_value_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    max_value_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    cycle_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    temp_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: PostgreSQL TEMPORARY sequences
    )
    owned_by_changed: Optional[Tuple[Any, Any]] = None  # ((table, column), (table, column))

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.start_value_changed, DiffSeverity.INFO),
                (self.increment_changed, DiffSeverity.INFO),
                (self.min_value_changed, DiffSeverity.ERROR),
                (self.max_value_changed, DiffSeverity.ERROR),
                (self.cycle_changed, DiffSeverity.INFO),
                # Grammar-based: PostgreSQL TEMPORARY sequence changes.
                (self.temp_changed, DiffSeverity.INFO),
                (self.owned_by_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class TriggerDiff(DiffResult):
    """Represents differences in a trigger definition.

    Attributes:
        trigger_name: Name of the trigger
        table_name: Table the trigger is attached to
        timing_changed: Whether timing changed (BEFORE/AFTER/INSTEAD OF, grammar-based)
        event_changed: Whether event changed (INSERT/UPDATE/DELETE/TRUNCATE, grammar-based)
        constraint_trigger_changed: Whether constraint trigger status changed (PostgreSQL, grammar-based)
        definer_changed: Whether definer changed (MySQL grammar-based: user@host)
        definition_changed: Whether trigger body changed
        enabled_changed: Whether enabled status changed
    """

    _name_field: ClassVar[str] = "trigger_name"
    _object_type_label: ClassVar[str] = "trigger"

    trigger_name: str = ""
    table_name: str = ""
    timing_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: Supports INSTEAD OF
    )
    event_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: Supports TRUNCATE
    )
    constraint_trigger_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: CONSTRAINT TRIGGER
    )
    definer_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - Grammar-based: MySQL definer
    )
    definition_changed: bool = False
    enabled_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    function_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - target function
    function_schema_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - function schema
    )
    function_arguments_changed: Optional[Tuple[Any, Any]] = (
        None  # (expected, actual) - function arguments signature
    )
    when_clause_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - WHEN condition
    constraint_deferrable_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    constraint_initially_deferred_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                # Structural changes — break consumers.
                (self.timing_changed, DiffSeverity.ERROR),
                (self.event_changed, DiffSeverity.ERROR),
                (self.function_changed, DiffSeverity.ERROR),
                (self.function_schema_changed, DiffSeverity.ERROR),
                (self.function_arguments_changed, DiffSeverity.ERROR),
                # Grammar-based: PostgreSQL CONSTRAINT TRIGGER.
                (self.constraint_trigger_changed, DiffSeverity.ERROR),
                # State / metadata changes — non-breaking.
                # Grammar-based: MySQL user@host definer.
                (self.definer_changed, DiffSeverity.WARNING),
                (self.definition_changed, DiffSeverity.WARNING),
                (self.enabled_changed, DiffSeverity.WARNING),
                (self.when_clause_changed, DiffSeverity.WARNING),
                (self.constraint_deferrable_changed, DiffSeverity.WARNING),
                (self.constraint_initially_deferred_changed, DiffSeverity.WARNING),
            ]
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = super().to_dict()
        result.update(
            {
                "trigger_name": self.trigger_name,
                "table_name": self.table_name,
                "timing_changed": self.timing_changed,
                "event_changed": self.event_changed,
                "constraint_trigger_changed": self.constraint_trigger_changed,  # Grammar-based: CONSTRAINT TRIGGER
                "definer_changed": self.definer_changed,  # Grammar-based: MySQL definer
                "definition_changed": self.definition_changed,
                "enabled_changed": self.enabled_changed,
                "function_changed": self.function_changed,
                "function_schema_changed": self.function_schema_changed,
                "function_arguments_changed": self.function_arguments_changed,
                "when_clause_changed": self.when_clause_changed,
                "constraint_deferrable_changed": self.constraint_deferrable_changed,
                "constraint_initially_deferred_changed": self.constraint_initially_deferred_changed,
            }
        )
        return result


@dataclass
class SynonymDiff(DiffResult):
    """Represents differences in a synonym definition.

    Attributes:
        synonym_name: Name of the synonym
        target_changed: Whether the target object changed
        target_schema_changed: Whether the target schema changed
        target_database_changed: Whether the target database changed (SQL Server)
        db_link_changed: Whether the database link changed (Oracle)
        expected_target: Expected target object
        actual_target: Actual target object
    """

    _name_field: ClassVar[str] = "synonym_name"
    _object_type_label: ClassVar[str] = "synonym"

    synonym_name: str = ""
    target_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    target_schema_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    target_database_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    db_link_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    expected_target: Optional[str] = None
    actual_target: Optional[str] = None

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.target_changed, DiffSeverity.ERROR),
                (self.target_schema_changed, DiffSeverity.ERROR),
                (self.target_database_changed, DiffSeverity.WARNING),
                (self.db_link_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class PackageDiff(DiffResult):
    """Represents differences in a package definition (Oracle).

    Attributes:
        package_name: Name of the package
        spec_changed: Whether package specification changed
        body_changed: Whether package body changed
        expected_spec: Expected package specification
        actual_spec: Actual package specification
        expected_body: Expected package body
        actual_body: Actual package body
    """

    _name_field: ClassVar[str] = "package_name"
    _object_type_label: ClassVar[str] = "package"

    package_name: str = ""
    spec_changed: bool = False
    body_changed: bool = False
    expected_spec: Optional[str] = None
    actual_spec: Optional[str] = None
    expected_body: Optional[str] = None
    actual_body: Optional[str] = None

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.spec_changed, DiffSeverity.ERROR),
                (self.body_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class DatabaseLinkDiff(DiffResult):
    """Represents differences in a database link definition (Oracle).

    Attributes:
        link_name: Name of the database link
        host_changed: Whether the host/connect string changed
        username_changed: Whether the username changed
        public_changed: Whether the public/private status changed
        expected_host: Expected host/connect string
        actual_host: Actual host/connect string
    """

    _name_field: ClassVar[str] = "link_name"
    _object_type_label: ClassVar[str] = "database_link"

    link_name: str = ""
    host_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    username_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    public_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    expected_host: Optional[str] = None
    actual_host: Optional[str] = None

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.host_changed, DiffSeverity.ERROR),
                (self.username_changed, DiffSeverity.ERROR),
                (self.public_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class LinkedServerDiff(DiffResult):
    """Represents differences in a linked server definition (SQL Server).

    Attributes:
        server_name: Name of the linked server
        product_changed: Whether the product name changed
        provider_changed: Whether the provider changed
        data_source_changed: Whether the data source changed
        catalog_changed: Whether the catalog changed
        username_changed: Whether the username changed
    """

    _name_field: ClassVar[str] = "server_name"
    _object_type_label: ClassVar[str] = "linked_server"

    server_name: str = ""
    product_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    provider_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    data_source_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    catalog_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    username_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.product_changed, DiffSeverity.ERROR),
                (self.provider_changed, DiffSeverity.ERROR),
                (self.data_source_changed, DiffSeverity.ERROR),
                (self.username_changed, DiffSeverity.ERROR),
                (self.catalog_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class ModuleDiff(DiffResult):
    """Represents differences in a DB2 module definition.

    Attributes:
        module_name: Name of the module
        definition_changed: Whether the module definition changed
    """

    _name_field: ClassVar[str] = "module_name"
    _object_type_label: ClassVar[str] = "module"

    module_name: str = ""
    definition_changed: bool = False

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        # Module changes require recreating the module — non-breaking → WARNING.
        self._set_severity_from_pairs(
            [
                (self.definition_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class ForeignDataWrapperDiff(DiffResult):
    """Represents differences in a foreign data wrapper definition (PostgreSQL).

    Attributes:
        fdw_name: Name of the foreign data wrapper
        handler_changed: Whether the handler function changed
        validator_changed: Whether the validator function changed
        options_changed: Whether the FDW options changed
    """

    _name_field: ClassVar[str] = "fdw_name"
    _object_type_label: ClassVar[str] = "foreign_data_wrapper"

    fdw_name: str = ""
    handler_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    validator_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    options_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.handler_changed, DiffSeverity.ERROR),
                (self.validator_changed, DiffSeverity.ERROR),
                (self.options_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class ForeignServerDiff(DiffResult):
    """Represents differences in a foreign server definition (PostgreSQL).

    Attributes:
        server_name: Name of the foreign server
        fdw_changed: Whether the FDW name changed
        host_changed: Whether the host changed
        port_changed: Whether the port changed
        dbname_changed: Whether the database name changed
        options_changed: Whether server options changed
    """

    _name_field: ClassVar[str] = "server_name"
    _object_type_label: ClassVar[str] = "foreign_server"

    server_name: str = ""
    fdw_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    host_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    port_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    dbname_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    options_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.fdw_changed, DiffSeverity.ERROR),
                (self.host_changed, DiffSeverity.ERROR),
                (self.port_changed, DiffSeverity.ERROR),
                (self.dbname_changed, DiffSeverity.WARNING),
                (self.options_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class ExtensionDiff(DiffResult):
    """Represents differences in an extension definition (PostgreSQL).

    Attributes:
        extension_name: Name of the extension
        version_changed: Whether the extension version changed
        schema_changed: Whether the extension schema changed
        expected_version: Expected extension version
        actual_version: Actual extension version
    """

    _name_field: ClassVar[str] = "extension_name"
    _object_type_label: ClassVar[str] = "extension"

    extension_name: str = ""
    version_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    schema_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    expected_version: Optional[str] = None
    actual_version: Optional[str] = None

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        # version_changed seul → WARNING (ALTER EXTENSION … UPDATE TO …);
        # schema_changed → ERROR.
        self._set_severity_from_pairs(
            [
                (self.schema_changed, DiffSeverity.ERROR),
                (self.version_changed, DiffSeverity.WARNING),
            ]
        )


@dataclass
class EventDiff(DiffResult):
    """Represents differences in an event definition (MySQL).

    Attributes:
        event_name: Name of the event
        definition_changed: Whether the event body changed
        schedule_changed: Whether the event schedule changed
        enabled_changed: Whether the enabled status changed
        event_type_changed: Whether the event type changed (ONE TIME/RECURRING)
    """

    _name_field: ClassVar[str] = "event_name"
    _object_type_label: ClassVar[str] = "event"

    event_name: str = ""
    definition_changed: bool = False
    schedule_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    enabled_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    event_type_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    definer_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - MySQL: user@host
    comment_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - MySQL: COMMENT clause

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        # definition / event_type / schedule are body-shape changes → WARNING.
        # enabled / definer / comment alone are state-only → INFO.
        self._set_severity_from_pairs(
            [
                (self.definition_changed, DiffSeverity.WARNING),
                (self.event_type_changed, DiffSeverity.WARNING),
                (self.schedule_changed, DiffSeverity.WARNING),
                (self.enabled_changed, DiffSeverity.INFO),
                (self.definer_changed, DiffSeverity.INFO),
                (self.comment_changed, DiffSeverity.INFO),
            ]
        )


@dataclass
class UserDefinedTypeDiff(DiffResult):
    """Represents differences in a user-defined type definition.

    Attributes:
        type_name: Name of the user-defined type
        type_category_changed: Whether the type category changed (COMPOSITE, ENUM, DOMAIN, etc.)
        base_type_changed: Whether the base type changed (for DOMAIN/DISTINCT types)
        attributes_changed: Whether composite type attributes changed
        enum_values_changed: Whether enum values changed
        definition_changed: Whether the type definition changed
        expected_type_category: Expected type category
        actual_type_category: Actual type category
        expected_base_type: Expected base type
        actual_base_type: Actual base type
    """

    _name_field: ClassVar[str] = "type_name"
    _object_type_label: ClassVar[str] = "user_defined_type"

    type_name: str = ""
    type_category_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    base_type_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    attributes_changed: bool = False
    enum_values_changed: bool = False
    definition_changed: bool = False
    expected_type_category: Optional[str] = None
    actual_type_category: Optional[str] = None
    expected_base_type: Optional[str] = None
    actual_base_type: Optional[str] = None
    expected_attributes: Optional[List[Any]] = None
    actual_attributes: Optional[List[Any]] = None
    expected_enum_values: Optional[List[Any]] = None
    actual_enum_values: Optional[List[Any]] = None

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        # Type category and base type changes are breaking → ERROR.
        # Attribute / enum value / definition changes are non-breaking → WARNING.
        self._set_severity_from_pairs(
            [
                (self.type_category_changed, DiffSeverity.ERROR),
                (self.base_type_changed, DiffSeverity.ERROR),
                (self.attributes_changed, DiffSeverity.WARNING),
                (self.enum_values_changed, DiffSeverity.WARNING),
                (self.definition_changed, DiffSeverity.WARNING),
            ]
        )
