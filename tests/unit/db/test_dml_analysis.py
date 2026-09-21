"""Tests for the dialect-agnostic DML undo-safety scanner."""

from dblift.db.base_quirks import BaseQuirks
from dblift.db.dml_analysis import (
    analyze_dml,
    cte_outer_statement_type,
    dml_where_predicate,
    extract_dml_table_name,
    insert_value_rows,
    is_full_table_dml,
    statement_dml_table,
    updates_restore_key,
)

_DEFAULT_KEYS = ("id", "pk", "uuid", "key")


def test_analyze_dml_classifies_basic_statements():
    assert analyze_dml("UPDATE users SET status = 'x' WHERE id = 1;").events == {"UPDATE"}
    assert analyze_dml("DELETE FROM users WHERE id = 1;").events == {"DELETE"}
    assert analyze_dml("INSERT INTO users (id) VALUES (1);").events == {"INSERT"}
    assert analyze_dml("TRUNCATE TABLE users;").events is None


def test_analyze_dml_marks_upserts_as_insert_and_update():
    pg = "INSERT INTO users (id, s) VALUES (1, 'a') ON CONFLICT (id) DO UPDATE SET s = excluded.s;"
    my = "INSERT INTO users (id, s) VALUES (1, 'a') ON DUPLICATE KEY UPDATE s = VALUES(s);"
    assert analyze_dml(pg).events == {"INSERT", "UPDATE"}
    assert analyze_dml(my).events == {"INSERT", "UPDATE"}


def test_analyze_dml_collects_merge_events_and_table():
    stmt = (
        "MERGE INTO users AS t USING s ON t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET a = 1 "
        "WHEN NOT MATCHED THEN INSERT (a) VALUES (1);"
    )
    mutation = analyze_dml(stmt)
    assert mutation.events == {"UPDATE", "INSERT"}
    assert mutation.table == "users"


def test_extract_dml_table_name_handles_qualified_names():
    assert extract_dml_table_name("DELETE FROM public.users WHERE id = 1;") == "public.users"
    assert extract_dml_table_name("UPDATE users SET a = 1 WHERE id = 1;") == "users"


def test_extract_dml_table_name_handles_quoted_insert_and_delete():
    # Quoted / schema-qualified INSERT and DELETE must resolve the table verbatim
    # (the closing quote must not defeat the pattern). Regression for BUG-DATA-01.
    assert extract_dml_table_name('DELETE FROM "s"."t" WHERE id = 1;') == '"s"."t"'
    assert extract_dml_table_name('INSERT INTO "s"."t" (id) VALUES (1);') == '"s"."t"'
    # No space before the INSERT column list.
    assert extract_dml_table_name('INSERT INTO "s"."t"(id) VALUES (1);') == '"s"."t"'
    # SQL Server brackets and MySQL backticks.
    assert extract_dml_table_name("DELETE FROM [s].[t] WHERE id = 1;") == "[s].[t]"
    assert extract_dml_table_name("INSERT INTO `s`.`t` (id) VALUES (1);") == "`s`.`t`"
    # Unquoted still works (no regression).
    assert extract_dml_table_name("DELETE FROM s.t WHERE id = 1;") == "s.t"
    assert extract_dml_table_name("INSERT INTO t (id) VALUES (1);") == "t"


def test_statement_dml_table_prefers_sqlglot_when_dialect_known():
    # With a dialect, table extraction goes through the sqlglot AST (dialect-
    # correct), not the regex scanner. Quoted/bracketed/backtick targets resolve
    # and the verbatim-quoted form is preserved for downstream raw SQL.
    assert statement_dml_table('DELETE FROM "s"."t" WHERE id = 1;', dialect="postgres") == '"s"."t"'
    assert (
        statement_dml_table('INSERT INTO "s"."t"(id) VALUES (1);', dialect="postgres") == '"s"."t"'
    )
    assert statement_dml_table("DELETE FROM [s].[t] WHERE id = 1;", dialect="tsql") == "[s].[t]"
    assert statement_dml_table("INSERT INTO `s`.`t` (id) VALUES (1);", dialect="mysql") == "`s`.`t`"
    # Unquoted is preserved unquoted (no spurious re-quoting).
    assert (
        statement_dml_table("UPDATE users SET a = 1 WHERE id = 1;", dialect="postgres") == "users"
    )


