"""MariaDB :class:`DialectQuirks` (Epic 26 story 26-13).

Inherits from :class:`MysqlQuirks` — same drop-statement variants,
delimiter wrapping, and definition-preservation rules. MariaDB-specific
overrides (sequences, system-versioned tables, native JSON typing on
modern versions) get added here as the epic touches each subsystem.
"""

from __future__ import annotations

from db.plugins.mysql.quirks import MysqlQuirks


class MariadbQuirks(MysqlQuirks):
    """MariaDB-specific :class:`DialectQuirks`, inheriting from :class:`MysqlQuirks`.

    Inherits all MySQL-family quirks (backtick quoting, ``DELIMITER``
    wrapping, definition-preservation for views / procedures /
    functions / triggers / events, no transactional DDL). MariaDB-only
    deviations land here as the codebase touches them: native ``JSON``
    type from 10.2+, native sequences and system-versioned tables on
    modern versions.
    """

    # MariaDB 10.2+ JSON; keep MySQL-family keys from parent for shared class attrs.
    version_specific_type_mappings = {
        **MysqlQuirks.version_specific_type_mappings,
        ("mariadb", "10.2+"): {"JSON": "JSON"},
    }

    # MariaDB historically did not need post-introspection rollback in dblift's
    # snapshot path (the legacy gate was ``dialect in ("db2", "mysql")``).
    # Override the parent ``True`` to preserve that behavior.
    requires_rollback_after_introspection: bool = False

    def __init__(self, dialect_name: str = "mariadb") -> None:
        """Initialize MariaDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)


__all__ = ["MariadbQuirks"]
