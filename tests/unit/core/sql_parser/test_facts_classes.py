"""The classes of difference between the object extraction and the statement-facts reader.

Every class has a triple that lands in it and an adjacent one that must not; the order in which
rules are tried is pinned by the triples that could match two of them.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

import pytest

from tests.support.facts_corpus.classes import (
    DEFAULT_SCHEMA,
    NO_OLD_FAMILIES,
    ORDER,
    classify,
    classify_row,
)

NO_DML = {
    "table": "",
    "events": None,
    "updated_columns": [],
    "predicate": None,
    "full_table": False,
}
SAFETY = "postgres statement holds U+00A0, which the engine may read as part of a name; its objects are not named"


def obj(
    name: str, kind: str = "TABLE", role: str = "created", schema: Optional[str] = None
) -> list:
    return [name, kind, role, schema]


def facts(*objects: list, op: str = "CREATE", kind: str = "DDL", **more: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"operation": op, "kind": kind, **more}
    if objects:
        out["objects"] = list(objects)
    return out


def old(*ids: Tuple[str, ...], dml: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Both frozen paths naming the same ``(type, name[, schema])`` identities."""
    out: Dict[str, Any] = {
        "hybrid": [[i[0], i[1], i[2] if len(i) > 2 else None] for i in ids],
        "analyzer": [
            [i[0], f"{i[2]}.{i[1]}" if len(i) > 2 else f"default_schema.{i[1]}"] for i in ids
        ],
    }
    if dml is not None:
        out["dml"] = dml
    return out


def cls(
    sql: str,
    new: Optional[Dict[str, Any]],
    before: Optional[Dict[str, Any]],
    family: str = "postgresql",
    reserved: Iterable[str] = (),
    path: str = "hybrid",
) -> str:
    return classify(sql, new, before, family, set(reserved), path)


UPDATE_DML = {
    "table": "t",
    "events": ["UPDATE"],
    "updated_columns": ["v"],
    "predicate": "t.id = src.id",
    "full_table": False,
}


def update_facts(target: str, *objects: list) -> Dict[str, Any]:
    return facts(
        *objects,
        op="UPDATE",
        kind="DML",
        target=target,
        target_sql=target,
        events=["UPDATE"],
        affected_columns=["v"],
        predicate="t.id = src.id",
    )


# raised, and what comes before everything else ------------------------------------------------


def test_raised_is_the_first_rule_whatever_else_would_match() -> None:
    boom = {"raised": "ValueError: x"}
    assert cls("SELECT 1", boom, None) == "raised"  # before no-old
    assert cls("SELECT 1", None, {"hybrid": boom, "analyzer": []}) == "raised"  # before no-reader
    assert (
        cls("DELETE FROM t", facts(op="DELETE", kind="DML"), old(dml={**NO_DML, "table": "t"}))
        != "raised"
    )
    dml_boom = old(dml={"raised": "KeyError: x"})
    assert (
        cls("DELETE FROM t", facts(op="DELETE", kind="DML"), dml_boom) == "raised"
    )  # before dml-differs


def test_a_path_that_raised_does_not_taint_the_other_path() -> None:
    row = {
        "sql": "CREATE TABLE a (id int)",
        "facts": facts(obj("a")),
        "old": {"hybrid": {"raised": "boom"}, "analyzer": [["TABLE", "default_schema.a"]]},
    }
    assert classify_row(row, "postgresql", set()) == {"hybrid": "raised", "analyzer": "same"}


def test_a_missing_side_is_its_own_class() -> None:
    assert cls("SELECT 1", None, old()) == "no-reader"
    assert cls("SELECT 1", facts(), None, family="postgresql") == "no-old"
    for family in NO_OLD_FAMILIES:
        assert cls("SELECT 1", facts(), None, family=family) == "no-old-side"


def test_same_when_identities_and_statement_fields_are_equal() -> None:
    assert cls("CREATE TABLE t (id int)", facts(obj("t")), old(("TABLE", "t"))) == "same"
    assert (
        cls("CREATE TABLE s.t (id int)", facts(obj("t", schema="s")), old(("TABLE", "t", "s")))
        == "same"
    )


def test_the_default_schema_is_the_same_as_no_schema_on_both_sides() -> None:
    assert DEFAULT_SCHEMA["postgresql"] == "public"
    sql = "CREATE TABLE t (id int)"
    assert cls(sql, facts(obj("t")), old(("TABLE", "t", "public"))) == "same"
    assert cls(sql, facts(obj("t", schema="public")), old(("TABLE", "t"))) == "same"
    assert cls(sql, facts(obj("t")), old(("TABLE", "t", "other"))) == "disagree"


