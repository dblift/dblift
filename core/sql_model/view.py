"""Dialect-agnostic ``View`` SQL object — supports regular and materialized views."""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.sql_model.base import SqlObject, SqlObjectType

if TYPE_CHECKING:
    from core.sql_model.view_options import ViewOptions


class View(SqlObject):
    """Represents a database view.

    Supports both regular views and materialized views with refresh options.

    # SIMP-48: ``__init__`` still exposes 20 kwargs because flattening them
    # would require a codemod over 249+ call sites. As a stepping stone,
    # ``core.sql_model.view_options.ViewOptions`` groups the dialect-specific
    # subset, and ``View.from_options`` / ``View.to_options`` below let new
    # call sites adopt the typed surface incrementally without breaking the
    # legacy constructor.
    """

    def __init__(
        self,
        name: str,
        schema: Optional[str] = None,
        query: Optional[str] = None,
        columns: Optional[List[str]] = None,
        materialized: bool = False,
        dialect: Optional[str] = None,
        is_updatable: Optional[bool] = None,
        check_option: Optional[str] = None,
        # Materialized view specific properties
        is_populated: Optional[bool] = None,
        refresh_method: Optional[str] = None,
        refresh_mode: Optional[str] = None,
        fast_refreshable: Optional[bool] = None,
        last_refresh: Optional[str] = None,
        # Grammar-based: UNLOGGED materialized views (PostgreSQL)
        unlogged: Optional[bool] = None,
        # Grammar-based: MySQL-specific view properties
        algorithm: Optional[str] = None,  # MERGE, TEMPTABLE, UNDEFINED (MySQL)
        sql_security: Optional[str] = None,  # DEFINER, INVOKER (MySQL)
        definer: Optional[str] = None,  # user@host (MySQL)
        # Grammar-based: Oracle-specific view properties
        force: Optional[bool] = None,  # FORCE (True) or NOFORCE (False) (Oracle)
        # PostgreSQL-specific view properties - Diff-relevant
        security_definer: Optional[bool] = None,  # SECURITY DEFINER (PostgreSQL) - Diff-relevant
        security_invoker: Optional[bool] = None,  # SECURITY INVOKER (PostgreSQL) - Diff-relevant
        # View dependencies - SQL-generation-only
        dependencies: Optional[
            List[str]
        ] = None,  # List of dependent tables/views - SQL-generation-only
    ):
        """Initialize a view.

        Args:
            name: View name
            schema: Schema name (optional)
            query: SELECT query that defines the view
            columns: List of column names (optional)
            materialized: Whether the view is materialized
            dialect: SQL dialect
            is_populated: Whether the materialized view is populated (PostgreSQL, Oracle)
            refresh_method: Refresh method - FAST, COMPLETE, FORCE, MANUAL (Oracle, DB2)
            refresh_mode: Refresh mode - ON DEMAND, ON COMMIT (Oracle)
            fast_refreshable: Whether fast refresh is available (Oracle)
            last_refresh: Timestamp of last refresh (Oracle, DB2)
            unlogged: Whether the materialized view is UNLOGGED (PostgreSQL grammar-based)
            algorithm: View algorithm - MERGE, TEMPTABLE, UNDEFINED (MySQL grammar-based)
            sql_security: SQL security - DEFINER, INVOKER (MySQL grammar-based)
            definer: Definer user - user@host (MySQL grammar-based)
            force: Whether view is created with FORCE (True) or NOFORCE (False) (Oracle grammar-based)
            security_definer: Whether view uses SECURITY DEFINER (PostgreSQL) - Diff-relevant
            security_invoker: Whether view uses SECURITY INVOKER (PostgreSQL) - Diff-relevant
            dependencies: List of tables/views this view depends on - SQL-generation-only
        """
        object_type = SqlObjectType.MATERIALIZED_VIEW if materialized else SqlObjectType.VIEW
        super().__init__(name, object_type, schema, dialect)
        self.query = query
        self.columns = columns or []
        self.is_updatable = is_updatable
        self.check_option = check_option
        self.materialized = materialized

        # Materialized view specific properties (dialect-neutral)
        self.is_populated = is_populated
        self.refresh_method = refresh_method
        self.refresh_mode = refresh_mode
        self.fast_refreshable = fast_refreshable
        self.last_refresh = last_refresh
        # View dependencies - SQL-generation-only
        self.dependencies = dependencies or []

        # Grammar-based view properties.
        # PostgreSQL:
        self.unlogged = unlogged  # ``UNLOGGED`` materialized view flag
        self.security_definer = security_definer  # ``SECURITY DEFINER`` view flag
        self.security_invoker = security_invoker  # ``SECURITY INVOKER`` view flag
        # MySQL:
        self.algorithm = algorithm  # ``ALGORITHM = MERGE|TEMPTABLE|UNDEFINED``
        self.sql_security = sql_security  # ``SQL SECURITY = DEFINER|INVOKER``
        self.definer = definer  # ``DEFINER = user@host``
        # Oracle:
        self.force = force  # ``FORCE`` / ``NOFORCE`` view modifier

    @property
    def create_statement(self) -> str:
        """OSS builds do not ship SQL generation for this object."""
        return ""

    @property
    def drop_statement(self) -> str:
        """Generate DROP VIEW statement.

        Returns:
            SQL DROP VIEW statement for this view
        """
        from db.base_quirks import BaseQuirks
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(self.dialect or "")
        quirks = ProviderRegistry.get_quirks(canonical) if canonical else BaseQuirks()

        schema_prefix = self.format_identifier(self.schema) + "." if self.schema else ""
        view_name = self.format_identifier(self.name)
        view_type = "MATERIALIZED VIEW" if self.materialized else "VIEW"

        if quirks.view_drop_supports_if_exists:
            return f"DROP {view_type} IF EXISTS {schema_prefix}{view_name}"
        return f"DROP {view_type} {schema_prefix}{view_name}"

    def __str__(self) -> str:
        """Return string representation of the view."""
        return self.create_statement

    def __eq__(self, other: Any) -> bool:
        """Check if two views are equal."""
        if not isinstance(other, View):
            return False
        return (
            super().__eq__(other)
            and self.query == other.query
            and self.columns == other.columns
            and self.materialized == other.materialized
            and self.is_updatable == other.is_updatable
            and self.check_option == other.check_option
            and self.is_populated == other.is_populated
            and self.refresh_method == other.refresh_method
            and self.refresh_mode == other.refresh_mode
            and self.fast_refreshable == other.fast_refreshable
            # Grammar-based: MySQL-specific properties
            and self.algorithm == other.algorithm
            and self.sql_security == other.sql_security
            and self.definer == other.definer
            # Grammar-based: Oracle-specific properties
            and self.force == other.force
            # Grammar-based: PostgreSQL-specific properties
            and self.unlogged == other.unlogged
            and self.security_definer == other.security_definer
            and self.security_invoker == other.security_invoker
            # Note: last_refresh is not compared as it changes with each refresh
            # Note: dependencies is SQL-generation-only, not diff-relevant
        )

    # ------------------------------------------------------------------
    # SIMP-48 — Typed-options surface (non-breaking).
    # ------------------------------------------------------------------

    @classmethod
    def from_options(
        cls,
        name: str,
        *,
        options: Optional["ViewOptions"] = None,
        schema: Optional[str] = None,
        query: Optional[str] = None,
        columns: Optional[List[str]] = None,
        materialized: bool = False,
        dialect: Optional[str] = None,
        is_updatable: Optional[bool] = None,
        check_option: Optional[str] = None,
    ) -> "View":
        """Build a ``View`` from the typed ``ViewOptions`` surface.

        Equivalent to calling ``View(name, ..., **options.to_kwargs())``
        but with a focused signature that hides the 13 dialect-specific
        kwargs.
        """
        from core.sql_model.view_options import ViewOptions

        opts = options if options is not None else ViewOptions()
        return cls(
            name=name,
            schema=schema,
            query=query,
            columns=columns,
            materialized=materialized,
            dialect=dialect,
            is_updatable=is_updatable,
            check_option=check_option,
            **opts.to_kwargs(),
        )

    def to_options(self) -> "ViewOptions":
        """Reconstruct the typed ``ViewOptions`` view from this instance.

        Useful for codemods migrating legacy callers and for round-trip
        tests.
        """
        from core.sql_model.view_options import (
            MaterializedViewOptions,
            MySqlViewOptions,
            OracleViewOptions,
            PostgresViewOptions,
            ViewOptions,
        )

        return ViewOptions(
            materialized_view=MaterializedViewOptions(
                is_populated=self.is_populated,
                refresh_method=self.refresh_method,
                refresh_mode=self.refresh_mode,
                fast_refreshable=self.fast_refreshable,
                last_refresh=self.last_refresh,
            ),
            postgres=PostgresViewOptions(
                unlogged=self.unlogged,
                security_definer=self.security_definer,
                security_invoker=self.security_invoker,
            ),
            mysql=MySqlViewOptions(
                algorithm=self.algorithm,
                sql_security=self.sql_security,
                definer=self.definer,
            ),
            oracle=OracleViewOptions(force=self.force),
            dependencies=list(self.dependencies),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "View":
        """Create view from dictionary representation.

        Args:
            data: Dictionary with view attributes

        Returns:
            View object
        """
        return cls(
            name=data["name"],
            schema=data.get("schema"),
            query=data.get("query"),
            columns=data.get("columns", []),
            materialized=data.get("materialized", False),
            dialect=data.get("dialect"),
            is_updatable=data.get("is_updatable"),
            check_option=data.get("check_option"),
            is_populated=data.get("is_populated"),
            refresh_method=data.get("refresh_method"),
            refresh_mode=data.get("refresh_mode"),
            fast_refreshable=data.get("fast_refreshable"),
            last_refresh=data.get("last_refresh"),
            unlogged=data.get("unlogged"),
            algorithm=data.get("algorithm"),
            sql_security=data.get("sql_security"),
            definer=data.get("definer"),
            force=data.get("force"),
            security_definer=data.get("security_definer"),
            security_invoker=data.get("security_invoker"),
            dependencies=data.get("dependencies", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert view to dictionary representation.

        Returns:
            Dictionary with view attributes
        """
        result = {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "query": self.query,
            "columns": self.columns,
            "materialized": self.materialized,
        }

        if self.is_updatable is not None:
            result["is_updatable"] = self.is_updatable
        if self.check_option:
            result["check_option"] = self.check_option
        # Add materialized view specific properties if present
        if self.is_populated is not None:
            result["is_populated"] = self.is_populated
        if self.refresh_method:
            result["refresh_method"] = self.refresh_method
        if self.refresh_mode:
            result["refresh_mode"] = self.refresh_mode
        if self.fast_refreshable is not None:
            result["fast_refreshable"] = self.fast_refreshable
        if self.last_refresh:
            result["last_refresh"] = self.last_refresh
        if self.security_definer is not None:
            result["security_definer"] = self.security_definer
        if self.security_invoker is not None:
            result["security_invoker"] = self.security_invoker
        if self.dependencies:
            result["dependencies"] = self.dependencies
        # Grammar-based: MySQL-specific properties
        if self.algorithm:
            result["algorithm"] = self.algorithm
        if self.sql_security:
            result["sql_security"] = self.sql_security
        if self.definer:
            result["definer"] = self.definer
        # Grammar-based: Oracle-specific properties
        if self.force is not None:
            result["force"] = self.force
        # Grammar-based: PostgreSQL-specific properties
        if self.unlogged is not None:
            result["unlogged"] = self.unlogged

        return result

    @staticmethod
    def _format_mysql_definer(definer: str) -> str:
        """Return a properly quoted MySQL DEFINER clause."""
        if not definer:
            return definer

        trimmed = definer.strip()
        # If already quoted (contains backticks and @), return as-is
        if "`" in trimmed or trimmed.upper() == "CURRENT_USER":
            return trimmed

        if "@" in trimmed:
            user_part, host_part = trimmed.split("@", 1)
        else:
            user_part, host_part = trimmed, "%"

        user_part = user_part.strip("`\"'")
        host_part = host_part.strip("`\"'") or "%"

        return f"`{user_part}`@`{host_part}`"
