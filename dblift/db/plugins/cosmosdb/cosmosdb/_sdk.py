"""Thin wrapper around the ``azure-cosmos`` SDK surface dblift uses.

Centralises the import path for sentinels and types so a single mistake
about where the SDK exposes a constant cannot recur in multiple call
sites.

B10-BUG-24 root cause: ``PartitionKey.NonePartitionKeyValue`` does not
exist on the ``PartitionKey`` *class*. The constant is defined at module
level in ``azure.cosmos.partition_key``. Both call sites (clean / repair)
hit the wrong path independently. Routing every reference through this
wrapper means future contributors get the right symbol without having to
re-discover the SDK layout.
"""

from __future__ import annotations

from azure.cosmos.partition_key import (
    NonePartitionKeyValue,
)

#: Sentinel value passed as ``partition_key`` when deleting a document
#: that lives in a partition-keyless container (e.g. R__ rows in
#: ``dblift_schema_history``). Re-exported from
#: ``azure.cosmos.partition_key`` to give callers a single, dblift-owned
#: import path.
NONE_PARTITION_KEY = NonePartitionKeyValue

__all__ = ["NONE_PARTITION_KEY"]
