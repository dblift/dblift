"""Splitting a DuckDB script costs a bounded number of operations per character, counted not timed.

The stages are handed counting objects through the attributes production reads: the tokenizer's text and
its five compiled patterns, the assembly's source, and the token list (``len()`` and ``tokens[i]`` only).
A shape grows the script fourfold; the count may grow at most fivefold. The counters are those of the Db2
cost test (``tests/support/splitting_cost.py``).

What no counter sees is caught by a source check over the segment path: open-ended slices of a text and
rebuilds of a string from itself inside loops. Regex shapes are certified before the native matcher runs;
the native regex VM's steps are not counted. The public-path probe constructs the tokenizer on the plain
script before wrapping its inputs, so tokenizer construction is outside that probe. Known limits: a rebuild through ``str.replace``, an f-string,
``m = m + text[a:b]`` or a helper call is not seen; an accumulator that is re-joined or re-sliced per cut
(the masked-text accumulator of the Db2 pass has the same blind spot) is not seen either; a rescan that happens once per script (the command word
of a refusal, which raises at once) is linear by construction and not measured.
"""

import ast
import inspect
import re
from dataclasses import replace
import textwrap
from pathlib import Path
from typing import List, Optional
from unittest import mock

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser import blank_pass
from dblift.core.sql_parser import segment_script as segment_module
from dblift.core.sql_parser import lexical_engine as engine_module
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.segment_script import SegmentScript
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_RULES, DUCKDB_SPEC
from tests.support.splitting_cost import (
    OUTSIDE_EXEMPT,
    PACKAGE,
    CountingPattern,
    CountingText,
    CountingTokens,
    Meter,
    forbidden,
    import_closure,
)

SMALL, LARGE, BOUND = 100, 400, 5
PATTERNS = (
    "_seg_word",
    "_seg_number",
    "_seg_tag",
    "_seg_parameter",
    "_seg_comment",
    "_seg_word_part",
    "_seg_kept_part",
)
UNICODE_BLANK = chr(0x3000)


class Capped(Meter):
    """A meter that refuses once a script has cost more operations than any bounded pass needs."""

    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def add(self, amount: int) -> None:
        super().add(amount)
        assert self.count <= self.cap, "a pass that does not return"


def counted(script: str, refusal: bool = False, meter: Optional[Meter] = None) -> int:
    """Operations of the lexeme pass and of the assembly on ``script``."""
    meter = Meter() if meter is None else meter
    tokenizer = LexicalTokenizer(script, spec=DUCKDB_SPEC)
    tokenizer.sql = CountingText(tokenizer.sql, meter)
    for name in PATTERNS:
        setattr(tokenizer, name, CountingPattern(getattr(tokenizer, name), meter))
    try:
        tokens = tokenizer.tokenize()
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError):
        assert refusal, "only a refusal shape may end the pass early"
        return meter.count
    original = blank_pass.kept_stretches  # the pass each statement is read through alone
    alone = lambda sql, *args: original(CountingText(sql, meter), *args)  # noqa: E731
    with mock.patch.object(blank_pass, "kept_stretches", alone):
        SegmentScript(
            DUCKDB_RULES,
            CountingText(script, meter),
            tokenizer.origin,
            DUCKDB_SPEC.text_blanks,
            tokenizer.kept,
        ).records(CountingTokens(tokens, meter))
    return meter.count


def public_counted(script: str) -> tuple[int, List]:
    """Enter the public engine with counted source and tokenizer inputs."""
    meter = Meter()
    original = LexicalTokenizer

    def tokenizer(source, *, spec):
        wrapped = original(source._value, spec=spec)
        wrapped.sql = CountingText(wrapped.sql, meter)
        for name in PATTERNS:
            setattr(wrapped, name, CountingPattern(getattr(wrapped, name), meter))
        return wrapped

    with mock.patch.object(engine_module, "LexicalTokenizer", tokenizer):
        records = LexicalEngine(DUCKDB_SPEC).split(CountingText(script, meter))
    return meter.count, records


