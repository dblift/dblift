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
    }

    # MariaDB historically did not need post-introspection rollback in dblift;
    # the legacy gate was ``dialect in ("db2", "mysql")``.
    # Override the parent ``True`` to preserve that behavior.
    requires_rollback_after_introspection: bool = False

    # MariaDB does not keep provider-compat snapshot DDL; reset the values
    # inherited from MysqlQuirks so a real MariadbProvider keeps the normal
    # existence check and raises (snapshots are not provider-owned).
    provider_compat_snapshot_skips_existence_check: bool = False

    def __init__(self, dialect_name: str = "mariadb") -> None:
        """Initialize MariaDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """Reject inherited MySQL snapshot table DDL."""
        raise NotImplementedError("MariaDB snapshots are not provider-owned")

    def build_provider_compat_snapshot_ddl(
        self, qualified_table: str, snapshot_id_size: int, checksum_size: int
    ) -> "Optional[str]":
        """MariaDB has no provider-compat snapshot DDL (overrides MySQL's)."""
        return None


__all__ = ["MariadbQuirks"]
