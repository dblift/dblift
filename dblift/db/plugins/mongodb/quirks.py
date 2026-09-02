"""MongoDB :class:`DialectQuirks`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Type

from dblift.db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from dblift.core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from dblift.core.sql_generator.base_generator import BaseSqlGenerator


class MongodbQuirks(BaseQuirks):
    """MongoDB-specific :class:`DialectQuirks` for the document dialect.

    Covers MongoDB's deviations from relational SQL: ``is_nosql=True``,
    schemaless collections (``schema_required=False``), collection names
    passed to the driver rather than interpolated into statements (no
    quoting), and Python-only migrations
    (``supports_sql_migrations=False``).
    """

    supports_transactions = False
    supports_transactional_ddl = False
    schema_required = False  # schemaless, no concept
    uppercase_identifiers = False
    clean_strategy = "native"
    default_schema_name = "default"
    boolean_false_literal = "false"
    is_nosql = True
    # Collections and indexes are created through pymongo, so migrations are
    # Python scripts (``migrate(context)``) rather than SQL.
    supports_sql_migrations = False
    # MongoDB authenticates with an ordinary username/password (or none at
    # all on a local mongod), unlike an account-key cloud API — so neither
    # of the credential gates applies.
    requires_cloud_account_auth = False
    requires_credentials = False
    # Collection names reach the driver as strings; they are never embedded
    # in a statement, so quoting them would corrupt the name.
    quote_open = ""
    quote_close = ""
    native_driver_display = "PyMongo"
    # No validate-sql offline lint: ``parser_class()`` returns None for every
    # parser_type because MongoDB has no SQL for dblift to read, so a
    # placeholder connection would not unlock anything. ``lint_placeholder_url``
    # stays unset (``None``, from BaseQuirks).
    connection_identifier_attrs = ("url", "host")
    missing_connection_identifier_hint = (
        "MongoDB connection target not specified (set database.url or "
        "database.host in the config file, or use --db-url with a "
        "mongodb:// or mongodb+srv:// URI)."
    )

    def __init__(self, dialect_name: str = "mongodb") -> None:
        """Initialize MongoDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """No SQL-DDL generator — collections are created through the driver."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator is supplied by an installed extension package."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """No parser — MongoDB has no SQL for dblift to read.

        Migrations are Python driving pymongo, and there is no read-side
        string language either: ``find()`` is a call, not a statement. Asking
        for a parser is therefore an error, not a silent degradation, and
        ``HybridParser`` cannot stand in because it falls back to a regex SQL
        parser that would match nothing meaningful.
        """
        return None

    # MongoDB has no SQL DDL, so every "DROP X" form renders as an
    # explanatory comment. Without this override, DROP rendering falls
    # through to the relational fallback in ``sql_generator.py`` and emits
    # SQL for a store that has no SQL DDL path at all.
    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """Render every DROP form as an explanatory comment.

        Nothing MongoDB drops is expressible in SQL: collections go through
        ``db.drop_collection`` and the remaining object types do not exist
        in the document API. Emitting a comment keeps generated scripts
        readable without pretending a statement is runnable.
        """
        if obj_type == "VIEW":
            # MongoDB has had read-only views since 3.4 (``db.createView``).
            # They are ordinary entries in ``listCollections`` (type
            # "view") and are dropped exactly like a collection.
            return (
                f"-- MongoDB views are dropped through the driver, not SQL.\n"
                f"-- In a Python migration: "
                f"context.db.drop_collection({obj_name!r})"
            )
        if obj_type == "MATERIALIZED_VIEW":
            # MongoDB has no distinct materialized-view catalog object. The
            # "on-demand materialized view" pattern in MongoDB's own docs is
            # an aggregation pipeline ending in $merge that writes into an
            # ordinary collection, so it is dropped the same way as one.
            return (
                "-- MongoDB has no materialized view catalog object; the "
                "on-demand materialized view\n"
                "-- pattern ($merge) writes to an ordinary collection, "
                "dropped the same way as one.\n"
                f"-- In a Python migration: "
                f"context.db.drop_collection({obj_name!r})"
            )
        if obj_type == "TABLE":
            return (
                f"-- MongoDB collections are dropped through the driver, not SQL.\n"
                f"-- In a Python migration: "
                f"context.db.drop_collection({obj_name!r})"
            )
        if obj_type == "INDEX":
            # Unlike CosmosDB, MongoDB indexes are real, individually named,
            # droppable objects — they are dropped per-collection, not
            # managed through an indexing policy. Leave the placeholder
            # unquoted (no ``!r``) when the collection is unknown so it
            # reads as a gap to fill in, not a literal collection name.
            collection_expr = repr(table_name) if table_name else "<collection>"
            return (
                f"-- MongoDB indexes are dropped through the driver, not SQL.\n"
                f"-- In a Python migration: "
                f"context.db[{collection_expr}].drop_index({obj_name!r})"
            )
        if obj_type == "SEQUENCE":
            return (
                f"-- MongoDB does not support sequences. "
                f"No DROP SEQUENCE needed for '{obj_name}'."
            )
        if obj_type in ("PROCEDURE", "FUNCTION"):
            return (
                "-- MongoDB does not support stored procedures/functions.\n"
                "-- Use application code or MongoDB aggregation pipelines instead."
            )
        if obj_type == "TRIGGER":
            return (
                f"-- MongoDB does not support triggers. "
                f"No DROP TRIGGER needed for '{obj_name}'."
            )
        if obj_type in ("PACKAGE", "PACKAGE_BODY"):
            return (
                f"-- MongoDB does not support packages. "
                f"No DROP PACKAGE needed for '{obj_name}'."
            )
        if obj_type == "SYNONYM":
            return (
                f"-- MongoDB does not support synonyms. "
                f"No DROP SYNONYM needed for '{obj_name}'."
            )
        if obj_type == "EXTENSION":
            return (
                f"-- MongoDB does not support extensions. "
                f"No DROP EXTENSION needed for '{obj_name}'."
            )
        # Unknown type: still emit a comment rather than invalid SQL.
        return (
            f"-- MongoDB does not support DROP {obj_type} via SQL "
            f"for '{obj_name}'.\n"
            "-- This operation may need to be performed via the driver."
        )

    def introspector_class(self) -> "Optional[Type[Any]]":
        """Introspection is supplied by an installed extension package."""
        return None

    def type_equivalents(self) -> "Dict[str, str]":
        """No cross-dialect type mapping — BSON types are not SQL types."""
        return {}

    def type_preferences(self) -> "Dict[str, str]":
        """No preferred-type mapping — see :meth:`type_equivalents`."""
        return {}


__all__ = ["MongodbQuirks"]