SHAPES = {
    "statements and comment lines": lambda n: "SELECT 1; -- c\n" * n,
    "one statement of many tokens": lambda n: "SELECT " + "1 + " * n + "1;",
    "escape strings across blanks": lambda n: "E'a\\'' " * n + ";",
    "dot lines while code is pending": lambda n: "SELECT 1\n" + ".5,\n" * n + ";",
    "tagged dollar quotes": lambda n: "$t$;$t$ " * n + ";",
    "unicode blanks": lambda n: ("SELECT" + UNICODE_BLANK + "x;") * n,
    "nested comments": lambda n: "/* a /* b */ ; */\n" * n + "SELECT 1;",
    "lone carriage returns": lambda n: "SELECT 1;\r" * n,
    "one long dollar body": lambda n: "SELECT $$" + "x;" * n + "$$;",
    "parameters": lambda n: "SELECT " + "$1, " * n + "1;",
    "line comments to the end": lambda n: "SELECT 1; " + "-- c " * n,
    "a refusal after many statements": lambda n: "SELECT 1;\n" * n + chr(0),
    "one huge escape string": lambda n: "SELECT E'" + "a\\'" * n + "';",
    "unterminated lexeme": lambda n: "SELECT 1; '" + "a;" * n,
    "blank pass: dollar strings": lambda n: "$t$;$t$ $$;$$ " * n + UNICODE_BLANK,
    "blank pass: quotes and comments": lambda n: "'a' \"b\" -- c\n/* d */ " * n + UNICODE_BLANK,
    "blank pass: failed tags": lambda n: "$a $b1 $_ $\u00e9 " * n + UNICODE_BLANK,
    "blank pass: one long failed tag": lambda n: "$" + "a" * (2 * n) + UNICODE_BLANK,
    "blank pass: long dollar tags": lambda n: "$" + "a" * n + "$;$" + "a" * n + "$" + UNICODE_BLANK,
    "blank pass: words after a stop": lambda n: "SELECT a$$ " + ("x" + UNICODE_BLANK + "y ") * n,
    "blank pass: each statement read alone": lambda n: ("SELECT x" + UNICODE_BLANK + "y;") * n,
    "blank pass: each statement read alone in a kept stretch": lambda n: (
        "SELECT 'x" + UNICODE_BLANK + "y';"
    )
    * n,
    "blank pass: one long statement read alone": lambda n: (
        "SELECT a$$ " + ("x" + UNICODE_BLANK + "y ") * n + ";"
    ),
    "blank pass: words in a kept stretch": lambda n: "'" + ("x" + UNICODE_BLANK + "y;") * n,
}


REFUSAL_SHAPES = {"a refusal after many statements"}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_duckdb_splitting_cost_grows_linearly(shape):
    refusal = shape in REFUSAL_SHAPES
    small, large = counted(SHAPES[shape](SMALL), refusal), counted(SHAPES[shape](LARGE), refusal)
    assert small > 0 and large <= BOUND * small, (shape, small, large)


def test_duckdb_public_split_counts_repeated_record_prefixes(monkeypatch):
    original = LexicalEngine.split

    def rescanning_split(self, source):
        records = original(self, source)
        for record in records:
            source[: record.source_start].count("\n")
        return records

    monkeypatch.setattr(LexicalEngine, "split", rescanning_split)
    shape = SHAPES["statements and comment lines"]
    small, small_records = public_counted(shape(SMALL))
    large, large_records = public_counted(shape(LARGE))
    assert (len(small_records), len(large_records)) == (SMALL, LARGE)
    assert large > BOUND * small, (small, large)


def test_duckdb_public_split_has_bounded_cost_and_ordered_records():
    shape = SHAPES["statements and comment lines"]
    small, first = public_counted(shape(SMALL))
    large, records = public_counted(shape(LARGE))
    assert len(first) == SMALL and len(records) == LARGE
    assert [r.source_start for r in records] == [0, *range(10, 10 + (LARGE - 1) * 15, 15)]
    assert records[0].text == "SELECT 1" and records[-1].text.endswith("SELECT 1")
    assert small > 0 and large <= BOUND * small


def test_the_pattern_counter_charges_the_span_a_search_scans():
    import re

    meter = Meter()
    text = CountingText("abc" * 10 + "x", meter)
    pattern = CountingPattern(re.compile("x"), meter)
    assert pattern.match(text, 3) is None and meter.count == 1
    meter.count = 0
    assert pattern.search(text, 3).start() == 30 and meter.count == 28
    meter.count = 0
    assert CountingPattern(re.compile("zz"), meter).search(text, 3) is None and meter.count == 28


