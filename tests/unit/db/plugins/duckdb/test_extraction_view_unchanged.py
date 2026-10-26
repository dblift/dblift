"""DuckDB object extraction and statement facts read the text as they did before the shared engine
cut its scripts, and literal masking reads the text through the engine: the recorded outputs below
must not move.

``duckdb_masking_golden.json`` holds each input next to its recorded output. Masking reads the
dialect's lexical specification (a dollar-quoted string and an escape string with a backslash are
literals), extraction reads the DuckDB comment tokenizer, and statement facts read comment-blanked
text.

One recording moved on purpose: ``script_20`` ends in a zero-width space, which the engine reads as a
blank, so the statement no longer carries it and its object is named. ``script_12`` and
``script_13`` lost the statement that was only a comment: a script cut into statements has none.
The three ``COPY ... FROM 'file'`` facts recordings now carry ``copy-from-file`` action.
"""

import dataclasses
import enum
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.redaction import (
    describe_statement,
    mask_string_literals,
)
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBStatementFactsReader
from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider
from tests.support.facts_parser import facts_parser

GOLDEN_PATH = Path(__file__).with_name("duckdb_masking_golden.json")


def golden(section: str) -> Dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="ascii"))[section]


def plain(value: Any, depth: int = 0) -> Any:
    """A JSON-ready copy of a result object."""
    if depth > 6:
        return type(value).__name__
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # ``cte_writes`` was added after the recording and is empty on every recorded input.
        # Quoted identity is verified separately; it was not part of this recording.
        unrecorded = {"name_quoted", "schema_quoted"} if isinstance(value, NamedObject) else ()
        return {
            f.name: plain(getattr(value, f.name), depth + 1)
            for f in dataclasses.fields(value)
            if f.name not in unrecorded
            and (f.name not in {"cte_writes", "renamed_to"} or getattr(value, f.name))
        }
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


def observe_extraction(script: str) -> Dict[str, Any]:
    regex, facts = facts_parser("duckdb"), facts_parser("duckdb")

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


def _cases(section: str):
    return [pytest.param(name, case, id=name) for name, case in golden(section).items()]


@pytest.mark.parametrize("name,case", _cases("masking"))
def test_masking_unchanged(name, case):
    assert observe_masking(case["input"]) == case["output"]


@pytest.mark.parametrize("name,case", _cases("masking"))
def test_describe_unchanged(name, case):
    assert observe_masking(case["input"])[1] == case["output"][1]


@pytest.mark.parametrize("name,case", _cases("facts"))
def test_facts_unchanged(name, case):
    assert observe_facts(case["input"]) == case["output"]


@pytest.mark.parametrize("name,case", _cases("returning"))
def test_returning_rewrite_decisions_unchanged(name, case):
    assert observe_returning(case["input"]) == case["output"]


def test_the_former_leak_shapes_are_masked():
    masked = {name: case["output"][0] for name, case in golden("masking").items()}
    assert masked["leak_untagged_dollar"] == "UPDATE t SET pw = '?'"
    assert masked["leak_tagged_dollar"] == "UPDATE t SET pw = '?'"
    assert masked["leak_escape_backslash"] == "UPDATE t SET pw = E'?'"
    assert masked["leak_plain_and_tagged"] == "INSERT INTO t VALUES ('?', '?')"
    assert "hunter2" not in "".join(masked.values())


def test_the_facts_reader_does_not_read_the_spec():
    plain_spec = LexicalSpec(name="x", text_blanks=" ")
    changed = LexicalSpec(
        name="y",
        text_blanks=" ",
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


def test_masking_reads_the_duckdb_specification():
    module = pytest.importorskip("dblift.db.plugins.duckdb.parser.lexical_spec")
    assert module.DUCKDB_SPEC.redaction_reads_engine is True
    assert ProviderRegistry.get_quirks("duckdb").lexical_spec().redaction_reads_engine is True


def test_placeholder_is_code_for_duckdb():
    parser = facts_parser("duckdb")
    assert parser.split_statements("SELECT ${a;b};") == golden("placeholder")["split"]
