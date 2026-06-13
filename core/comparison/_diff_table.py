"""Table-related diffs: ``ColumnDiff``, ``ConstraintDiff``, ``TableDiff``.

Extracted from ``diff_models.py`` (PR-G4). These three classes are kept
together because ``TableDiff`` carries lists of ``ColumnDiff`` and
``ConstraintDiff`` and shares helper logic with them.
"""

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Tuple

from core.comparison._diff_base import DiffResult, DiffSeverity

if TYPE_CHECKING:
    from core.sql_model.table import Table


@dataclass
class ColumnDiff(DiffResult):
    """Represents differences in a column definition.

    Attributes:
        column_name: Name of the column
        data_type_diff: Data type differences (expected vs actual)
        nullable_diff: Nullability differences
        default_diff: Default value differences
        identity_diff: Identity column differences
        computed_diff: Computed column differences
    """

    _name_field: ClassVar[str] = "column_name"
    _object_type_label: ClassVar[str] = "column"

    column_name: str = ""
    data_type_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    nullable_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    default_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    identity_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    computed_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    collation_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual) - Diff-relevant

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self._set_severity_from_pairs(
            [
                (self.data_type_diff, DiffSeverity.ERROR),
                (self.nullable_diff, DiffSeverity.WARNING),
                (self.default_diff, DiffSeverity.WARNING),
                (self.identity_diff, DiffSeverity.ERROR),
                (self.computed_diff, DiffSeverity.WARNING),
                (self.collation_diff, DiffSeverity.WARNING),
            ]
        )

    def _tuple_diff_fields(self) -> Dict[str, Optional[Tuple[Any, Any]]]:
        """Return mapping of diff field names to their tuple values."""
        return {
            "data_type": self.data_type_diff,
            "nullable": self.nullable_diff,
            "default": self.default_diff,
            "identity": self.identity_diff,
            "computed": self.computed_diff,
            "collation": self.collation_diff,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = super().to_dict()
        result.update({"column_name": self.column_name, "differences": {}})
        self._add_tuple_diffs(result, self._tuple_diff_fields())
        return result

    def __str__(self) -> str:
        """Human-readable string representation."""
        if not self.has_diffs:
            return f"Column '{self.column_name}': No differences"

        diff_parts = self._format_tuple_diffs(self._tuple_diff_fields())
        return f"Column '{self.column_name}' [{self.severity.value}]: {', '.join(diff_parts)}"


@dataclass
class ConstraintDiff(DiffResult):
    """Represents differences in a constraint definition.

    Attributes:
        constraint_name: Name of the constraint
        constraint_type: Type of constraint (PK, FK, UNIQUE, CHECK)
        columns_diff: Differences in constrained columns
        references_diff: Differences in foreign key references
        check_clause_diff: Differences in CHECK constraint expressions
    """

    _name_field: ClassVar[str] = "constraint_name"
    _object_type_label: ClassVar[str] = "constraint"

    constraint_name: str = ""
    constraint_type: str = ""
    columns_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    references_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    check_clause_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual)
    enabled_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual) - Diff-relevant
    validated_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual) - Diff-relevant
    deferrable_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual) - Diff-relevant
    initially_deferred_diff: Optional[Tuple[Any, Any]] = None  # (expected, actual) - Diff-relevant

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        self.has_diffs = any(
            [
                self.columns_diff,
                self.references_diff,
                self.check_clause_diff,
                self.enabled_diff,
                self.validated_diff,
                self.deferrable_diff,
                self.initially_deferred_diff,
            ]
        )

        if self.has_diffs:
            # Structural differences (columns, references, check clause) are errors
            # Constraint state (enabled, validated) are errors - affects behavior significantly
            # Deferrable properties are warnings - affects behavior but less critical
            if (
                self.columns_diff
                or self.references_diff
                or self.check_clause_diff
                or self.enabled_diff
                or self.validated_diff
            ):
                self.severity = DiffSeverity.ERROR
            else:
                self.severity = DiffSeverity.WARNING

    def _tuple_diff_fields(self) -> Dict[str, Optional[Tuple[Any, Any]]]:
        """Return mapping of diff field names to their tuple values."""
        return {
            "columns": self.columns_diff,
            "references": self.references_diff,
            "check_clause": self.check_clause_diff,
            "enabled": self.enabled_diff,
            "validated": self.validated_diff,
            "deferrable": self.deferrable_diff,
            "initially_deferred": self.initially_deferred_diff,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = super().to_dict()
        result.update(
            {
                "constraint_name": self.constraint_name,
                "constraint_type": self.constraint_type,
                "differences": {},
            }
        )
        self._add_tuple_diffs(result, self._tuple_diff_fields())
        return result

    def __str__(self) -> str:
        """Human-readable string representation."""
        if not self.has_diffs:
            return f"Constraint '{self.constraint_name}' ({self.constraint_type}): No differences"

        # Use concise format for check_clause (can be very long SQL expressions)
        diff_parts = []
        for label, value in self._tuple_diff_fields().items():
            if value is not None:
                if label == "check_clause":
                    diff_parts.append("check clause differs")
                else:
                    diff_parts.append(f"{label}: {value[0]} → {value[1]}")
        return f"Constraint '{self.constraint_name}' ({self.constraint_type}) [{self.severity.value}]: {', '.join(diff_parts)}"


@dataclass
class TableDiff(DiffResult):
    """Represents differences in a table definition.

    Attributes:
        table_name: Name of the table
        missing_columns: Columns in expected but not in actual
        extra_columns: Columns in actual but not in expected
        modified_columns: Columns with differences
        missing_constraints: Constraints in expected but not in actual
        extra_constraints: Constraints in actual but not in expected
        modified_constraints: Constraints with differences
        missing_indexes: Indexes in expected but not in actual
        extra_indexes: Indexes in actual but not in expected
        temporary_changed: Whether temporary property changed (grammar-based enhancement)
        filegroup_changed: Whether filegroup changed (T-SQL grammar-based)
        memory_optimized_changed: Whether memory-optimized property changed (T-SQL grammar-based)
        system_versioned_changed: Whether system-versioned property changed (T-SQL grammar-based)
        history_table_changed: Whether history table changed (T-SQL grammar-based)
        partition_method_changed: Whether partition method changed (partition scheme tracking)
        partition_columns_changed: Whether partition columns changed (partition scheme tracking)
        compress_changed: Whether compress property changed (DB2 grammar-based)
        compress_type_changed: Whether compress type changed (DB2 grammar-based)
        logged_changed: Whether logged property changed (DB2 grammar-based)
        organize_by_changed: Whether organize_by property changed (DB2 grammar-based)
        inherits_changed: Whether table inheritance changed (PostgreSQL) - Diff-relevant
        expected_table: Reference to the Table object from the expected source
            (snapshot or migrations). Used to render DDL lazily via render_table_ddl
            at HTML/JSON emit time.
        actual_table: Reference to the Table object from live introspection.
            Used to render DDL lazily via render_table_ddl at HTML/JSON emit time.
    """

    _name_field: ClassVar[str] = "table_name"
    _object_type_label: ClassVar[str] = "table"
    _LIST_STR_FIELDS: ClassVar[List[str]] = [
        "missing_columns",
        "extra_columns",
        "missing_constraints",
        "extra_constraints",
        "missing_indexes",
        "extra_indexes",
    ]
    _LIST_OBJ_FIELDS: ClassVar[List[str]] = [
        "modified_columns",
        "modified_constraints",
    ]
    _BOOL_FIELDS: ClassVar[List[str]] = [
        "temporary_changed",
        "filegroup_changed",
        "memory_optimized_changed",
        "system_versioned_changed",
        "history_table_changed",
        "partition_method_changed",
        "partition_columns_changed",
        "compress_changed",
        "compress_type_changed",
        "logged_changed",
        "organize_by_changed",
    ]

    table_name: str = ""
    missing_columns: List[str] = field(default_factory=list)
    extra_columns: List[str] = field(default_factory=list)
    modified_columns: List[ColumnDiff] = field(default_factory=list)
    missing_constraints: List[str] = field(default_factory=list)
    extra_constraints: List[str] = field(default_factory=list)
    modified_constraints: List[ConstraintDiff] = field(default_factory=list)
    missing_indexes: List[str] = field(default_factory=list)
    extra_indexes: List[str] = field(default_factory=list)
    temporary_changed: bool = False
    filegroup_changed: bool = False
    memory_optimized_changed: bool = False
    system_versioned_changed: bool = False
    history_table_changed: bool = False
    partition_method_changed: bool = False
    partition_columns_changed: bool = False
    compress_changed: bool = False
    compress_type_changed: bool = False
    logged_changed: bool = False
    organize_by_changed: bool = False
    inherits_changed: Optional[Tuple[Any, Any]] = None  # (expected, actual) - Diff-relevant
    expected_table: Optional["Table"] = None
    actual_table: Optional["Table"] = None

    def __post_init__(self) -> None:
        # Validate _BOOL_FIELDS before super().__post_init__(), which invokes
        # _calculate_diffs(). Otherwise a misspelled field would raise AttributeError
        # inside _calculate_diffs before this validation runs. Run every time so
        # tests/monkey-patches to _BOOL_FIELDS cannot be masked by a prior instance.
        actual_field_names = frozenset(f.name for f in fields(self))
        invalid = [f for f in self._BOOL_FIELDS if f not in actual_field_names]
        if invalid:
            raise AssertionError(
                f"{type(self).__name__}._BOOL_FIELDS references non-existent fields: {invalid}"
            )
        super().__post_init__()

    def _calculate_diffs(self) -> None:
        """Calculate whether differences exist and their severity."""
        # Check if any differences exist
        # Grammar-based: Added temporary_changed to track temporary property differences
        # T-SQL grammar-based: Added filegroup, memory_optimized, system_versioned, history_table tracking
        # Partition tracking: Added partition_method_changed, partition_columns_changed
        # DB2 grammar-based: Added compress, compress_type, logged, organize_by tracking
        self.has_diffs = any(
            [
                self.missing_columns,
                self.extra_columns,
                self.modified_columns,
                self.missing_constraints,
                self.extra_constraints,
                self.modified_constraints,
                self.missing_indexes,
                self.extra_indexes,
                self.temporary_changed,
                self.filegroup_changed,
                self.memory_optimized_changed,
                self.system_versioned_changed,
                self.history_table_changed,
                self.partition_method_changed,
                self.partition_columns_changed,
                self.compress_changed,
                self.compress_type_changed,
                self.logged_changed,
                self.organize_by_changed,
                self.inherits_changed is not None,
                any(any(opts.values()) for opts in self.dialect_options_changed.values()),
            ]
        )

        if not self.has_diffs:
            return

        # Calculate severity based on type of differences
        if self.missing_columns or self.missing_constraints:
            # Missing columns/constraints are errors
            self.severity = DiffSeverity.ERROR
        elif self.modified_columns or self.modified_constraints:
            # Check modified column severities
            for col_diff in self.modified_columns:
                if col_diff.severity == DiffSeverity.ERROR:
                    self.severity = DiffSeverity.ERROR
                    return
            # Check modified constraint severities
            for con_diff in self.modified_constraints:
                if con_diff.severity == DiffSeverity.ERROR:
                    self.severity = DiffSeverity.ERROR
                    return
            self.severity = DiffSeverity.WARNING
        elif self.extra_columns or self.extra_constraints:
            # Extra columns/constraints are warnings
            self.severity = DiffSeverity.WARNING
        elif any(getattr(self, f) for f in self._BOOL_FIELDS):
            # Boolean property changes (filegroup, partition, compress, etc.) are warnings
            self.severity = DiffSeverity.WARNING
        else:
            # Only index differences → info
            self.severity = DiffSeverity.INFO

    def get_diff_count(self) -> Dict[str, int]:
        """Get count of each type of difference.

        Returns:
            Dictionary with 20 keys:
            - _LIST_STR_FIELDS (6) and _LIST_OBJ_FIELDS (2): value = len(field)
            - _BOOL_FIELDS (11): value = 0 or 1 (int(bool))
            - "inherits_changed": 0 if None, else 1
        """
        result = {}
        for f in self._LIST_STR_FIELDS + self._LIST_OBJ_FIELDS:
            result[f] = len(getattr(self, f))
        for f in self._BOOL_FIELDS:
            result[f] = int(getattr(self, f))
        result["inherits_changed"] = 0 if self.inherits_changed is None else 1
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = super().to_dict()
        result["table_name"] = self.table_name
        for f in self._LIST_STR_FIELDS:
            result[f] = getattr(self, f)
        for f in self._LIST_OBJ_FIELDS:
            result[f] = [obj.to_dict() for obj in getattr(self, f)]
        for f in self._BOOL_FIELDS:
            result[f] = getattr(self, f)
        # Top-level bool for API consumers (tuple detail lives under differences["inherits"]).
        result["inherits_changed"] = self.inherits_changed is not None
        result["diff_count"] = self.get_diff_count()
        # Render DDL lazily for JSON consumers — same single path as HTML diff.
        # Resolve dialect from either Table ref so JSON output matches the
        # actual database dialect regardless of which side has it set.
        resolved_dialect = self._resolve_dialect(self.expected_table, self.actual_table)
        result["expected_create_statement"] = self._render_ddl(
            self.expected_table, resolved_dialect
        )
        result["actual_create_statement"] = self._render_ddl(self.actual_table, resolved_dialect)
        result["differences"] = {}
        if self.inherits_changed is not None:
            result["differences"]["inherits"] = {
                "expected": self.inherits_changed[0],
                "actual": self.inherits_changed[1],
            }
        return result

    @staticmethod
    def _resolve_dialect(*tables: Optional["Table"]) -> str:
        """Pick a dialect from the first Table whose ``dialect`` attribute is set.

        Snapshot loaders and live introspectors both populate ``Table.dialect``,
        so this is reliable in production. Returns ``""`` (changed from
        ``"postgresql"`` in PR #252 / commit ea5891f) when no Table ref carries
        a dialect — for example test fixtures constructed without one. The
        downstream renderer (``render_table_ddl`` →
        ``SqlGeneratorFactory.create("")`` → generic ``SqlGenerator``) treats
        empty as **"no dialect-specific rendering"**: PostgreSQL aliasing
        (``SERIAL`` → ``INTEGER``), sqlglot view-definition parsing and
        dialect-specific quirks all become no-ops.

        Production callers MUST set ``Table.dialect``; relying on the empty
        fallback is only correct when dialect-agnostic rendering is the
        explicit intent.
        """
        for t in tables:
            d = getattr(t, "dialect", None) if t is not None else None
            if d:
                return str(d)
        return ""

    @staticmethod
    def _render_ddl(table: Optional["Table"], dialect: str) -> Optional[str]:
        """Render a Table to its CREATE statement via the single DDL path.

        Returns None if no Table reference is attached. Failures are swallowed —
        serialization must not crash on dialect-specific render edge cases.
        """
        if table is None:
            return None
        try:
            from core.sql_generator.table_ddl_render import render_table_ddl

            return render_table_ddl(table, dialect=dialect, format_for_compare=True)
        except Exception:
            return None

    def __str__(self) -> str:
        """Human-readable string representation."""
        if not self.has_diffs:
            return f"Table '{self.table_name}': No differences"

        parts = []
        counts = self.get_diff_count()

        if counts["missing_columns"]:
            parts.append(f"{counts['missing_columns']} missing column(s)")
        if counts["extra_columns"]:
            parts.append(f"{counts['extra_columns']} extra column(s)")
        if counts["modified_columns"]:
            parts.append(f"{counts['modified_columns']} modified column(s)")
        if counts["missing_constraints"]:
            parts.append(f"{counts['missing_constraints']} missing constraint(s)")
        if counts["extra_constraints"]:
            parts.append(f"{counts['extra_constraints']} extra constraint(s)")
        if counts["modified_constraints"]:
            parts.append(f"{counts['modified_constraints']} modified constraint(s)")
        if counts["missing_indexes"]:
            parts.append(f"{counts['missing_indexes']} missing index(es)")
        if counts["extra_indexes"]:
            parts.append(f"{counts['extra_indexes']} extra index(es)")
        if self.temporary_changed:
            parts.append("temporary property changed")
        if self.filegroup_changed:
            parts.append("filegroup changed")
        if self.memory_optimized_changed:
            parts.append("memory-optimized property changed")
        if self.system_versioned_changed:
            parts.append("system-versioned property changed")
        if self.history_table_changed:
            parts.append("history table changed")
        if self.inherits_changed is not None:
            parts.append("inherits changed")

        return f"Table '{self.table_name}' [{self.severity.value}]: {', '.join(parts)}"