@pytest.mark.parametrize(
    "mutant",
    (r"[\s\S]*?(?=\$)", r"(?![\s\S]*\$\$)", r"(?:[\s\S]*?)?"),
)
def test_duckdb_number_regex_rejects_unbounded_scanning(mutant, monkeypatch):
    assert CountingPattern(re.compile(DUCKDB_RULES.number), Meter()).match(
        CountingText("123", Meter()), 0
    ) is not None
    monkeypatch.setattr(
        "tests.unit.core.sql_parser.test_duckdb_splitting_cost.DUCKDB_SPEC",
        replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, number=mutant)),
    )
    with pytest.raises(AssertionError, match="uncertified regex"):
        public_counted("SELECT 1;")


def test_a_failed_duckdb_tag_probe_charges_the_identifier_run():
    meter = Meter()
    script = "$" + "a" * 100 + "!"
    pattern = CountingPattern(re.compile(DUCKDB_RULES.dollar_tag), meter)
    assert pattern.match(CountingText(script, meter), 0) is None
    assert meter.count >= 101
    meter.count = 0
    assert pattern.match(CountingText(script, meter), 0, 11) is None
    assert 10 <= meter.count <= 12


@pytest.mark.parametrize(
    "mutant",
    (
        r"[A-Z_][A-Z_0-9]{100000000,}",
        r"[A-Z_]*X",
        r"(?:[A-Z_]+)+",
        r"(?=[A-Z_]*X)",
        r"[A-Z_]*",
    ),
)
def test_uncertified_regex_shapes_are_refused(mutant):
    with pytest.raises(AssertionError, match="uncertified regex"):
        CountingPattern(re.compile(mutant), Meter())


SEGMENT_METHODS = {
    "_kept_until",
    "_kept_word",
    "_tokenize_segment_script",
    "_next_segment_token",
    "_at_command_line",
    "_refuse_command_line",
    "_segment_token",
    "_segment_lexeme",
    "_segment_line_comment",
    "_segment_block_comment",
    "_segment_string",
    "_segment_identifier",
    "_segment_dollar",
    "_segment_delimiter",
    "_segment_word",
    "_opens_escape_string",
    "_handle_standard_string",
    "_handle_escape_string",
    "_handle_quoted_identifier",
}


def _methods(path: Path, names: set) -> List[ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]


def test_the_segment_path_never_copies_or_scans_its_inputs():
    package = Path(inspect.getfile(segment_module)).parent
    closure, outside = import_closure(package, ("segment_script",))
    assert f"{PACKAGE}.segment_script" in closure
    assert [
        name
        for name in outside
        if name.rsplit(".", 1)[0] not in OUTSIDE_EXEMPT and name not in OUTSIDE_EXEMPT
    ] == []
    for dotted, path in closure.items():
        assert forbidden(ast.parse(path.read_text(encoding="utf-8"))) == [], dotted
    found = _methods(package / "lexical_tokenizer.py", SEGMENT_METHODS)
    assert {n.name for n in found} == SEGMENT_METHODS
    found += _methods(package / "base_tokenizer.py", {"_read_block_comment"})
    found += _methods(
        package / "blank_pass.py",
        {"kept_stretches", "_dollar", "reads_differently_alone", "_unread"},
    )
    found += _methods(package / "lexical_engine.py", {"blank_comments"})
    found += _methods(package / "segment_script.py", {"_refuse_read_differently_alone"})
    assert len(found) == len(SEGMENT_METHODS) + 7
    for node in found:
        assert forbidden(node) == [], node.name


def test_the_source_check_sees_the_forms_it_exists_for():
    flagged = (
        "while c:\n    x = sql[pos:]",
        "for i in r:\n    y = self.source[i:]",
        "for i in r:\n    y = self.sql[i + 1 :]",
        "for i in r:\n    m = m[:a] + ' ' + m[b:]",
        "for i in r:\n    m += text[a:b]",
        "x = str.find(text, 'a')",
        "x = pattern.search(source, 3)",
        "x = pattern.search(sql[start:])",
        "x = self._comment.match(self.sql[pos + 1 :])",
    )
    for source in flagged:
        assert forbidden(ast.parse(source)) != [], source
    allowed = (
        "for i in r:\n    x = text[a:b]",
        "for i in r:\n    parts.append(text[a:b])\nm = ''.join(parts)",
        "for t in ts:\n    x = line.text[a:]",
        "for i in r:\n    x = ts.lines[i].text[a:]",
        "x = sql[pos:]",
        "for i in r:\n    x = other[a:]",
        "for i in r:\n    n += 1",
        "x = pattern.search(sql[start:end])",
    )
    for source in allowed:
        assert forbidden(ast.parse(source)) == [], source