def test_statement_dml_table_sqlglot_strips_merge_alias():
    # MERGE's table carries an alias in the AST; it must not leak into the name.
    stmt = 'MERGE INTO "S"."T" t USING x ON (t.id = x.id) WHEN MATCHED THEN UPDATE SET a = 1;'
    assert statement_dml_table(stmt, dialect="oracle") == '"S"."T"'


def test_statement_dml_table_falls_back_to_regex_without_dialect():
    # No dialect -> regex scanner (dialect-agnostic last resort) still resolves.
    assert statement_dml_table('DELETE FROM "s"."t" WHERE id = 1;') == '"s"."t"'
    assert (
        statement_dml_table("MERGE INTO users USING s ON s.id = users.id WHEN MATCHED THEN DELETE;")
        == "users"
    )


def test_updates_restore_key_detects_keys_across_clauses():
    cases = [
        "UPDATE users SET id = id + 100, status = 'active' WHERE id = 1;",
        "INSERT INTO users (id) VALUES (1) ON CONFLICT (id) DO UPDATE SET id = excluded.id + 1;",
        "INSERT INTO users (id) VALUES (1) ON DUPLICATE KEY UPDATE id = id + 1;",
        "UPDATE users SET status = CASE WHEN active THEN 'a' ELSE 'b' END, id = id + 1 WHERE id = 1;",
    ]
    for stmt in cases:
        assert updates_restore_key(stmt, _DEFAULT_KEYS), stmt


def test_updates_restore_key_ignores_non_key_columns():
    assert not updates_restore_key("UPDATE users SET status = 'x' WHERE id = 1;", _DEFAULT_KEYS)


def test_updates_restore_key_is_configurable():
    # A custom restore key (tenant) is flagged when configured...
    assert updates_restore_key("UPDATE t SET tenant = 1 WHERE id = 1;", ("tenant",))
    # ...and the built-in 'key' column is allowed once dropped from the set.
    assert not updates_restore_key("UPDATE t SET key = 1 WHERE id = 1;", ("id", "pk", "uuid"))
    # An empty restore-key set never flags anything.
    assert not updates_restore_key("UPDATE t SET id = 1 WHERE id = 1;", ())


def test_base_quirks_exposes_dml_analysis():
    quirks = BaseQuirks(dialect_name="postgresql")
    assert quirks.analyze_dml("UPDATE t SET id = 1 WHERE id = 1;").events == {"UPDATE"}
    assert quirks.statement_updates_restore_key("UPDATE t SET id = 1 WHERE id = 1;", _DEFAULT_KEYS)
    assert not quirks.statement_updates_restore_key(
        "UPDATE t SET status = 'x' WHERE id = 1;", _DEFAULT_KEYS
    )


def test_analyze_dml_routes_by_sqlglot_dialect():
    # Dialect-specific syntax is parsed correctly when the dialect is supplied.
    dialect = "mysql"
    mysql = "INSERT INTO users (id) VALUES (1) ON DUPLICATE KEY UPDATE id = id + 1;"
    assert analyze_dml(mysql, sqlglot_dialect=dialect).events == {"INSERT", "UPDATE"}
    assert updates_restore_key(mysql, _DEFAULT_KEYS, sqlglot_dialect=dialect)


def test_analyze_dml_falls_back_to_regex_for_unparseable_sql():
    # A procedural block sqlglot parses as an opaque Command falls back to the
    # regex scanner, which still finds the restore-key assignment.
    dialect = "postgres"
    procedural = "DO $$ BEGIN UPDATE users SET id = 1; END $$;"
    assert updates_restore_key(procedural, _DEFAULT_KEYS, sqlglot_dialect=dialect)


def test_is_full_table_dml_flags_update_delete_without_top_level_where():
    assert is_full_table_dml("UPDATE t SET x = 1;")
    assert is_full_table_dml("DELETE FROM t;")
    assert not is_full_table_dml("UPDATE t SET x = 1 WHERE id = 1;")
    assert not is_full_table_dml("DELETE FROM t WHERE id = 1;")
    # INSERT / MERGE are not full-table UPDATE/DELETE guards.
    assert not is_full_table_dml("INSERT INTO t (a) VALUES (1);")


