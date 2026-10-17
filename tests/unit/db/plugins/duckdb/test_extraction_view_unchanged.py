"""DuckDB literal masking, object extraction and statement facts read the text as they did before the
shared engine cut its scripts: the recorded outputs below must not move.

``duckdb_masking_golden.json`` holds each input next to the output recorded from the scanner and
readers this change started from. Masking reads the generic tokenizer (a dollar-quoted string is not
read as a literal: the recorded outputs show it), extraction reads the DuckDB comment tokenizer, and
statement facts read comment-blanked text.
"""

import dataclasses
import enum
import hashlib
import json
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.redaction import (
    _dialect_tokenizer,
    describe_statement,
    mask_string_literals,
)
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import (
    DuckDBFactsParser,
    DuckDBStatementFactsReader,
)
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.duckdb.parser.duckdb_tokenizer import DuckDBTokenizer
from dblift.db.plugins.duckdb.parser.parser_config import DuckDBParserConfig
from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

GOLDEN_PATH = Path(__file__).with_name("duckdb_masking_golden.json")


def golden(section: str) -> Dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="ascii"))[section]


def plain(value: Any, depth: int = 0) -> Any:
    """A JSON-ready copy of a result object."""
    if depth > 6:
        return type(value).__name__
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name), depth + 1) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [plain(x, depth + 1) for x in items]
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {k: plain(v, depth + 1) for k, v in sorted(vars(value).items()) if k[0] != "_"}
    return repr(value)


def guard(call):
    try:
        return call()
    except Exception as error:  # the recorded output includes the failure
        return ["error", type(error).__name__, str(error)]


def observe_masking(sql: str) -> List[str]:
    return [mask_string_literals(sql, "duckdb"), describe_statement(sql, "duckdb")]


