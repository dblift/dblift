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

    from dblift.db.provider_registry import ProviderRegistry

    case = ProviderRegistry.get_quirks(dialect).unquoted_identifier_case
    return object_name.upper() if case == "uppercase" else object_name.lower()


def configured_identifier_text(name: str) -> str:
    """Return a configured identifier with surrounding quotes removed.

    Case is left as written. ``${dblift_schema}`` expands to this so a
    double-quoted Oracle schema ``"myschema"`` becomes ``myschema`` inside
    ``"${dblift_schema}"``, the spelling 4.8.0 scripts already used, and an
    unquoted value is not uppercased.
    """
    if not name:
        return ""
    clean = name.strip()
    if len(clean) >= 2 and clean[0] == '"' and clean[-1] == '"':
        return clean[1:-1].replace('""', '"')
    return clean


def dictionary_identifier(name: str, dialect: str) -> str:
    """Return the catalog spelling of a possibly double-quoted identifier.

    A name wrapped in double quotes keeps the exact text inside the quotes
    (a doubled quote inside is one quote character). An unquoted name is
    folded with :func:`get_normalized_object_name`.

    Schema caches should key on this spelling. Quoted and unquoted forms of
    the same catalog name (``myschema`` and ``"MYSCHEMA"`` on Oracle) share
    a key; a quoted lowercase name (``"myschema"``) stays distinct from the
    folded uppercase one.
    """
    if not name:
        return ""
    clean = name.strip()
    if len(clean) >= 2 and clean[0] == '"' and clean[-1] == '"':
        return configured_identifier_text(clean)
    return get_normalized_object_name(clean, dialect)


def normalized_quoted_identifier(name: str, dialect: str) -> str:
    """Quote *name* after normalizing it to the dialect's identifier case.

    Use when emitting SQL that references a column/table whose name came from a
    driver result set or catalog introspection (i.e. driver-cased). Such names
    are folded to the driver's convention (e.g. lower-case ``id`` from the Oracle
    driver), but the database stored them in its own case (``ID``); quoting the
    folded name verbatim would target a non-existent identifier (ORA-00904 on
    Oracle). Normalizing first then quoting yields the correct ``"ID"``.

    Composes the two canonical helpers — :func:`get_normalized_object_name` and
    ``dblift.core.sql_model.dialect.quote_identifier`` — so callers never duplicate the
    pattern.
    """
    from dblift.core.sql_model.dialect import quote_identifier

    return quote_identifier(dialect, get_normalized_object_name(name, dialect))
