"""The T-SQL tokenizer and the nested-comment extraction view keep their previous outputs.

Statement splitting reads a block comment the way the client does (it ends at the first
``*/``). Object extraction, the comment-only check and literal masking read comments the way
the server does (they nest), through ``SQLServerTokenizer`` and the shared comment scanner.
The outputs below were recorded before the splitter moved to the shared engine; a change in
any of them is a change to what those readers see.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dblift.core.migration.sql.execution_statement import is_comment_only_statement
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser
from dblift.db.plugins.sqlserver.parser.sqlserver_tokenizer import SQLServerTokenizer

GOLDEN = Path(__file__).with_name("extraction_golden.json")


def tokens(script: str) -> Any:
    """The token stream of the T-SQL tokenizer, or the error it raised."""
    try:
        return [
            [t.type.name, t.text, t.pos, t.line, t.col, t.parens_depth]
            for t in SQLServerTokenizer(script).tokenize()
        ]
    except Exception as error:  # noqa: BLE001
        return ["error", type(error).__name__, str(error)]


def stripped(script: str) -> Any:
    """Comment stripping as object extraction reads it."""
    try:
        return SqlServerRegexParser()._strip_comments_preserving_quotes(script)
    except Exception as error:  # noqa: BLE001
        return ["error", type(error).__name__, str(error)]


def comment_only(script: str) -> bool:
    """Whether the script holds nothing but comments, the server's way."""
    return is_comment_only_statement(script, nested_block_comments=True)


def objects(script: str) -> Any:
    """The objects object extraction finds (it reads the comment-stripped text, not the batches)."""
    try:
        found = SqlServerRegexParser().extract_objects(script)
    except Exception as error:  # noqa: BLE001
        return ["error", type(error).__name__, str(error)]
    return [[str(o.object_type), o.name, o.schema] for o in found]


VIEWS = {"tokens": tokens, "stripped": stripped, "comment_only": comment_only, "objects": objects}


@lru_cache(maxsize=None)
def golden() -> Dict[str, Dict[str, Any]]:
    """Recorded outputs: view name -> script -> output."""
    return json.loads(GOLDEN.read_text())  # type: ignore[no-any-return]


def check(view: str, scripts: List[str]) -> None:
    recorded = golden()[view]
    for script in scripts:
        assert script in recorded, f"no recorded {view} for {script!r}"
        assert VIEWS[view](script) == recorded[script], f"{view} of {script!r}"


def test_extraction_comment_view_is_nested():
    assert stripped("/* a /* b */ c */ SELECT 1") == "SELECT 1"
    check(
        "stripped",
        [
            "/* a /* b */ c */ SELECT 1",
            "SELECT /* a /* b */ 'x' */ 1",
            "/* a /* b */ c */",
            "SELECT 1 /* a /* b /* c */ */ */",
            "/* a */ b */ SELECT 1",
        ],
    )


def test_comment_markers_inside_quoted_spans_survive():
    check(
        "stripped",
        [
            "SELECT [a]]--b] FROM t -- c",
            "SELECT 'it''s -- not' -- c",
            "CREATE TABLE [a]]/*b*/] (id INT) /* c */",
        ],
    )


def test_comment_stripping_unchanged():
    check("stripped", list(golden()["stripped"]))


def test_nested_comment_only_statement():
    assert comment_only("/* a /* b */ c */") is True
    assert comment_only("/* a */ b */") is False
    check("comment_only", list(golden()["comment_only"]))


def test_tokenizer_streams_unchanged():
    check("tokens", list(golden()["tokens"]))


def test_object_extraction_unchanged():
    check("objects", list(golden()["objects"]))


def test_every_recorded_view_is_covered_by_a_named_test():
    assert set(golden()) == set(VIEWS)
    assert all(golden()[view] for view in VIEWS)


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_the_recording_holds_the_server_and_client_comment_probes(view):
    probes = ["/* a /* b */ c */ SELECT 1", "SELECT [a]]b]", "SELECT @@ROWCOUNT, @p, #t, ##g"]
    assert all(probe in golden()[view] for probe in probes)
