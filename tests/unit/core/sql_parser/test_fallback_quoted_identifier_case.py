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
from dblift.db.provider_registry import ProviderRegistry


def _created_by_facts(sql):
    facts = ProviderRegistry.get_quirks("postgresql").statement_facts(sql)
    return [
        (obj.type, obj.schema, obj.name) for obj in facts.affected_objects if obj.role == "created"
    ]


@pytest.mark.unit
class TestHybridFallbackKeepsQuotedCase:
    """End-to-end through ``HybridParser.extract_objects`` on statements
    sqlglot does not turn into a CREATE expression."""

    @pytest.mark.parametrize(
        "sql, expected",
        [
            (
                'CREATE TABLE "Case" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, None, "Case"),
            ),
            (
                'CREATE TABLE "S"."Case" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, "S", "Case"),
            ),
            (
                'CREATE TABLE "a""b" (a int) WITH (fillfactor=70) TABLESPACE ts;',
                (SqlObjectType.TABLE, None, 'a"b'),
            ),
            (
                'CREATE VIEW "S"."Vw" WITH (security_barrier) AS SELECT 1;',
                (SqlObjectType.VIEW, "S", "Vw"),
            ),
            ('CREATE INDEX "Ix" ON "T" (a) TABLESPACE ts;', (SqlObjectType.INDEX, None, "Ix")),
            (
                'CREATE FUNCTION "S"."Fn"() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;',
                (SqlObjectType.FUNCTION, "S", "Fn"),
            ),
            (
                'CREATE PROCEDURE "Pr"() AS $$ BEGIN END $$ LANGUAGE plpgsql;',
                (SqlObjectType.PROCEDURE, None, "Pr"),
            ),
            (
                'CREATE TRIGGER "Tg" AFTER INSERT ON "T" FOR EACH ROW EXECUTE FUNCTION f();',
                (SqlObjectType.TRIGGER, None, "Tg"),
            ),
            ('CREATE TABLE "Case" (a int);', (SqlObjectType.TABLE, None, "Case")),
        ],
    )
    def test_postgresql_statement_facts_keep_quoted_name_text(self, sql, expected):
        assert _created_by_facts(sql) == [expected]


@pytest.mark.unit
class TestRegexParserKeepsQuotedCase:
    """The regex parser itself, for object kinds sqlglot usually handles
    (its result is what ``HybridParser`` reports whenever sqlglot cannot)."""


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
