"""Every announced legacy entry point warns once; canonical paths stay silent."""

from __future__ import annotations

import warnings

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser import _deprecation
from dblift.core.sql_parser.parser_factory import SqlParserFactory


@pytest.fixture(autouse=True)
def fresh_notices():
    with _deprecation._warned_lock:
        saved = set(_deprecation._warned)
        _deprecation._warned.clear()
    yield
    with _deprecation._warned_lock:
        _deprecation._warned.clear()
        _deprecation._warned.update(saved)


def _silent(cls, *args):
    with _deprecation.internal_parser_construction():
        return cls(*args)


def _notices(action):
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        action()
    return [str(w.message) for w in seen if w.category is DeprecationWarning]


@pytest.mark.parametrize(
    ("name", "action", "replacement"),
    [
        ("SqlParserFactory", lambda: SqlParserFactory("sqlite"), "StatementSplitter"),
        ("SqlAnalyzer", lambda: SqlAnalyzer("sqlite"), "StatementSplitter"),
    ],
    ids=[
        "factory",
        "analyzer",
    ],
)
def test_legacy_entry_point_warns_naming_its_replacement(name, action, replacement):
    messages = _notices(action)
    assert len(messages) == 1, messages
    assert name in messages[0]
    assert replacement in messages[0]
    assert "read_statement_facts" in messages[0]


def test_explicit_parser_type_has_its_own_notice():
    messages = _notices(lambda: SqlParserFactory("sqlite", "regex"))
    assert len(messages) == 1, messages
    assert "parser_type" in messages[0]
    assert "StatementSplitter" in messages[0]
    assert "read_statement_facts" in messages[0]


def test_each_notice_is_once_per_process():
    assert len(_notices(lambda: SqlAnalyzer("sqlite"))) == 1
    assert _notices(lambda: SqlAnalyzer("sqlite")) == []


def test_internal_bridges_are_silent_and_canonical_paths_do_not_warn():
    from dblift.core.sql_parser.redaction import _dialect_tokenizer, mask_string_literals

    def canonical():
        splitter = StatementSplitter("sqlite")
        splitter.split("SELECT 1;")
        splitter.split_statements("SELECT 1;")
        analyzer = _silent(SqlAnalyzer, "sqlite")
        analyzer.split_statements("SELECT 1;")
        analyzer.split_statements_for_analysis("SELECT 1;")
        _ = analyzer.parser_factory
        _dialect_tokenizer("mongodb")
        mask_string_literals("SELECT 'a'", "postgresql")

    assert _notices(canonical) == []


def test_silent_contexts_at_the_remaining_internal_construction_sites(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from dblift.api import DBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog
    from dblift.db.provider_registry import ProviderRegistry
    from tests.unit._migration_factory import make_migration

    migrations = tmp_path / "m"
    migrations.mkdir()
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "d.db"), "schema": "main"}}
    )
    with DBLiftClient.from_config(config, migrations_dir=migrations, logger=NullLog()) as client:
        engine = client.executor.execution_engine
        engine.sql_analyzer = _silent(SqlAnalyzer, "postgresql")  # forces the fallback analyzer
        migration = make_migration(
            script_name="V1__a.sql", content="SELECT 1;", config=client.config
        )

        def canonical():
            engine._prepare_sql_statements(migration)  # execution-engine fallback

            legacy = MagicMock()
            legacy.database.type = "sqlite"
            make_migration(
                script_name="V1__b.sql", content="SELECT 1;", config=legacy
            ).parse_sql_statements()  # Migration.parse_sql_statements

            quirks = ProviderRegistry.get_quirks("sqlite")
            monkeypatch.setattr(type(quirks), "lexical_spec", lambda self: None)
            StatementSplitter("sqlite")  # the splitter's regex fallback factory

        assert _notices(canonical) == []
