"""``DocumentSnapshotManager`` — snapshot storage without DDL.

The relational default (``BaseSnapshotManager``) renders ``CREATE TABLE``.
A document plugin that inherits it silently gets a SQL path that dies at
execution, so the contract makes the collection-create abstract: omitting
it is a TypeError at construction, not a failure during a migrate run.
"""

import pytest

from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE
from db.plugins.nosql_base import DocumentSnapshotManager


class _Recording(DocumentSnapshotManager):
    def __init__(self, provider=None, log=None):
        super().__init__(provider=provider, log=log)
        self.created = []

    def create_snapshot_collection(self, collection_name: str) -> None:
        self.created.append(collection_name)


class _Forgetful(DocumentSnapshotManager):
    """Subclass that never implements the abstract method."""


def test_forgetting_the_create_is_a_construction_error():
    with pytest.raises(TypeError):
        _Forgetful(provider=object())


def test_default_collection_name_is_the_shared_constant():
    manager = _Recording()
    manager.create_snapshot_table_if_not_exists("ignored_schema")
    assert manager.created == [DBLIFT_SCHEMA_SNAPSHOTS_TABLE]


def test_explicit_name_wins():
    manager = _Recording()
    manager.create_snapshot_table_if_not_exists("ignored_schema", "custom_snaps")
    assert manager.created == ["custom_snaps"]


def test_empty_name_falls_back_to_the_default():
    """An empty string is a caller bug, not a request for a nameless
    collection — treat it as absent rather than creating ``""``."""
    manager = _Recording()
    manager.create_snapshot_table_if_not_exists("ignored_schema", "")
    assert manager.created == [DBLIFT_SCHEMA_SNAPSHOTS_TABLE]


def test_no_ddl_is_produced():
    """Nothing on this contract may return or execute SQL."""
    manager = _Recording()
    manager.create_snapshot_table_if_not_exists("ignored_schema")
    assert not any("CREATE" in name.upper() for name in manager.created)
