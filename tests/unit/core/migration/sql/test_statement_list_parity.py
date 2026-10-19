"""Every consumer of a script's statements reads the list the splitter returned.

The splitter decides what a statement is. Migrate, analysis, undo and lint each take that list
through their own code path; a consumer that strips, filters or re-classifies it disagrees with
the others on the pieces that sit at the edge of "a statement" (a lone ``;``, a comment, a
character the dialect does not treat as blank). For every dialect and every shape of script, the
reference is built here from the splitter's records, and each view must equal it, or every view
must refuse with the same exception class.
"""

from __future__ import annotations

from typing import Any, Iterator, List
from unittest.mock import patch

import pytest

from dblift.core.migration.executor import execution_engine
from dblift.core.migration.sql import migration_sql_parser
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.snowflake.statement_parser import SnowflakeStatementParser
from tests.support import statement_list_parity as parity
from tests.support.statement_list_parity import (
    CELLS,
    DIALECTS,
    SHAPES,
    VIEWS,
    Outcome,
    View,
    reference,
)

pytestmark = pytest.mark.unit

EXPECTED_SHAPES = frozenset(
    """empty_term blank_term kept_nbsp_term kept_ideo_term kept_c0_term line_cmt_term
    block_cmt_term nested_cmt_term hash_cmt_term ctrl_hash_term kept_cmt_term execcmt_term
    cmt_then_sql unclosed_block unclosed_only tail_blank tail_nbsp tail_ideo tail_c0
    tail_line_cmt tail_block_cmt tail_hash_cmt tail_nested_cmt only_cmt only_empty only_blank
    batch_only_semi batch_only_cmt slash_cmt_term go_go directive_psql directive_oracle
    directive_delimiter copy_stdin go_n directive_oracle_exit directive_oracle_prompt
    directive_oracle_set exec_oracle body_oracle body_mysql delimiter_two body_postgres""".split()
)


ANALYSIS_ERRORS = ("analysis", "lint_analysis")


def _cells() -> Iterator[Any]:
    for view in VIEWS:
        for dialect, shape in CELLS:
            if dialect in view.dialects:
                yield pytest.param(view, dialect, shape, id=f"{view.name}-{dialect}-{shape.name}")


def _verdict(view: View, dialect: str, shape: parity.Shape) -> str:
    """Empty when the view reads the reference, otherwise how it differs."""
    expected = getattr(reference(dialect, shape), view.compares_with)
    got = Outcome.of(lambda: view.run(dialect, shape.script), shape.exact)
    if expected.raised is not None:
        # ``analyse_script`` never raises: a refusal is its only error and its class is not kept.
        # Every view must carry the splitter's own message (analysis prefixes it).
        class_ok = got.raised is expected.raised or view.name in ANALYSIS_ERRORS
        same = class_ok and bool(expected.message) and expected.message in got.message
        return "" if same else f"expected a refusal {expected.raised.__name__}, got {got}"
    if got == expected:
        return ""
    return f"{view.name} on {shape.script!r}\n  expected {expected.statements}\n  got      {got}"


@pytest.mark.parametrize("view, dialect, shape", list(_cells()))
def test_a_consumer_reads_the_list_the_splitter_returned(view, dialect, shape):
    assert _verdict(view, dialect, shape) == ""


# --- the test itself is checked ----------------------------------------------------------------


def test_every_shape_and_every_dialect_is_covered():
    assert {shape.name for shape in SHAPES} == EXPECTED_SHAPES
    assert len(SHAPES) == len(EXPECTED_SHAPES) == 43
    assert len(DIALECTS) == len(set(DIALECTS)) == 12
    assert {dialect for dialect, _ in CELLS} == set(DIALECTS)
    for view in VIEWS:
        assert {dialect for dialect, _ in CELLS if dialect in view.dialects} == set(view.dialects)


def test_the_shapes_are_the_scripts_the_specs_describe():
    by_name = {shape.name: shape.script for shape in SHAPES}
    assert by_name["kept_nbsp_term"] == "SELECT 1;\n\xa0;\nSELECT 2;"
    assert by_name["tail_c0"] == "SELECT 1;\n\x1c"
    assert by_name["unclosed_only"] == "/* never closed"
    assert by_name["go_n"] == "SELECT 1\nGO 3\nSELECT 2"


def test_a_strip_planted_in_a_consumer_turns_a_kept_character_cell_red():
    def strip_each(analyzer, content, log, **kwargs):
        return [s.strip() for s in real(analyzer, content, log, **kwargs) if s.strip()]

    real = migration_sql_parser.parse_migration_sql
    shape = next(s for s in SHAPES if s.name == "kept_nbsp_term")
    view = next(v for v in VIEWS if v.name == "migrate_classified")
    with patch.object(execution_engine, "parse_migration_sql", strip_each):
        assert _verdict(view, "mysql", shape) != ""


def test_a_comment_filter_planted_in_a_consumer_turns_a_comment_record_cell_red():
    """The splitter returns a comment record (planted); a consumer that skips it disagrees."""
    real_split = LexicalEngine.split
    real_parse = migration_sql_parser.parse_migration_sql

    def with_comment(self, script, *args, **kwargs):
        return [*real_split(self, script, *args, **kwargs), Statement("-- planted", 1, None)]

    def drop_comments(analyzer, content, log, **kwargs):
        return [s for s in real_parse(analyzer, content, log, **kwargs) if not s.startswith("--")]

    shape = next(s for s in SHAPES if s.name == "only_cmt")
    view = next(v for v in VIEWS if v.name == "migrate_classified")
    with patch.object(LexicalEngine, "split", with_comment):
        assert _verdict(view, "postgresql", shape) == ""  # the list is read as it is
        with patch.object(execution_engine, "parse_migration_sql", drop_comments):
            assert _verdict(view, "postgresql", shape) != ""


