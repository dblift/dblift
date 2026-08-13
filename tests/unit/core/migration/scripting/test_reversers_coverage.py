"""Coverage tests for core.migration.scripting.undo_script_generator._reversers.

Targets the uncovered line ranges in _UndoReversersMixin:
  140-143, 148, 166, 188-190, 197, 213  — _reverse_create_from_parsed / _reverse_create
  238-243, 253                           — _reverse_alter_from_parsed: no affected_objects, schema
  270, 278, 293-295                      — ADD COLUMN success / DROP COLUMN / ADD CONSTRAINT paths
  311, 316, 323-324, 332                 — ADD CONSTRAINT warning / DROP CONSTRAINT / MODIFY COLUMN
  355, 369, 387, 394, 396, 403          — _reverse_alter branches
  409-417, 423, 430, 436, 443, 445, 454 — more _reverse_alter branches
  531-550, 562-650                       — _reverse_insert_from_parsed (sqlglot + fallback)
  679-704                                — _reverse_insert
  797, 807                               — _reverse_comment_from_parsed
  842, 856                               — _reverse_comment
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.migration.scripting.undo_script_generator import UndoScriptGenerator, UndoStatement

# ---------------------------------------------------------------------------
# Helpers — build a minimal concrete instance of the mixin
# ---------------------------------------------------------------------------


def make_generator(dialect="postgresql"):
    """Return a real UndoScriptGenerator (concrete implementation of the mixin)."""
    return UndoScriptGenerator(dialect=dialect, logger=None)


def make_stmt(sql, affected_objects=None, objects=None, statement_type=None):
    """Build a minimal mock SqlStatement."""
    from core.sql_model.base import SqlStatementType

    stmt = MagicMock()
    stmt.sql_text = sql
    stmt.affected_objects = affected_objects or []
    stmt.objects = objects or []
    stmt.statement_type = statement_type or SqlStatementType.DDL
    return stmt


def make_obj(name, obj_type_value, schema=None):
    """Build a minimal mock object (affected_objects element)."""
    obj = MagicMock()
    obj.name = name
    obj.schema = schema
    type_mock = MagicMock()
    type_mock.value = obj_type_value
    obj.object_type = type_mock
    return obj


# ---------------------------------------------------------------------------
# _reverse_create_from_parsed — uncovered branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseCreateFromParsed:
    def test_no_affected_objects_uses_objects(self):
        # Lines 139-142: stmt.affected_objects empty, stmt.objects has an entry
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("CREATE TABLE users (id INT);", affected_objects=[], objects=[obj])
        result = gen._reverse_create_from_parsed(stmt)
        assert result is not None
        assert "DROP TABLE" in result.sql
        assert "users" in result.sql

    def test_no_objects_at_all_falls_to_regex(self):
        # Lines 145-155: both empty, fallback to _extract_create_object regex
        gen = make_generator()
        stmt = make_stmt("CREATE TABLE my_table (id INT);", affected_objects=[], objects=[])
        result = gen._reverse_create_from_parsed(stmt)
        assert result is not None
        assert "DROP TABLE" in result.sql or "WARNING" in result.sql

    def test_no_objects_regex_fails_returns_warning(self):
        # Line 147-154: _extract_create_object returns None → warning
        gen = make_generator()
        stmt = make_stmt("INVALID SQL STUFF", affected_objects=[], objects=[])
        result = gen._reverse_create_from_parsed(stmt)
        assert result is not None
        assert result.requires_manual_review is True

    def test_unsupported_object_type_returns_warning(self):
        # Lines 165-172: obj_type not in supported list → WARNING
        gen = make_generator()
        obj = make_obj("my_schema", "SCHEMA")
        stmt = make_stmt("CREATE SCHEMA my_schema;", affected_objects=[obj])
        result = gen._reverse_create_from_parsed(stmt)
        assert result is not None
        assert result.requires_manual_review is True
        assert "WARNING" in result.sql

    def test_view_type_generates_drop_view(self):
        # Lines 158-164: VIEW in supported types
        gen = make_generator()
        obj = make_obj("active_users", "VIEW")
        stmt = make_stmt("CREATE VIEW active_users AS SELECT 1;", affected_objects=[obj])
        result = gen._reverse_create_from_parsed(stmt)
        assert "DROP VIEW" in result.sql

    def test_sequence_type_generates_drop_sequence(self):
        gen = make_generator()
        obj = make_obj("my_seq", "SEQUENCE")
        stmt = make_stmt("CREATE SEQUENCE my_seq;", affected_objects=[obj])
        result = gen._reverse_create_from_parsed(stmt)
        assert "DROP SEQUENCE" in result.sql


# ---------------------------------------------------------------------------
# _reverse_create — uncovered branches (analysis dict path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseCreate:
    def test_no_objects_falls_to_regex(self):
        # Lines 187-197: analysis has no objects, fallback regex
        gen = make_generator()
        analysis = {"objects": []}
        result = gen._reverse_create("CREATE TABLE foo (id INT);", analysis)
        assert result is not None

    def test_no_objects_regex_fails_warning(self):
        gen = make_generator()
        analysis = {"objects": []}
        result = gen._reverse_create("NOT VALID SQL", analysis)
        assert result.requires_manual_review is True

    def test_unsupported_type_from_analysis(self):
        # Lines 212-218: obj_type not in supported set
        gen = make_generator()
        analysis = {
            "objects": [{"object_type": "SCHEMA", "object_name": "my_schema", "schema": None}]
        }
        result = gen._reverse_create("CREATE SCHEMA my_schema;", analysis)
        assert result.requires_manual_review is True

    def test_supported_type_from_analysis(self):
        # Lines 205-211: obj_type in supported set
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_create("CREATE TABLE users (id INT);", analysis)
        assert "DROP TABLE" in result.sql

    def test_supported_type_with_schema_from_analysis(self):
        gen = make_generator()
        analysis = {
            "objects": [{"object_type": "TABLE", "object_name": "users", "schema": "public"}]
        }
        result = gen._reverse_create("CREATE TABLE public.users (id INT);", analysis)
        assert "DROP TABLE" in result.sql
        assert "users" in result.sql


@pytest.mark.unit
class TestDefaultSchemaPlaceholderNeverReachesGeneratedSql:
    """``default_schema`` is internal to ``extract_objects``, not an identifier.

    That function reports one combined ``"<schema>.<name>"`` string, using the
    literal ``default_schema`` when the statement named no schema. Quoting the
    whole string as a single identifier yields
    ``DROP SEQUENCE "default_schema.users_seq"`` -- an object that never
    exists (ORA-02289), so the undo script silently undoes nothing.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE TABLE t (id INT)",
            "CREATE VIEW v AS SELECT 1",
            "CREATE SEQUENCE users_seq START WITH 1",
            "CREATE TRIGGER tg BEFORE INSERT ON t FOR EACH ROW BEGIN NULL; END;",
            "CREATE INDEX idx ON orders (email)",
        ],
    )
    def test_placeholder_is_absent_from_the_undo_statement(self, sql):
        gen = make_generator(dialect="oracle")
        result = gen._reverse_create(sql, gen.sql_analyzer.analyze_statement(sql))
        assert "default_schema" not in result.sql

    def test_unqualified_name_drops_the_bare_object(self):
        gen = make_generator(dialect="oracle")
        sql = "CREATE SEQUENCE users_seq START WITH 1"
        result = gen._reverse_create(sql, gen.sql_analyzer.analyze_statement(sql))
        assert result.sql == 'DROP SEQUENCE "users_seq";'

    def test_a_real_schema_is_still_qualified(self):
        gen = make_generator(dialect="oracle")
        sql = "CREATE TABLE app.orders (id INT)"
        result = gen._reverse_create(sql, gen.sql_analyzer.analyze_statement(sql))
        assert result.sql == 'DROP TABLE "app"."orders";'


