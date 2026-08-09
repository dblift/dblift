"""History-table predicates must include ``PYTHON``, not just ``SQL``.

``MigrationType.SQL`` does not mean "SQL format" — it is what
``parse_filename`` returns for *every* versioned script, whatever the
extension. ``Migration`` then relabels non-SQL formats as
``MigrationType.PYTHON``, so a ``.py`` migration lands in the history table
with ``type = 'PYTHON'``.

Any read-side predicate spelled ``type = 'SQL'`` therefore drops every
Python migration. These tests pin the widened predicate, the single shared
constant the dialects must build it from, and the fact that the persisted
vocabulary itself is unchanged (history stores ``MigrationType.<member>.name``
and is read back with the name-based ``MigrationType[...]`` lookup, so a
renamed or added stored value would silently degrade old rows to ``UNKNOWN``).
"""

from __future__ import annotations

import ast
import io
import sqlite3
import tokenize
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient
from core.migration.migration import MigrationType
from db.plugins.base_history_manager import (
    VERSIONED_HISTORY_TYPES,
    VERSIONED_HISTORY_TYPES_SQL_IN,
)

V_SQL = "CREATE TABLE items (id INTEGER PRIMARY KEY);"
U_SQL = "DROP TABLE IF EXISTS items;"
V_PY = 'def migrate(context):\n    context.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")\n'
U_PY = 'def migrate(context):\n    context.execute("DROP TABLE IF EXISTS items")\n'

_BODIES = {"sql": (V_SQL, U_SQL), "py": (V_PY, U_PY)}

# Every module under db/ that owns a history-table predicate or writes a
# history ``type``. Scanned as source so a new dialect copy-pasting the old
# literal is caught even if nothing instantiates it.
# Every module that composes history SQL: the shared base, the relational
# providers that own their history inline, and the two dialects that still
# attach a history component.
_HISTORY_SOURCES = [
    "db/plugins/base_history_manager.py",
    "db/plugins/postgresql/provider.py",
    "db/plugins/oracle/provider.py",
    "db/plugins/snowflake/provider.py",
    "db/plugins/mysql/provider.py",
    "db/plugins/sqlserver/provider.py",
    "db/plugins/duckdb/provider.py",
    "db/plugins/db2/provider.py",
    "db/plugins/sqlite/sqlite/history_manager.py",
    "db/plugins/cosmosdb/cosmosdb/history_manager.py",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _executable_source(relpath: str) -> str:
    """Source with comments and docstrings removed.

    The guards below look for SQL that a dialect actually emits. Prose that
    *names* the old predicate — this module's own docstring, or the comment on
    ``VERSIONED_HISTORY_TYPES`` explaining why the predicate was widened — is
    not a violation, so it must not be scanned.
    """
    src = (_repo_root() / relpath).read_text(encoding="utf-8")

    docstring_lines: set[int] = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str) and first.end_lineno is not None:
                docstring_lines.update(range(first.lineno, first.end_lineno + 1))

    kept = []
    for token in tokenize.generate_tokens(io.StringIO(src).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.start[0] in docstring_lines:
            continue
        kept.append(token.string)
    return "\n".join(kept)


def _make_project(tmp_path: Path, ext: str, *, with_undo: bool = False):
    body, undo_body = _BODIES[ext]
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"V1__create_items.{ext}").write_text(body)
    if with_undo:
        (migrations / f"U1__create_items.{ext}").write_text(undo_body)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return engine, migrations


def _history_rows(db_path: Path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT installed_rank, version, type, success FROM dblift_schema_history"
            " ORDER BY installed_rank"
        ).fetchall()
    finally:
        con.close()


