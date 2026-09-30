"""Keep obsolete generator-only members out of the execution quirks boundary."""

import pytest

from dblift.core.dialect_boundary import DdlQuirks
from dblift.db.base_quirks import BaseQuirks
from dblift.db.provider_registry import ProviderRegistry

REMOVED_MEMBERS = (
    "column_comment_template",
    "index_comment_template",
    "table_comment_template",
    "proc_drop_supports_if_exists",
    "proc_supports_create_or_replace",
    "seq_drop_supports_if_exists",
    "synonym_keyword",
    "synonym_supports_create_or_replace",
    "table_check_strip_utf8mb4",
    "table_check_via_alter",
    "table_create_keyword",
    "table_create_supports_if_not_exists",
    "table_fk_suppress_on_update",
    "table_inline_unique_single_col",
    "table_not_null_implicit_on_identity_pk",
    "table_not_null_implicit_on_inline_pk",
    "table_prefers_inline_single_pk",
    "table_self_ref_fk_via_alter",
    "table_supports_constraint_nocheck",
    "table_supports_constraint_state",
    "table_supports_deferrable_constraints",
    "table_supports_inline_collate",
    "table_tablespace_style",
    "table_temporary_style",
    "view_create_or_replace_keyword",
    "view_drop_supports_if_exists",
    "view_supports_create_or_replace",
    "normalize_column_data_type",
    "render_computed_column",
    "render_column_nullable_change",
    "render_column_default_change",
    "render_column_type_change",
    "render_column_collation_change",
    "_cosmosdb_noop",
    "render_drop_for_object",
    "render_identity_clause",
    "render_system_versioning_alter",
    "requires_block_delimiter_wrapping",
    "requires_dialect_specific_wrapping",
    "script_header_session_init",
    "unwrap_default_value",
    "wrap_dialect_specific_block",
)


@pytest.mark.parametrize("name", REMOVED_MEMBERS)
def test_quirks_have_no_removed_rendering_member(name: str) -> None:
    ProviderRegistry.discover_plugins()
    classes = {BaseQuirks}
    for plugin in ProviderRegistry.list_plugins():
        classes.add(ProviderRegistry.quirks_base_class(plugin.name))
        for dialect in plugin.dialects:
            classes.add(type(ProviderRegistry.get_quirks(dialect)))
    for cls in sorted(classes, key=lambda cls: cls.__name__):
        assert not hasattr(cls, name), f"{cls.__name__}.{name} must be removed"


@pytest.mark.parametrize("name", REMOVED_MEMBERS)
def test_ddl_quirks_has_no_removed_rendering_member(name: str) -> None:
    assert not hasattr(DdlQuirks, name), f"DdlQuirks.{name} must be removed"
    assert name not in DdlQuirks.__annotations__
