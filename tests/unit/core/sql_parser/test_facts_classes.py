"""The classes of difference between the object extraction and the statement-facts reader.

Every class has a triple that lands in it and an adjacent one that must not; the order in which
rules are tried is pinned by the triples that could match two of them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Tuple

import pytest

from tests.support.facts_corpus import CORPUS_DIR
from tests.support.facts_corpus import classes as classes_module
from tests.support.facts_corpus.classes import (
    DEFAULT_SCHEMA,
    FOLD,
    MECHANICAL,
    NO_OLD_FAMILIES,
    ORDER,
    REVIEW,
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
    """Facts target the CTE instead of ``t``."""
    sql = "WITH src AS (SELECT id FROM s) UPDATE t SET v = 1 FROM src WHERE t.id = src.id"
    before = old(("TABLE", "t"), ("TABLE", "src"), ("TABLE", "s"), dml=UPDATE_DML)
    new = update_facts("src", obj("src", role="altered"), obj("s", role="referenced"))
    assert cls(sql, new, before) == "dml-differs"


def test_the_statement_fields_are_compared_before_any_mechanical_class() -> None:
    """The facts name exactly the objects that leave only the CTE alias unmatched, so
    ``old-cte-alias`` would explain the difference; only the wrong target tells them apart."""
    sql = "WITH src AS (SELECT id FROM s) UPDATE t SET v = 1 FROM src WHERE t.id = src.id"
    before = old(("TABLE", "t"), ("TABLE", "src"), ("TABLE", "s"), dml=UPDATE_DML)
    right = update_facts("t", obj("t", role="altered"), obj("s", role="referenced"))
    assert cls(sql, right, before) == "old-cte-alias"
    wrong = update_facts("src", obj("t", role="altered"), obj("s", role="referenced"))
    assert cls(sql, wrong, before) == "dml-differs"


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


def test_old_keyword_needs_the_reader_not_to_be_opaque() -> None:
    opaque = facts(obj("ix", "INDEX"), obj("t", role="referenced"), diagnostic="x is opaque")
    assert cls(IF_SQL, opaque, IF_OLD, family="mysql", reserved={"IF"}) == "opaque-reader-gap"


#: Every statement form that writes, each with a reserved word ``b`` the extraction took for an
#: object and the reader does not name: the word is a write target there, so it is never excused.
WRITE_FORMS = [
    ("postgresql", "DROP TABLE a, b", facts(obj("a", role="dropped"), op="DROP")),
    ("postgresql", "DROP TABLE a, public.b", facts(obj("a", role="dropped"), op="DROP")),
    ("postgresql", "TRUNCATE a, b", facts(obj("a", role="altered"), op="TRUNCATE")),
    (
        "mysql",
        "DELETE a, b FROM a JOIN c ON a.i = c.i",
        facts(obj("a", role="altered"), op="DELETE"),
    ),
    ("postgresql", "DELETE FROM b USING a WHERE a.i = b.i", facts(obj("a", role="referenced"))),
    ("mysql", "UPDATE a JOIN b ON a.i = b.i SET a.v = 1", facts(obj("a", role="altered"))),
    ("postgresql", "UPDATE b SET v = 1 FROM a", facts(obj("a", role="referenced"), op="UPDATE")),
    ("postgresql", "INSERT INTO b SELECT * FROM a", facts(obj("a", role="referenced"))),
    (
        "oracle",
        "INSERT ALL INTO a VALUES (1) INTO b VALUES (2) SELECT * FROM dual",
        facts(obj("a", role="altered"), op="INSERT"),
    ),
    ("postgresql", "CREATE TABLE b AS SELECT * FROM a", facts(obj("a", role="referenced"))),
    ("postgresql", "CREATE INDEX b ON a (c)", facts(obj("a", role="referenced"))),
    ("postgresql", "ALTER TABLE b RENAME TO a", facts(obj("a", role="altered"), op="ALTER")),
    ("snowflake", "ALTER TABLE a SWAP WITH b", facts(obj("a", role="altered"), op="ALTER")),
    (
        "postgresql",
        "MERGE INTO b USING a ON a.i = b.i WHEN MATCHED THEN DELETE",
        facts(obj("a", role="referenced")),
    ),
    ("postgresql", "COPY b FROM STDIN", facts(obj("a", role="referenced"))),
    ("mysql", "RENAME TABLE b TO a", facts(obj("a", role="altered"), op="ALTER")),
]


@pytest.mark.parametrize("family,sql,new", WRITE_FORMS, ids=[f[1] for f in WRITE_FORMS])
def test_old_keyword_never_excuses_a_name_any_write_form_targets(
    family: str, sql: str, new: Dict[str, Any]
) -> None:
    before = old(("TABLE", "a"), ("TABLE", "b"))
    assert cls(sql, new, before, family=family, reserved={"B"}) == "facts-fewer"


def test_old_keyword_still_excuses_a_reserved_word_in_a_read_position() -> None:
    sql = "INSERT INTO a SELECT * FROM b"
    new = facts(obj("a", role="altered"), op="INSERT")
    assert cls(sql, new, old(("TABLE", "a"), ("TABLE", "b")), reserved={"B"}) == "old-keyword"


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


def test_quote_decoded_needs_an_escaped_quote_in_the_statement() -> None:
    sql = "CREATE TABLE a (x int)"
    assert cls(sql, facts(obj('a"; x')), old(("TABLE", "a")), family="oracle") == "disagree"


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


SPELLED = "CREATE TABLE Users (id int)"


@pytest.mark.parametrize(
    "family,folded",
    [("postgresql", "users"), ("redshift", "users"), ("oracle", "USERS"), ("snowflake", "USERS")],
)
def test_case_folded_when_the_facts_keep_the_spelling_and_the_extraction_folded(
    family: str, folded: str
) -> None:
    assert cls(SPELLED, facts(obj("Users")), old(("TABLE", folded)), family=family) == "case-folded"


def test_case_folded_is_directional_the_facts_side_is_never_the_folded_one() -> None:
    """Facts that fold the name themselves, or hold a spelling the statement does not, are
    reviewed: nothing proves the reader and the extraction mean the same object."""
    for family, folded in (("postgresql", "users"), ("oracle", "USERS")):
        assert cls(SPELLED, facts(obj(folded)), old(("TABLE", "Users")), family=family) == (
            "disagree"
        )
    assert cls(SPELLED, facts(obj("Users")), old(("TABLE", "USERS")), family="postgresql") == (
        "disagree"
    )


def test_case_folded_never_accepts_the_extraction_as_the_unfolded_side() -> None:
    sql = "CREATE TABLE users (id int)"
    assert cls(sql, facts(obj("users")), old(("TABLE", "USERS")), family="postgresql") == (
        "disagree"
    )


def test_case_folded_needs_the_facts_name_as_the_statement_spells_it() -> None:
    sql = "CREATE TABLE users (id int)"
    assert cls(sql, facts(obj("Users")), old(("TABLE", "USERS")), family="oracle") == "disagree"
    assert cls(sql, facts(obj("users")), old(("TABLE", "USERS")), family="oracle") == "case-folded"


def test_case_folded_is_refused_when_the_reader_is_opaque() -> None:
    new = facts(obj("Users"), diagnostic="index expression columns are opaque")
    assert cls(SPELLED, new, old(("TABLE", "users")), family="postgresql") == "opaque-reader-gap"


def test_a_quoted_name_is_never_case_folded() -> None:
    sql = 'CREATE TABLE "Users" (id int)'
    assert cls(sql, facts(obj("Users")), old(("TABLE", "users")), family="postgresql") == (
        "disagree"
    )


@pytest.mark.parametrize("family", ["mysql", "sqlserver"])
def test_case_only_differences_need_a_review_entry_where_folding_is_a_setting(family: str) -> None:
    assert cls(SPELLED, facts(obj("Users")), old(("TABLE", "users")), family=family) == "disagree"


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
    named = facts(obj("t", role="altered"), diagnostic="x is opaque")
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


# roles --------------------------------------------------------------------------------------


def test_an_object_the_statement_acts_on_cannot_be_demoted_to_a_read() -> None:
    sql = "DROP TABLE t"
    assert cls(sql, facts(obj("t", role="dropped"), op="DROP"), old(("TABLE", "t"))) == "same"
    assert cls(sql, facts(obj("t", role="referenced"), op="DROP"), old(("TABLE", "t"))) == (
        "role-differs"
    )


def test_a_created_object_marked_as_a_read_is_a_role_difference() -> None:
    """``SELECT ... INTO`` creates ``t2``; the reader marks it as a read."""
    new = facts(
        obj("t2", role="referenced"), obj("t", role="referenced"), op="SELECT", kind="QUERY"
    )
    before = old(("TABLE", "t"), ("TABLE", "t2"), dml=NO_DML)
    assert cls("SELECT * INTO t2 FROM t", new, before) == "role-differs"
    fixed = facts(obj("t2"), obj("t", role="referenced"), op="SELECT", kind="QUERY")
    assert cls("SELECT * INTO t2 FROM t", fixed, before) == "same"


def test_a_role_difference_is_found_on_an_extra_object_too() -> None:
    assert cls("DROP TABLE t", facts(obj("t", role="referenced"), op="DROP"), old()) == (
        "role-differs"
    )


def test_an_object_the_statement_only_reads_cannot_be_promoted_to_an_action() -> None:
    sql = "SELECT * FROM t"
    new = facts(obj("t", role="created"), op="SELECT", kind="QUERY")
    assert cls(sql, new, old(("TABLE", "t"), dml=NO_DML)) == "role-differs"
    read = facts(obj("t", role="referenced"), op="SELECT", kind="QUERY")
    assert cls(sql, read, old(("TABLE", "t"), dml=NO_DML)) == "same"


def test_the_table_of_a_created_index_may_be_a_read() -> None:
    new = facts(obj("ix", "INDEX"), obj("t", role="referenced"))
    assert cls("CREATE INDEX ix ON t (c)", new, old(("INDEX", "ix"), ("TABLE", "t"))) == "same"


def test_roles_are_not_judged_when_the_statement_does_not_say_what_it_writes() -> None:
    new = facts(obj("a", role="referenced"), op="ALTER")
    assert cls("RENAME TABLE a TO b", new, old(("TABLE", "a")), family="mysql") == "same"


# the schema the extraction adds ------------------------------------------------------------


def test_the_analyzer_path_drops_the_default_schema_it_prefixes() -> None:
    sql = "CREATE TABLE x (i int)"
    prefixed = {"hybrid": [], "analyzer": [["TABLE", "public.x"]]}
    assert cls(sql, facts(obj("x")), prefixed, path="analyzer") == "same"
    other = {"hybrid": [], "analyzer": [["TABLE", "other.x"]]}
    assert cls(sql, facts(obj("x")), other, path="analyzer") == "disagree"


def test_select_into_is_a_write_only_where_it_creates_a_table() -> None:
    sql = "SELECT COUNT(*) INTO v FROM t"
    new = facts(obj("v", role="referenced"), obj("t", role="referenced"), op="SELECT", kind="QUERY")
    before = old(("TABLE", "v"), ("TABLE", "t"), dml=NO_DML)
    assert cls(sql, new, before, family="mysql") == "same"
    assert cls(sql, new, before, family="sqlserver") == "role-differs"


def test_a_statement_nested_in_a_routine_body_is_not_run_by_its_creation() -> None:
    sql = "CREATE PROCEDURE p() BEGIN DROP TABLE users; END"
    new = facts(obj("p", "PROCEDURE"), obj("users", role="referenced"))
    assert cls(sql, new, old(("PROCEDURE", "p"), ("TABLE", "users")), family="mysql") == "same"


def test_a_data_modifying_cte_acts_on_its_table() -> None:
    sql = "WITH d AS (DELETE FROM src RETURNING id) SELECT * FROM d"
    new = facts(obj("src", role="referenced"), op="SELECT", kind="QUERY")
    before = old(("TABLE", "d"), ("TABLE", "src"), dml=NO_DML)
    assert cls(sql, new, before) == "role-differs"


# the full role of every name -------------------------------------------------------------------

#: ``(family, sql, [(name, type, role the statement gives it)])``. Each must be ``same`` as written
#: and ``role-differs`` when the reader gives any one of its names any other role.
ROLE_CASES = [
    ("postgresql", "DROP TABLE t", [("t", "TABLE", "dropped")]),
    ("postgresql", "DROP TABLE a, b", [("a", "TABLE", "dropped"), ("b", "TABLE", "dropped")]),
    ("postgresql", "CREATE TABLE t (i int)", [("t", "TABLE", "created")]),
    (
        "postgresql",
        "CREATE TABLE t AS SELECT * FROM s",
        [("t", "TABLE", "created"), ("s", "TABLE", "referenced")],
    ),
    (
        "postgresql",
        "CREATE VIEW v AS SELECT * FROM t",
        [("v", "VIEW", "created"), ("t", "TABLE", "referenced")],
    ),
    (
        "postgresql",
        "CREATE INDEX ix ON t (c)",
        [("ix", "INDEX", "created"), ("t", "TABLE", "referenced")],
    ),
    (
        "mysql",
        "CREATE INDEX s.ix ON t (c)",
        [("ix", "INDEX", "created", "s"), ("t", "TABLE", "referenced")],
    ),
    (
        "mysql",
        "DROP INDEX ix ON t",
        [("ix", "INDEX", "dropped"), ("t", "TABLE", "referenced")],
    ),
    (
        "sqlserver",
        "CREATE PROCEDURE p AS BEGIN SELECT * FROM users; END",
        [("p", "PROCEDURE", "created"), ("users", "TABLE", "referenced")],
    ),
    ("postgresql", "COPY t TO STDOUT", [("t", "TABLE", "referenced")]),
    ("postgresql", "COPY t FROM STDIN", [("t", "TABLE", "altered")]),
    ("postgresql", "TRUNCATE t", [("t", "TABLE", "altered")]),
    ("postgresql", "ALTER TABLE t ADD COLUMN c int", [("t", "TABLE", "altered")]),
    (
        "postgresql",
        "SELECT * FROM t JOIN u ON t.i = u.i",
        [("t", "TABLE", "referenced"), ("u", "TABLE", "referenced")],
    ),
    (
        "sqlserver",
        "SELECT * INTO t2 FROM t",
        [("t2", "TABLE", "created"), ("t", "TABLE", "referenced")],
    ),
    (
        "postgresql",
        "INSERT INTO t SELECT * FROM s",
        [("t", "TABLE", "altered"), ("s", "TABLE", "referenced")],
    ),
    ("postgresql", "INSERT INTO t VALUES (1)", [("t", "TABLE", "altered")]),
    (
        "postgresql",
        "DELETE FROM t USING u WHERE t.i = u.i",
        [("t", "TABLE", "altered"), ("u", "TABLE", "referenced")],
    ),
    (
        "mysql",
        "UPDATE a JOIN b ON a.i = b.i SET a.v = 1",
        [("a", "TABLE", "altered"), ("b", "TABLE", "referenced")],
    ),
    (
        "postgresql",
        "MERGE INTO t USING s ON t.i = s.i WHEN MATCHED THEN DELETE",
        [("t", "TABLE", "altered"), ("s", "TABLE", "referenced")],
    ),
    (
        "oracle",
        "INSERT ALL INTO a VALUES (1) INTO b VALUES (2) SELECT * FROM dual",
        [("a", "TABLE", "altered"), ("b", "TABLE", "altered")],
    ),
]
ALL_ROLES = ("created", "altered", "dropped", "referenced")


def _role_row(sql: str, family: str, wanted: list, wrong: Optional[Tuple[int, str]] = None) -> str:
    objects = [
        obj(w[0], w[1], wrong[1] if wrong and wrong[0] == i else w[2], *w[3:])
        for i, w in enumerate(wanted)
    ]
    return cls(sql, facts(*objects), old(*[(w[1], w[0], *w[3:]) for w in wanted]), family=family)


@pytest.mark.parametrize("family,sql,wanted", ROLE_CASES, ids=[c[1] for c in ROLE_CASES])
def test_every_name_must_carry_the_role_the_statement_gives_it(
    family: str, sql: str, wanted: list
) -> None:
    assert _role_row(sql, family, wanted) == "same"
    for index, item in enumerate(wanted):
        for role in ALL_ROLES:
            if role != item[2]:
                got = _role_row(sql, family, wanted, (index, role))
                assert got == "role-differs", (item[0], role)


def test_a_dropped_table_marked_created_is_a_role_difference() -> None:
    assert cls("DROP TABLE t", facts(obj("t"), op="DROP"), old(("TABLE", "t"))) == "role-differs"


def test_a_table_the_reader_calls_dropped_under_an_index_is_a_role_difference() -> None:
    new = facts(obj("ix", "INDEX"), obj("t", role="dropped"))
    assert cls("CREATE INDEX ix ON t (c)", new, old(("INDEX", "ix"), ("TABLE", "t"))) == (
        "role-differs"
    )


def test_a_dml_target_marked_dropped_is_a_role_difference() -> None:
    new = facts(obj("t", role="dropped"), op="INSERT", kind="DML")
    assert cls("INSERT INTO t VALUES (1)", new, old(("TABLE", "t"))) == "role-differs"


def test_the_table_of_a_joined_update_marked_created_is_a_role_difference() -> None:
    sql = "UPDATE a JOIN b ON a.i = b.i SET a.v = 1"
    new = update_facts("a", obj("a", role="altered"), obj("b"))
    before = old(("TABLE", "a"), ("TABLE", "b"), dml={**UPDATE_DML, "table": "a"})
    assert cls(sql, new, before, family="mysql") == "role-differs"


def test_a_copy_source_marked_dropped_is_a_role_difference() -> None:
    new = facts(obj("t", role="dropped"), op="COPY")
    assert cls("COPY t TO STDOUT", new, old(("TABLE", "t"))) == "role-differs"


# which classes need a reason ----------------------------------------------------------------


def _readme() -> str:
    return (CORPUS_DIR / "README.md").read_text(encoding="utf-8")


def test_the_classes_that_need_a_reason_are_exactly_the_review_set() -> None:
    paragraph = next((p for p in _readme().split("\n\n") if "need a reason" in p), "")
    assert paragraph, "the README no longer says which classes need a reason"
    listed = set(re.findall(r"`([a-z-]+)`", paragraph.partition("need a reason")[0]))
    assert listed == set(REVIEW)
    for name in REVIEW:
        assert name in classes_module.__doc__, name


def test_every_class_is_exactly_one_of_review_mechanical_or_neither_with_a_stated_reason() -> None:
    neither = {"raised", "same", "no-old-side"}
    assert not set(REVIEW) & set(MECHANICAL)
    assert set(ORDER) == set(REVIEW) | set(MECHANICAL) | neither
    table = set(re.findall(r"^\| `([a-z-]+)` \|", _readme(), re.M))
    assert table == set(ORDER)
    assert "role-differs" in REVIEW


# a reserved word after a dot is a legal name ------------------------------------------------


QUALIFIED = [
    (
        "postgresql",
        "INSERT INTO a SELECT * FROM public.order",
        facts(obj("a", role="altered"), op="INSERT", kind="DML"),
    ),
    (
        "mysql",
        "INSERT INTO a SELECT * FROM db.order",
        facts(obj("a", role="altered"), op="INSERT", kind="DML"),
    ),
    (
        "postgresql",
        "SELECT * FROM a, public.order",
        facts(obj("a", role="referenced"), op="SELECT", kind="QUERY"),
    ),
    (
        "postgresql",
        "ALTER TABLE a ADD CONSTRAINT fk FOREIGN KEY (x) REFERENCES public.order (id)",
        facts(obj("a", role="altered"), op="ALTER"),
    ),
    (
        "postgresql",
        "CREATE FUNCTION a() RETURNS void AS $$ DROP TABLE public.order $$ LANGUAGE sql",
        facts(obj("a", "FUNCTION")),
    ),
]


@pytest.mark.parametrize("family,sql,new", QUALIFIED, ids=[q[1] for q in QUALIFIED])
def test_old_keyword_never_excuses_a_name_written_after_a_dot(
    family: str, sql: str, new: Dict[str, Any]
) -> None:
    kind = "FUNCTION" if "FUNCTION" in sql else "TABLE"
    before = old((kind, "a"), ("TABLE", "order"))
    assert cls(sql, new, before, family=family, reserved={"ORDER"}) == "facts-fewer"


def test_old_keyword_still_excuses_the_same_word_unqualified() -> None:
    sql = "SELECT * FROM a, order"
    new = facts(obj("a", role="referenced"), op="SELECT", kind="QUERY")
    before = old(("TABLE", "a"), ("TABLE", "order"))
    assert cls(sql, new, before, family="mysql", reserved={"ORDER"}) == "old-keyword"


# case-folded anchors to the names of the statement, not to its text -------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE users (c text DEFAULT 'Users')",
        "CREATE TABLE users (c int) -- Users",
        "CREATE TABLE users (Users int)",
    ],
)
def test_case_folded_is_not_matched_inside_a_literal_a_comment_or_a_column(sql: str) -> None:
    got = cls(sql, facts(obj("Users")), old(("TABLE", "users")), family="postgresql")
    assert got != "case-folded"


def test_case_folded_matches_a_schema_part_and_an_index_name() -> None:
    new = facts(obj("Users", schema="Sch"))
    assert cls("CREATE TABLE Sch.Users (i int)", new, old(("TABLE", "users", "sch"))) == (
        "case-folded"
    )
    ix = facts(obj("Ix", "INDEX"), obj("t", role="referenced"))
    got = cls("CREATE INDEX Ix ON t (c)", ix, old(("INDEX", "ix"), ("TABLE", "t")))
    assert got == "case-folded"


# the folding table is the engines' ---------------------------------------------------------


def test_fold_agrees_with_the_quirks_and_is_stricter_where_folding_is_a_setting() -> None:
    from dblift.db.provider_registry import ProviderRegistry

    direction = {"uppercase": "upper", "lowercase": "lower"}
    for family in ("postgresql", "redshift", "oracle", "snowflake", "db2"):
        quirk = ProviderRegistry.get_quirks(family).unquoted_identifier_case
        assert FOLD[family] == direction[quirk], family
    # MySQL folds by lower_case_table_names and SQL Server by collation: no direction is certain.
    assert "mysql" not in FOLD and "sqlserver" not in FOLD


# the same name in two schemas ---------------------------------------------------------------


def _copy_rows(archive: str, public: str) -> str:
    sql = "INSERT INTO archive.orders SELECT * FROM public.orders"
    new = facts(
        obj("orders", role=archive, schema="archive"),
        obj("orders", role=public, schema="public"),
        op="INSERT",
        kind="DML",
    )
    return cls(sql, new, old(("TABLE", "orders", "archive"), ("TABLE", "orders")))


def test_a_name_in_two_schemas_keeps_the_role_of_each() -> None:
    assert _copy_rows("altered", "referenced") == "same"
    assert _copy_rows("referenced", "altered") == "role-differs"
    assert _copy_rows("altered", "altered") == "role-differs"
    assert _copy_rows("referenced", "referenced") == "role-differs"


def test_the_default_schema_is_the_unqualified_name_when_roles_are_compared() -> None:
    wrong = facts(obj("t", role="created", schema="public"), op="SELECT", kind="QUERY")
    assert cls("SELECT * FROM t", wrong, old(("TABLE", "t"))) == "role-differs"
    assert cls("SELECT * FROM public.t", wrong, old(("TABLE", "t"))) == "role-differs"
    right = facts(obj("t", role="referenced", schema="public"), op="SELECT", kind="QUERY")
    assert cls("SELECT * FROM t", right, old(("TABLE", "t"))) == "same"


# the allowances -----------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["created", "altered"])
def test_a_rename_target_may_be_read_as_created_or_altered(role: str) -> None:
    """The facts vocabulary has no ``renamed``: the new name is created or the table altered."""
    new = facts(obj("a", role="altered"), obj("b", role=role), op="ALTER")
    assert cls("ALTER TABLE a RENAME TO b", new, old(("TABLE", "a"), ("TABLE", "b"))) == "same"


@pytest.mark.parametrize("role", ["dropped", "referenced"])
def test_a_rename_target_is_not_dropped_or_only_read(role: str) -> None:
    new = facts(obj("a", role="altered"), obj("b", role=role), op="ALTER")
    got = cls("ALTER TABLE a RENAME TO b", new, old(("TABLE", "a"), ("TABLE", "b")))
    assert got == "role-differs"


def test_a_data_modifying_cte_of_a_create_table_as_is_run_by_it() -> None:
    sql = "CREATE TABLE t2 AS WITH d AS (DELETE FROM t RETURNING id) SELECT * FROM d"
    read = facts(obj("t2"), obj("t", role="referenced"), diagnostic="opaque")
    before = old(("TABLE", "t2"), ("TABLE", "t"))
    assert cls(sql, read, before) == "role-differs"
    done = facts(obj("t2"), obj("t", role="altered"), diagnostic="opaque")
    assert cls(sql, done, before) != "role-differs"