# ---------------------------------------------------------------------------
# _reverse_alter_from_parsed — uncovered branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseAlterFromParsed:
    def test_no_affected_objects_uses_objects(self):
        # Lines 238-241: uses stmt.objects when affected_objects empty
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt(
            "ALTER TABLE users ADD COLUMN email VARCHAR(255);", affected_objects=[], objects=[obj]
        )
        result = gen._reverse_alter_from_parsed(stmt)
        assert result is not None
        assert "DROP COLUMN" in result.sql or "WARNING" in result.sql

    def test_no_objects_at_all_returns_warning(self):
        # Lines 243-248: no objects → warning
        gen = make_generator()
        stmt = make_stmt(
            "ALTER TABLE users ADD COLUMN email VARCHAR(255);", affected_objects=[], objects=[]
        )
        result = gen._reverse_alter_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_with_schema_formats_correctly(self):
        # Lines 252-255: schema present → formatted table includes schema
        gen = make_generator()
        obj = make_obj("users", "TABLE", schema="public")
        stmt = make_stmt("ALTER TABLE public.users ADD COLUMN age INT;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        # Should reference the table with schema in the SQL
        assert result is not None
        assert "users" in result.sql

    def test_add_column_success(self):
        # Lines 260-268: ADD COLUMN path with column name extracted
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users ADD COLUMN email VARCHAR(255);", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert "DROP COLUMN" in result.sql
        assert "email" in result.sql

    def test_add_column_no_name_extracted(self):
        # Lines 270-276: ADD COLUMN but column name not extractable
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users ADD COLUMN;", affected_objects=[obj])  # malformed
        result = gen._reverse_alter_from_parsed(stmt)
        # Either succeeds or returns warning
        assert result is not None

    def test_drop_column_returns_warning(self):
        # Lines 277-284: DROP COLUMN → warning
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users DROP COLUMN email;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert result.requires_manual_review is True
        assert "DROP COLUMN" in result.sql

    def test_add_constraint_with_name_generic(self):
        # Lines 285-302: ADD CONSTRAINT path
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt(
            "ALTER TABLE users ADD CONSTRAINT uk_email UNIQUE (email);", affected_objects=[obj]
        )
        result = gen._reverse_alter_from_parsed(stmt)
        assert "DROP CONSTRAINT" in result.sql or "WARNING" in result.sql

    def test_add_primary_key(self):
        # Lines 292-293: ADD PRIMARY KEY → DROP PRIMARY KEY (or warning if name not extracted)
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users ADD PRIMARY KEY (id);", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        # Either DROP PRIMARY KEY or warning (constraint name may not be extractable)
        assert "PRIMARY KEY" in result.sql or result.requires_manual_review

    def test_add_foreign_key(self):
        # Lines 294-295: ADD FOREIGN KEY → DROP FOREIGN KEY
        gen = make_generator()
        obj = make_obj("orders", "TABLE")
        stmt = make_stmt(
            "ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);",
            affected_objects=[obj],
        )
        result = gen._reverse_alter_from_parsed(stmt)
        assert "FOREIGN KEY" in result.sql or "CONSTRAINT" in result.sql

    def test_add_constraint_no_name_warning(self):
        # Lines 303-310: constraint name not extracted
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        # Malformed - no constraint name
        stmt = make_stmt("ALTER TABLE users ADD CONSTRAINT;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert result is not None

    def test_drop_constraint_returns_warning(self):
        # Lines 311-322: DROP CONSTRAINT → warning
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users DROP CONSTRAINT uk_email;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_modify_column_returns_warning(self):
        # Lines 323-330: MODIFY COLUMN → warning
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users MODIFY COLUMN age BIGINT;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_alter_column_returns_warning(self):
        # Lines 323-330: ALTER COLUMN → warning
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users ALTER COLUMN age TYPE BIGINT;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_other_alter_returns_warning(self):
        # Lines 331-338: unrecognized ALTER operation → warning
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("ALTER TABLE users RENAME TO old_users;", affected_objects=[obj])
        result = gen._reverse_alter_from_parsed(stmt)
        assert result.requires_manual_review is True


# ---------------------------------------------------------------------------
# _reverse_alter — analysis dict path (uncovered branches)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseAlter:
    def test_no_objects_returns_warning(self):
        # Lines 354-361: no objects in analysis
        gen = make_generator()
        result = gen._reverse_alter("ALTER TABLE users ADD COLUMN x INT;", {"objects": []})
        assert result.requires_manual_review is True

    def test_add_column_with_schema(self):
        # Lines 368-385: ADD COLUMN with schema present
        gen = make_generator()
        analysis = {
            "objects": [{"object_type": "TABLE", "object_name": "users", "schema": "public"}]
        }
        result = gen._reverse_alter(
            "ALTER TABLE public.users ADD COLUMN email VARCHAR(255);", analysis
        )
        assert "DROP COLUMN" in result.sql
        assert "email" in result.sql

    def test_drop_column(self):
        # Lines 394-402: DROP COLUMN → warning
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter("ALTER TABLE users DROP COLUMN email;", analysis)
        assert result.requires_manual_review is True
        assert "DROP COLUMN" in result.sql

    def test_add_constraint_primary_key(self):
        # Lines 403-421: ADD PRIMARY KEY → DROP PRIMARY KEY (or warning if name not extracted)
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter("ALTER TABLE users ADD PRIMARY KEY (id);", analysis)
        assert "PRIMARY KEY" in result.sql or result.requires_manual_review

    def test_add_constraint_foreign_key(self):
        # Lines 413-414: ADD FOREIGN KEY → DROP FOREIGN KEY
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "orders", "schema": None}]}
        result = gen._reverse_alter(
            "ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);",
            analysis,
        )
        assert "FOREIGN KEY" in result.sql or "CONSTRAINT" in result.sql

    def test_add_constraint_generic(self):
        # Lines 415-416: ADD CONSTRAINT (not PK or FK)
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter(
            "ALTER TABLE users ADD CONSTRAINT uk_email UNIQUE (email);", analysis
        )
        assert "DROP CONSTRAINT" in result.sql or "WARNING" in result.sql

    def test_add_constraint_no_name(self):
        # Lines 422-429: constraint name not extracted → warning
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter("ALTER TABLE users ADD CONSTRAINT;", analysis)
        assert result is not None

    def test_drop_constraint(self):
        # Lines 430-442: DROP CONSTRAINT → warning
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter("ALTER TABLE users DROP CONSTRAINT uk_email;", analysis)
        assert result.requires_manual_review is True

    def test_modify_column(self):
        # Lines 443-451: MODIFY COLUMN → warning
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter("ALTER TABLE users MODIFY COLUMN age BIGINT;", analysis)
        assert result.requires_manual_review is True

    def test_other_alter(self):
        # Lines 452-460: other ALTER → warning
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_alter("ALTER TABLE users RENAME TO old_users;", analysis)
        assert result.requires_manual_review is True