def test_is_full_table_dml_ignores_leading_dblift_directive_comments():
    # Regression: SQLite split_statements keeps leading comments; the guard
    # must still see the bare UPDATE/DELETE through them.
    commented = "-- dblift:formatted\n-- dblift: expect=>=1\nUPDATE accounts SET status = 'x';"
    assert is_full_table_dml(commented, sqlglot_dialect="sqlite")
    with_where = (
        "-- dblift:formatted\n-- dblift: expect=1\nUPDATE accounts SET s = 'x' WHERE id = 1;"
    )
    assert not is_full_table_dml(with_where, sqlglot_dialect="sqlite")


def test_is_full_table_dml_treats_quoted_where_identifier_as_column_not_clause():
    # A column literally named "where" (any dialect's quoting) is not a WHERE clause.
    assert is_full_table_dml("UPDATE users SET `where` = 1;")
    assert is_full_table_dml("UPDATE users SET [where] = 1;")
    # A WHERE nested inside a subquery is not a top-level guard either.
    assert is_full_table_dml(
        "UPDATE users SET active = (SELECT 1 FROM audit WHERE audit.user_id = users.id);"
    )


def test_is_full_table_dml_ignores_where_inside_dollar_quoted_value():
    # A WHERE textually inside a dollar-quoted value is data, not a clause,
    # regardless of whether the quote is tagged.
    assert is_full_table_dml(
        "UPDATE t SET body = $$ this text mentions WHERE and it is not a clause $$"
    )
    assert is_full_table_dml(
        "UPDATE t SET body = $tag$ this text mentions WHERE and it is not a clause $tag$"
    )
    assert is_full_table_dml(
        "UPDATE t SET body = $_$ this text mentions WHERE and it is not a clause $_$"
    )


def test_is_full_table_dml_still_finds_a_real_where_after_a_dollar_quoted_value():
    assert not is_full_table_dml("UPDATE t SET body = $$ text $$ WHERE id = 1")
    # A "$1"-style placeholder is not a dollar-quote tag and must not be
    # swallowed looking for a matching close.
    assert not is_full_table_dml("UPDATE t SET a = $1 WHERE b = $2")
    # A bare "$" inside an ordinary string literal is not a dollar quote either.
    assert not is_full_table_dml("UPDATE t SET price_note = 'costs $5' WHERE id = 1")


def test_is_full_table_dml_ignores_where_inside_ordinary_string_literal():
    assert is_full_table_dml("UPDATE t SET note = 'the WHERE clause explained'")


def test_is_full_table_dml_unterminated_dollar_quote_finds_no_where():
    # Same unterminated-comment convention as `_skip_comment`: an unclosed
    # dollar quote swallows to end of text, so a WHERE inside it is not found.
    assert is_full_table_dml("UPDATE t SET body = $$ never closes, mentions WHERE")


def test_cte_outer_statement_type_flags_data_modifying_cte_feeding_insert():
    # RETURNING on the CTE's own DELETE doesn't mean the outer INSERT returns
    # rows — the outer verb decides that.
    sql = (
        "WITH deleted AS (DELETE FROM src WHERE id = 1 RETURNING id) "
        "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted"
    )
    assert cte_outer_statement_type(sql, sqlglot_dialect="postgres") == "DML"


def test_cte_outer_statement_type_keeps_select_as_query():
    sql = "WITH x AS (INSERT INTO src VALUES (99) RETURNING id) SELECT * FROM x"
    assert cte_outer_statement_type(sql, sqlglot_dialect="postgres") == "QUERY"


def test_cte_outer_statement_type_none_for_truncated_sql():
    # Neither sqlglot nor the keyword scan can find an outer verb: the CTE's
    # own paren never closes, so the scan never returns to depth 0.
    assert cte_outer_statement_type("WITH x AS ( NOT VALID SQL", sqlglot_dialect="postgres") is None


def test_cte_outer_statement_type_none_for_comment_only_statement():
    # Comments strip down to nothing before sqlglot or the keyword scan ever
    # sees the text.
    assert cte_outer_statement_type("-- just a comment\n", sqlglot_dialect="postgres") is None
    assert cte_outer_statement_type("   \n  ", sqlglot_dialect="postgres") is None


def test_cte_outer_statement_type_none_when_neither_dml_nor_query():
    # sqlglot parses this fine, but into a statement type this function
    # doesn't model (DROP), and there is no SELECT/INSERT/UPDATE/DELETE/
    # MERGE/VALUES/TABLE keyword for the scan to fall back on either — the
    # one remaining path back to None, where the caller keeps its own
    # default. Practically unreachable from a real WITH-prefixed migration
    # statement (there is always an outer verb); kept for the "give up
    # cleanly" branch itself, not because this input is realistic.
    assert cte_outer_statement_type("DROP INDEX idx", sqlglot_dialect="postgres") is None


