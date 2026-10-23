"""Regression tests for Db2 ``CREATE``/``DROP INDEX`` object extraction.

``DB2Config.object_patterns["index"]`` captured the ``ON``-target table
into the same (schema, name) group pair the generic heuristic in
``EnhancedRegexParser._create_object_from_match_enhanced`` reads for every
other object type, so an unqualified index name landed in ``schema`` and
the table name landed in ``name`` — e.g. ``CREATE INDEX idx1 ON
myschema.mytable`` reported ``name='MYTABLE', schema='IDX1'``.

Unlike SQL Server and MySQL, a Db2 index *is* independently schema-
qualified (``CREATE INDEX [indexschema.]indexname ON
[tableschema.]tablename ...`` — ``SYSCAT.INDEXES`` has its own
``INDSCHEMA`` column, separate from the table's ``TABSCHEMA``). So the
fix here is not "drop the schema, default it" as it was for SQL Server:
the index name itself gains the same optional ``schema.name`` capture
every other Db2 object pattern already has, and only the ``ON``-target is
stopped from being captured.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from tests.support.facts_parser import facts_parser


@pytest.mark.unit
class TestDb2IndexObjectSchemaRegexParser:
    """Exercises ``DB2RegexParser`` directly."""

    def setup_method(self):
        self.parser = facts_parser("db2")

    def test_create_index_own_schema_qualified(self):
        # The index's own schema ("idxschema") is captured; the table's
        # schema ("myschema") is not — they are independent in Db2.
        objects = self.parser.extract_objects(
            "CREATE INDEX idxschema.idx1 ON myschema.mytable (col);"
        )

        assert len(objects) == 1
        assert objects[0].name == "IDX1"
        assert objects[0].schema == "IDXSCHEMA"

    def test_drop_index_own_schema_qualified(self):
        # Db2 DROP INDEX has no ON clause at all — the index's own
        # schema.name is the entire target.
        objects = self.parser.extract_objects("DROP INDEX idxschema.idx1;")

        assert len(objects) == 1
        assert objects[0].name == "IDX1"
        assert objects[0].schema == "IDXSCHEMA"


@pytest.mark.unit
class TestDb2IndexObjectSchemaDefaultParser:
    """Same assertions through the default parser, which reads statement facts.
    An index name without a schema takes the default schema as given."""

    def setup_method(self):
        self.parser = SqlParserFactory("db2").get_parser()

    def test_create_index(self):
        objects = self.parser.extract_objects(
            "CREATE INDEX idx1 ON myschema.mytable (col);", default_schema="myschema"
        )

        assert len(objects) == 1
        assert objects[0].name == "IDX1"
        assert objects[0].schema == "myschema"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_index_own_schema_qualified(self):
        objects = self.parser.extract_objects(
            "CREATE INDEX idxschema.idx1 ON myschema.mytable (col);",
            default_schema="myschema",
        )

        assert len(objects) == 1
        assert objects[0].name == "IDX1"
        assert objects[0].schema == "IDXSCHEMA"

    def test_drop_index_own_schema_qualified(self):
        objects = self.parser.extract_objects(
            "DROP INDEX idxschema.idx1;", default_schema="myschema"
        )

        assert len(objects) == 1
        assert objects[0].name == "IDX1"
        assert objects[0].schema == "IDXSCHEMA"