def observe_tokens(sql: str) -> Dict[str, Any]:
    def stream(cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return [[t.type.name, t.text, t.pos, t.line, t.col] for t in cls(sql).tokenize()]

    return {
        "base": guard(lambda: stream(BaseTokenizer)),
        "duckdb": guard(lambda: stream(DuckDBTokenizer)),
    }


def observe_extraction(script: str) -> Dict[str, Any]:
    regex, facts = DuckDBRegexParser(), DuckDBFactsParser()

    def parsed(parser):
        result = parser.parse_sql(script, "main")
        return {
            "success": result.success,
            "errors": list(result.errors),
            "statements": plain(result.statements),
        }

    return {
        "regex_objects": guard(lambda: plain(regex.extract_objects(script, "main"))),
        "regex_parse": guard(lambda: parsed(regex)),
        "regex_extraction": guard(lambda: regex.split_for_extraction(script)),
        "facts_objects": guard(lambda: plain(facts.extract_objects(script, "main"))),
        "facts_parse": guard(lambda: parsed(facts)),
        "facts_validate": guard(lambda: facts.validate_sql(script)),
    }


def observe_facts(sql: str) -> Dict[str, Any]:
    quirks = ProviderRegistry.get_quirks("duckdb")
    return {
        "facts": guard(lambda: plain(quirks.statement_facts(sql))),
        "dml": guard(lambda: plain(quirks.analyze_dml(sql))),
        "blank": guard(lambda: quirks.blank_comments(sql)),
    }


def observe_returning(sql: str) -> Any:
    """The statement the provider would send for ``sql`` (None: no rewrite)."""
    sent: List[str] = []

    class Result:
        @staticmethod
        def fetchall():
            return [(1,)]

    def spy(connection, text):
        sent.append(text)
        return Result()

    provider = object.__new__(DuckDBProvider)
    provider._tx = object()  # an open transaction: the rewrite does not commit
    with (
        patch.object(DuckDBProvider, "_ensure_connection", lambda self: "connection"),
        patch.object(SqlAlchemyProvider, "_exec_unbound", staticmethod(spy)),
    ):
        count = provider._try_dml_rowcount_via_returning(sql)
    return [count, sent]


def config_digest() -> str:
    """A digest of every compiled pattern the DuckDB parser configuration holds."""
    items = []
    for name, value in sorted(vars(DuckDBParserConfig()).items()):
        group = list(value.values()) if isinstance(value, dict) else [value]
        for part in group:
            for item in part if isinstance(part, (list, tuple)) else [part]:
                if hasattr(item, "pattern"):
                    items.append([name, item.pattern, item.flags])
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()


def _cases(section: str):
    return [pytest.param(name, case, id=name) for name, case in golden(section).items()]


@pytest.mark.parametrize("name,case", _cases("masking"))
def test_masking_unchanged(name, case):
    assert observe_masking(case["input"]) == case["output"]


@pytest.mark.parametrize("name,case", _cases("masking"))
def test_describe_unchanged(name, case):
    assert observe_masking(case["input"])[1] == case["output"][1]


@pytest.mark.parametrize("name,case", _cases("tokens"))
def test_comment_stripping_tokens_unchanged(name, case):
    assert observe_tokens(case["input"]) == case["output"]


@pytest.mark.parametrize("name,case", _cases("extraction"))
def test_object_extraction_unchanged(name, case):
    assert observe_extraction(case["input"]) == case["output"]


@pytest.mark.parametrize("name,case", _cases("facts"))
def test_facts_unchanged(name, case):
    assert observe_facts(case["input"]) == case["output"]


@pytest.mark.parametrize("name,case", _cases("returning"))
def test_returning_rewrite_decisions_unchanged(name, case):
    assert observe_returning(case["input"]) == case["output"]


def test_parser_config_patterns_unchanged():
    assert config_digest() == golden("config")["digest"]


def test_the_leak_shapes_are_pinned_as_they_mask_today():
    masked = {name: case["output"][0] for name, case in golden("masking").items()}
    assert masked["leak_untagged_dollar"] == "UPDATE t SET pw = $$hunter2$$"
    assert masked["leak_tagged_dollar"] == "UPDATE t SET pw = $t$hunter2$t$"
    assert masked["leak_escape_backslash"] == "UPDATE"
    assert (
        "$k$secret$k$" in masked["leak_plain_and_tagged"]
        and "'?'" in masked["leak_plain_and_tagged"]
    )
    assert "hunter2" not in masked["plain_literal"]


def test_the_facts_reader_does_not_read_the_spec():
    plain_spec = LexicalSpec(name="x")
    changed = LexicalSpec(
        name="y",
        client_name="other",
        nested_comments=True,
        quoted_identifier="`",
        escape_prefixes=("E'",),
        plain_string_escapes=True,
        dollar_quotes=True,
        meta_prefix="\\",
        terminator_respects_parens=True,
        quoted_identifier_escape=False,
        parameter_prefix="@",
        placeholder_open=None,
        leading_bom_is_blank=True,
        silent_unclaimed=True,
        redaction_reads_engine=False,
        string_quote_doubling=False,
    )
    inputs = [case["input"] for case in golden("facts").values()]
    for spec in (None, plain_spec, changed):
        reader = DuckDBStatementFactsReader("duckdb", spec)
        assert [plain(reader.read(sql)) for sql in inputs] == [
            plain(DuckDBStatementFactsReader("duckdb").read(sql)) for sql in inputs
        ]


def test_extraction_comment_reading_is_not_re_pointed():
    assert getattr(DuckDBRegexParser(), "lexical_spec", None) is None
    assert DuckDBRegexParser.tokenizer_class is DuckDBTokenizer


def test_redaction_keeps_the_generic_tokenizer_for_duckdb():
    assert _dialect_tokenizer("duckdb") is BaseTokenizer


def test_the_quirks_spec_does_not_move_masking_to_the_engine():
    spec = ProviderRegistry.get_quirks("duckdb").lexical_spec()
    assert spec is None or spec.redaction_reads_engine is False


def test_the_duckdb_spec_does_not_move_masking_to_the_engine():
    module = pytest.importorskip("dblift.db.plugins.duckdb.parser.lexical_spec")
    assert module.DUCKDB_SPEC.redaction_reads_engine is False


def test_masking_that_read_the_engine_would_be_seen():
    module = pytest.importorskip("dblift.db.plugins.duckdb.parser.lexical_spec")
    quirks = ProviderRegistry.get_quirks("duckdb")
    engine_masking = replace(module.DUCKDB_SPEC, redaction_reads_engine=True)
    with patch.object(type(quirks), "lexical_spec", lambda self: engine_masking):
        moved = {name: observe_masking(case["input"]) for name, case in golden("masking").items()}
    assert moved != {name: case["output"] for name, case in golden("masking").items()}
    assert moved["leak_untagged_dollar"][0] != "UPDATE t SET pw = $$hunter2$$"


def test_strict_tokenizer_has_no_effect_for_duckdb():
    parser = DuckDBFactsParser()
    for script in ("SELECT @ # \\ ` ~ ^ % & | ? !;", "SELECT 1; SELECT $$a;b$$", "SELECT 'x"):
        assert parser.split_statements(script, strict_tokenizer=True) == parser.split_statements(
            script
        )


def test_placeholder_is_code_for_duckdb():
    parser = DuckDBFactsParser()
    assert parser.split_statements("SELECT ${a;b};") == golden("placeholder")["split"]