def test_cte_outer_statement_type_deterministic_for_unmapped_sqlglot_dialect():
    # A raw dblift dialect name that isn't a valid sqlglot dialect (e.g. a
    # call site that forgot to route through get_sqlglot_dialect) makes
    # sqlglot raise rather than parse — caught, not propagated — but the
    # keyword-scan fallback still finds the right answer regardless, because
    # it never looks at the dialect at all. A wrong dialect string can no
    # longer silently reinstate the old "WITH always means QUERY" bug.
    sql = "WITH c AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT 1 FROM c)"
    assert cte_outer_statement_type(sql, sqlglot_dialect="sqlserver") == "DML"
    assert cte_outer_statement_type(sql, sqlglot_dialect="db2") == "DML"


def test_cte_outer_statement_type_db2_none_dialect_parses_as_generic_sql():
    # get_sqlglot_dialect("db2") is None (no dedicated sqlglot dialect), and
    # sqlglot parses None as generic SQL rather than raising.
    sql = (
        "WITH c AS (SELECT 1 FROM sysibm.sysdummy1) "
        "MERGE INTO t USING c ON t.id = c.id WHEN MATCHED THEN UPDATE SET v = 1"
    )
    assert cte_outer_statement_type(sql, sqlglot_dialect=None) == "DML"


def test_cte_outer_statement_type_db2_trailing_clause_sqlglot_cannot_parse():
    # BLOCKER regression: DB2 lets a CTE feed INSERT/UPDATE/DELETE/MERGE, the
    # same as the reported defect, but two ordinary DB2 idioms (OPTIMIZE FOR,
    # the WITH UR isolation-level clause) aren't in sqlglot's db2 grammar, so
    # parsing the whole statement fails. Returning to the caller's old QUERY
    # default here would silently reinstate the exact bug this PR fixes — the
    # keyword scan must find the real answer instead.
    optimize_for = (
        "WITH cte AS (SELECT id FROM src) DELETE FROM src "
        "WHERE id IN (SELECT id FROM cte) OPTIMIZE FOR 1 ROW"
    )
    with_ur = (
        "WITH cte AS (SELECT id FROM src) DELETE FROM src "
        "WHERE id IN (SELECT id FROM cte) WITH UR"
    )
    assert cte_outer_statement_type(optimize_for, sqlglot_dialect=None) == "DML"
    assert cte_outer_statement_type(with_ur, sqlglot_dialect=None) == "DML"


def test_cte_outer_statement_type_skips_dollar_quoted_region():
    # BLOCKER regression: the keyword scan used ``)`` to track paren depth
    # without knowing about PostgreSQL dollar-quoting. A ``)`` or a keyword
    # sitting inside a ``$$...$$``/``$tag$...$tag$`` literal must not be
    # read as real code — a stray ``)`` inside the quoted text zeroed the
    # depth counter early, and the ``SELECT`` still textually inside the
    # quotes was then read as the outer verb: a *confident wrong* "QUERY"
    # for a statement that genuinely executes as DML.
    untagged = (
        "WITH x AS (DELETE FROM t WHERE note = $$ premature ) SELECT trap $$ RETURNING id) "
        "INSERT INTO app_logs(msg) SELECT 'x' FROM x"
    )
    tagged = (
        "WITH x AS (DELETE FROM t WHERE note = $tag$ premature ) SELECT trap $tag$ RETURNING id) "
        "INSERT INTO app_logs(msg) SELECT 'x' FROM x"
    )
    assert cte_outer_statement_type(untagged, sqlglot_dialect=None) == "DML"
    assert cte_outer_statement_type(tagged, sqlglot_dialect=None) == "DML"


def test_cte_outer_statement_type_none_for_unterminated_dollar_quote():
    # An unclosed dollar-quote swallows the rest of the text (same
    # unterminated-comment convention as _skip_comment): there is no way to
    # tell what the outer statement is, so this must surrender to None
    # rather than guess from whatever partial text remains.
    sql = "WITH x AS (DELETE FROM t WHERE note = $$ never closes"
    assert cte_outer_statement_type(sql, sqlglot_dialect=None) is None