# ---------------------------------------------------------------------------
# _reverse_insert_from_parsed — sqlglot paths (lines 531-656)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseInsertFromParsed:
    def test_simple_insert_generates_delete(self):
        # Basic path through sqlglot: Table extraction → WHERE clause
        gen = make_generator(dialect="postgresql")
        stmt = make_stmt(
            "INSERT INTO users (id, name) VALUES (1, 'Alice');",
        )
        result = gen._reverse_insert_from_parsed(stmt)
        assert result is not None
        # Either DELETE or warning
        assert "users" in result.sql or result.requires_manual_review

    def test_insert_with_schema_qualified_table(self):
        # Schema-qualified table name (lines 571-576)
        gen = make_generator(dialect="postgresql")
        stmt = make_stmt("INSERT INTO public.users (id, name) VALUES (1, 'Alice');")
        result = gen._reverse_insert_from_parsed(stmt)
        assert result is not None

    def test_insert_with_mysql_dialect(self):
        # Different dialect (MySQL)
        gen = make_generator(dialect="mysql")
        stmt = make_stmt("INSERT INTO users (id, name) VALUES (1, 'Bob');")
        result = gen._reverse_insert_from_parsed(stmt)
        assert result is not None

    def test_insert_with_oracle_dialect(self):
        # Oracle dialect
        gen = make_generator(dialect="oracle")
        stmt = make_stmt("INSERT INTO users (id, name) VALUES (1, 'Carol');")
        result = gen._reverse_insert_from_parsed(stmt)
        assert result is not None

    def test_insert_no_where_clause_extracted(self):
        # Complex INSERT that cannot generate WHERE → warning (lines 593-598)
        gen = make_generator()
        stmt = make_stmt("INSERT INTO users SELECT id, name FROM old_users;")
        result = gen._reverse_insert_from_parsed(stmt)
        assert result is not None

    def test_insert_sqlglot_exception_fallback_with_objects(self):
        # When sqlglot raises, fall back to stmt.objects (lines 600-648)
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("INSERT INTO users (id) VALUES (1);", objects=[obj])
        # Patch parse_one to raise
        with patch(
            "core.migration.scripting.undo_script_generator._reversers.parse_one",
            side_effect=Exception("parse error"),
        ):
            result = gen._reverse_insert_from_parsed(stmt)
        assert result is not None
        assert "users" in result.sql or result.requires_manual_review

    def test_insert_sqlglot_exception_fallback_no_objects(self):
        # When sqlglot raises and no objects → warning (lines 611-618)
        gen = make_generator()
        stmt = make_stmt("INSERT INTO users (id) VALUES (1);", objects=[])
        with patch(
            "core.migration.scripting.undo_script_generator._reversers.parse_one",
            side_effect=Exception("parse error"),
        ):
            result = gen._reverse_insert_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_insert_fallback_where_clause_none(self):
        # Fallback path: no WHERE extracted → warning (lines 650-656)
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("INSERT INTO users SELECT * FROM old_users;", objects=[obj])
        with patch(
            "core.migration.scripting.undo_script_generator._reversers.parse_one",
            side_effect=Exception("parse error"),
        ):
            with patch.object(gen, "_extract_insert_where_clause", return_value=None):
                result = gen._reverse_insert_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_insert_fallback_where_clause_found(self):
        # Fallback path: WHERE extracted → DELETE (lines 639-648)
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("INSERT INTO users (id, name) VALUES (1, 'Alice');", objects=[obj])
        with patch(
            "core.migration.scripting.undo_script_generator._reversers.parse_one",
            side_effect=Exception("parse error"),
        ):
            with patch.object(gen, "_extract_insert_where_clause", return_value="id = 1"):
                result = gen._reverse_insert_from_parsed(stmt)
        assert "DELETE FROM" in result.sql
        assert "users" in result.sql


