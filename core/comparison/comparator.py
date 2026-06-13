"""SQL Object Comparator for Drift Detection.

This module provides the ObjectComparator class which compares SQL Model objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.

Key Features:
- Compare tables, views, procedures, triggers, sequences
- Detect missing, extra, and modified objects
- Type-aware comparison using DataTypeNormalizer
- Generate structured diff results
- Handle case sensitivity and identifier normalization
"""

from functools import cached_property
from types import MappingProxyType
from typing import Any, ClassVar, List, Mapping, Optional, Tuple, Type

from core.comparison._comparator_registry import (
    _FIRST_PARTY_COMPARATORS,
    get_comparator_class,
)
from core.comparison.comparison_utils import (
    normalize_view_definition,
)
from core.comparison.database_link_comparator import DatabaseLinkComparator
from core.comparison.diff_models import (
    DatabaseLinkDiff,
    EventDiff,
    ExtensionDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    FunctionDiff,
    IndexDiff,
    LinkedServerDiff,
    ModuleDiff,
    PackageDiff,
    ProcedureDiff,
    SchemaDiff,
    SequenceDiff,
    SynonymDiff,
    TableDiff,
    TriggerDiff,
    UserDefinedTypeDiff,
    ViewDiff,
)
from core.comparison.event_comparator import EventComparator
from core.comparison.extension_comparator import ExtensionComparator
from core.comparison.foreign_data_wrapper_comparator import ForeignDataWrapperComparator
from core.comparison.foreign_server_comparator import ForeignServerComparator
from core.comparison.function_comparator import FunctionComparator
from core.comparison.index_comparator import IndexComparator
from core.comparison.linked_server_comparator import LinkedServerComparator
from core.comparison.module_comparator import ModuleComparator
from core.comparison.package_comparator import PackageComparator
from core.comparison.procedure_comparator import ProcedureComparator
from core.comparison.sequence_comparator import SequenceComparator
from core.comparison.synonym_comparator import SynonymComparator
from core.comparison.table_comparator import TableComparator
from core.comparison.trigger_comparator import TriggerComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.comparison.user_defined_type_comparator import UserDefinedTypeComparator
from core.logger import NullLog
from core.logger._base import Log
from core.sql_model.database_link import DatabaseLink
from core.sql_model.event import Event
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.linked_server import LinkedServer
from core.sql_model.module import Module
from core.sql_model.package import Package
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View


def _diff_attr(expected: Any, actual: Any, attr_name: str, default: Any = None) -> Tuple[Any, Any]:
    """Return (expected_val, actual_val) for an optional attribute.

    Reduces dual-getattr boilerplate common in ObjectComparator comparison methods.
    """
    return getattr(expected, attr_name, default), getattr(actual, attr_name, default)


