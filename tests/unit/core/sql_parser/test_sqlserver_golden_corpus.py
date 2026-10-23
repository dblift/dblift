"""A corpus of T-SQL scripts with the exact outputs of the batch scanner this engine replaced.

Each entry records what the public views returned for a script: the batch records (all nine
fields, offsets included), the execution strings, the analysis statements, the masked and
described text of every statement, or the refusal (class and message). The recording was made
from the scanner that preceded the shared lexical engine, except that the four unterminated
lexeme refusals carry the engine's wording. The scripts were chosen by branch coverage of that
scanner, then extended until every rule change tried against the engine was caught here alone.
The texts of validate_sql, parse_sql and extraction are held by the comparison through the public
entry points and by the extraction guard, not by this corpus.
"""

import dataclasses
import itertools
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from tests.support.facts_parser import facts_parser


def recorded(record):
    """The fields the corpus records; ``execution_text`` is pinned by the string comparison."""
    return {k: v for k, v in dataclasses.asdict(record).items() if k != "execution_text"}


CORPUS = Path(__file__).with_name("sqlserver_golden_corpus.json")
CHUNK = 50


def evaluate(script: str) -> Dict[str, Any]:
    """The recorded views of one script, or its refusal."""
    parser = facts_parser("sqlserver")
    try:
        records = parser.split(script)
        strings = parser.split_statements(script)
        analysis = parser.split_for_analysis(script)
        executed = SqlAnalyzer("sqlserver").split_statements_for_analysis(script)
    except Exception as error:  # noqa: BLE001
        return {"error": [type(error).__name__, str(error)]}
    return json.loads(json.dumps(_views(records, strings, analysis, executed)))


def _views(records: Any, strings: Any, analysis: Any, executed: Any) -> Dict[str, Any]:
    texts: List[str] = []
    for record in records:
        texts.append(record.text)
        texts.extend(record.analysis_statements or ())
    return {
        "records": [recorded(r) for r in records],
        "strings": [[text, len(list(run))] for text, run in itertools.groupby(strings)],
        "analysis": analysis,
        "executed": executed,
        "masking": [
            [mask_string_literals(t, "sqlserver"), describe_statement(t, "sqlserver")]
            for t in texts
        ],
    }


@lru_cache(maxsize=None)
def corpus() -> List[Dict[str, Any]]:
    """The recorded entries: ``{"script": ..., "expected": ...}``."""
    return json.loads(CORPUS.read_text())  # type: ignore[no-any-return]


def chunks() -> List[int]:
    return list(range((len(corpus()) + CHUNK - 1) // CHUNK))


@pytest.mark.parametrize("chunk", chunks())
def test_scripts_give_the_recorded_outputs(chunk):
    for entry in corpus()[chunk * CHUNK : (chunk + 1) * CHUNK]:
        assert evaluate(entry["script"]) == entry["expected"], entry["script"]


def test_the_corpus_holds_refusals_and_successes():
    kinds = {"error" in entry["expected"] for entry in corpus()}
    assert kinds == {True, False}
    wordings = [
        entry["expected"]["error"][1]
        for entry in corpus()
        if "error" in entry["expected"] and "unterminated" in entry["expected"]["error"][1]
    ]
    assert len(wordings) >= 4 and all("opened at" in w for w in wordings)
