"""Tests structurels : vérification absence d'import re inline dans schema_introspector (Story 16-7)."""

import inspect

import pytest

import core.introspection.schema_introspector as mod


@pytest.mark.unit
class TestSchemaIntrospectorInlineImports:
    """AC#6 — vérification structurelle (absence inline import re)."""

    # Story 16-7 originally required the module-level ``import re``; the
    # last consumer (``_normalize_oracle_partition_bound``) moved to
    # ``_oracle_utils`` so ``re`` is no longer imported in this module.
    # The "must exist / single occurrence" checks are deleted to track
    # the new reality. The inline-import checks below still guard
    # against re-introduction inside methods.

    def test_enrich_columns_computed_no_inline_import_re(self):
        """AC#1 : enrich_columns_with_computed n'a plus d'import re inline."""
        source = inspect.getsource(mod.SchemaIntrospector.enrich_columns_with_computed)
        assert (
            "import re" not in source
        ), "inline 'import re' should be removed from enrich_columns_with_computed"

    def test_enrich_table_partition_scheme_no_inline_import_re(self):
        """AC#2-4 : enrich_table_with_partition_scheme n'a plus d'import re inline."""
        source = inspect.getsource(mod.SchemaIntrospector.enrich_table_with_partition_scheme)
        assert (
            "import re" not in source
        ), "inline 'import re' should be removed from enrich_table_with_partition_scheme"

    # The ``_SQL_PARTITION_FUNCTIONS`` constant moved into
    # ``MysqlQuirks.extract_partition_scheme_from_row`` during the
    # H.2-followup-enrichers refactor — MySQL is the only dialect that
    # uses it. The "must live on _partition_enricher" structural check
    # was retired; the row-parsing logic now lives in the plugin
    # quirks where the partition method projection actually originates.