def test_dml_differs_is_reported_even_when_identities_are_equal() -> None:
    sql = "UPDATE t SET v = 1 WHERE t.id = src.id"
    same = update_facts("t", obj("t", role="altered"))
    assert cls(sql, same, old(("TABLE", "t"), dml=UPDATE_DML)) == "same"
    other = {**same, "predicate": "t.id = 2"}
    assert cls(sql, other, old(("TABLE", "t"), dml=UPDATE_DML)) == "dml-differs"
    for key, value in (("events", ["DELETE"]), ("affected_columns", ["w"]), ("target_sql", "u")):
        assert (
            cls(sql, {**same, key: value}, old(("TABLE", "t"), dml=UPDATE_DML)) == "dml-differs"
        ), key
    unfiltered = {k: v for k, v in same.items() if k != "predicate"}
    assert cls(sql, unfiltered, old(("TABLE", "t"), dml=UPDATE_DML)) == "dml-differs"


# old-cte-alias ------------------------------------------------------------------------------


CTE_SELECT = "WITH x AS (SELECT 1 AS a) SELECT * FROM x"


def test_old_cte_alias_accepts_an_alias_the_extraction_took_for_a_table() -> None:
    assert (
        cls(CTE_SELECT, facts(op="SELECT", kind="QUERY"), old(("TABLE", "x"), dml=NO_DML))
        == "old-cte-alias"
    )


def test_old_cte_alias_never_hides_a_statement_field_that_differs() -> None:
    """The reviewer's case: facts target the CTE instead of ``t``. Also pins the order: the
    statement-field check precedes every mechanical class."""
    sql = "WITH src AS (SELECT id FROM s) UPDATE t SET v = 1 FROM src WHERE t.id = src.id"
    before = old(("TABLE", "t"), ("TABLE", "src"), ("TABLE", "s"), dml=UPDATE_DML)
    new = update_facts("src", obj("src", role="altered"), obj("s", role="referenced"))
    assert cls(sql, new, before) == "dml-differs"


def test_old_cte_alias_never_accepts_a_missing_write_target() -> None:
    sql = "WITH t AS (SELECT 1 AS a) INSERT INTO t SELECT a FROM t"
    dml = {**NO_DML, "table": "t", "events": ["INSERT"]}
    nothing = facts(op="INSERT", kind="DML", target="t", target_sql="t", events=["INSERT"])
    assert cls(sql, nothing, old(("TABLE", "t"), dml=dml)) == "facts-fewer"


# old-keyword --------------------------------------------------------------------------------


IF_SQL = "CREATE INDEX IF NOT EXISTS ix ON t (c)"
IF_FACTS = facts(obj("ix", "INDEX"), obj("t", role="referenced"))
IF_OLD = old(("INDEX", "ix"), ("TABLE", "t"), ("INDEX", "if"))


def test_old_keyword_where_the_word_is_reserved_and_the_real_target_is_read() -> None:
    assert cls(IF_SQL, IF_FACTS, IF_OLD, family="mysql", reserved={"IF"}) == "old-keyword"


def test_the_same_extra_name_where_the_word_is_not_reserved_is_facts_fewer() -> None:
    assert cls(IF_SQL, IF_FACTS, IF_OLD, family="postgresql", reserved=set()) == "facts-fewer"


def test_old_keyword_needs_the_word_unquoted_in_the_statement() -> None:
    sql = 'CREATE INDEX ix ON t ("if")'
    assert cls(sql, IF_FACTS, IF_OLD, family="mysql", reserved={"IF"}) == "facts-fewer"


def test_old_keyword_never_excuses_a_write_target_when_the_reader_names_nothing() -> None:
    sql = "ALTER TABLE comment ADD COLUMN x int"
    before = old(("TABLE", "comment"))
    assert cls(sql, facts(op="ALTER"), before, reserved={"COMMENT"}) == "facts-fewer"
    opaque = facts(op="ALTER", diagnostic="postgres ALTER names no object")
    assert cls(sql, opaque, before, reserved={"COMMENT"}) == "opaque-reader-gap"
    assert cls(sql, facts(op="ALTER"), before, reserved=set()) == "facts-fewer"


