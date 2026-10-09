"""Quoted identifiers keep their exact text on the regex fallback path.

When sqlglot cannot parse a statement (it degrades it to a ``Command``) or
is skipped for it, ``HybridParser.extract_objects`` reports the regex
parser's objects. A double-quoted identifier is case-sensitive in
PostgreSQL and Db2: ``"Case"`` and ``case`` are different objects, and
``"a""b"`` names ``a"b``. The fallback must keep that exact text, while an
unquoted identifier still folds to the dialect's catalog case.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.hybrid_parser import HybridParser


def _extract(dialect, sql):
    return [
        (obj.object_type, obj.schema, obj.name)
        for obj in HybridParser(dialect).extract_objects(sql)
    ]


def _extract_regex(dialect, sql):
    return [
        (obj.object_type, obj.schema, obj.name)
        for obj in HybridParser(dialect).regex_parser.extract_objects(sql)
    ]


@pytest.mark.unit
class TestHybridFallbackKeepsQuotedCase:
    """End-to-end through ``HybridParser.extract_objects`` on statements
    sqlglot does not turn into a CREATE expression."""

    @pytest.mark.parametrize(
        "dialect, sql, expected",
        [
            (
                "postgresql",
                'CREATE TABLE "Case" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, "public", "Case"),
            ),
            (
                "postgresql",
                'CREATE TABLE "S"."Case" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, "S", "Case"),
            ),
            (
                "postgresql",
                'CREATE TABLE "a""b" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, "public", 'a"b'),
            ),
            (
                "postgresql",
                'CREATE VIEW "S"."Vw" WITH (security_barrier) AS SELECT 1;',
                (SqlObjectType.VIEW, "S", "Vw"),
            ),
            (
                "postgresql",
                'CREATE INDEX "Ix" ON "T" (a) TABLESPACE ts;',
                (SqlObjectType.INDEX, "public", "Ix"),
            ),
            (
                "postgresql",
                'CREATE FUNCTION "S"."Fn"() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;',
                (SqlObjectType.FUNCTION, "S", "Fn"),
            ),
            (
                "postgresql",
                'CREATE PROCEDURE "Pr"() AS $$ BEGIN END $$ LANGUAGE plpgsql;',
                (SqlObjectType.PROCEDURE, "public", "Pr"),
            ),
            (
                "postgresql",
                'CREATE TRIGGER "Tg" AFTER INSERT ON "T" FOR EACH ROW EXECUTE FUNCTION f();',
                (SqlObjectType.TRIGGER, "public", "Tg"),
            ),
            (
                "db2",
                'CREATE TABLE "Case" (a int) IN TS1;',
                (SqlObjectType.TABLE, "SYSIBM", "Case"),
            ),
            (
                "db2",
                'CREATE TABLE "S"."Case" (a int) IN TS1;',
                (SqlObjectType.TABLE, "S", "Case"),
            ),
            (
                "db2",
                'CREATE TABLE "a""b" (a int) IN TS1;',
                (SqlObjectType.TABLE, "SYSIBM", 'a"b'),
            ),
            (
                "db2",
                'CREATE VIEW "S"."Vw" AS SELECT 1 FROM sysibm.sysdummy1;',
                (SqlObjectType.VIEW, "S", "Vw"),
            ),
            (
                "db2",
                'CREATE INDEX "S"."Ix" ON "T" (a);',
                (SqlObjectType.INDEX, "S", "Ix"),
            ),
            (
                "db2",
                'CREATE SEQUENCE "Sq";',
                (SqlObjectType.SEQUENCE, "SYSIBM", "Sq"),
            ),
            (
                "db2",
                'CREATE FUNCTION "Fn"() RETURNS int RETURN 1;',
                (SqlObjectType.FUNCTION, "SYSIBM", "Fn"),
            ),
            (
                "db2",
                'CREATE PROCEDURE "Pr"() BEGIN END;',
                (SqlObjectType.PROCEDURE, "SYSIBM", "Pr"),
            ),
            (
                "db2",
                'CREATE TRIGGER "Tg" AFTER INSERT ON "T" FOR EACH ROW BEGIN END;',
                (SqlObjectType.TRIGGER, "SYSIBM", "Tg"),
            ),
        ],
    )
    def test_quoted_name_keeps_exact_text(self, dialect, sql, expected):
        assert _extract(dialect, sql) == [expected]

    @pytest.mark.parametrize(
        "dialect, sql, expected",
        [
            (
                "postgresql",
                "CREATE TABLE MiXed (a int) WITH (fillfactor=70) TABLESPACE ts;",
                (SqlObjectType.TABLE, "public", "mixed"),
            ),
            (
                "postgresql",
                'CREATE TABLE "S".MiXed (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, "S", "mixed"),
            ),
            (
                "postgresql",
                'CREATE TABLE MySchema."Case" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, "myschema", "Case"),
            ),
            (
                "db2",
                "CREATE TABLE MiXed (a int) IN TS1;",
                (SqlObjectType.TABLE, "SYSIBM", "MIXED"),
            ),
            (
                "db2",
                'CREATE TABLE MySchema."Case" (a int) IN TS1;',
                (SqlObjectType.TABLE, "MYSCHEMA", "Case"),
            ),
        ],
    )
    def test_unquoted_name_still_folds(self, dialect, sql, expected):
        assert _extract(dialect, sql) == [expected]

    def test_sqlglot_parsed_statement_unchanged(self):
        # sqlglot parses this one; the merge keeps a single object.
        assert _extract("postgresql", 'CREATE TABLE "Case" (a int);') == [
            (SqlObjectType.TABLE, "public", "Case")
        ]


@pytest.mark.unit
class TestRegexParserKeepsQuotedCase:
    """The regex parser itself, for object kinds sqlglot usually handles
    (its result is what ``HybridParser`` reports whenever sqlglot cannot)."""

    @pytest.mark.parametrize("dialect", ["postgresql", "redshift"])
    @pytest.mark.parametrize(
        "sql, expected",
        [
            ('CREATE TABLE "S"."Case" (a int);', (SqlObjectType.TABLE, "S", "Case")),
            ('CREATE VIEW "Vw" AS SELECT 1;', (SqlObjectType.VIEW, None, "Vw")),
            ('CREATE SEQUENCE "S"."Sq";', (SqlObjectType.SEQUENCE, "S", "Sq")),
            ('CREATE INDEX "Ix" ON t (a);', (SqlObjectType.INDEX, None, "Ix")),
            ('DROP TABLE "S"."Case";', (SqlObjectType.TABLE, "S", "Case")),
            ('ALTER TABLE "Case" ADD COLUMN b int;', (SqlObjectType.TABLE, None, "Case")),
            ("CREATE SEQUENCE MiXed;", (SqlObjectType.SEQUENCE, None, "mixed")),
        ],
    )
    def test_postgresql_family(self, dialect, sql, expected):
        assert _extract_regex(dialect, sql) == [expected]

    @pytest.mark.parametrize(
        "sql, expected",
        [
            ('DROP TABLE "S"."Case";', (SqlObjectType.TABLE, "S", "Case")),
            ('ALTER TABLE "Case" ADD COLUMN b int;', (SqlObjectType.TABLE, "SYSIBM", "Case")),
            ("CREATE SEQUENCE MiXed;", (SqlObjectType.SEQUENCE, "SYSIBM", "MIXED")),
        ],
    )
    def test_db2(self, sql, expected):
        assert _extract_regex("db2", sql) == [expected]


# PostgreSQL object patterns that capture no quoted name at all (their name
# is matched with ``\w+`` or not captured), so they have nothing to keep.
_PG_PATTERNS_WITHOUT_QUOTED_NAME = {
    "create_cast",
    "drop_operator",
    "drop_cast",
    "comment_index",
    "comment_sequence",
    "comment_procedure",
    "comment_trigger",
    "comment_type",
    "comment_domain",
    "comment_schema",
}


def _statement_for(key):
    """Build ``<VERB> <OBJECT WORDS> "Q""x"`` from an object_patterns key.

    PostgreSQL keys are ``<verb>_<kind>``; Db2 keys are just the kind, and
    each Db2 pattern accepts CREATE.
    """
    verb, _, kind = key.partition("_")
    if verb not in ("create", "alter", "drop", "comment"):
        verb, kind = "create", key
    verb = "COMMENT ON" if verb == "comment" else verb.upper()
    words = "SERVER" if kind == "foreign_server" else kind.replace("_", " ").upper()
    if kind == "column":
        return f'{verb} {words} "Q""x"."Q""x"'
    return f'{verb} {words} "Q""x"'


def _pattern_cases(dialect, excluded=frozenset()):
    config = HybridParser(dialect).regex_parser.config
    return [
        pytest.param(dialect, key, _statement_for(key), id=f"{dialect}-{key}")
        for key in config.object_patterns
        if key not in excluded
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "dialect, key, sql",
    _pattern_cases("postgresql", _PG_PATTERNS_WITHOUT_QUOTED_NAME) + _pattern_cases("db2"),
)
def test_every_object_pattern_keeps_quoted_name(dialect, key, sql):
    """Each object pattern on its own captures the quoted name whole."""
    config = HybridParser(dialect).regex_parser.config
    match = config.object_patterns[key].search(sql)

    assert match is not None, sql
    name = [group for group in match.groups() if group is not None][-1]
    assert config.normalize_identifier(name) == 'Q"x'
