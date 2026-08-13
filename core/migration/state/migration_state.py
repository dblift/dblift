"""Structured migration state snapshot models.

These dataclasses provide a transport-friendly representation of the current
migration state that can be serialized to JSON for consumption by CLI commands
and external tooling.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.migration.state.migration_display_state import MigrationDisplayState


@dataclass(slots=True)
class ChecksumChange:
    """Represents a checksum difference for a migration script."""

    script_name: str
    previous_checksum: Optional[str]
    current_checksum: Optional[str]

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Return a JSON-serializable representation."""

        return {
            "script": self.script_name,
            "previous": self.previous_checksum,
            "current": self.current_checksum,
        }


@dataclass(slots=True)
class MigrationEntry:
    """Summary view of a migration used in state payloads."""

    script: str
    version: Optional[str]
    description: Optional[str]
    type: Optional[str]
    status: Optional[str]
    checksum: Optional[str]
    installed_on: Optional[str] = None
    installed_by: Optional[str] = None
    execution_time_ms: Optional[int] = None

    @staticmethod
    def _format_datetime(value: Any) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, str):
            return value

        # Provider objects often come back as driver timestamp objects or datetime
        if hasattr(value, "isoformat"):
            return str(value.isoformat())

        return str(value)

    @classmethod
    def from_migration(cls, migration: Any, status: Optional[str] = None) -> "MigrationEntry":
        """Create an entry from a migration-like object."""

        version_val = getattr(migration, "version", None)
        return cls(
            script=getattr(migration, "script_name", ""),
            version=str(version_val) if version_val not in (None, "") else None,
            description=getattr(migration, "description", None),
            type=(
                getattr(getattr(migration, "type", None), "name", None)
                if getattr(migration, "type", None) is not None
                else getattr(migration, "type", None)
            ),
            status=status
            or getattr(migration, "state", None)
            or getattr(migration, "status", None),
            checksum=getattr(migration, "checksum", None),
            installed_on=cls._format_datetime(getattr(migration, "installed_on", None)),
            installed_by=getattr(migration, "installed_by", None),
            execution_time_ms=getattr(migration, "execution_time", None),
        )

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Return a JSON-serializable representation."""

        data = asdict(self)
        # Filter out None values for cleaner payloads
        return {key: value for key, value in data.items() if value is not None}


@dataclass(slots=True)
class MigrationState:
    """Snapshot of migration state consumed by commands and formatters."""

    generated_at: str = field(default_factory=lambda: _dt.datetime.utcnow().isoformat() + "Z")
    current_version: Optional[str] = None
    baseline_version: Optional[str] = None
    applied: List[MigrationEntry] = field(default_factory=list)
    pending: List[MigrationEntry] = field(default_factory=list)
    failed: List[MigrationEntry] = field(default_factory=list)
    undone_versions: List[str] = field(default_factory=list)
    deleted_scripts: List[str] = field(default_factory=list)
    checksum_changes: List[ChecksumChange] = field(default_factory=list)
    applied_objects: List[Any] = field(default_factory=list, repr=False)
    all_applied_objects: List[Any] = field(default_factory=list, repr=False)
    pending_objects: List[Any] = field(default_factory=list, repr=False)
    failed_objects: List[Any] = field(default_factory=list, repr=False)
    executed_scripts: List[str] = field(default_factory=list, repr=False)
    repeatable_checksums: Dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def has_failures(self) -> bool:
        """True when any migration is in the failed bucket."""
        return bool(self.failed)

    @property
    def has_pending(self) -> bool:
        """True when any catalog entry is still executable Pending."""
        pending_status = MigrationDisplayState.PENDING.value
        return any(entry.status == pending_status for entry in self.pending)

    def executable_pending_objects(self) -> List[Any]:
        """Return catalog objects whose paired entry status is Pending."""
        pending_status = MigrationDisplayState.PENDING.value
        return [
            obj
            for obj, entry in zip(self.pending_objects, self.pending)
            if entry.status == pending_status
        ]

    @property
    def checksum_change_count(self) -> int:
        """Number of migrations whose on-disk checksum diverges from the recorded one."""
        return len(self.checksum_changes)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready dict representation of the state."""

        return {
            "generated_at": self.generated_at,
            "current_version": self.current_version,
            "baseline_version": self.baseline_version,
            "applied": [entry.to_dict() for entry in self.applied],
            "pending": [entry.to_dict() for entry in self.pending],
            "failed": [entry.to_dict() for entry in self.failed],
            "undone_versions": list(self.undone_versions),
            "deleted_scripts": list(self.deleted_scripts),
            "checksum_changes": [change.to_dict() for change in self.checksum_changes],
            "has_failures": self.has_failures,
            "has_pending": self.has_pending,
            "checksum_change_count": self.checksum_change_count,
            "executed_scripts": list(self.executed_scripts),
            "repeatable_checksums": dict(self.repeatable_checksums),
        }

    def copy(self) -> "MigrationState":
        """Return a shallow copy of the state for safe reuse."""

        return MigrationState(
            generated_at=self.generated_at,
            current_version=self.current_version,
            baseline_version=self.baseline_version,
            applied=list(self.applied),
            pending=list(self.pending),
            failed=list(self.failed),
            undone_versions=list(self.undone_versions),
            deleted_scripts=list(self.deleted_scripts),
            checksum_changes=list(self.checksum_changes),
            applied_objects=list(self.applied_objects),
            all_applied_objects=list(self.all_applied_objects),
            pending_objects=list(self.pending_objects),
            failed_objects=list(self.failed_objects),
            executed_scripts=list(self.executed_scripts),
            repeatable_checksums=dict(self.repeatable_checksums),
        )
