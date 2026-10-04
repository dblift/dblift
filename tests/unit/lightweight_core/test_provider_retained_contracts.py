"""Keep consumer-owned storage out of the migration-provider contract."""

import importlib.util

import pytest

from dblift.core.constants import (
    DBLIFT_DATA_AUDIT_TABLE,
    DBLIFT_DATA_CHANGE_SET_TABLE,
    DBLIFT_SCHEMA_SNAPSHOTS_TABLE,
    DEFAULT_HISTORY_TABLE,
    MIGRATION_LOCK_TABLE,
)
from dblift.db.base_provider import BaseProvider
from dblift.db.base_quirks import BaseQuirks
from dblift.db.provider_interfaces import SchemaProvider
from dblift.db.provider_registry import ProviderRegistry

REMOVED_PROVIDER_MEMBERS = (
    "_create_data_table_if_not_exists",
    "create_data_history_table_if_not_exists",
    "create_data_change_set_table_if_not_exists",
    "create_data_audit_table_if_not_exists",
)
REMOVED_QUIRKS_MEMBERS = (
    "data_history_text_type",
    "data_change_set_blob_type",
    "data_timestamp_column_ddl",
    "build_data_history_table_ddl",
    "build_data_change_set_table_ddl",
    "build_data_audit_table_ddl",
    "is_data_history_table_already_exists_error",
    "is_data_change_set_table_already_exists_error",
)
REMOVED_SNAPSHOT_QUIRKS_MEMBERS = (
    "build_snapshot_table_ddl",
    "build_provider_compat_snapshot_ddl",
    "is_snapshot_table_already_exists_error",
    "provider_compat_snapshot_skips_existence_check",
)


def _registered_dialects():
    ProviderRegistry.discover_plugins()
    return sorted(
        {
            dialect
            for plugin in ProviderRegistry.list_plugins()
            if plugin.provider_class.__module__.startswith("dblift.db.")
            for dialect in plugin.dialects
        }
    )


@pytest.mark.parametrize("name", REMOVED_PROVIDER_MEMBERS)
def test_data_storage_is_absent_from_provider_classes_and_aliases(name: str) -> None:
    classes = {BaseProvider, SchemaProvider}
    classes.update(
        cls
        for dialect in _registered_dialects()
        if (cls := ProviderRegistry.get_provider_class(dialect))
        and cls.__module__.startswith("dblift.db.")
    )
    for cls in classes:
        assert not hasattr(cls, name), f"{cls.__name__}.{name} retains data storage"


@pytest.mark.parametrize("name", REMOVED_QUIRKS_MEMBERS)
def test_data_storage_is_absent_from_quirks_classes_and_aliases(name: str) -> None:
    classes = {BaseQuirks}
    classes.update(
        cls
        for dialect in _registered_dialects()
        if (cls := type(ProviderRegistry.get_quirks(dialect))).__module__.startswith("dblift.db.")
    )
    for cls in classes:
        assert not hasattr(cls, name), f"{cls.__name__}.{name} retains data storage"


def test_storage_names_remain_stable_for_cleanup() -> None:
    assert DEFAULT_HISTORY_TABLE == "dblift_schema_history"
    assert MIGRATION_LOCK_TABLE == "dblift_migration_lock"
    assert DBLIFT_SCHEMA_SNAPSHOTS_TABLE == "dblift_schema_snapshots"
    assert DBLIFT_DATA_CHANGE_SET_TABLE == "dblift_data_change_set"
    assert DBLIFT_DATA_AUDIT_TABLE == "dblift_data_audit"


def test_builtin_snapshot_storage_is_absent_from_provider_contract() -> None:
    classes = {BaseProvider, SchemaProvider}
    classes.update(
        cls
        for dialect in _registered_dialects()
        if (cls := ProviderRegistry.get_provider_class(dialect))
        and cls.__module__.startswith("dblift.db.")
    )
    for cls in classes:
        assert not hasattr(cls, "create_snapshot_table_if_not_exists"), cls.__name__


@pytest.mark.parametrize("name", REMOVED_SNAPSHOT_QUIRKS_MEMBERS)
def test_builtin_snapshot_storage_is_absent_from_quirks(name: str) -> None:
    from dblift.db.plugins.redshift.quirks import RedshiftQuirks

    classes = {BaseQuirks}
    classes.update(
        cls
        for dialect in _registered_dialects()
        if (cls := type(ProviderRegistry.get_quirks(dialect))).__module__.startswith("dblift.db.")
        and (cls is not RedshiftQuirks or name != "build_snapshot_table_ddl")
    )
    for cls in classes:
        assert not hasattr(cls, name), f"{cls.__name__}.{name} retains snapshot storage"


def test_unqualified_redshift_override_remains_local() -> None:
    from dblift.db.plugins.redshift.quirks import RedshiftQuirks

    assert "build_snapshot_table_ddl" in RedshiftQuirks.__dict__


def test_builtin_snapshot_manager_modules_are_absent() -> None:
    for module in (
        "dblift.db.plugins.base_snapshot_manager",
        "dblift.db.plugins.mongodb.mongodb.snapshot_manager",
        "dblift.db.plugins.cosmosdb.cosmosdb.snapshot_manager",
    ):
        assert importlib.util.find_spec(module) is None


def test_document_snapshot_manager_interface_remains() -> None:
    from dblift.db.plugins.nosql_base import DocumentSnapshotManager

    assert callable(DocumentSnapshotManager.create_snapshot_table_if_not_exists)