class ObjectComparator:
    """Compares SQL Model objects and generates diff results.

    This class provides methods to compare SQL objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.

    Example:
        >>> normalizer = DataTypeNormalizer()
        >>> comparator = ObjectComparator(normalizer)
        >>> diff = comparator.compare_tables(script_table, db_table, "postgresql")
        >>> if diff.has_diffs:
        ...     print(f"Found differences: {diff}")
    """

    # Roadmap action #13 made this registry pluggable via the
    # ``dblift.comparators`` entry-point group; see
    # :mod:`core.comparison._comparator_registry`. The class attribute is
    # preserved as a read-only ``MappingProxyType`` view over
    # ``_FIRST_PARTY_COMPARATORS`` so any external caller that introspected
    # ``ObjectComparator._COMPARATOR_REGISTRY`` still sees the same names.
    #
    # Why ``MappingProxyType`` rather than a direct reference: a plain
    # alias would let ``ObjectComparator._COMPARATOR_REGISTRY["custom"] =
    # MyClass`` silently mutate the registry module's source-of-truth
    # dict, which would then make ``register_external_comparator("custom",
    # ...)`` raise ValueError (the name would now look "reserved for
    # first-party"). The proxy turns that legacy in-place mutation into a
    # ``TypeError: 'mappingproxy' object does not support item assignment``
    # so the failure is loud and immediate. The modern entry point for
    # plugins is ``get_comparator_class(name)`` / the
    # ``dblift.comparators`` entry-point group — not direct ``ClassVar``
    # mutation.
    _COMPARATOR_REGISTRY: ClassVar[Mapping[str, Type[Any]]] = MappingProxyType(
        _FIRST_PARTY_COMPARATORS
    )

    def __init__(self, type_normalizer: DataTypeNormalizer, log: Optional[Log] = None) -> None:
        """Initialize the object comparator.

        Args:
            type_normalizer: DataTypeNormalizer for type comparison
            log: Logger instance; defaults to NullLog
        """
        self.type_normalizer = type_normalizer
        self.log = log if log is not None else NullLog()

    # ------------------------------------------------------------------
    # First-party comparator accessors (roadmap action #14).
    #
    # Replaces the previous lazy ``__getattr__`` dispatch with one explicit
    # ``@cached_property`` per first-party comparator. Each property is
    # annotated with the concrete comparator class so mypy and IDE
    # autocomplete see the real return type instead of ``Any`` — the 16
    # ``# type: ignore[no-any-return]`` annotations on ``compare_*``
    # methods came from the dispatched-via-Any path and are now removed.
    #
    # cached_property caches in ``self.__dict__`` on first access (same
    # contract as the old ``object.__setattr__`` hand-coded caching) and
    # bypasses ``__getattr__`` entirely for first-party names. ``__getattr__``
    # below is kept to handle third-party comparators registered via the
    # ``dblift.comparators`` entry-point group (action #13).
    # ------------------------------------------------------------------

    @cached_property
    def table_comparator(self) -> TableComparator:
        """Lazily built :class:`TableComparator`. Uniquely receives ``log=``
        so it can warn about constraint-validation issues during column
        comparison."""
        return TableComparator(self.type_normalizer, log=self.log)

    @cached_property
    def index_comparator(self) -> IndexComparator:
        """Lazily built :class:`IndexComparator` for ``compare_indexes``."""
        return IndexComparator(self.type_normalizer)

    @cached_property
    def trigger_comparator(self) -> TriggerComparator:
        """Lazily built :class:`TriggerComparator` for ``compare_triggers``."""
        return TriggerComparator(self.type_normalizer)

    @cached_property
    def procedure_comparator(self) -> ProcedureComparator:
        """Lazily built :class:`ProcedureComparator` for ``compare_procedures``."""
        return ProcedureComparator(self.type_normalizer)

    @cached_property
    def function_comparator(self) -> FunctionComparator:
        """Lazily built :class:`FunctionComparator` for ``compare_functions``."""
        return FunctionComparator(self.type_normalizer)

    @cached_property
    def synonym_comparator(self) -> SynonymComparator:
        """Lazily built :class:`SynonymComparator` for ``compare_synonyms``."""
        return SynonymComparator(self.type_normalizer)

    @cached_property
    def user_defined_type_comparator(self) -> UserDefinedTypeComparator:
        """Lazily built :class:`UserDefinedTypeComparator` for
        ``compare_user_defined_types``."""
        return UserDefinedTypeComparator(self.type_normalizer)

    @cached_property
    def module_comparator(self) -> ModuleComparator:
        """Lazily built :class:`ModuleComparator` for ``compare_modules``."""
        return ModuleComparator(self.type_normalizer)

    @cached_property
    def package_comparator(self) -> PackageComparator:
        """Lazily built :class:`PackageComparator` for ``compare_packages``."""
        return PackageComparator(self.type_normalizer)

    @cached_property
    def extension_comparator(self) -> ExtensionComparator:
        """Lazily built :class:`ExtensionComparator` for ``compare_extensions``."""
        return ExtensionComparator(self.type_normalizer)

    @cached_property
    def event_comparator(self) -> EventComparator:
        """Lazily built :class:`EventComparator` for ``compare_events``."""
        return EventComparator(self.type_normalizer)

    @cached_property
    def database_link_comparator(self) -> DatabaseLinkComparator:
        """Lazily built :class:`DatabaseLinkComparator` for
        ``compare_database_links``."""
        return DatabaseLinkComparator(self.type_normalizer)

    @cached_property
    def linked_server_comparator(self) -> LinkedServerComparator:
        """Lazily built :class:`LinkedServerComparator` for
        ``compare_linked_servers``."""
        return LinkedServerComparator(self.type_normalizer)

    @cached_property
    def foreign_data_wrapper_comparator(self) -> ForeignDataWrapperComparator:
        """Lazily built :class:`ForeignDataWrapperComparator` for
        ``compare_foreign_data_wrappers``."""
        return ForeignDataWrapperComparator(self.type_normalizer)

    @cached_property
    def foreign_server_comparator(self) -> ForeignServerComparator:
        """Lazily built :class:`ForeignServerComparator` for
        ``compare_foreign_servers``."""
        return ForeignServerComparator(self.type_normalizer)

    @cached_property
    def sequence_comparator(self) -> SequenceComparator:
        """Lazily built :class:`SequenceComparator` for ``compare_sequences``."""
        return SequenceComparator(self.type_normalizer)

    def __getattr__(self, name: str) -> Any:
        """Lazy resolver for third-party comparators registered via the
        ``dblift.comparators`` entry-point group (roadmap action #13).

        First-party comparators (the 16 ``@cached_property`` accessors above)
        are intercepted by normal attribute lookup before ``__getattr__``
        runs, so the dispatch here only ever sees third-party names. Returns
        ``Any`` because the loaded class type is only known at runtime —
        first-party callers go through the typed properties and never see
        this method.

        Args:
            name: Attribute name being accessed.

        Returns:
            A lazily-initialized third-party comparator instance.

        Raises:
            AttributeError: If ``name`` is registered in neither the
                first-party table nor any external entry point.
        """
        cls = get_comparator_class(name)
        if cls is None:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        comparator = cls(self.type_normalizer)
        object.__setattr__(self, name, comparator)
        return comparator

    def compare_tables(
        self,
        expected: Table,
        actual: Table,
        dialect: str = "",
    ) -> TableDiff:
        """Compare two table objects.

        Delegates to TableComparator to avoid duplication of column/constraint
        comparison logic (_compare_column_details, _compare_constraints, etc.).

        Args:
            expected: Expected table (from scripts)
            actual: Actual table (from database)
            dialect: SQL dialect for type normalization. Defaults to ``""``
                since PR #252 / commit ea5891f (was previously
                ``"postgresql"``). An empty string disables dialect-specific
                normalisation: ``ProviderRegistry.get_quirks("")`` returns the
                base ``BaseQuirks`` (e.g. ``serial_types_alias_integer=False``,
                ``sqlglot_dialect=None``), so PostgreSQL ``SERIAL`` → ``INTEGER``
                aliasing and dialect-specific property comparisons become
                no-ops. Production callers always pass an explicit dialect;
                the ``""`` default is intended for dialect-agnostic test
                fixtures.

        Returns:
            TableDiff object with comparison results

        Example:
            >>> diff = comparator.compare_tables(script_table, db_table, "postgresql")
            >>> print(f"Missing columns: {diff.missing_columns}")
        """
        return self.table_comparator.compare_tables(expected, actual, dialect)

    def compare_schemas(
        self,
        expected_tables: List[Table],
        actual_tables: List[Table],
        dialect: str = "",
        schema_name: str = "public",
    ) -> SchemaDiff:
        """Compare lists of tables from two schemas.

        Args:
            expected_tables: Expected tables (from scripts)
            actual_tables: Actual tables (from database)
            dialect: SQL dialect for type normalization. Same ``""`` default
                contract as :meth:`compare_tables` — PR #252 dropped the
                ``"postgresql"`` fallback so production callers must pass an
                explicit dialect to get dialect-specific normalisation.
            schema_name: Name of the schema being compared

        Returns:
            SchemaDiff object with comparison results
        """
        # Create lookup maps (case-insensitive)
        # Convert to Python strings to handle driver-returned objects
        expected_map = {str(t.name).lower(): t for t in expected_tables}
        actual_map = {str(t.name).lower(): t for t in actual_tables}

        # Find missing, extra, and common tables
        expected_names = set(expected_map.keys())
        actual_names = set(actual_map.keys())

        missing_table_names = list(expected_names - actual_names)
        extra_table_names = list(actual_names - expected_names)
        common_table_names = expected_names & actual_names

        # Compare common tables
        modified_tables = []
        for table_name in common_table_names:
            expected_table = expected_map[table_name]
            actual_table = actual_map[table_name]
            table_diff = self.compare_tables(expected_table, actual_table, dialect)
            if table_diff.has_diffs:
                modified_tables.append(table_diff)
                # Log details about what changed
                self.log.debug(
                    f"Table '{table_name}' has differences (severity: {table_diff.severity})"
                )
                if table_diff.modified_columns:
                    self.log.debug(
                        f"  Modified columns: {[c.object_name for c in table_diff.modified_columns]}"
                    )
                    for col_diff in table_diff.modified_columns:
                        self.log.debug(
                            f"    Column '{col_diff.object_name}' (severity: {col_diff.severity}):"
                        )
                        if col_diff.data_type_diff:
                            self.log.debug(f"      Data type: {col_diff.data_type_diff}")
                        if col_diff.nullable_diff:
                            self.log.debug(f"      Nullable: {col_diff.nullable_diff}")
                        if col_diff.default_diff:
                            self.log.debug(f"      Default: {col_diff.default_diff}")

        # Create SchemaDiff
        schema_diff = SchemaDiff(
            object_name=schema_name,
            schema_name=schema_name,
            missing_tables=missing_table_names,
            extra_tables=extra_table_names,
            modified_tables=modified_tables,
        )

        return schema_diff

    def compare_views(
        self,
        expected: View,
        actual: View,
        dialect: str = "",
    ) -> Optional[ViewDiff]:
        """Compare two view objects.

        Args:
            expected: Expected view from migrations
            actual: Actual view from database
            dialect: SQL dialect

        Returns:
            ViewDiff if differences found, None otherwise
        """
        view_name = expected.name or actual.name
        diff = ViewDiff(object_name=view_name, view_name=view_name)

        # Compare definitions (normalize whitespace and case)
        expected_def = self._normalize_view_definition(expected.query, dialect)
        actual_def = self._normalize_view_definition(actual.query, dialect)

        if expected_def != actual_def:
            diff.definition_changed = True
            diff.expected_definition = expected.query
            diff.actual_definition = actual.query
            self.log.info(f"View '{view_name}': definition changed")

        # Compare materialized status (PostgreSQL)
        expected_mat, actual_mat = _diff_attr(expected, actual, "materialized", False)
        if expected_mat != actual_mat:
            diff.materialized_changed = (expected_mat, actual_mat)
            self.log.info(
                f"View '{view_name}': materialized status changed from {expected_mat} to {actual_mat}"
            )

        # Story 26-6: dialect branches use ``canonical_dialect_name``
        # so aliases (``postgres``, ``mariadb``, etc.) resolve via the
        # plugin registry instead of being repeated in tuples.
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(dialect) or (dialect or "").lower()
        _quirks = ProviderRegistry.get_quirks(canonical)

        # Grammar-based: Compare PostgreSQL UNLOGGED (materialized views)
        if _quirks.view_supports_unlogged_and_security:
            expected_unlogged, actual_unlogged = _diff_attr(expected, actual, "unlogged")
            if expected_unlogged is not None and actual_unlogged is not None:
                if expected_unlogged != actual_unlogged:
                    diff.unlogged_changed = (expected_unlogged, actual_unlogged)
                    self.log.info(
                        f"View '{view_name}': UNLOGGED status changed from {expected_unlogged} to {actual_unlogged}"
                    )

            # Compare security context - Diff-relevant
            expected_security_definer, actual_security_definer = _diff_attr(
                expected, actual, "security_definer"
            )
            if expected_security_definer is not None and actual_security_definer is not None:
                if expected_security_definer != actual_security_definer:
                    diff.security_definer_changed = (
                        expected_security_definer,
                        actual_security_definer,
                    )
                    self.log.info(
                        f"View '{view_name}': SECURITY DEFINER changed from {expected_security_definer} to {actual_security_definer}"
                    )

            expected_security_invoker, actual_security_invoker = _diff_attr(
                expected, actual, "security_invoker"
            )
            if expected_security_invoker is not None and actual_security_invoker is not None:
                if expected_security_invoker != actual_security_invoker:
                    diff.security_invoker_changed = (
                        expected_security_invoker,
                        actual_security_invoker,
                    )
                    self.log.info(
                        f"View '{view_name}': SECURITY INVOKER changed from {expected_security_invoker} to {actual_security_invoker}"
                    )

        # Grammar-based: Compare MySQL view properties.
        # MariaDB shares MySQL view grammar via ``MariadbQuirks(MysqlQuirks)``,
        # so both inherit ``view_supports_algorithm = True``.
        if _quirks.view_supports_algorithm:
            # Compare algorithm
            expected_algorithm, actual_algorithm = _diff_attr(expected, actual, "algorithm")
            if expected_algorithm != actual_algorithm:
                diff.algorithm_changed = (expected_algorithm, actual_algorithm)
                self.log.info(
                    f"View '{view_name}': algorithm changed from {expected_algorithm} to {actual_algorithm}"
                )

            # Compare SQL SECURITY
            expected_sql_sec, actual_sql_sec = _diff_attr(expected, actual, "sql_security")
            if expected_sql_sec and actual_sql_sec and expected_sql_sec != actual_sql_sec:
                diff.sql_security_changed = (expected_sql_sec, actual_sql_sec)
                self.log.info(
                    f"View '{view_name}': SQL SECURITY changed from {expected_sql_sec} to {actual_sql_sec}"
                )

            # Compare definer
            expected_definer, actual_definer = _diff_attr(expected, actual, "definer")
            if expected_definer and actual_definer and expected_definer != actual_definer:
                diff.definer_changed = (expected_definer, actual_definer)
                self.log.info(
                    f"View '{view_name}': definer changed from {expected_definer} to {actual_definer}"
                )

        # Grammar-based: Compare Oracle FORCE/NOFORCE
        if _quirks.view_supports_force_noforce:
            expected_force, actual_force = _diff_attr(expected, actual, "force")
            if expected_force is not None and actual_force is not None:
                if expected_force != actual_force:
                    diff.force_changed = (expected_force, actual_force)
                    self.log.info(
                        f"View '{view_name}': FORCE/NOFORCE changed from {expected_force} to {actual_force}"
                    )

        # Compare materialized view specific properties (only if both are materialized)
        if expected_mat and actual_mat:
            # Compare is_populated status
            expected_populated, actual_populated = _diff_attr(expected, actual, "is_populated")
            if expected_populated is not None and actual_populated is not None:
                if expected_populated != actual_populated:
                    diff.is_populated_changed = (expected_populated, actual_populated)
                    self.log.info(
                        f"Materialized view '{view_name}': populated status changed from {expected_populated} to {actual_populated}"
                    )

            # Compare refresh_method
            expected_method, actual_method = _diff_attr(expected, actual, "refresh_method")
            if expected_method and actual_method:
                # Normalize for comparison (case-insensitive)
                if expected_method.upper() != actual_method.upper():
                    diff.refresh_method_changed = (expected_method, actual_method)
                    self.log.info(
                        f"Materialized view '{view_name}': refresh method changed from {expected_method} to {actual_method}"
                    )

            # Compare refresh_mode (Oracle)
            expected_mode, actual_mode = _diff_attr(expected, actual, "refresh_mode")
            if expected_mode and actual_mode:
                # Normalize for comparison (case-insensitive)
                if expected_mode.upper() != actual_mode.upper():
                    diff.refresh_mode_changed = (expected_mode, actual_mode)
                    self.log.info(
                        f"Materialized view '{view_name}': refresh mode changed from {expected_mode} to {actual_mode}"
                    )

            # Compare fast_refreshable (Oracle)
            expected_fast, actual_fast = _diff_attr(expected, actual, "fast_refreshable")
            if expected_fast is not None and actual_fast is not None:
                if expected_fast != actual_fast:
                    diff.fast_refreshable_changed = (expected_fast, actual_fast)
                    self.log.info(
                        f"Materialized view '{view_name}': fast refresh capability changed from {expected_fast} to {actual_fast}"
                    )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None

    def _normalize_view_definition(
        self,
        definition: Optional[str],
        dialect: str = "",
    ) -> str:
        """Normalize view definition for comparison.

        Delegates to the shared ``normalize_view_definition`` utility in
        ``comparison_utils`` so that identical logic is maintained in a single place.

        Args:
            definition: View definition SQL
            dialect: SQL dialect (passed to sqlglot for parsing)

        Returns:
            Normalized definition
        """
        return normalize_view_definition(definition, dialect)

    def compare_indexes(
        self,
        expected: Index,
        actual: Index,
        dialect: str = "",
    ) -> Optional[IndexDiff]:
        """Compare two index objects.

        Args:
            expected: Expected index from migrations
            actual: Actual index from database
            dialect: SQL dialect

        Returns:
            IndexDiff if differences found, None otherwise
        """
        return self.index_comparator.compare_indexes(expected, actual, dialect)

    def compare_sequences(
        self,
        expected: Sequence,
        actual: Sequence,
        dialect: str = "",
    ) -> Optional[SequenceDiff]:
        """Compare two sequence objects.

        Args:
            expected: Expected sequence from migrations
            actual: Actual sequence from database
            dialect: SQL dialect

        Returns:
            SequenceDiff if differences found, None otherwise
        """
        return self.sequence_comparator.compare_sequences(expected, actual, dialect)

    def compare_triggers(
        self,
        expected: Trigger,
        actual: Trigger,
        dialect: str = "",
    ) -> Optional[TriggerDiff]:
        """Compare two trigger objects.

        Args:
            expected: Expected trigger from migrations
            actual: Actual trigger from database
            dialect: SQL dialect

        Returns:
            TriggerDiff if differences found, None otherwise
        """
        return self.trigger_comparator.compare_triggers(expected, actual, dialect)

    def compare_procedures(
        self,
        expected: Procedure,
        actual: Procedure,
        dialect: str = "",
    ) -> Optional[ProcedureDiff]:
        """Compare two procedure objects.

        Args:
            expected: Expected procedure from migrations
            actual: Actual procedure from database
            dialect: SQL dialect

        Returns:
            ProcedureDiff if differences found, None otherwise
        """
        return self.procedure_comparator.compare_procedures(expected, actual, dialect)

    def compare_functions(
        self,
        expected: Procedure,
        actual: Procedure,
        dialect: str = "",
    ) -> Optional[FunctionDiff]:
        """Compare two function objects (Procedure with is_function=True).

        Args:
            expected: Expected function from migrations (Procedure with is_function=True)
            actual: Actual function from database (Procedure with is_function=True)
            dialect: SQL dialect

        Returns:
            FunctionDiff if differences found, None otherwise
        """
        return self.function_comparator.compare_functions(expected, actual, dialect)

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
        return self.synonym_comparator.compare_synonyms(expected, actual, dialect)

    def compare_user_defined_types(
        self,
        expected: UserDefinedType,
        actual: UserDefinedType,
        dialect: str = "",
    ) -> Optional[UserDefinedTypeDiff]:
        """Compare two user-defined type objects.

        Args:
            expected: Expected UDT from migrations
            actual: Actual UDT from database
            dialect: SQL dialect

        Returns:
            UserDefinedTypeDiff if differences found, None otherwise
        """
        return self.user_defined_type_comparator.compare_user_defined_types(
            expected, actual, dialect
        )

    def compare_packages(
        self,
        expected: Package,
        actual: Package,
        dialect: str = "",
    ) -> Optional[PackageDiff]:
        """Compare two package objects (Oracle).

        Args:
            expected: Expected package from migrations
            actual: Actual package from database
            dialect: SQL dialect (typically oracle)

        Returns:
            PackageDiff if differences found, None otherwise
        """
        return self.package_comparator.compare_packages(expected, actual, dialect)

    def compare_modules(
        self,
        expected: Module,
        actual: Module,
        dialect: str = "",
    ) -> Optional[ModuleDiff]:
        """Compare two module objects (DB2).

        Args:
            expected: Expected module from migrations
            actual: Actual module from database
            dialect: SQL dialect (typically db2)

        Returns:
            ModuleDiff if differences found, None otherwise
        """
        return self.module_comparator.compare_modules(expected, actual, dialect)

    def compare_extensions(
        self,
        expected: Extension,
        actual: Extension,
        dialect: str = "",
    ) -> Optional[ExtensionDiff]:
        """Compare two extension objects (PostgreSQL).

        Args:
            expected: Expected extension from migrations
            actual: Actual extension from database
            dialect: SQL dialect (typically postgresql)

        Returns:
            ExtensionDiff if differences found, None otherwise
        """
        return self.extension_comparator.compare_extensions(expected, actual, dialect)

    def compare_events(
        self,
        expected: Event,
        actual: Event,
        dialect: str = "",
    ) -> Optional[EventDiff]:
        """Compare two event objects (MySQL).

        Args:
            expected: Expected event from migrations
            actual: Actual event from database
            dialect: SQL dialect (typically mysql)

        Returns:
            EventDiff if differences found, None otherwise
        """
        return self.event_comparator.compare_events(expected, actual, dialect)

    def compare_database_links(
        self,
        expected: DatabaseLink,
        actual: DatabaseLink,
        dialect: str = "",
    ) -> Optional[DatabaseLinkDiff]:
        """Compare two database link objects (Oracle).

        Args:
            expected: Expected database link from migrations
            actual: Actual database link from database
            dialect: SQL dialect (typically oracle)

        Returns:
            DatabaseLinkDiff if differences found, None otherwise
        """
        return self.database_link_comparator.compare_database_links(expected, actual, dialect)

    def compare_linked_servers(
        self,
        expected: LinkedServer,
        actual: LinkedServer,
        dialect: str = "",
    ) -> Optional[LinkedServerDiff]:
        """Compare two linked server objects (SQL Server).

        Args:
            expected: Expected linked server from migrations
            actual: Actual linked server from database
            dialect: SQL dialect (typically sqlserver)

        Returns:
            LinkedServerDiff if differences found, None otherwise
        """
        return self.linked_server_comparator.compare_linked_servers(expected, actual, dialect)

    def compare_foreign_data_wrappers(
        self,
        expected: ForeignDataWrapper,
        actual: ForeignDataWrapper,
        dialect: str = "",
    ) -> Optional[ForeignDataWrapperDiff]:
        """Compare two foreign data wrapper objects (PostgreSQL).

        Args:
            expected: Expected FDW from migrations
            actual: Actual FDW from database
            dialect: SQL dialect (typically postgresql)

        Returns:
            ForeignDataWrapperDiff if differences found, None otherwise
        """
        return self.foreign_data_wrapper_comparator.compare_foreign_data_wrappers(
            expected, actual, dialect
        )

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
        return self.foreign_server_comparator.compare_foreign_servers(expected, actual, dialect)