def test_the_engine_still_blanks_comments_with_one_join():
    source = inspect.getsource(LexicalEngine.blank_comments)
    assert source.count('"".join') == 1


KNOWN_GAP_SHAPES = [
    "SELECT 1 AS a$$, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;",
    "/* don't */ SELECT 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;",
    "/* $$ */ SELECT 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;",
    "SELECT E'a\\'b' AS c, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;",
    "SELECT 1 AS a$$x$$$, 2 AS e\u00a0$t$x; DROP TABLE t; SELECT 3;",
]


@pytest.mark.parametrize("script", KNOWN_GAP_SHAPES)
def test_the_scripts_with_kept_blanks_return_within_the_counted_budget(script):
    assert 0 < counted(script, meter=Capped(50 * len(script))) <= 50 * len(script)


def _mutant(function, anchor, replacement, namespace):
    """``function`` with one line changed, compiled in ``namespace``."""
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(anchor) == 1, anchor  # a mutation that changes nothing proves nothing
    exec(source.replace(anchor, replacement), namespace)  # noqa: S102 - test-owned source
    return namespace[function.__name__]


def test_a_quadratic_pass_is_over_budget(monkeypatch):
    from dblift.core.sql_parser import blank_pass, lexical_tokenizer

    namespace = dict(vars(blank_pass))
    _ = _mutant(  # the slow _dollar lands in ``namespace``, which the quadratic pass below is built in
        blank_pass._dollar,
        "    close = sql.find(tag, end)\n",
        '    sql.find("\\x00")\n    close = sql.find(tag, end)\n',
        namespace,
    )
    shape = SHAPES["blank pass: dollar strings"]
    honest = counted(shape(LARGE))
    assert honest <= BOUND * counted(shape(SMALL))
    quadratic = _mutant(  # exec'd in the namespace that holds the slow _dollar, which it then calls
        blank_pass.kept_stretches,
        "_dollar(sql, pos, rules, stretches)",
        "_dollar(sql, pos, rules, stretches)",
        namespace,
    )
    monkeypatch.setattr(lexical_tokenizer, "kept_stretches", quadratic)
    assert counted(shape(LARGE)) > BOUND * counted(shape(SMALL))


def test_reading_each_statement_alone_over_the_rest_of_the_script_is_over_budget(monkeypatch):
    namespace = dict(vars(blank_pass))
    mutant = _mutant(
        blank_pass.reads_differently_alone, "text = source[lo:hi]", "text = source[lo:]", namespace
    )
    shape = SHAPES["blank pass: each statement read alone"]
    honest = counted(shape(LARGE))
    assert honest <= BOUND * counted(shape(SMALL))
    monkeypatch.setattr(blank_pass, "reads_differently_alone", mutant)
    monkeypatch.setattr(segment_module, "reads_differently_alone", mutant)
    assert counted(shape(LARGE)) > BOUND * counted(shape(SMALL))


def test_the_alone_pass_runs_only_on_statements_holding_a_non_ascii_blank(monkeypatch):
    calls = []
    original = blank_pass.kept_stretches
    monkeypatch.setattr(
        blank_pass, "kept_stretches", lambda *args: calls.append(args[0]) or original(*args)
    )
    script = "SELECT 1; " * 20 + "SELECT x" + UNICODE_BLANK + "y; " + "SELECT 2; " * 20
    LexicalEngine(DUCKDB_SPEC).split(script)
    assert [UNICODE_BLANK in sql for sql in calls] == [True]


def test_a_word_loop_that_does_not_advance_is_refused_by_the_cap(monkeypatch):
    anchor = "while stretch and self.sql[end] in self._seg_wide:"
    mutant = _mutant(
        LexicalTokenizer._kept_word,
        anchor,
        "while stretch and self.sql[end] in self._seg_blanks:",
        dict(vars(inspect.getmodule(LexicalTokenizer))),
    )
    monkeypatch.setattr(LexicalTokenizer, "_kept_word", mutant)
    with pytest.raises(AssertionError, match="does not return"):
        counted(KNOWN_GAP_SHAPES[0], meter=Capped(5000))
