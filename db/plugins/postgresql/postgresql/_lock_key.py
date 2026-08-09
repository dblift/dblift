"""Advisory lock key derivation for the PostgreSQL provider.

Kept in its own module rather than on the provider: two processes must
derive the same key for the same schema, so the derivation is pure and
independently testable. ``hashlib`` rather than ``hash()`` because Python
randomizes string hashes per process, which would let two concurrent
DBLift runs take different locks for one schema and migrate in parallel.
"""

import hashlib


def _get_advisory_lock_key(schema: str) -> int:
    """Return a deterministic PostgreSQL advisory lock key for a DBLift schema."""
    lock_name = f"dblift_migration_lock:{schema}"
    digest = hashlib.sha256(lock_name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)