def test_cte_outer_statement_type_keyword_scan_handles_comments_and_bare_dollar():
    # A comment between the CTE and the outer verb, and a "$" that is not a
    # dollar-quote tag (a positional parameter placeholder, e.g. $1) must
    # not confuse the scan either.
    sql = (
        "WITH cte AS (SELECT id FROM src) -- find rows\n"
        "DELETE FROM src /* filter */ WHERE id IN (SELECT id FROM cte) "
        "AND note = $1 OPTIMIZE FOR 1 ROW"
    )
    assert cte_outer_statement_type(sql, sqlglot_dialect=None) == "DML"


def test_cte_outer_statement_type_tsql_output_clause_is_dml_by_keyword_scan():
    # T-SQL's OUTPUT clause (SQL Server's RETURNING equivalent) isn't in
    # sqlglot's tsql grammar here, so this now goes through the keyword scan,
    # which finds DELETE and returns DML — even though OUTPUT means this
    # particular DELETE does return rows. The scan reads the outer VERB only;
    # it doesn't look for a RETURNING/OUTPUT clause on the outer statement.
    # That is not a new gap: the sqlglot path above has the identical
    # limitation for SQL it *can* parse (see the postgres case below), so a
    # WITH-fed DELETE with its own RETURNING/OUTPUT was already
    # misclassified before this fallback existed. Out of scope for this
    # defect, which is about a CTE that does NOT return rows; the OUTPUT/
    # RETURNING-on-the-outer-statement gap is a separate, pre-existing one.
    sql = "WITH c AS (SELECT 1 AS id) DELETE FROM t OUTPUT deleted.id FROM t JOIN c ON t.id = c.id"
    assert cte_outer_statement_type(sql, sqlglot_dialect="tsql") == "DML"


def test_cte_outer_statement_type_ignores_outer_returning_even_when_sqlglot_parses():
    # Same limitation as the tsql/OUTPUT case above, but via the sqlglot
    # path (this parses fine) rather than the keyword-scan fallback — proof
    # the fallback isn't introducing a new class of gap, just extending an
    # existing, accepted one to unparseable input too.
    sql = "WITH x AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT 1 FROM x) RETURNING id"
    assert cte_outer_statement_type(sql, sqlglot_dialect="postgres") == "DML"


def test_base_quirks_exposes_is_full_table_dml():
    quirks = BaseQuirks(dialect_name="sqlite")
    assert quirks.is_full_table_dml("-- c\nUPDATE t SET a = 1;")
    assert not quirks.is_full_table_dml("UPDATE t SET a = 1 WHERE id = 1;")


def test_dml_where_predicate_extracts_update_and_delete_conditions():
    assert dml_where_predicate("UPDATE t SET x = 1 WHERE id = 5;") == "id = 5"
    assert (
        dml_where_predicate("DELETE FROM t WHERE id IN (1, 2) AND status = 'old';")
        == "id IN (1, 2) AND status = 'old'"
    )


def test_dml_where_predicate_none_for_full_table_and_non_update_delete():
    assert dml_where_predicate("UPDATE t SET x = 1;") is None  # full-table
    assert dml_where_predicate("INSERT INTO t (id) VALUES (1);") is None
    assert dml_where_predicate("not sql at all") is None


def test_insert_value_rows_extracts_explicit_literals():
    assert insert_value_rows("INSERT INTO t (id, s) VALUES (5, 'x');") == [{"id": 5, "s": "x"}]
    assert insert_value_rows("INSERT INTO t (a, b) VALUES (1, 'p'), (2, 'q');") == [
        {"a": 1, "b": "p"},
        {"a": 2, "b": "q"},
    ]
    assert insert_value_rows("INSERT INTO t (id, n, ok) VALUES (-3, NULL, TRUE);") == [
        {"id": -3, "n": None, "ok": True}
    ]


def test_insert_value_rows_omits_non_literals_and_rejects_unparseable():
    # DEFAULT / non-literal columns are omitted (signals an auto-generated key).
    assert insert_value_rows("INSERT INTO t (id, s) VALUES (DEFAULT, 'x');") == [{"s": "x"}]
    # No column list, INSERT ... SELECT, and non-INSERT all yield None.
    assert insert_value_rows("INSERT INTO t VALUES (1, 'x');") is None
    assert insert_value_rows("INSERT INTO t (id) SELECT id FROM other;") is None
    assert insert_value_rows("UPDATE t SET x = 1 WHERE id = 1;") is None
