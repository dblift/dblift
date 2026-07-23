"""Typed view of a captured server identity (edition + version).

Snapshot capture stores the probed server identity as a plain mapping
(``metadata["server"] = {"edition": ..., "version": ...}``) so the payload
format stays dumb and stable. :class:`ServerInfo` is the read-side parse of
that mapping: it resolves the dialect's quirks and turns the raw version
banner into a comparable
:class:`~core.introspection.version_detector.DatabaseVersion` via the
``parse_server_version`` quirks hook. Parsing failures degrade to ``None``
fields — consumers treat "unknown" conservatively (see
:mod:`core.sql_model.feature_gates`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from core.introspection.version_detector import DatabaseVersion


@dataclass(frozen=True)
class ServerInfo:
    """Parsed server identity: edition string plus raw and parsed version."""

    edition: Optional[str] = None
    version_raw: Optional[str] = None
    version: "Optional[DatabaseVersion]" = None

    @classmethod
    def from_mapping(
        cls, dialect: Optional[str], mapping: Optional[Mapping[str, Any]]
    ) -> "ServerInfo":
        """Build a :class:`ServerInfo` from a raw ``{"edition", "version"}`` mapping.

        Tolerant by contract: a missing/empty mapping yields an all-``None``
        instance, and any registry or parsing failure degrades to
        ``version=None`` — never raises.
        """
        if not mapping:
            return cls()
        edition_value = mapping.get("edition")
        version_value = mapping.get("version")
        edition = str(edition_value) if edition_value not in (None, "") else None
        version_raw = str(version_value) if version_value not in (None, "") else None
        version: "Optional[DatabaseVersion]" = None
        if version_raw is not None:
            from core.introspection.version_detector import DatabaseVersion, parse_version

            if dialect:
                try:
                    from db.provider_registry import ProviderRegistry

                    quirks = ProviderRegistry.get_quirks(dialect.strip().lower())
                    parsed = quirks.parse_server_version(version_raw)
                    if isinstance(parsed, DatabaseVersion):
                        version = parsed
                except Exception:
                    version = None
            if version is None:
                version = parse_version(version_raw)
        return cls(edition=edition, version_raw=version_raw, version=version)


__all__ = ["ServerInfo"]
