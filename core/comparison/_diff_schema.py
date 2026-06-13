"""Schema diff: ``SchemaDiff`` aggregate.

Extracted from ``diff_models.py`` (PR-G4). ``SchemaDiff`` aggregates lists
of every other ``*Diff`` subclass.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List

from core.comparison._diff_base import DiffResult, DiffSeverity
from core.comparison._diff_index import IndexDiff
from core.comparison._diff_routine import FunctionDiff, ProcedureDiff
from core.comparison._diff_simple import (
    DatabaseLinkDiff,
    EventDiff,
    ExtensionDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    LinkedServerDiff,
    ModuleDiff,
    PackageDiff,
    SequenceDiff,
    SynonymDiff,
    TriggerDiff,
    UserDefinedTypeDiff,
)
from core.comparison._diff_table import TableDiff
from core.comparison._diff_view import ViewDiff


@dataclass
class SchemaDiff(DiffResult):
    """Represents schema-level comparison results.

    Attributes:
        schema_name: Name of the schema
        missing_tables: Tables in expected but not in actual
        extra_tables: Tables in actual but not in expected
        modified_tables: Tables with differences
        missing_views: Views in expected but not in actual
        extra_views: Views in actual but not in expected
        modified_views: Views with differences
        missing_indexes: Indexes in expected but not in actual
        extra_indexes: Indexes in actual but not in expected
        modified_indexes: Indexes with differences
        missing_sequences: Sequences in expected but not in actual
        extra_sequences: Sequences in actual but not in expected
        modified_sequences: Sequences with differences
        missing_triggers: Triggers in expected but not in actual
        extra_triggers: Triggers in actual but not in expected
        modified_triggers: Triggers with differences
        missing_procedures: Procedures in expected but not in actual
        extra_procedures: Procedures in actual but not in expected
        modified_procedures: Procedures with differences
        missing_functions: Functions in expected but not in actual
        extra_functions: Functions in actual but not in expected
        modified_functions: Functions with differences
        missing_synonyms: Synonyms in expected but not in actual
        extra_synonyms: Synonyms in actual but not in expected
        modified_synonyms: Synonyms with differences
        missing_packages: Packages in expected but not in actual
        extra_packages: Packages in actual but not in expected
        modified_packages: Packages with differences
        missing_extensions: Extensions in expected but not in actual
        extra_extensions: Extensions in actual but not in expected
        modified_extensions: Extensions with differences
        missing_events: Events in expected but not in actual
        extra_events: Events in actual but not in expected
        modified_events: Events with differences
        missing_user_defined_types: User-defined types in expected but not in actual
        extra_user_defined_types: User-defined types in actual but not in expected
        modified_user_defined_types: User-defined types with differences
    """

    _name_field: ClassVar[str] = "schema_name"
    _object_type_label: ClassVar[str] = "schema"

    schema_name: str = ""
    missing_tables: List[str] = field(default_factory=list)
    extra_tables: List[str] = field(default_factory=list)
    modified_tables: List[TableDiff] = field(default_factory=list)
    missing_views: List[str] = field(default_factory=list)
    extra_views: List[str] = field(default_factory=list)
    modified_views: List[ViewDiff] = field(default_factory=list)
    missing_indexes: List[str] = field(default_factory=list)
    extra_indexes: List[str] = field(default_factory=list)
    modified_indexes: List[IndexDiff] = field(default_factory=list)
    missing_sequences: List[str] = field(default_factory=list)
    extra_sequences: List[str] = field(default_factory=list)
    modified_sequences: List[SequenceDiff] = field(default_factory=list)
    missing_triggers: List[str] = field(default_factory=list)
    extra_triggers: List[str] = field(default_factory=list)
    modified_triggers: List[TriggerDiff] = field(default_factory=list)
    missing_procedures: List[str] = field(default_factory=list)
    extra_procedures: List[str] = field(default_factory=list)
    modified_procedures: List[ProcedureDiff] = field(default_factory=list)
    missing_functions: List[str] = field(default_factory=list)
    extra_functions: List[str] = field(default_factory=list)
    modified_functions: List[FunctionDiff] = field(default_factory=list)
    missing_synonyms: List[str] = field(default_factory=list)
    extra_synonyms: List[str] = field(default_factory=list)
    modified_synonyms: List[SynonymDiff] = field(default_factory=list)
    missing_packages: List[str] = field(default_factory=list)
    extra_packages: List[str] = field(default_factory=list)
    modified_packages: List["PackageDiff"] = field(default_factory=list)
    missing_modules: List[str] = field(default_factory=list)
    extra_modules: List[str] = field(default_factory=list)
    modified_modules: List["ModuleDiff"] = field(default_factory=list)
    missing_database_links: List[str] = field(default_factory=list)
    extra_database_links: List[str] = field(default_factory=list)
    modified_database_links: List[DatabaseLinkDiff] = field(default_factory=list)
    missing_linked_servers: List[str] = field(default_factory=list)
    extra_linked_servers: List[str] = field(default_factory=list)
    modified_linked_servers: List[LinkedServerDiff] = field(default_factory=list)
    missing_foreign_data_wrappers: List[str] = field(default_factory=list)
    extra_foreign_data_wrappers: List[str] = field(default_factory=list)
    modified_foreign_data_wrappers: List[ForeignDataWrapperDiff] = field(default_factory=list)
    missing_foreign_servers: List[str] = field(default_factory=list)
    extra_foreign_servers: List[str] = field(default_factory=list)
    modified_foreign_servers: List[ForeignServerDiff] = field(default_factory=list)
    missing_extensions: List[str] = field(default_factory=list)
    extra_extensions: List[str] = field(default_factory=list)
    modified_extensions: List[ExtensionDiff] = field(default_factory=list)
    missing_events: List[str] = field(default_factory=list)
    extra_events: List[str] = field(default_factory=list)
    modified_events: List[EventDiff] = field(default_factory=list)
    missing_user_defined_types: List[str] = field(default_factory=list)
    extra_user_defined_types: List[str] = field(default_factory=list)
    modified_user_defined_types: List[UserDefinedTypeDiff] = field(default_factory=list)

    _MISSING_ERROR_PREFIXES = {
        "tables",
        "views",
        "procedures",
        "functions",
        "packages",
        "user_defined_types",
    }

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self.has_diffs = any(
            getattr(self, f"{action}_{prefix}", [])
            for prefix, _ in self._OBJECT_TYPE_LABELS
            for action in ("missing", "extra", "modified")
        )

        if not self.has_diffs:
            return

        has_error = False

        # Missing critical types are always errors
        if any(getattr(self, f"missing_{prefix}", []) for prefix in self._MISSING_ERROR_PREFIXES):
            has_error = True

        if self.extra_user_defined_types:
            has_error = True

        # Check all modified objects for ERROR severity
        if not has_error:
            for prefix, _ in self._OBJECT_TYPE_LABELS:
                for diff_obj in getattr(self, f"modified_{prefix}", []):
                    if diff_obj.severity == DiffSeverity.ERROR:
                        has_error = True
                        break
                if has_error:
                    break

        self.severity = DiffSeverity.ERROR if has_error else DiffSeverity.WARNING

    def get_diff_count(self) -> Dict[str, int]:
        """Get count of each type of difference.

        Returns:
            Dictionary with counts of different types
        """
        result = {}
        for prefix, _ in self._OBJECT_TYPE_LABELS:
            for action in ("missing", "extra", "modified"):
                key = f"{action}_{prefix}"
                result[key] = len(getattr(self, key, []))
        return result

    def get_total_diff_count(self) -> int:
        """Get total count of all differences.

        Returns:
            Total number of differences
        """
        counts = self.get_diff_count()
        return sum(counts.values())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = super().to_dict()
        result["schema_name"] = self.schema_name
        for prefix, _ in self._OBJECT_TYPE_LABELS:
            for action in ("missing", "extra"):
                key = f"{action}_{prefix}"
                result[key] = getattr(self, key, [])
            key = f"modified_{prefix}"
            result[key] = [obj.to_dict() for obj in getattr(self, key, [])]
        result["diff_count"] = self.get_diff_count()
        result["total_diff_count"] = self.get_total_diff_count()
        return result

    # Object type labels for __str__ formatting: (key_prefix, display_label)
    _OBJECT_TYPE_LABELS = [
        ("tables", "table(s)"),
        ("views", "view(s)"),
        ("indexes", "index(es)"),
        ("sequences", "sequence(s)"),
        ("triggers", "trigger(s)"),
        ("procedures", "procedure(s)"),
        ("functions", "function(s)"),
        ("synonyms", "synonym(s)"),
        ("packages", "package(s)"),
        ("modules", "module(s)"),
        ("database_links", "database link(s)"),
        ("linked_servers", "linked server(s)"),
        ("foreign_data_wrappers", "foreign data wrapper(s)"),
        ("foreign_servers", "foreign server(s)"),
        ("extensions", "extension(s)"),
        ("events", "event(s)"),
        ("user_defined_types", "user-defined type(s)"),
    ]

    def __str__(self) -> str:
        """Human-readable string representation."""
        if not self.has_diffs:
            return f"Schema '{self.schema_name}': No differences"

        parts = []
        counts = self.get_diff_count()

        for key_prefix, label in self._OBJECT_TYPE_LABELS:
            for action in ("missing", "extra", "modified"):
                key = f"{action}_{key_prefix}"
                if counts.get(key):
                    parts.append(f"{counts[key]} {action} {label}")

        total = self.get_total_diff_count()
        return f"Schema '{self.schema_name}' [{self.severity.value}]: {total} difference(s) - {', '.join(parts)}"
