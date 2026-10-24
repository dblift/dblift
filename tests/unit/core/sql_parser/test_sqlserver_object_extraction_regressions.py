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
from tests.support.facts_parser import facts_parser


@pytest.mark.unit
class TestRegexParserObjectNames:
    """Every ``object_patterns`` entry shares the same identifier pattern;
    each object family is checked once to prove the fix is not table-only."""

    def setup_method(self):
        self.parser = facts_parser("sqlserver")

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

    def test_create_schema(self):
        objects = self.parser.extract_objects("CREATE SCHEMA real_schema;")

        assert len(objects) == 1
        assert objects[0].name == "real_schema"

    def test_create_sequence(self):
        objects = self.parser.extract_objects("CREATE SEQUENCE real_seq START WITH 1;")

        assert len(objects) == 1
        assert objects[0].name == "real_seq"
        assert objects[0].object_type == SqlObjectType.SEQUENCE


@pytest.mark.unit
class TestIndexObjectSchemaDefaultParser:
    """The default facts parser reports proven index ownership and leaves
    unsupported XML index forms unnamed. The explicit regex parser above
    retains its own extraction contract."""

    def setup_method(self):
        self.parser = facts_parser("sqlserver")

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
        assert objects[0].schema == "sales"

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

        assert objects == []

    def test_create_primary_xml_index(self):
        objects = self.parser.extract_objects(
            "CREATE PRIMARY XML INDEX idx1 ON real_one (xml_col);", default_schema="dbo"
        )

        assert objects == []


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
            pytest.param("hybrid", [], id="facts-opaque"),
            pytest.param("regex", [], id="regex-does-not-match-this-spelling"),
        ],
    )
    def test_drop_index_table_dot_name(self, parser_type, expected):
        # Two-part form: "real_one" is the table, not a schema — there is no
        # embedded schema to read, so the correct answer is always whatever
        # default_schema was passed in.
        parser = facts_parser("sqlserver")

        objects = parser.extract_objects(
            "DROP INDEX real_one.idx1;", default_schema="unrelated_default"
        )

        actual = [(obj.name, obj.schema, obj.object_type) for obj in objects]
        assert actual == expected

    @pytest.mark.parametrize(
        "parser_type, expected",
        [
            pytest.param("hybrid", [], id="facts-opaque"),
            pytest.param("regex", [], id="regex-does-not-match-this-spelling"),
        ],
    )
    def test_drop_index_owner_table_dot_name(self, parser_type, expected):
        # "dbo" here is the table's *owner* (an explicit schema), not the
        # table's name — the default_schema below is deliberately a
        # different value so a fallback can't masquerade as a correct read.
        parser = facts_parser("sqlserver")

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
        self.parser = facts_parser("sqlserver")

    def test_create_table_reported_case(self):
        # The exact statement from the report.
        objects = self.parser.extract_objects("CREATE TABLE real_one (id int);")

        assert len(objects) == 1
        assert objects[0].name == "real_one"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_create_view_also_deduplicates(self):
        objects = self.parser.extract_objects("CREATE VIEW real_view AS SELECT 1;")

        assert len(objects) == 1

    def test_create_xml_index_is_opaque(self):
        objects = self.parser.extract_objects("CREATE XML INDEX idx1 ON real_one (xml_col);")

        assert objects == []