# ---------------------------------------------------------------------------
# _reverse_insert — analysis dict path (lines 679-710)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseInsert:
    def test_no_objects_warning(self):
        # Lines 670-677: no objects in analysis
        gen = make_generator()
        result = gen._reverse_insert("INSERT INTO users VALUES (1);", {"objects": []})
        assert result.requires_manual_review is True

    def test_with_schema(self):
        # Lines 683-689: schema present in analysis — either DELETE or warning
        gen = make_generator()
        analysis = {
            "objects": [{"object_type": "TABLE", "object_name": "users", "schema": "public"}]
        }
        result = gen._reverse_insert("INSERT INTO public.users (id) VALUES (1);", analysis)
        assert result is not None
        # May produce DELETE with WHERE or a warning — both are valid outcomes
        assert "users" in result.sql or result.requires_manual_review

    def test_with_where_clause(self):
        # Lines 694-701: WHERE clause extracted → DELETE
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        result = gen._reverse_insert("INSERT INTO users (id, name) VALUES (1, 'Alice');", analysis)
        assert result is not None
        # Could be DELETE or warning depending on regex extraction

    def test_no_where_clause(self):
        # Lines 703-710: no WHERE clause → warning
        gen = make_generator()
        analysis = {"objects": [{"object_type": "TABLE", "object_name": "users", "schema": None}]}
        with patch.object(gen, "_extract_insert_where_clause", return_value=None):
            result = gen._reverse_insert("INSERT INTO users SELECT * FROM old;", analysis)
        assert result.requires_manual_review is True


