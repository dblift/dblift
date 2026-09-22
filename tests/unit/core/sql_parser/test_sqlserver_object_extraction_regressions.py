"""Regression tests for SQL Server object-name extraction.

The T-SQL identifier pattern used by ``SqlServerConfig.object_patterns``
captured an unquoted name with ``[^\\]]+`` — "anything but a closing
bracket" — which has no closing bracket to stop at for an unquoted
identifier, so the match ran to the end of the statement (the column
list, the trailing parenthesis, the semicolon). On the default
``HybridParser`` this garbled name did not replace the correct one sqlglot
produced; it survived alongside it, because the merge dedups by
``(name.lower(), object_type)`` and the two names no longer matched.

These tests assert the complete extracted-object list (exact names and
count) rather than membership, so a garbled name cannot pass by
coincidentally containing the real one.

``id_pattern`` also only modeled two dot-separated parts, so a three-part
``database.schema.object`` reference (legal for ``CREATE``/``ALTER``/``DROP
TABLE``) matched a two-part prefix of itself and dropped the real object
name; see ``TestThreePartNames``.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.parser_factory import SqlParserFactory


@pytest.mark.unit
class TestRegexParserObjectNames:
    """Every ``object_patterns`` entry shares the same identifier pattern;
    each object family is checked once to prove the fix is not table-only."""

    def setup_method(self):
        self.parser = SqlParserFactory("sqlserver", parser_type="regex").get_parser()

    def test_create_table_with_space_before_paren(self):
        objects = self.parser.extract_objects("CREATE TABLE real_one (id int);")

        assert len(objects) == 1
        assert objects[0].name == "real_one"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_create_table_no_space_before_paren(self):
        objects = self.parser.extract_objects("CREATE TABLE real_one(id int);")

        assert len(objects) == 1
        assert objects[0].name == "real_one"

    def test_create_table_no_trailing_semicolon(self):
        objects = self.parser.extract_objects("CREATE TABLE real_one (id int)")

        assert len(objects) == 1
        assert objects[0].name == "real_one"

    def test_create_table_schema_qualified(self):
        objects = self.parser.extract_objects("CREATE TABLE sales.real_one (id int);")

        assert len(objects) == 1
        assert objects[0].name == "real_one"
        assert objects[0].schema == "sales"

    def test_create_table_bracketed_name_containing_a_space(self):
        objects = self.parser.extract_objects("CREATE TABLE [dbo].[my table] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "my table"
        assert objects[0].schema == "dbo"

    def test_create_table_double_quoted_identifier(self):
        objects = self.parser.extract_objects('CREATE TABLE "real_one" (id int);')

        assert len(objects) == 1
        assert objects[0].name == "real_one"

    def test_drop_table(self):
        objects = self.parser.extract_objects("DROP TABLE real_one;")

        assert len(objects) == 1
        assert objects[0].name == "real_one"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_alter_table(self):
        objects = self.parser.extract_objects("ALTER TABLE real_one ADD col int;")

        assert len(objects) == 1
        assert objects[0].name == "real_one"

    def test_create_view(self):
        objects = self.parser.extract_objects("CREATE VIEW real_view AS SELECT 1;")

        assert len(objects) == 1
        assert objects[0].name == "real_view"
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_create_index_reports_index_name(self):
        # The index's own name is the object name; the ON-target table is
        # not captured at all (see TestIndexObjectSchema for the reasoning).
        objects = self.parser.extract_objects("CREATE INDEX idx1 ON real_one (id);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"

    def test_create_procedure(self):
        objects = self.parser.extract_objects("CREATE PROCEDURE real_proc AS SELECT 1;")

        assert len(objects) == 1
        assert objects[0].name == "real_proc"
        assert objects[0].object_type == SqlObjectType.PROCEDURE

    def test_create_function(self):
        sql = "CREATE FUNCTION real_func() RETURNS int AS BEGIN RETURN 1; END;"
        objects = self.parser.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "real_func"
        assert objects[0].object_type == SqlObjectType.FUNCTION

    def test_create_trigger(self):
        sql = "CREATE TRIGGER real_trig ON real_one AFTER INSERT AS BEGIN SELECT 1; END;"
        objects = self.parser.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "real_trig"
        assert objects[0].object_type == SqlObjectType.TRIGGER

    def test_create_synonym(self):
        objects = self.parser.extract_objects("CREATE SYNONYM real_syn FOR dbo.real_one;")

        assert len(objects) == 1
        assert objects[0].name == "real_syn"

    def test_create_schema(self):
        objects = self.parser.extract_objects("CREATE SCHEMA real_schema;")

        assert len(objects) == 1
        assert objects[0].name == "real_schema"

    def test_create_type(self):
        objects = self.parser.extract_objects("CREATE TYPE real_type FROM int;")

        assert len(objects) == 1
        assert objects[0].name == "real_type"

    def test_create_sequence(self):
        objects = self.parser.extract_objects("CREATE SEQUENCE real_seq START WITH 1;")

        assert len(objects) == 1
        assert objects[0].name == "real_seq"
        assert objects[0].object_type == SqlObjectType.SEQUENCE


@pytest.mark.unit
class TestThreePartNames:
    """``database.schema.object`` is a legitimate T-SQL reference for
    ``CREATE``/``ALTER``/``DROP TABLE``. ``id_pattern`` originally modeled
    only two dot-separated parts, so a three-part name matched a two-part
    prefix of itself: the database part landed in ``schema`` and the real
    schema landed in ``name``, dropping the actual object name entirely."""

    def setup_method(self):
        self.parser = SqlParserFactory("sqlserver", parser_type="regex").get_parser()

    def test_create_table_three_part_name(self):
        objects = self.parser.extract_objects("CREATE TABLE mydb.dbo.mytable (id int);")

        assert len(objects) == 1
        assert objects[0].name == "mytable"
        assert objects[0].schema == "dbo"

    def test_alter_table_three_part_name(self):
        objects = self.parser.extract_objects("ALTER TABLE mydb.dbo.mytable ADD col int;")

        assert len(objects) == 1
        assert objects[0].name == "mytable"
        assert objects[0].schema == "dbo"

    def test_drop_table_three_part_name(self):
        objects = self.parser.extract_objects("DROP TABLE mydb.dbo.mytable;")

        assert len(objects) == 1
        assert objects[0].name == "mytable"
        assert objects[0].schema == "dbo"

    def test_three_part_name_brackets_on_some_parts_not_others(self):
        objects = self.parser.extract_objects("CREATE TABLE [mydb].dbo.[my table] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "my table"
        assert objects[0].schema == "dbo"

    def test_three_part_name_all_bracketed(self):
        objects = self.parser.extract_objects("CREATE TABLE [mydb].[dbo].[mytable] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "mytable"
        assert objects[0].schema == "dbo"


@pytest.mark.unit
class TestIndexObjectSchema:
    """``CREATE``/``DROP INDEX`` mapped their capture groups so the index's
    own name landed in ``schema`` and the ON-target table's name landed in
    ``name``. An index is not itself schema-qualified in T-SQL — it belongs
    to a table, which has a schema — so the object's name is the index
    name and its schema is the default/current schema, never derived from
    the ON-target table."""

    def setup_method(self):
        self.parser = SqlParserFactory("sqlserver", parser_type="regex").get_parser()

    def test_create_index(self):
        objects = self.parser.extract_objects("CREATE INDEX idx1 ON real_one (id);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_unique_index(self):
        objects = self.parser.extract_objects("CREATE UNIQUE INDEX idx1 ON real_one (id);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"

    def test_create_index_on_schema_qualified_table(self):
        # The table's schema ("sales") is not the index's schema.
        objects = self.parser.extract_objects("CREATE INDEX idx1 ON sales.real_one (id);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"

    def test_create_index_bracketed_name(self):
        objects = self.parser.extract_objects("CREATE INDEX [idx 1] ON [real_one] (id);")

        assert len(objects) == 1
        assert objects[0].name == "idx 1"
        assert objects[0].schema == "dbo"

    def test_drop_index_on_syntax(self):
        objects = self.parser.extract_objects("DROP INDEX idx1 ON real_one;")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_xml_index(self):
        objects = self.parser.extract_objects("CREATE XML INDEX idx1 ON real_one (xml_col);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_primary_xml_index(self):
        objects = self.parser.extract_objects(
            "CREATE PRIMARY XML INDEX idx1 ON real_one (xml_col);"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"


@pytest.mark.unit
class TestXmlIndexNoDuplicateMatch:
    """``CREATE XML INDEX`` was matched by both the general "index_create"
    pattern (which allowed an optional XML keyword) and the dedicated
    "xml_index_create" pattern, extracting the same statement twice. The
    general pattern now excludes XML indexes, so only one pattern matches."""

    def setup_method(self):
        self.parser = SqlParserFactory("sqlserver", parser_type="regex").get_parser()

    def test_create_xml_index_matches_once(self):
        objects = self.parser.extract_objects("CREATE XML INDEX idx1 ON real_one (xml_col);")

        assert len(objects) == 1

    def test_create_primary_xml_index_matches_once(self):
        objects = self.parser.extract_objects(
            "CREATE PRIMARY XML INDEX idx1 ON real_one (xml_col);"
        )

        assert len(objects) == 1


@pytest.mark.unit
class TestIndexObjectSchemaDefaultParser:
    """Same assertions as ``TestIndexObjectSchema``, run through the default
    (hybrid) parser rather than the regex parser in isolation. The hybrid
    parser lets sqlglot's result override the regex one on a ``(name, type)``
    collision, so a fix verified only on the regex parser can still be wrong
    for every caller that uses the default — as the dotted "table.name"
    ``DROP INDEX`` syntax was: sqlglot's own handling of it reports the
    table as the schema, and the merge kept that over the regex result.
    The dotted "table.name" ``DROP INDEX`` syntax itself is covered
    separately, against both parser types, by
    ``TestDropIndexLegacyTableDotName`` below — see #367."""

    def setup_method(self):
        self.parser = SqlParserFactory("sqlserver").get_parser()

    def test_create_index(self):
        objects = self.parser.extract_objects(
            "CREATE INDEX idx1 ON real_one (id);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_unique_index(self):
        objects = self.parser.extract_objects(
            "CREATE UNIQUE INDEX idx1 ON real_one (id);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"

    def test_create_index_on_schema_qualified_table(self):
        objects = self.parser.extract_objects(
            "CREATE INDEX idx1 ON sales.real_one (id);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"

    def test_create_index_bracketed_name(self):
        objects = self.parser.extract_objects(
            "CREATE INDEX [idx 1] ON [real_one] (id);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx 1"
        assert objects[0].schema == "dbo"

    def test_drop_index_on_syntax(self):
        objects = self.parser.extract_objects("DROP INDEX idx1 ON real_one;", default_schema="dbo")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_xml_index(self):
        objects = self.parser.extract_objects(
            "CREATE XML INDEX idx1 ON real_one (xml_col);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_create_primary_xml_index(self):
        objects = self.parser.extract_objects(
            "CREATE PRIMARY XML INDEX idx1 ON real_one (xml_col);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"


@pytest.mark.unit
class TestDropIndexLegacyTableDotName:
    """The deprecated but still-valid T-SQL
    ``DROP INDEX [owner.]table.index_name`` spelling. sqlglot has no
    SQL-Server-specific handling for ``DROP INDEX`` and parses the dotted
    qualifier the same generic way it would parse ``[catalog.]schema.table``
    for ``DROP TABLE`` — as the object's schema (and catalog, for the
    three-part form). An index is never itself schema-qualified in T-SQL
    (see ``TestIndexObjectSchema`` above); the qualifier immediately before
    the index name is the table it belongs to, not its schema. But an
    owner prefix ahead of the table — the three-part
    ``owner.table.index_name`` form — *is* real schema data: sqlglot parses
    it into ``Table.catalog``, and that must survive, not fall back to the
    default schema.

    ``index_drop`` (``parser_config.py``) does not match either spelling at
    all — support for the two-part form was added and then deliberately
    withdrawn (see that file's history) because it only worked through the
    regex-only parser while the default (hybrid) parser stayed wrong, which
    is the same trap #367 is about. So the regex-only parser correctly
    extracts nothing here, and the fix instead corrects the sqlglot-derived
    answer that the default parser actually uses.

    Every case below uses a ``default_schema`` that differs from any schema
    embedded in the SQL. A test whose ``default_schema`` equals the
    expected answer cannot tell a correct read of an explicit qualifier
    apart from a fallback silently discarding it — the three-part case here
    exists because that gap let exactly that regression through in review.

    Parametrize over both parser types for any test like this one — with
    the expected result for *each* spelled out, not assumed identical — so
    a fix verified only on ``parser_type="regex"`` can't mask a still-wrong
    default parser again.
    """

    @pytest.mark.parametrize(
        "parser_type, expected",
        [
            pytest.param(
                "hybrid", [("idx1", "unrelated_default", SqlObjectType.INDEX)], id="hybrid"
            ),
            pytest.param("regex", [], id="regex-does-not-match-this-spelling"),
        ],
    )
    def test_drop_index_table_dot_name(self, parser_type, expected):
        # Two-part form: "real_one" is the table, not a schema — there is no
        # embedded schema to read, so the correct answer is always whatever
        # default_schema was passed in.
        parser = SqlParserFactory("sqlserver", parser_type=parser_type).get_parser()

        objects = parser.extract_objects(
            "DROP INDEX real_one.idx1;", default_schema="unrelated_default"
        )

        actual = [(obj.name, obj.schema, obj.object_type) for obj in objects]
        assert actual == expected

    @pytest.mark.parametrize(
        "parser_type, expected",
        [
            pytest.param("hybrid", [("idx1", "dbo", SqlObjectType.INDEX)], id="hybrid"),
            pytest.param("regex", [], id="regex-does-not-match-this-spelling"),
        ],
    )
    def test_drop_index_owner_table_dot_name(self, parser_type, expected):
        # "dbo" here is the table's *owner* (an explicit schema), not the
        # table's name — the default_schema below is deliberately a
        # different value so a fallback can't masquerade as a correct read.
        parser = SqlParserFactory("sqlserver", parser_type=parser_type).get_parser()

        objects = parser.extract_objects(
            "DROP INDEX dbo.real_one.idx1;", default_schema="unrelated_default"
        )

        actual = [(obj.name, obj.schema, obj.object_type) for obj in objects]
        assert actual == expected


@pytest.mark.unit
class TestHybridParserNoDuplicateOnFixedName:
    """The default (hybrid) parser combines the regex and sqlglot results,
    keyed by name. Once the regex name matches sqlglot's, the dict key
    collides and sqlglot's entry alone survives — no separate merge change
    is needed."""

    def setup_method(self):
        self.parser = SqlParserFactory("sqlserver")

    def test_create_table_reported_case(self):
        # The exact statement from the report.
        objects = self.parser.extract_objects("CREATE TABLE real_one (id int);")

        assert len(objects) == 1
        assert objects[0].name == "real_one"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_create_view_also_deduplicates(self):
        objects = self.parser.extract_objects("CREATE VIEW real_view AS SELECT 1;")

        assert len(objects) == 1

    def test_create_xml_index_no_near_duplicate(self):
        # Regression for the general/xml index pattern overlap: since both
        # now extract the same (name, schema), the merge's (name, type) key
        # collapses them instead of the two differing enough to survive
        # as a near-duplicate.
        objects = self.parser.extract_objects("CREATE XML INDEX idx1 ON real_one (xml_col);")

        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].object_type == SqlObjectType.INDEX
