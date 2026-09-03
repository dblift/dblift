"""Shared foundation for document-store (NoSQL) plugins.

dblift's relational plugins share a lot through ``BaseQueryExecutor`` /
``BaseHistoryManager`` / ``BaseLockingManager``, all of which assume SQL.
Document stores do not: they have no DDL, no transactions, and their
history and lock rows are documents written through a vendor SDK.

Before this package the only NoSQL plugin (Cosmos DB) expressed those
concerns ad hoc, which is why a second one could not have shared anything
with it. The contracts here name what every document store must provide,
so a new plugin implements a known surface instead of inventing one — and,
in particular, so it never reaches for a SQL-shaped front-end. See
``docs/user-guide/nosql-python-migrations.md`` for the user-facing model.

What a document-store plugin supplies:

* :class:`DocumentHistoryManager` — migration history as documents.
* :class:`DocumentLockingManager` — a lease document guarding concurrent runs.
* :class:`DocumentSnapshotManager` — snapshot storage created through the
  driver instead of DDL.
* :class:`DocumentStoreProvider` — document-level reads and writes for
  storage dblift keeps inside the target database.
* :class:`SamplingIntrospector` — schema inferred by sampling documents.

Its quirks must also declare ``is_nosql = True`` and
``supports_sql_migrations = False`` so the framework routes ``.sql``
migrations to ``DBLIFT-NOSQL-001`` rather than to a translator.
"""

from dblift.db.plugins.nosql_base.history import DocumentHistoryManager
from dblift.db.plugins.nosql_base.introspection import SamplingIntrospector
from dblift.db.plugins.nosql_base.locking import DocumentLockingManager
from dblift.db.plugins.nosql_base.provider import DocumentStoreProvider
from dblift.db.plugins.nosql_base.snapshot import DocumentSnapshotManager

__all__ = [
    "DocumentHistoryManager",
    "DocumentLockingManager",
    "DocumentSnapshotManager",
    "DocumentStoreProvider",
    "SamplingIntrospector",
]