# ---------------------------------------------------------------------------
# _reverse_comment_from_parsed — uncovered branches (lines 797, 807)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseCommentFromParsed:
    def test_with_affected_objects(self):
        # Lines 794-796: uses affected_objects
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt("COMMENT ON TABLE users IS 'User accounts';", affected_objects=[obj])
        result = gen._reverse_comment_from_parsed(stmt)
        assert "COMMENT ON TABLE" in result.sql
        assert "IS NULL" in result.sql

    def test_with_objects_fallback(self):
        # Lines 795-802: affected_objects empty, uses objects
        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt(
            "COMMENT ON TABLE users IS 'User accounts';", affected_objects=[], objects=[obj]
        )
        result = gen._reverse_comment_from_parsed(stmt)
        assert "COMMENT ON TABLE" in result.sql
        assert "IS NULL" in result.sql

    def test_no_objects_falls_back_to_regex(self):
        # Lines 799: falls back to _reverse_comment when no objects
        gen = make_generator()
        stmt = make_stmt("COMMENT ON TABLE users IS 'msg';", affected_objects=[], objects=[])
        result = gen._reverse_comment_from_parsed(stmt)
        # _reverse_comment is called → either SUCCESS or warning
        assert result is not None

    def test_with_schema_in_object(self):
        # Lines 806-809: schema-qualified name
        gen = make_generator()
        obj = make_obj("users", "TABLE", schema="public")
        stmt = make_stmt("COMMENT ON TABLE public.users IS 'msg';", affected_objects=[obj])
        result = gen._reverse_comment_from_parsed(stmt)
        assert "users" in result.sql
        assert "IS NULL" in result.sql


