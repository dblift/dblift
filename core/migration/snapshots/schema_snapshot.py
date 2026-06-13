"""Schema snapshot payload model and codec.

Defines the canonical :class:`SchemaSnapshotPayload` (one list per object kind
captured at a point in time), the :class:`SchemaSnapshot` envelope persisted
in the ``dblift_schema_snapshots`` table, and helpers for gzip/base64 payload
encoding and SHA-256 checksum computation.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# Re-export for in-tree callers (snapshot_repository, tests).
from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE as SNAPSHOT_TABLE_NAME  # noqa: F401
from core.sql_model.database_link import DatabaseLink
from core.sql_model.event import Event
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.linked_server import LinkedServer
from core.sql_model.module import Module
from core.sql_model.package import Package
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.table_canonicalizer import TableCanonicalizer
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _isoformat(dt: datetime) -> str:
    return _to_utc(dt).isoformat().replace("+00:00", "Z")


def _parse_iso(timestamp: str) -> datetime:
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    return datetime.fromisoformat(timestamp)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return _isoformat(obj)
    if isinstance(obj, Enum):
        return getattr(obj, "value", str(obj))
    return str(obj)


def _payload_to_json_bytes(payload_data: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload_data,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    ).encode("utf-8")


def encode_payload(payload: "SchemaSnapshotPayload") -> str:
    """Serialize ``payload`` to canonical JSON, gzip-compress it, and return base64 ASCII."""
    json_bytes = _payload_to_json_bytes(payload.to_dict())
    compressed = gzip.compress(json_bytes)
    return base64.b64encode(compressed).decode("ascii")


def decode_payload(encoded: str) -> "SchemaSnapshotPayload":
    """Inverse of :func:`encode_payload`; tolerates missing base64 padding (CosmosDB strips it)."""
    # Fix base64 padding if needed (CosmosDB might strip padding)
    encoded_clean = encoded.strip()
    # Add padding if needed (base64 strings must be multiples of 4)
    missing_padding = len(encoded_clean) % 4
    if missing_padding:
        encoded_clean += "=" * (4 - missing_padding)

    try:
        decoded = base64.b64decode(encoded_clean.encode("ascii"))
        json_bytes = gzip.decompress(decoded)
        payload_dict = json.loads(json_bytes.decode("utf-8"))
        return SchemaSnapshotPayload.from_dict(payload_dict)
    except Exception:
        # If padding fix didn't work, try original
        if encoded_clean != encoded.strip():
            try:
                decoded = base64.b64decode(encoded.encode("ascii"))
                json_bytes = gzip.decompress(decoded)
                payload_dict = json.loads(json_bytes.decode("utf-8"))
                return SchemaSnapshotPayload.from_dict(payload_dict)
            except Exception:
                # Intentional: gzip fallback also failed; re-raise original JSON parse error
                pass
        raise


def compute_payload_checksum(payload: "SchemaSnapshotPayload") -> str:
    """Return the SHA-256 hex digest of the canonical JSON encoding of ``payload``."""
    json_bytes = _payload_to_json_bytes(payload.to_dict())
    return hashlib.sha256(json_bytes).hexdigest()


@dataclass
class SchemaSnapshotPayload:
    """Canonical schema representation captured at a point in time."""

    tables: List[Table] = field(default_factory=list)
    views: List[View] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
    sequences: List[Sequence] = field(default_factory=list)
    triggers: List[Trigger] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    procedures: List[Procedure] = field(default_factory=list)
    functions: List[Procedure] = field(default_factory=list)
    packages: List[Package] = field(default_factory=list)
    synonyms: List[Synonym] = field(default_factory=list)
    user_defined_types: List[UserDefinedType] = field(default_factory=list)
    extensions: List[Extension] = field(default_factory=list)
    foreign_data_wrappers: List[ForeignDataWrapper] = field(default_factory=list)
    foreign_servers: List[ForeignServer] = field(default_factory=list)
    database_links: List[DatabaseLink] = field(default_factory=list)
    linked_servers: List[LinkedServer] = field(default_factory=list)
    modules: List[Module] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize every captured object list (plus metadata) into a JSON-ready dict."""
        return {
            "tables": [table.to_dict() for table in self.tables],
            "views": [view.to_dict() for view in self.views],
            "indexes": [index.to_dict() for index in self.indexes],
            "sequences": [sequence.to_dict() for sequence in self.sequences],
            "triggers": [trigger.to_dict() for trigger in self.triggers],
            "events": [event.to_dict() for event in self.events],
            "procedures": [proc.to_dict() for proc in self.procedures],
            "functions": [func.to_dict() for func in self.functions],
            "packages": [pkg.to_dict() for pkg in self.packages],
            "synonyms": [synonym.to_dict() for synonym in self.synonyms],
            "user_defined_types": [udt.to_dict() for udt in self.user_defined_types],
            "extensions": [ext.to_dict() for ext in self.extensions],
            "foreign_data_wrappers": [fdw.to_dict() for fdw in self.foreign_data_wrappers],
            "foreign_servers": [server.to_dict() for server in self.foreign_servers],
            "database_links": [link.to_dict() for link in self.database_links],
            "linked_servers": [ls.to_dict() for ls in self.linked_servers],
            "modules": [mod.to_dict() for mod in self.modules],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchemaSnapshotPayload":
        """Rehydrate a payload from its dict form; tables go through ``TableCanonicalizer``."""
        canonicalizer = TableCanonicalizer()
        tables = [Table.from_dict(item) for item in data.get("tables", [])]
        canonicalizer.canonicalize_tables(tables)
        return cls(
            tables=tables,
            views=[View.from_dict(item) for item in data.get("views", [])],
            indexes=[Index.from_dict(item) for item in data.get("indexes", [])],
            sequences=[Sequence.from_dict(item) for item in data.get("sequences", [])],
            triggers=[Trigger.from_dict(item) for item in data.get("triggers", [])],
            events=[Event.from_dict(item) for item in data.get("events", [])],
            procedures=[Procedure.from_dict(item) for item in data.get("procedures", [])],
            functions=[Procedure.from_dict(item) for item in data.get("functions", [])],
            packages=[Package.from_dict(item) for item in data.get("packages", [])],
            synonyms=[Synonym.from_dict(item) for item in data.get("synonyms", [])],
            user_defined_types=[
                UserDefinedType.from_dict(item) for item in data.get("user_defined_types", [])
            ],
            extensions=[Extension.from_dict(item) for item in data.get("extensions", [])],
            foreign_data_wrappers=[
                ForeignDataWrapper.from_dict(item) for item in data.get("foreign_data_wrappers", [])
            ],
            foreign_servers=[
                ForeignServer.from_dict(item) for item in data.get("foreign_servers", [])
            ],
            database_links=[
                DatabaseLink.from_dict(item) for item in data.get("database_links", [])
            ],
            linked_servers=[
                LinkedServer.from_dict(item) for item in data.get("linked_servers", [])
            ],
            modules=[Module.from_dict(item) for item in data.get("modules", [])],
            metadata=data.get("metadata", {}),
        )


@dataclass
class SchemaSnapshot:
    """Persisted schema snapshot metadata and payload."""

    snapshot_id: str
    captured_at: datetime
    payload: SchemaSnapshotPayload
    checksum: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.checksum:
            self.checksum = compute_payload_checksum(self.payload)

    @property
    def captured_at_iso(self) -> str:
        """Return ``captured_at`` as an ISO-8601 string in UTC with a trailing ``Z``."""
        return _isoformat(self.captured_at)

    @property
    def metadata(self) -> Dict[str, Any]:
        """Shortcut to the snapshot payload's metadata dict."""
        return self.payload.metadata

    @property
    def dialect(self) -> Optional[str]:
        """Database dialect recorded in the payload metadata, if any."""
        return self.payload.metadata.get("dialect")

    @property
    def schema_name(self) -> Optional[str]:
        """Source schema name recorded in the payload metadata, if any."""
        return self.payload.metadata.get("schema")

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "SchemaSnapshot":
        """Rebuild a :class:`SchemaSnapshot` from a history-table row (decoding model_data)."""
        normalized_record = {
            (key.lower() if isinstance(key, str) else key): value for key, value in record.items()
        }
        payload_raw = normalized_record.get("model_data")
        if payload_raw is None:
            raise KeyError("model_data")
        if isinstance(payload_raw, bytes):
            payload_raw = payload_raw.decode("ascii")
        payload = decode_payload(payload_raw)
        captured_at_value = normalized_record.get("captured_at")
        if isinstance(captured_at_value, datetime):
            captured_at_dt = _to_utc(captured_at_value)
        elif isinstance(captured_at_value, str) and captured_at_value:
            captured_at_dt = _to_utc(_parse_iso(captured_at_value))
        else:
            captured_at_dt = datetime.now(timezone.utc)
        return cls(
            snapshot_id=str(normalized_record["snapshot_id"]),
            captured_at=captured_at_dt,
            payload=payload,
            checksum=normalized_record.get("checksum"),
        )

    def to_record_values(self) -> List[Any]:
        """Return the positional row values used by the snapshot repository INSERT."""
        payload_encoded = encode_payload(self.payload)
        return [
            self.snapshot_id,
            _to_utc(self.captured_at).replace(tzinfo=None),
            self.checksum or "",
            payload_encoded,
        ]