def test_old_keyword_needs_the_reader_to_name_something() -> None:
    """The extraction named only the reserved word; a reader that names nothing is not agreement."""
    assert (
        cls(IF_SQL, facts(), old(("INDEX", "if")), family="mysql", reserved={"IF"}) == "facts-fewer"
    )


def test_old_keyword_never_excuses_a_reserved_word_the_statement_writes_to() -> None:
    sql = "ALTER TABLE comment ADD COLUMN x int"
    new = facts(obj("t", role="referenced"), op="ALTER")
    before = old(("TABLE", "comment"), ("TABLE", "t"))
    assert cls(sql, new, before, reserved={"COMMENT"}) == "facts-fewer"


def test_old_keyword_is_not_a_substitution() -> None:
    """Old named ``if`` where the reader names ``ix``: a different object, reviewed by hand."""
    sql = "CREATE INDEX IF NOT EXISTS ix ON t (c)"
    assert (
        cls(sql, facts(obj("ix", "INDEX")), old(("INDEX", "if")), family="mysql", reserved={"IF"})
        == "disagree"
    )


def test_old_keyword_does_not_cover_a_schema_taken_for_the_index() -> None:
    sql = "CREATE UNIQUE INDEX IF NOT EXISTS s.ix ON t (c)"
    new = facts(obj("ix", "INDEX", schema="s"), obj("t", role="referenced"))
    before = old(("INDEX", "s"), ("TABLE", "t"))
    assert cls(sql, new, before, family="mysql", reserved={"IF"}) == "disagree"


# type-refined -------------------------------------------------------------------------------


def test_type_refined_accepts_unknown_to_any_and_view_to_materialized_view() -> None:
    assert (
        cls(
            "CREATE MATERIALIZED VIEW v AS SELECT 1",
            facts(obj("v", "MATERIALIZED_VIEW")),
            old(("VIEW", "v")),
        )
        == "type-refined"
    )
    assert (
        cls("CREATE SCHEMA x", facts(obj("x", "SCHEMA")), old(("UNKNOWN", "x"))) == "type-refined"
    )


def test_type_refined_is_only_a_strict_subtype_in_one_direction() -> None:
    assert (
        cls("CREATE VIEW v AS SELECT 1", facts(obj("v", "TABLE")), old(("VIEW", "v"))) == "disagree"
    )
    assert (
        cls(
            "CREATE MATERIALIZED VIEW v AS SELECT 1",
            facts(obj("v", "VIEW")),
            old(("MATERIALIZED_VIEW", "v")),
        )
        == "disagree"
    )
    assert cls("CREATE SCHEMA x", facts(obj("x", "UNKNOWN")), old(("SCHEMA", "x"))) == "disagree"


# quote-decoded ------------------------------------------------------------------------------


def test_quote_decoded_accepts_a_name_cut_at_an_escaped_quote() -> None:
    sql = 'CREATE TABLE "a""b" (a int)'
    assert cls(sql, facts(obj('a"b')), old(("TABLE", "a")), family="oracle") == "quote-decoded"
    assert (
        cls("CREATE TABLE [a]]b] (a int)", facts(obj("a]b")), old(("TABLE", "a")), family="oracle")
        == "quote-decoded"
    )


def test_a_name_that_is_merely_longer_is_not_quote_decoded() -> None:
    assert (
        cls("CREATE TABLE ab (a int)", facts(obj("ab")), old(("TABLE", "a")), family="oracle")
        == "disagree"
    )
    assert (
        cls(
            'CREATE TABLE "a""b" (a int)',
            facts(obj('a"b', "VIEW")),
            old(("TABLE", "a")),
            family="oracle",
        )
        == "disagree"
    )


# case-folded --------------------------------------------------------------------------------


def test_case_folded_on_an_engine_that_folds_in_the_direction_seen() -> None:
    sql = "CREATE TABLE Users (id int)"
    assert (
        cls(sql, facts(obj("users")), old(("TABLE", "Users")), family="postgresql") == "case-folded"
    )
    assert cls(sql, facts(obj("users")), old(("TABLE", "USERS")), family="oracle") == "case-folded"
    assert (
        cls(sql, facts(obj("users")), old(("TABLE", "USERS")), family="snowflake") == "case-folded"
    )


def test_a_quoted_name_is_never_case_folded() -> None:
    sql = 'CREATE TABLE "Users" (id int)'
    assert cls(sql, facts(obj("users")), old(("TABLE", "Users")), family="postgresql") == "disagree"