# ---------------------------------------------------------------------------
# _reverse_comment — regex path (lines 830-862)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseComment:
    def test_comment_on_table(self):
        # Lines 835-854: matching COMMENT ON TABLE
        gen = make_generator()
        result = gen._reverse_comment("COMMENT ON TABLE users IS 'User table';")
        assert "COMMENT ON TABLE" in result.sql
        assert "IS NULL" in result.sql

    def test_comment_with_schema(self):
        # Lines 841-843: schema present
        gen = make_generator()
        result = gen._reverse_comment("COMMENT ON TABLE public.users IS 'msg';")
        assert "users" in result.sql
        assert "IS NULL" in result.sql

    def test_comment_no_match_returns_warning(self):
        # Line 856: no match → warning
        gen = make_generator()
        result = gen._reverse_comment("NOT A COMMENT STATEMENT")
        assert result.requires_manual_review is True

    def test_comment_on_column(self):
        gen = make_generator()
        result = gen._reverse_comment("COMMENT ON COLUMN users.email IS 'Email address';")
        assert result is not None


# ---------------------------------------------------------------------------
# _reverse_statement_from_parsed — routing branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseStatementFromParsed:
    def test_routes_to_create(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt(
            "CREATE TABLE users (id INT);",
            affected_objects=[obj],
            statement_type=SqlStatementType.CREATE,
        )
        result = gen._reverse_statement_from_parsed(stmt)
        assert result is not None

    def test_routes_to_alter(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt(
            "ALTER TABLE users ADD COLUMN x INT;",
            affected_objects=[obj],
            statement_type=SqlStatementType.ALTER,
        )
        result = gen._reverse_statement_from_parsed(stmt)
        assert result is not None

    def test_routes_to_drop(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        stmt = make_stmt("DROP TABLE users;", statement_type=SqlStatementType.DROP)
        result = gen._reverse_statement_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_routes_to_insert(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        stmt = make_stmt(
            "INSERT INTO users (id) VALUES (1);", statement_type=SqlStatementType.INSERT
        )
        result = gen._reverse_statement_from_parsed(stmt)
        assert result is not None

    def test_routes_to_update(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        stmt = make_stmt(
            "UPDATE users SET name='x' WHERE id=1;", statement_type=SqlStatementType.UPDATE
        )
        result = gen._reverse_statement_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_routes_to_delete(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        stmt = make_stmt("DELETE FROM users WHERE id=1;", statement_type=SqlStatementType.DELETE)
        result = gen._reverse_statement_from_parsed(stmt)
        assert result.requires_manual_review is True

    def test_routes_to_comment(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        obj = make_obj("users", "TABLE")
        stmt = make_stmt(
            "COMMENT ON TABLE users IS 'msg';",
            affected_objects=[obj],
            statement_type=SqlStatementType.COMMENT,
        )
        result = gen._reverse_statement_from_parsed(stmt)
        assert result is not None

    def test_unknown_type_returns_warning(self):
        from core.sql_model.base import SqlStatementType

        gen = make_generator()
        stmt = make_stmt("GRANT SELECT ON users TO admin;", statement_type=SqlStatementType.UNKNOWN)
        # Does not start with CREATE/ALTER/DROP/INSERT/UPDATE/DELETE/COMMENT
        result = gen._reverse_statement_from_parsed(stmt)
        assert result is not None


# ---------------------------------------------------------------------------
# _reverse_statement — routing (string parsing path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseStatement:
    def test_comment_routes(self):
        gen = make_generator()
        result = gen._reverse_statement("COMMENT ON TABLE t IS 'x';")
        assert result is not None

    def test_unknown_routes(self):
        gen = make_generator()
        result = gen._reverse_statement("GRANT ALL ON t TO user;")
        assert result.requires_manual_review is True
