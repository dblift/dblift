"""Alpha notices stay on direct legacy use, away from canonical SQL paths."""

from __future__ import annotations

import subprocess
import sys
import warnings

import pytest
from sqlalchemy import create_engine

from dblift.api.client import DBLiftClient
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser._deprecation import internal_parser_construction
from dblift.core.sql_parser.statement import execution_strings


def test_direct_hybrid_parser_warns_once_per_process_and_preserves_parse_result() -> None:
    code = """
import warnings
from dblift.core.sql_parser.hybrid_parser import HybridParser
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", DeprecationWarning)
    first = HybridParser("snowflake")
    HybridParser("snowflake")

messages = [str(item.message) for item in seen if item.category is DeprecationWarning]
assert len(messages) == 1, messages
message = messages[0]
assert "StatementSplitter" in message, message
assert "StatementFactsParser" in message, message
assert "introspection" in message, message

result = first.parse_sql("CREATE TABLE alpha_notice (id INT);")
assert result.success, result.errors
assert len(result.statements) == 1
assert result.tables and result.tables[0].name == "alpha_notice"
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "constructor",
    ["SqlGlotParser", "RegexBasedParser", "RegexParser", "EnhancedRegexParser"],
)
def test_direct_legacy_parser_roots_warn_once_per_process(constructor: str) -> None:
    code = f"""
import warnings
from dblift.core.sql_parser.common.base_parser import RegexBasedParser
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.unified_regex_parser import RegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

construct = {{
    "SqlGlotParser": lambda: SqlGlotParser("snowflake"),
    "RegexBasedParser": lambda: RegexBasedParser("oracle"),
    "RegexParser": lambda: RegexParser(MySqlConfig()),
    "EnhancedRegexParser": lambda: EnhancedRegexParser(MySqlConfig()),
}}["{constructor}"]
with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", DeprecationWarning)
    first = construct()
    construct()
messages = [str(item.message) for item in seen if item.category is DeprecationWarning]
assert len(messages) == 1, messages
assert "{constructor}" in messages[0], messages[0]
assert "StatementSplitter" in messages[0], messages[0]
assert "introspection" in messages[0], messages[0]
assert first.dialect_name
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_nested_and_concurrent_legacy_construction_warns_once_per_process() -> None:
    code = """
import warnings
from concurrent.futures import ThreadPoolExecutor
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.db.provider_registry import ProviderRegistry
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

ProviderRegistry.get_quirks("snowflake")
with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", DeprecationWarning)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: HybridParser("snowflake"), range(16)))
messages = [str(item.message) for item in seen if item.category is DeprecationWarning]
assert len(messages) == 1, messages
assert "HybridParser" in messages[0], messages[0]
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_factory_failure_does_not_hide_following_direct_notice() -> None:
    code = """
import warnings
from dblift.core.exceptions import ParserNotAvailableError
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.db.provider_registry import ProviderRegistry
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

quirks_class = type(ProviderRegistry.get_quirks("snowflake"))
original = quirks_class.parser_class
def broken(self, parser_type):
    raise RuntimeError("plugin construction failed")
quirks_class.parser_class = broken
try:
    with snowflake_facts_off():
        try:
            SqlParserFactory("snowflake").get_parser()
        except ParserNotAvailableError:
            pass
        else:
            raise AssertionError("factory should have failed")
finally:
    quirks_class.parser_class = original

with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", DeprecationWarning)
    parser = SqlGlotParser("snowflake")
assert parser.dialect_name == "snowflake"
assert len([item for item in seen if item.category is DeprecationWarning]) == 1
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_invalid_direct_sqlglot_parser_keeps_facts_refusal_and_notice_state() -> None:
    code = """
import warnings
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

with warnings.catch_warnings():
    warnings.simplefilter("error", DeprecationWarning)
    try:
        SqlGlotParser("postgresql")
    except ValueError as exc:
        assert "StatementFactsParser" in str(exc)
    else:
        raise AssertionError("facts-enabled dialect should refuse this parser")

with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", DeprecationWarning)
    assert SqlGlotParser("snowflake").dialect_name == "snowflake"
assert len([item for item in seen if item.category is DeprecationWarning]) == 1
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_warning_filter_error_does_not_consume_process_once_notice() -> None:
    code = """
import warnings
from dblift.core.sql_parser.hybrid_parser import HybridParser
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

with snowflake_facts_off(), warnings.catch_warnings():
    warnings.simplefilter("error", DeprecationWarning)
    for _ in range(2):
        try:
            HybridParser("snowflake")
        except DeprecationWarning:
            pass
        else:
            raise AssertionError("each attempted notice must raise")

with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", DeprecationWarning)
    HybridParser("snowflake")
    HybridParser("snowflake")
assert len([item for item in seen if item.category is DeprecationWarning]) == 1
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_warning_hook_can_construct_another_legacy_parser_without_deadlock() -> None:
    code = """
import warnings
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.unified_regex_parser import RegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

messages = []
def showwarning(message, category, filename, lineno, file=None, line=None):
    messages.append(str(message))
    if str(message).startswith("HybridParser is deprecated"):
        RegexParser(MySqlConfig())

warnings.showwarning = showwarning
warnings.simplefilter("always", DeprecationWarning)
with snowflake_facts_off():
    HybridParser("snowflake")
assert len(messages) == 2, messages
assert messages[0].startswith("HybridParser is deprecated"), messages
assert messages[1].startswith("RegexParser is deprecated"), messages
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=4
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_direct_sqlglot_scanner_hook_keeps_nested_legacy_construction_silent() -> None:
    code = """
