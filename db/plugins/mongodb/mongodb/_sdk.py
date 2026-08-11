"""Thin wrapper around the ``pymongo`` surface dblift uses.

Centralises the import path for the driver symbols and exception types so
a single mistake about where the driver exposes one cannot recur across
call sites — the same role ``db/plugins/cosmosdb/cosmosdb/_sdk.py`` plays
for ``azure-cosmos``.

Imported lazily by its callers: plugin discovery must register ``mongodb``
on a machine where pymongo is not installed, and only *using* the plugin
may require the driver.
"""

from __future__ import annotations

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import CollectionInvalid, DuplicateKeyError, PyMongoError

#: Sort/index direction constant, re-exported so callers need not decide
#: between the driver's ``1`` literal and its named constant.
ASCENDING_ORDER = ASCENDING

__all__ = [
    "ASCENDING_ORDER",
    "CollectionInvalid",
    "DuplicateKeyError",
    "PyMongoError",
    "ReturnDocument",
]