def test_case_folded_is_refused_in_the_wrong_direction() -> None:
    sql = "CREATE TABLE Users (id int)"
    assert cls(sql, facts(obj("users")), old(("TABLE", "Users")), family="oracle") == "disagree"


@pytest.mark.parametrize("family", ["mysql", "sqlserver"])
def test_case_only_differences_need_a_review_entry_where_folding_is_a_setting(family: str) -> None:
    sql = "CREATE TABLE Users (id int)"
    assert cls(sql, facts(obj("users")), old(("TABLE", "Users")), family=family) == "disagree"


# facts-adds-referenced / facts-adds-acted -------------------------------------------------------


def test_facts_adds_referenced_when_every_extra_is_only_read() -> None:
    sql = "SELECT * FROM t"
    assert (
        cls(sql, facts(obj("t", role="referenced"), op="SELECT", kind="QUERY"), old())
        == "facts-adds-referenced"
    )


def test_facts_adds_acted_when_an_extra_is_created_altered_or_dropped() -> None:
    assert cls("CREATE TABLE t (id int)", facts(obj("t")), old()) == "facts-adds-acted"
    mixed = facts(obj("a", role="referenced"), obj("b", role="dropped"), op="DROP")
    assert cls("DROP TABLE b", mixed, old()) == "facts-adds-acted"


# opaque classes ---------------------------------------------------------------------------


def test_opaque_safety_matches_the_unread_name_diagnostic_only() -> None:
    sql = "CREATE TABLE t x (id int)"
    assert cls(sql, facts(diagnostic=SAFETY), old(("TABLE", "t"))) == "opaque-safety"
    other = facts(diagnostic="postgres COPY source or destination is opaque")
    assert cls(sql, other, old(("TABLE", "t"))) == "opaque-reader-gap"


def test_opaque_both_empty_needs_both_sides_to_name_nothing() -> None:
    assert cls("COPY t FROM STDIN", facts(diagnostic="x is opaque"), old()) == "opaque-both-empty"
    named = facts(obj("t"), diagnostic="x is opaque")
    assert cls("COPY t FROM STDIN", named, old()) == "facts-adds-acted"


def test_opaque_reader_gap_when_the_extraction_named_something() -> None:
    assert (
        cls(
            "CREATE INDEX i ON t ((a + 1))",
            facts(diagnostic="index expression columns are opaque"),
            old(("INDEX", "i")),
        )
        == "opaque-reader-gap"
    )


def test_an_opaque_reader_that_names_the_same_objects_is_the_same() -> None:
    new = facts(obj("t"), diagnostic="virtual table module arguments are opaque")
    assert cls("CREATE TABLE t (id int)", new, old(("TABLE", "t"))) == "same"


# facts-fewer / disagree ---------------------------------------------------------------------


def test_facts_fewer_and_disagree() -> None:
    assert (
        cls("CREATE TABLE a (i int)", facts(obj("a")), old(("TABLE", "a"), ("TABLE", "b")))
        == "facts-fewer"
    )
    assert cls("CREATE TABLE a (i int)", facts(obj("b")), old(("TABLE", "a"))) == "disagree"


def test_a_quoted_name_that_changes_is_a_disagreement() -> None:
    sql = 'ALTER TABLE "comment" RENAME TO notes'
    new = facts(obj("notes", role="altered"), op="ALTER")
    assert cls(sql, new, old(("TABLE", "comment")), reserved={"COMMENT"}) == "disagree"


# the two paths -------------------------------------------------------------------------------


def test_the_paths_are_classified_separately() -> None:
    """Facts equal to ``hybrid`` but without an object ``analyzer`` named."""
    row = {
        "sql": "CREATE TABLE a (i int)",
        "facts": facts(obj("a")),
        "old": {
            "hybrid": [["TABLE", "a", None]],
            "analyzer": [["TABLE", "default_schema.a"], ["INDEX", "default_schema.i"]],
        },
    }
    assert classify_row(row, "postgresql", set()) == {"hybrid": "same", "analyzer": "facts-fewer"}


def test_the_analyzer_path_reads_schema_qualified_names() -> None:
    row = {
        "sql": "CREATE TABLE s.a (i int)",
        "facts": facts(obj("a", schema="s")),
        "old": {"hybrid": [["TABLE", "a", "s"]], "analyzer": [["TABLE", "s.a"]]},
    }
    assert classify_row(row, "postgresql", set()) == {"hybrid": "same", "analyzer": "same"}


def test_every_class_is_ordered_once() -> None:
    assert len(ORDER) == len(set(ORDER))
