"""Golden corpus: the recorded behaviour of the Oracle scanner this engine replaced.

oracle_golden_corpus.json holds a small set of scripts chosen so that together they
reach every branch the previous scanner (and the comment-masking scanner) reached,
plus the shapes where the behaviour was deliberately corrected. Each entry stores
what the previous scanner returned for it, except where `difference` names the
declared correction (a slash that is statement text, a statement ending in a
comment, a slash followed only by a comment, a refusal naming the true line); there
it stores the corrected value. The entries are compared exactly: records with their
offsets, execution strings, analysis projection, comment masking, SQL*Plus context
and the class and message of every refusal.
"""

import dataclasses
import json
import warnings
from pathlib import Path

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.oracle.parser._comments import strip_comments, strip_sql_comments
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser
from dblift.db.plugins.oracle.parser.sqlplus_context import extract_sqlplus_context

CORPUS = json.loads(Path(__file__).with_name("oracle_golden_corpus.json").read_text())
CHUNK = 50
DECLARED = {"covered", "old_crash", "old_refusal_line"}


def outcome(call):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return call()
    except Exception as exc:  # noqa: BLE001 - the class and message are the contract
        return ["error", type(exc).__name__, str(exc)]


def observed(script):
    parser, analyzer = OracleParser(), SqlAnalyzer("oracle")

    def context():
        found = extract_sqlplus_context(script)
        return {
            "serveroutput": found.serveroutput,
            "prompts": found.prompts,
            "wants_session_output": found.wants_session_output,
        }

    return {
        "records": outcome(lambda: [dataclasses.asdict(r) for r in parser.split(script)]),
        "execution": outcome(lambda: parser.split_statements(script)),
        "analysis": outcome(lambda: parser.split_for_analysis(script)),
        "analyzer": outcome(lambda: analyzer.split_statements(script)),
        "strip_comments": outcome(lambda: strip_comments(script)),
        "strip_sql_comments": outcome(lambda: strip_sql_comments(script)),
        "context": outcome(context),
    }


def test_the_corpus_is_small_and_declares_its_differences():
    assert 20 <= len(CORPUS) <= 400
    assert {e["difference"] for e in CORPUS if e["difference"]} <= DECLARED
    assert len({e["script"] for e in CORPUS}) == len(CORPUS)


@pytest.mark.parametrize("start", range(0, len(CORPUS), CHUNK), ids=lambda s: f"entries-{s}")
def test_entries_are_reproduced_exactly(start):
    for entry in CORPUS[start : start + CHUNK]:
        got = observed(entry["script"])
        for key, value in got.items():
            assert value == entry[key], (entry["script"], key)
