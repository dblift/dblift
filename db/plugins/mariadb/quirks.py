"""MariaDB :class:`DialectQuirks` (Epic 26 story 26-13).

Inherits from :class:`MysqlQuirks` — same drop-statement variants,
delimiter wrapping, and definition-preservation rules. MariaDB-specific
overrides (sequences, system-versioned tables, native JSON typing on
modern versions) get added here as the epic touches each subsystem.
"""

from __future__ import annotations

from typing import Optional

from db.feature_gate import FeatureGate
from db.plugins.mysql.quirks import MysqlQuirks


class MariadbQuirks(MysqlQuirks):
    """MariaDB-specific :class:`DialectQuirks`, inheriting from :class:`MysqlQuirks`.

    Inherits all MySQL-family quirks (backtick quoting, ``DELIMITER``
    wrapping, definition-preservation for views / procedures /
    functions / triggers / events, no transactional DDL). MariaDB-only
    deviations land here as the codebase touches them: native ``JSON``
    type from 10.2+, native sequences and system-versioned tables on
    modern versions.

    Provider-compat snapshot DDL is inherited from :class:`MysqlQuirks`
    (InnoDB + LONGTEXT, ``CREATE TABLE IF NOT EXISTS``, skip existence
    probe). Managed snapshot DDL still raises via the MySQL parent so
    :class:`BaseSnapshotManager` falls through to the compat path.
    """

    # MariaDB 10.2+ JSON; keep MySQL-family keys from parent for shared class attrs.
    version_specific_type_mappings = {
        **MysqlQuirks.version_specific_type_mappings,
        ("mariadb", "10.2+"): {"JSON": "JSON"},
    }

    # Version-gated features. ``feature_gates`` replaces the parent dict
    # wholesale (no MRO merging) — every gate MariaDB wants must be
    # restated here with its own thresholds.
    feature_gates = {
        "rename_column": FeatureGate(
            min_version="10.5.2+",
            description="ALTER TABLE ... RENAME COLUMN",
        ),
        "instant_add_column": FeatureGate(
            # 10.3.7 is the first GA release carrying the ALGORITHM=INSTANT
            # syntax (the feature landed as alpha in 10.3.2). Not the same
            # threshold as MySQL -- MariaDB and MySQL's InnoDB forks
            # diverged on when this shipped. Version-only: this is not
            # edition-gated, but still narrower than "any ADD COLUMN is
            # instant" -- callers must separately account for the
            # per-statement restrictions this gate does not model
            # (ROW_FORMAT=COMPRESSED, a hidden FTS_DOC_ID column from a
            # FULLTEXT index, and, before 10.4, INSTANT only adding a
            # column as the last column).
            min_version="10.3.7+",
            description="ALTER TABLE ... ADD COLUMN, ALGORITHM=INSTANT",
        ),
    }

    # MariaDB historically did not need post-introspection rollback in dblift;
    # the legacy gate was ``dialect in ("db2", "mysql")``.
    # Override the parent ``True`` to preserve that behavior.
    requires_rollback_after_introspection: bool = False

    # MariaDB accepts UPDATE t ... WHERE id IN (SELECT id FROM t ...);
    # MySQL error 1093 does not apply. Do not inherit MysqlQuirks' True.
    update_subquery_requires_derived_table: bool = False

    # MariaDB does not implement ``CAST(expr AS JSON)`` (MDEV-26448, still
    # open). Its ``JSON`` type is only an alias for ``LONGTEXT`` with a
    # validity CHECK, so inheriting MySQL's ``"JSON"`` here would emit a cast
    # the MariaDB parser rejects; a serialized JSON value binds as plain text
    # with no cast at all.
    json_bind_cast_type: Optional[str] = None

    def __init__(self, dialect_name: str = "mariadb") -> None:
        """Initialize MariaDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)


__all__ = ["MariadbQuirks"]
