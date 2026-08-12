"""MongoDB :class:`DialectQuirks`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Type

from db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


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
