"""BUG-COSMOS-02 regression: generate_ddl must emit CREATE CONTAINER and suppress CREATE INDEX.

CosmosDB executor only understands CREATE CONTAINER; CREATE TABLE fails at
runtime. Indexes are auto-managed via indexing policy — CREATE INDEX must be
replaced by a comment consistent with generate_drop_sql() behavior.
"""

from __future__ import annotations

import pytest

from core.sql_generator.sql_generator import SqlGenerator
from core.sql_model.base import SqlColumn
from core.sql_model.index import Index
from core.sql_model.table import Table

pytestmark = [pytest.mark.unit]


@pytest.mark.unit
class TestSqlGeneratorCosmosDb:
    def _generator(self) -> SqlGenerator:
        return SqlGenerator(default_dialect="cosmosdb")

    def _table(self, name: str = "orders") -> Table:
        col = SqlColumn("id", "STRING", is_nullable=False)
        return Table(name, columns=[col], dialect="cosmosdb")

    def _index(self, name: str = "idx_orders") -> Index:
        return Index(name, table_name="orders", columns=["id"], dialect="cosmosdb")

    def test_generate_ddl_table_emits_create_container(self):
        gen = self._generator()
        result = gen.generate_ddl([self._table()], target_dialect="cosmosdb")
        assert "CREATE CONTAINER" in result
        assert "CREATE TABLE" not in result

    def test_generate_ddl_index_emits_comment_not_create_index(self):
        gen = self._generator()
        result = gen.generate_ddl([self._index()], target_dialect="cosmosdb")
        assert "CREATE INDEX" not in result
        assert "indexing policy" in result.lower()

    def test_generate_ddl_table_and_index_together(self):
        gen = self._generator()
        result = gen.generate_ddl([self._table(), self._index()], target_dialect="cosmosdb")
        assert "CREATE CONTAINER" in result
        assert "CREATE TABLE" not in result
        assert "CREATE INDEX" not in result
        assert "indexing policy" in result.lower()

    def test_non_cosmosdb_index_unaffected(self):
        gen = SqlGenerator(default_dialect="postgresql")
        idx = Index("idx_users", table_name="users", columns=["id"], dialect="postgresql")
        result = gen.generate_ddl([idx], target_dialect="postgresql")
        assert "CREATE INDEX" in result
