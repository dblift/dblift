"""Regression tests for MySQL ``CREATE``/``DROP INDEX`` object extraction.

``MySqlConfig.object_patterns["index"]`` captured the ``ON``-target table
into the same (schema, name) group pair the generic heuristic in
``EnhancedRegexParser._create_object_from_match_enhanced`` reads for every
other object type, so an unqualified index name landed in ``schema`` and
the table name landed in ``name`` — e.g. ``CREATE INDEX idx1 ON
myschema.mytable`` reported ``name='mytable', schema='idx1'``.

MySQL indexes are not independently schema-qualified the way a Db2 index
is — ``CREATE INDEX index_name ON tbl_name ...`` allows no schema prefix
on ``index_name`` at all, the same as SQL Server's T-SQL. So this follows
the SQL Server fix directly: the ``ON``-target is matched but never
captured, and the index reports its own name with the default schema.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser


@pytest.mark.unit
class TestMySqlIndexObjectSchemaRegexParser:
    """Exercises ``MySqlRegexParser`` directly."""

    def setup_method(self):
        self.parser = MySqlRegexParser()

    def test_create_index(self):
        objects = self.parser.extract_objects("CREATE INDEX idx1 ON myschema.mytable (col);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema is None
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_unique_index(self):
        objects = self.parser.extract_objects("CREATE UNIQUE INDEX idx1 ON myschema.mytable (col);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema is None

    def test_create_fulltext_index(self):
        objects = self.parser.extract_objects(
            "CREATE FULLTEXT INDEX idx1 ON myschema.mytable (col);"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema is None

    def test_create_index_on_unqualified_table(self):
        objects = self.parser.extract_objects("CREATE INDEX idx1 ON mytable (col);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema is None

    def test_create_index_quoted_name(self):
        objects = self.parser.extract_objects("CREATE INDEX `idx 1` ON `myschema`.`mytable` (col);")

        assert len(objects) == 1
        assert objects[0].name == "idx 1"
        assert objects[0].schema is None

    def test_drop_index(self):
        # MySQL's DROP INDEX always requires an ON clause.
        objects = self.parser.extract_objects("DROP INDEX idx1 ON myschema.mytable;")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema is None
        assert objects[0].object_type == SqlObjectType.INDEX


@pytest.mark.unit
class TestMySqlIndexObjectSchemaDefaultParser:
    """Same assertions through the default (hybrid) parser. MySQL has a
    real sqlglot dialect, so the merge can mask the regex bug by letting
    a correct sqlglot entry survive alongside the wrong regex one — this
    was true here before the fix (two INDEX objects came back for the
    same statement) and must not regress to that."""

    def setup_method(self):
        self.parser = SqlParserFactory("mysql").get_parser()

    def test_create_index(self):
        objects = self.parser.extract_objects(
            "CREATE INDEX idx1 ON myschema.mytable (col);", default_schema="myschema"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "myschema"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_unique_index(self):
        objects = self.parser.extract_objects(
            "CREATE UNIQUE INDEX idx1 ON myschema.mytable (col);", default_schema="myschema"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "myschema"

    def test_drop_index(self):
        objects = self.parser.extract_objects(
            "DROP INDEX idx1 ON myschema.mytable;", default_schema="myschema"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "myschema"
