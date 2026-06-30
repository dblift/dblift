"""
Centralized object naming conventions per database dialect.

This module provides the single source of truth for how object names
(table, schema, etc.) should be standardized for each database type.

The correct case for unquoted identifiers is not hardcoded per dialect;
it is derived from the dialect's quirks (``unquoted_identifier_case``),
so framework code never needs to know dialect names.
"""


def get_normalized_object_name(object_name: str, dialect: str) -> str:
    """Return the correct object name for the given database dialect.

    The case is resolved from the dialect's quirks
    (``unquoted_identifier_case``): dialects whose quirks report
    ``"uppercase"`` get an upper-cased name; everything else
    (``"lowercase"``, ``"case_insensitive"``, unknown, or missing
    dialect) gets a lower-cased name (the safe default).

    Use this function whenever you need to resolve object names for
    database operations (e.g. history table, lock table) to ensure
    the correct case is used.

    Args:
        object_name: Base object name (e.g., "dblift_schema_history")
        dialect: Database dialect name (e.g., "oracle", "postgresql")

    Returns:
        Object name with appropriate case for the database dialect
    """
    if not dialect:
        return object_name.lower()

    from db.provider_registry import ProviderRegistry

    case = ProviderRegistry.get_quirks(dialect).unquoted_identifier_case
    return object_name.upper() if case == "uppercase" else object_name.lower()


def normalized_quoted_identifier(name: str, dialect: str) -> str:
    """Quote *name* after normalizing it to the dialect's identifier case.

    Use when emitting SQL that references a column/table whose name came from a
    driver result set or catalog introspection (i.e. driver-cased). Such names
    are folded to the driver's convention (e.g. lower-case ``id`` from the Oracle
    driver), but the database stored them in its own case (``ID``); quoting the
    folded name verbatim would target a non-existent identifier (ORA-00904 on
    Oracle). Normalizing first then quoting yields the correct ``"ID"``.

    Composes the two canonical helpers — :func:`get_normalized_object_name` and
    ``core.sql_model.dialect.quote_identifier`` — so callers never duplicate the
    pattern.
    """
    from core.sql_model.dialect import quote_identifier

    return quote_identifier(dialect, get_normalized_object_name(name, dialect))
