"""MariaDB :class:`DialectQuirks`.

Inherits from :class:`MysqlQuirks` — same drop-statement variants,
delimiter wrapping, and definition-preservation rules. MariaDB-specific
overrides (sequences, system-versioned tables, native JSON typing on
modern versions) get added here as the epic touches each subsystem.
"""

from __future__ import annotations

from dblift.db.feature_gate import FeatureGate
from dblift.db.plugins.mysql.quirks import MysqlQuirks


class MariadbQuirks(MysqlQuirks):
    """MariaDB-specific :class:`DialectQuirks`, inheriting from :class:`MysqlQuirks`.

    Inherits all MySQL-family quirks (backtick quoting, ``DELIMITER``
    wrapping, definition-preservation for views / procedures /
    functions / triggers / events, no transactional DDL). MariaDB-only
    deviations land here as the codebase touches them: native ``JSON``
    type from 10.2+, native sequences and system-versioned tables on
    modern versions.

    """

    # Plain-view redefinition inherits MySQL's CREATE OR REPLACE support.
    # https://mariadb.com/docs/server/server-usage/views/create-view

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

    def __init__(self, dialect_name: str = "mariadb") -> None:
        """Initialize MariaDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)


__all__ = ["MariadbQuirks"]