import warnings
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.unified_regex_parser import RegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig
from dblift.db.plugins.snowflake.lexical_parser import SnowflakeLexicalParser
from dblift.db.provider_registry import ProviderRegistry
from tests.support.legacy_snowflake_parsers import snowflake_facts_off

quirks_class = type(ProviderRegistry.get_quirks("snowflake"))
original = quirks_class.parser_class
def eager_scanner(self, parser_type):
    assert parser_type == "regex"
    RegexParser(MySqlConfig())
    return SnowflakeLexicalParser

quirks_class.parser_class = eager_scanner
try:
    with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        parser = SqlGlotParser("snowflake")
        assert parser.split_statements("SELECT 1;") == ["SELECT 1"]
        assert parser.parse_sql("SELECT 1;").success
finally:
    quirks_class.parser_class = original

messages = [str(item.message) for item in seen if item.category is DeprecationWarning]
assert len(messages) == 1, messages
assert messages[0].startswith("SqlGlotParser is deprecated"), messages
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_canonical_snowflake_and_plugin_parser_construction_stay_silent(monkeypatch) -> None:
    from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
    from dblift.core.sql_parser.parser_factory import SqlParserFactory
    from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig
    from dblift.db.plugins.snowflake.lexical_parser import SnowflakeLexicalParser
    from dblift.db.provider_registry import ProviderRegistry

    class CustomParser(EnhancedRegexParser):
        def __init__(self) -> None:
            super().__init__(MySqlConfig())

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with internal_parser_construction():
            factory = SqlParserFactory("snowflake")
        assert type(factory.get_parser()).__name__ == "StatementFactsParser"
        assert isinstance(SnowflakeLexicalParser(), SnowflakeLexicalParser)
        quirks = ProviderRegistry.get_quirks("snowflake")
        monkeypatch.setattr(type(quirks), "parser_class", lambda self, mode: CustomParser)
        with internal_parser_construction():
            factory = SqlParserFactory("snowflake", "regex")
        assert type(factory.get_parser()) is CustomParser


@pytest.mark.parametrize(
    "dialect",
    [
        "sqlite",
        "postgresql",
        "cockroachdb",
        "redshift",
        "mysql",
        "mariadb",
        "oracle",
        "sqlserver",
        "db2",
        "duckdb",
        "snowflake",
    ],
)
def test_canonical_splitter_has_no_deprecation_warning(dialect: str) -> None:
    script = "SELECT 1\nGO\nSELECT 2\nGO\n" if dialect == "sqlserver" else "SELECT 1;\nSELECT 2;\n"
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        splitter = StatementSplitter(dialect)
        records = splitter.split(script)
        strings = splitter.split_statements(script)
    assert strings == execution_strings(records)
    assert len(strings) == 2


def test_canonical_sqlite_migrate_and_info_have_no_deprecation_warning(tmp_path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__alpha_notice.sql").write_text("CREATE TABLE alpha_notice (id INT);")
    engine = create_engine(f"sqlite:///{tmp_path / 'alpha_notice.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            before = client.info()
            migrated = client.migrate()
            after = client.info()
        assert before.success
        assert migrated.success
        assert after.success
    finally:
        client.close()
        engine.dispose()


def test_canonical_paths_and_handwritten_undo_are_silent_in_fresh_process() -> None:
    code = """
import tempfile
import warnings
from pathlib import Path
from sqlalchemy import create_engine, inspect
from dblift.api.client import DBLiftClient
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser._deprecation import internal_parser_construction
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.snowflake.lexical_parser import SnowflakeLexicalParser

with warnings.catch_warnings():
    warnings.simplefilter("error", DeprecationWarning)
    with internal_parser_construction():
        factory = SqlParserFactory("snowflake")
    assert type(factory.get_parser()).__name__ == "StatementFactsParser"
    assert SnowflakeLexicalParser().dialect_name == "snowflake"
    for dialect in (
        "sqlite", "postgresql", "cockroachdb", "redshift", "mysql", "mariadb",
        "oracle", "sqlserver", "db2", "duckdb", "snowflake",
    ):
        script = (
            "SELECT 1\\nGO\\nSELECT 2\\nGO\\n"
            if dialect == "sqlserver"
            else "SELECT 1;\\nSELECT 2;\\n"
        )
        splitter = StatementSplitter(dialect)
        assert len(splitter.split(script)) == 2
        assert len(splitter.split_statements(script)) == 2

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        migrations = root / "migrations"
        migrations.mkdir()
        (migrations / "V1__alpha_notice.sql").write_text("CREATE TABLE alpha_notice (id INT);")
        (migrations / "U1__alpha_notice.sql").write_text("DROP TABLE alpha_notice;")
        engine = create_engine(f"sqlite:///{root / 'app.db'}")
        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
        try:
            assert client.info().success
            assert client.migrate().success
            assert inspect(engine).has_table("alpha_notice")
            assert client.info().success
            assert client.undo().success
            assert not inspect(engine).has_table("alpha_notice")
            assert client.migrate().success
            assert inspect(engine).has_table("alpha_notice")
        finally:
            client.close()
            engine.dispose()
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