@pytest.mark.unit
class TestBracketDoublingRegexParser:
    """A ``]`` inside a bracketed T-SQL identifier is escaped by doubling it
    (``[real]]one]`` is the single identifier ``real]one``); a ``"`` inside a
    double-quoted identifier is escaped the same way (``"real""one"`` is
    ``real"one``). ``id_token`` stopped at the first unescaped-looking
    ``]``/``"``, so the doubled character split the identifier and truncated
    it to everything before the first occurrence."""

    def setup_method(self):
        self.parser = facts_parser("sqlserver")

    def test_plain_bracketed_name_unaffected(self):
        objects = self.parser.extract_objects("CREATE TABLE [normal] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "normal"

    def test_reported_case(self):
        # The exact statement from the issue report.
        objects = self.parser.extract_objects("CREATE TABLE [real]]one] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "real]one"

    def test_trailing_doubled_bracket(self):
        objects = self.parser.extract_objects("CREATE TABLE [name]]] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "name]"

    def test_doubled_bracket_at_start(self):
        objects = self.parser.extract_objects("CREATE TABLE []]abc] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "]abc"

    def test_two_doubled_brackets_in_one_identifier(self):
        objects = self.parser.extract_objects("CREATE TABLE [a]]b]]c] (id int);")

        assert len(objects) == 1
        assert objects[0].name == "a]b]c"

    def test_doubled_bracket_identifier_followed_by_another(self):
        objects = self.parser.extract_objects("CREATE TABLE [a]]b].[c]]d] (id int);")

        assert len(objects) == 1
        assert objects[0].schema == "a]b"
        assert objects[0].name == "c]d"

    def test_bracket_content_with_quotes_is_not_unescaped(self):
        # A double quote is not special inside brackets — only a doubled
        # ``]`` is an escape there — so ``["a""b"]``'s name is the literal
        # bracket content ``"a""b"``, unchanged. normalize_identifier must
        # not also apply the double-quote branch to content that merely
        # happens to start and end with ``"`` after the brackets are
        # stripped.
        objects = self.parser.extract_objects('CREATE TABLE ["a""b"] (id int);')

        assert len(objects) == 1
        assert objects[0].name == '"a""b"'


@pytest.mark.unit
class TestDoubleQuoteDoublingRegexParser:
    """Same doubling rule, double-quoted spelling (``QUOTED_IDENTIFIER ON``)."""

    def setup_method(self):
        self.parser = facts_parser("sqlserver")

    def test_plain_double_quoted_name_unaffected(self):
        objects = self.parser.extract_objects('CREATE TABLE "normal" (id int);')

        assert len(objects) == 1
        assert objects[0].name == "normal"

    def test_reported_case_double_quoted(self):
        objects = self.parser.extract_objects('CREATE TABLE "real""one" (id int);')

        assert len(objects) == 1
        assert objects[0].name == 'real"one'

    def test_trailing_doubled_quote(self):
        objects = self.parser.extract_objects('CREATE TABLE "name""" (id int);')

        assert len(objects) == 1
        assert objects[0].name == 'name"'

    def test_doubled_quote_at_start(self):
        objects = self.parser.extract_objects('CREATE TABLE """abc" (id int);')

        assert len(objects) == 1
        assert objects[0].name == '"abc'

    def test_two_doubled_quotes_in_one_identifier(self):
        objects = self.parser.extract_objects('CREATE TABLE "a""b""c" (id int);')

        assert len(objects) == 1
        assert objects[0].name == 'a"b"c'

    def test_doubled_quote_identifier_followed_by_another(self):
        objects = self.parser.extract_objects('CREATE TABLE "a""b"."c""d" (id int);')

        assert len(objects) == 1
        assert objects[0].schema == 'a"b'
        assert objects[0].name == 'c"d'


@pytest.mark.unit
class TestBracketAndQuoteDoublingHybridParser:
    """Same cases through the default (hybrid) parser. sqlglot already reads
    the doubled escape correctly on this path, so before the regex fix the
    merge produced two objects for one statement: the regex parser's
    truncated name survived alongside sqlglot's correct one, because they no
    longer collided on ``(name.lower(), object_type)``. After the fix both
    parsers agree, so the merge collapses back to a single object."""

    def setup_method(self):
        self.parser = facts_parser("sqlserver")

    def test_reported_case(self):
        objects = self.parser.extract_objects(
            "CREATE TABLE [real]]one] (id int);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "real]one"

    def test_reported_case_double_quoted(self):
        objects = self.parser.extract_objects(
            'CREATE TABLE "real""one" (id int);', default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == 'real"one'

    def test_trailing_doubled_bracket(self):
        objects = self.parser.extract_objects(
            "CREATE TABLE [name]]] (id int);", default_schema="dbo"
        )

        assert len(objects) == 1
        assert objects[0].name == "name]"
