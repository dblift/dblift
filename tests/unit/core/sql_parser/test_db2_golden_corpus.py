"""A corpus of Db2 scripts with the exact outputs of the scanner the shared engine replaced.

Each entry records what the public views returned for a script: the records (all nine fields,
offsets included), the execution strings, the analysis statements, the statements the analyzer
executes, the masked and described text of every record, or the refusal (class and message). The
recording was made from the scanner that preceded the shared lexical engine, except entries 23, 24,
50 and 51 (``form_feed_kept``, ``nbsp_kept``, ``form_feed_first_line``, ``u2028_edge``): a statement
now keeps a character outside space, tab, line feed and carriage return at its edge, so those four
were re-recorded from the splitter that keeps it. The scripts are the shapes that found or guard a
defect while the engine was written (see ``name``), plus the few
scripts that reach every branch of the terminator path.
"""

import dataclasses
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from tests.support.facts_parser import facts_parser


def recorded(record):
    """The fields the corpus records; ``execution_text`` is pinned by the string comparison."""
    return {k: v for k, v in dataclasses.asdict(record).items() if k != "execution_text"}


CORPUS = Path(__file__).with_name("db2_golden_corpus.json")
CHUNK = 50


@lru_cache(maxsize=None)
def entries() -> List[Dict[str, Any]]:
    loaded: List[Dict[str, Any]] = json.loads(CORPUS.read_text(encoding="utf-8"))
    return loaded


def evaluate(script: str) -> Dict[str, Any]:
    """The recorded views of one script, or its refusal."""
    parser = facts_parser("db2")
    try:
        records = parser.split(script)
        views = {
            "records": [recorded(r) for r in records],
            "strings": parser.split_statements(script),
            "analysis": parser.split_for_extraction(script),
            "executed": StatementReader("db2").split_statements_for_analysis(script),
            "masking": [
                [mask_string_literals(r.text, "db2"), describe_statement(r.text, "db2")]
                for r in records
            ],
        }
    except Exception as error:  # noqa: BLE001 - the class and text are what is recorded
        return {"error": [type(error).__name__, str(error)]}
    loaded: Dict[str, Any] = json.loads(json.dumps(views))
    return loaded


def test_the_corpus_is_small_and_named() -> None:
    assert 50 <= len(entries()) <= 500, len(entries())
    assert all(e["name"] for e in entries())
    assert len({e["name"] for e in entries()}) == len(entries())
    assert len({e["script"] for e in entries()}) == len(entries())


@pytest.mark.parametrize("chunk", range(0, len(entries()), CHUNK))
def test_the_engine_gives_the_recorded_views(chunk: int) -> None:
    for entry in entries()[chunk : chunk + CHUNK]:
        assert evaluate(entry["script"]) == entry["views"], entry["name"]


def test_the_engine_s_analysis_view_is_the_recorded_extraction() -> None:
    engine = LexicalEngine(DB2_SPEC)
    for entry in entries():
        if "error" not in entry["views"]:
            assert engine.split_for_analysis(entry["script"]) == entry["views"]["analysis"], entry[
                "name"
            ]