def test_the_reference_takes_only_statements_from_a_record_it_knows():
    stub = [Statement("SELECT 1", 1, ";"), Statement("-- c", 2, None, kind="comment")]  # type: ignore[arg-type]
    shape = next(s for s in SHAPES if s.name == "only_cmt")
    with patch.object(parity, "records", lambda dialect, script: stub):
        ref = reference("postgresql", shape)
    assert ref.executed.statements == ("SELECT 1",)
    assert ref.analysis.statements == ("SELECT 1",)


STUBBED_DIALECTS = ("postgresql", "sqlite", "sqlserver", "snowflake")


@pytest.mark.parametrize(
    "view, dialect",
    [(v, d) for v in VIEWS for d in STUBBED_DIALECTS if d in v.dialects],
    ids=lambda p: p.name if isinstance(p, View) else p,
)
def test_a_record_of_an_unknown_kind_is_no_statement_to_any_consumer(view, dialect):
    stub: List[Statement] = [
        Statement("SELECT 1", 1, ";"),
        Statement("SELECT 99", 2, ";", kind="comment"),  # type: ignore[arg-type]
    ]
    with (
        patch.object(LexicalEngine, "split", lambda self, script, *a, **k: list(stub)),
        patch.object(SnowflakeStatementParser, "split", lambda self, script: list(stub)),
    ):
        got = Outcome.of(lambda: view.run(dialect, "SELECT 1; SELECT 99;"))
    assert got.statements == ("SELECT 1",), got


def test_the_reference_never_reads_split_statements():
    def refuse(self, script, *args, **kwargs):
        raise AssertionError("the reference read split_statements")

    with patch.object(StatementSplitter, "split_statements", refuse):
        for dialect, shape in CELLS:
            reference(dialect, shape)


def test_a_literal_execution_list_agrees_with_the_records_it_keeps():
    """The literal list differs from the records only by the client text it adds or repeats."""
    for dialect, shape in CELLS:
        if shape.execution is None:
            continue
        kept = [
            parity.normalise(r.text)
            for r in parity.records(dialect, shape.script)
            if r.kind in ("sql", "copy_stdin") and r.repeat > 0
            for _ in range(r.repeat)
        ]
        literal = iter(parity.normalise(sql) for sql in shape.execution)
        assert all(text in literal for text in kept), (dialect, shape.name, kept, shape.execution)


def test_a_dropped_statement_in_the_literal_shapes_is_seen():
    """The shapes with client text are checked against a literal list, not the splitter's own."""
    real = StatementSplitter.split_statements

    def lose_last(self, script, *args, **kwargs):
        out = real(self, script, *args, **kwargs)
        return out[:-1] if any(m in script for m in ("WHENEVER", "COPY", "DELIMITER")) else out

    with patch.object(StatementSplitter, "split_statements", lose_last):
        verdicts = [
            _verdict(view, dialect, shape)
            for view in VIEWS
            if view.name.startswith("migrate_")
            for dialect, shape in CELLS
            if shape.execution is not None and dialect in view.dialects
        ]
    assert any(verdicts)


def test_a_body_that_loses_its_closing_semicolon_turns_its_cell_red():
    real = migration_sql_parser.parse_migration_sql

    def drop_semicolon(analyzer, content, log, **kwargs):
        return [s.rstrip().rstrip(";") for s in real(analyzer, content, log, **kwargs)]

    shape = next(s for s in SHAPES if s.name == "body_oracle")
    view = next(v for v in VIEWS if v.name == "migrate_classified")
    assert _verdict(view, "oracle", shape) == ""
    with patch.object(execution_engine, "parse_migration_sql", drop_semicolon):
        assert _verdict(view, "oracle", shape) != ""


def test_a_refusal_with_another_message_is_not_the_refusal():
    from dblift.core.exceptions import UnsafeStatementSplitError

    def crash(analyzer, content, log, **kwargs):
        raise UnsafeStatementSplitError("something else broke")

    shape = next(s for s in SHAPES if s.name == "unclosed_block")
    view = next(v for v in VIEWS if v.name == "migrate_classified")
    assert _verdict(view, "postgresql", shape) == ""
    with patch.object(execution_engine, "parse_migration_sql", crash):
        assert _verdict(view, "postgresql", shape) != ""


def test_an_analysis_error_that_is_not_the_refusal_is_not_the_refusal():
    from dblift.core.migration.sql.script_analysis import ScriptAnalysis

    shape = next(s for s in SHAPES if s.name == "unclosed_block")
    view = next(v for v in VIEWS if v.name == "analysis")
    assert _verdict(view, "postgresql", shape) == ""
    crashed = ScriptAnalysis(statements=(), cautions=(), errors=("parser crashed: boom",))
    with patch.object(parity, "analyse_script", lambda script, dialect: crashed):
        assert _verdict(view, "postgresql", shape) != ""


def test_every_refusal_has_a_message_to_match():
    for dialect, shape in CELLS:
        refusal = reference(dialect, shape).executed
        assert refusal.raised is None or refusal.message, (dialect, shape.name)
