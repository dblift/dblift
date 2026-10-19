"""The records a splitter returns, and the three lists derived from them.

``execution_strings`` is what execution sends (a ``GO n`` batch n times, a policy directive by its
rendered line), ``execution_units`` is each executable record once, ``analysis_sql`` is the
constituents the analysis reads. All three are positive on ``kind``: a record of a kind none of
them names is no statement. ``split_statements`` is the first projection; it is pinned against what
it returned before it became one.
"""

from __future__ import annotations

import functools
import json
import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.statement import (
    Statement,
    analysis_sql,
    executable_records,
    execution_strings,
    execution_units,
)
from tests.support import split_statements_inputs as inputs
from tests.support.statement_list_parity import CELLS

pytestmark = pytest.mark.unit


def _record(text: str = "SELECT 1", **kwargs) -> Statement:
    return Statement(text=text, line=1, terminator=";", **kwargs)


# --- the selector and the projections -----------------------------------------------------------


def test_executable_records_are_the_sql_and_copy_records_that_run():
    sql, copy = _record("a"), _record("b", kind="copy_stdin")
    skipped = [
        _record("c", repeat=0),
        _record("d", kind="directive"),
        _record("e", kind="comment"),  # type: ignore[arg-type]
    ]
    assert executable_records([sql, *skipped, copy]) == [sql, copy]


def test_a_record_that_never_set_execution_text_is_sent_as_its_text():
    records = [_record("a"), _record("b", kind="copy_stdin")]
    assert execution_strings(records) == ["a", "b"]


def test_execution_text_is_what_is_sent_in_place_of_the_text():
    assert execution_strings([_record("a", execution_text="a;")]) == ["a;"]


def test_a_batch_is_sent_as_often_as_it_repeats_and_never_when_it_is_skipped():
    records = [_record("a", repeat=3), _record("b", repeat=0), _record("c")]
    assert execution_strings(records) == ["a", "a", "a", "c"]
    assert execution_units(records) == ["a", "c"]


def test_a_directive_is_sent_only_when_it_has_text_to_send():
    quiet = _record("PROMPT x", kind="directive")
    policy = _record("WHENEVER SQLERROR EXIT", kind="directive", execution_text="WHENEVER ...;")
    assert execution_strings([quiet, policy, _record("a")]) == ["WHENEVER ...;", "a"]
    assert execution_units([quiet, policy, _record("a")]) == ["a"]
    assert analysis_sql([quiet, policy, _record("a")]) == ["a"]


def test_analysis_reads_the_constituents_once_per_unit():
    unit = _record("a; b", repeat=2, analysis_statements=("a", "b"))
    empty = _record("c", analysis_statements=())
    assert analysis_sql([unit, empty, _record("d")]) == ["a", "b", "d"]


@pytest.mark.parametrize("projection", [execution_strings, execution_units, analysis_sql])
def test_a_record_of_a_kind_no_projection_names_is_no_statement(projection):
    unknown = _record("SELECT 99", kind="comment", execution_text="SELECT 99;")  # type: ignore[arg-type]
    assert projection([_record("SELECT 1"), unknown]) == ["SELECT 1"]


# --- split_statements is the first projection ---------------------------------------------------


@functools.lru_cache(maxsize=None)
def _expected_snapshot():
    return json.loads(inputs.SNAPSHOT.read_text(encoding="ascii"))


_SETS = inputs.input_sets()


@pytest.mark.parametrize("name", sorted(_SETS))
def test_the_strings_are_byte_for_byte_what_they_were_before_they_were_a_projection(name):
    """Every input, every dialect, the splitter and the engine; any difference names the input."""
    expected = _expected_snapshot()[name]
    fresh = inputs.record(name, _SETS[name])
    assert fresh["count"] == expected["count"]
    if expected["observed"] is not None:
        differences = [
            (old[0], old[1], old[2], new[2])
            for old, new in zip(expected["observed"], fresh["observed"])
            if old != new
        ]
        assert differences == []
    assert fresh["sha256"] == expected["sha256"]


def test_the_inputs_cover_what_the_projections_are_pinned_on():
    sets = _SETS
    assert {len(sets[n]) > 0 for n in sets} == {True}
    assert {dialect for dialect, _ in sets["golden"]} == {
        "oracle",
        "db2",
        "duckdb",
        "sqlserver",
        "mysql",
        "mariadb",
    }
    assert {dialect for dialect, _ in sets["postgres_family"]} == {
        "postgresql",
        "redshift",
        "cockroachdb",
        "yugabytedb",
    }
    assert sum(len(v) for v in sets.values()) > 6000


@pytest.mark.parametrize(
    "dialect, shape", [pytest.param(d, s, id=f"{d}-{s.name}") for d, s in CELLS]
)
def test_split_statements_is_the_execution_projection_of_split(dialect, shape):
    splitter = StatementSplitter(dialect)
    try:
        records = splitter.split(shape.script)
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as refusal:
        with pytest.raises(type(refusal)) as raised:
            splitter.split_statements(shape.script)
        assert str(raised.value) == str(refusal)
        return
    assert splitter.split_statements(shape.script) == execution_strings(records)


def test_the_go_0_notice_is_logged_once_by_split_statements(caplog):
    script = "SELECT 1\nGO 0\nSELECT 2"
    with caplog.at_level(logging.INFO):
        sent = StatementSplitter("sqlserver").split_statements(script)
    assert sent == ["SELECT 2"]
    notices = [r.getMessage() for r in caplog.records if "GO 0 follows" in r.getMessage()]
    assert notices == ["GO 0 follows the batch starting on line 1: it is not run"]


def test_the_go_0_notice_is_logged_once_by_split(caplog):
    with caplog.at_level(logging.INFO):
        StatementSplitter("sqlserver").split("SELECT 1\nGO 0\nSELECT 2")
    assert len([r for r in caplog.records if "GO 0 follows" in r.getMessage()]) == 1