@pytest.mark.unit
class TestVersionedHistoryTypeConstant:
    """The shared constant, and the name/value coincidence it rests on."""

    def test_constant_holds_both_versioned_type_names(self):
        assert VERSIONED_HISTORY_TYPES == frozenset({"SQL", "PYTHON"})

    def test_constant_is_built_from_migration_type_names(self):
        assert VERSIONED_HISTORY_TYPES == frozenset(
            {MigrationType.SQL.name, MigrationType.PYTHON.name}
        )

    def test_sql_in_clause_renders_a_quoted_deterministic_list(self):
        assert VERSIONED_HISTORY_TYPES_SQL_IN == "('PYTHON', 'SQL')"

    @pytest.mark.parametrize("member", [MigrationType.SQL, MigrationType.PYTHON])
    def test_versioned_names_and_values_have_not_drifted(self, member):
        """History is written by name and read by name; ``.value`` merely coincides.

        If these ever diverge, code that reaches for ``.value`` when it means
        the persisted string starts writing rows that
        ``AppliedMigration.from_history_row`` degrades to ``UNKNOWN``.
        """
        assert member.name == member.value

    def test_undo_type_name_and_value_have_not_drifted(self):
        assert MigrationType.UNDO_SQL.name == MigrationType.UNDO_SQL.value == "UNDO_SQL"


@pytest.mark.unit
class TestNoDialectKeepsItsOwnSqlPredicate:
    """No history module may hand-roll the versioned-type predicate."""

    @pytest.mark.parametrize("relpath", _HISTORY_SOURCES)
    def test_source_has_no_sql_only_type_predicate(self, relpath):
        src = _executable_source(relpath)
        assert "type = 'SQL'" not in src, f"{relpath} still filters on type = 'SQL' alone"
        assert "type IN ('SQL'" not in src, f"{relpath} hand-rolls its own IN list"

    @pytest.mark.parametrize("relpath", _HISTORY_SOURCES)
    def test_source_has_no_hardcoded_undo_type_literal(self, relpath):
        """No history-info dict may spell its ``type`` as a string literal.

        The write site is always a ``{"type": ...}`` entry in the dict handed to
        ``record_migration``. Oracle's *read* comparisons against ``"UNDO_SQL"``
        are a different thing and are left alone.
        """
        tree = ast.parse((_repo_root() / relpath).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                is_type_key = isinstance(key, ast.Constant) and key.value == "type"
                if is_type_key and isinstance(value, ast.Constant):
                    pytest.fail(
                        f"{relpath}:{value.lineno} writes history type "
                        f"{value.value!r} as a literal instead of deriving it "
                        "from MigrationType"
                    )


@pytest.mark.unit
class TestGetCurrentVersionEndToEnd:
    """A real SQLite migration, a real history table, the real read path."""

    @pytest.mark.parametrize("ext", ["sql", "py"])
    def test_current_version_is_returned_for_either_format(self, tmp_path, ext):
        engine, migrations = _make_project(tmp_path, ext)
        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
        try:
            assert client.migrate().success
            provider = client.provider
            assert provider.history_manager.get_current_version(provider.connection, "main") == "1"
        finally:
            client.close()

    @pytest.mark.parametrize("ext", ["sql", "py"])
    def test_history_row_type_matches_the_widened_predicate(self, tmp_path, ext):
        """The persisted vocabulary is unchanged: 'SQL' for .sql, 'PYTHON' for .py."""
        engine, migrations = _make_project(tmp_path, ext)
        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
        try:
            assert client.migrate().success
        finally:
            client.close()
        rows = _history_rows(tmp_path / "app.db")
        assert [r[2] for r in rows] == ["SQL" if ext == "sql" else "PYTHON"]
        assert set(r[2] for r in rows) <= VERSIONED_HISTORY_TYPES

    @pytest.mark.parametrize("ext", ["sql", "py"])
    def test_undo_row_is_excluded_from_the_predicate_for_either_format(self, tmp_path, ext):
        """Undo appends an ``UNDO_SQL`` row; widening must not pull it in.

        Both formats must reach the identical conclusion — the undo row is
        outside the versioned predicate, so ``ORDER BY installed_rank DESC``
        still lands on the original versioned row.
        """
        engine, migrations = _make_project(tmp_path, ext, with_undo=True)
        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
        try:
            assert client.migrate().success
            assert client.undo().success
            provider = client.provider
            current = provider.history_manager.get_current_version(provider.connection, "main")
        finally:
            client.close()

        rows = _history_rows(tmp_path / "app.db")
        assert [r[2] for r in rows] == ["SQL" if ext == "sql" else "PYTHON", "UNDO_SQL"]
        # The undo row has the higher installed_rank but must not be selected.
        assert current == "1"
