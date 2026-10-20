"""Count the work of splitting SQL Server scripts through the public lexical engine.

Native-regex helpers are charged for their bounded input spans before receiving plain strings.
A source check rejects repeated whole-source method calls inside the listed helpers; native VM
steps remain outside the counter.
"""

import ast
import inspect
import re
import textwrap
from unittest import mock

import pytest

from dblift.core.sql_parser import batch_commands, batch_division, batch_script
from dblift.core.sql_parser import lexical_engine as engine_module
from dblift.core.sql_parser import lexical_tokenizer as tokenizer_module
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from tests.support.splitting_cost import (
    CountingParserTokens,
    CountingPattern,
    CountingText,
    Meter,
    loop_findings,
)

SMALL, LARGE, BOUND = 100, 400, 5

#: shape name -> script of n units. Each shape stresses one reader.
SHAPES = {
    "one lexeme across many lines": lambda n: "SELECT '" + "line of text\n" * n + "'\nGO\n",
    "many GO batches": lambda n: "SELECT 1\nGO\n" * n,
    "many head lines": lambda n: "SELECT 'x'\n" * n + "/*" + "x" * (200 * n) + "*/\nGO\n",
    "one line of comments, words and semicolons": lambda n: (
        "/**/ " * n + "/**/ SELECT 1 " * n + ";" * (n // 20) + "\r" * n + "x GO x\nGO\n"
    ),
}

IDENTIFIERS = {
    "quoted identifier": lambda n: 'SELECT "' + "line of text\n" * n + '"\nGO\n',
    "bracketed identifier": lambda n: "SELECT [" + "line of text\n" * n + "]\nGO\n",
}


def counted(script: str) -> int:
    meter = Meter()
    original_command = tokenizer_module.read_command
    original_lone_cr = tokenizer_module.find_lone_cr
    original_code = tokenizer_module.refuse_variable_in_code
    original_lexeme = tokenizer_module.refuse_variable_in_lexeme
    original_positions = batch_script.code_positions
    original_divide = batch_script.divide

    def read_command(rules, client_name, source, pos, line, commented):
        newline = source.find("\n", pos)
        meter.add((len(source) if newline < 0 else newline) - pos)
        return original_command(rules, client_name, source._value, pos, line, commented)

    def find_lone_cr(rules, source, start, end):
        meter.add(end - start)
        return original_lone_cr(rules, source._value, start, end)

    def refuse_variable_in_code(rules, client_name, source, start, end, line):
        meter.add(end - start)
        return original_code(rules, client_name, source._value, start, end, line)

    def refuse_variable_in_lexeme(rules, client_name, source, start, end, line):
        meter.add(end - start)
        return original_lexeme(rules, client_name, source._value, start, end, line)

    def code_positions(rules, source, spans, lexeme_starts):
        meter.add(sum(hi - lo for lo, hi in spans))
        return original_positions(rules, source._value, spans, lexeme_starts)

    def divide(rules, source, batch_start, batch_end, spans, positions, text_blanks):
        meter.add(batch_end - batch_start)
        return original_divide(
            rules, source._value, batch_start, batch_end, spans, positions, text_blanks
        )

    def tokenizer(source, *, spec):
        wrapped = LexicalTokenizer(source._value, spec=spec)
        wrapped.sql = CountingText(wrapped.sql, meter)
        wrapped._opener_re = CountingPattern(wrapped._opener_re, meter)
        original_tokenize = wrapped.tokenize
        wrapped.tokenize = lambda: CountingParserTokens(original_tokenize(), meter)
        return wrapped

    with (
        mock.patch.object(engine_module, "LexicalTokenizer", tokenizer),
        mock.patch.object(tokenizer_module, "read_command", read_command),
        mock.patch.object(tokenizer_module, "find_lone_cr", find_lone_cr),
        mock.patch.object(tokenizer_module, "refuse_variable_in_code", refuse_variable_in_code),
        mock.patch.object(tokenizer_module, "refuse_variable_in_lexeme", refuse_variable_in_lexeme),
        mock.patch.object(batch_script, "code_positions", code_positions),
        mock.patch.object(batch_script, "divide", divide),
    ):
        LexicalEngine(SQLSERVER_SPEC).split(CountingText(script, meter))
    return meter.count


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_sqlserver_cost_grows_linearly(shape):
    make = SHAPES[shape]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert small > 0 and large <= BOUND * small, (shape, small, large)


@pytest.mark.parametrize("shape", sorted(IDENTIFIERS))
def test_sqlserver_identifier_cost_grows_linearly(shape):
    make = IDENTIFIERS[shape]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert small > 0 and large <= BOUND * small, (shape, small, large)


def test_sqlserver_cost_detects_a_prefix_rescan_per_comment(monkeypatch):
    original = LexicalEngine._parser

    def rescanning_parser(self, script):
        parser = original(self, script)
        for start, _ in parser._comments:
            script[:start].count("\n")
        return parser

    monkeypatch.setattr(LexicalEngine, "_parser", rescanning_parser)
    make = SHAPES["one line of comments, words and semicolons"]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert large > BOUND * small, (small, large)


def test_sqlserver_cost_detects_a_token_prefix_copy_in_the_parser(monkeypatch):
    original = LexicalEngine._parser

    def rescanning_parser(self, script):
        parser = original(self, script)
        for index in range(len(parser.tokens)):
            parser.tokens[:index]
        return parser

    monkeypatch.setattr(LexicalEngine, "_parser", rescanning_parser)
    make = SHAPES["many GO batches"]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert large > BOUND * small, (small, large)


@pytest.mark.parametrize("pattern", ("ab|ac|d", "a||b", "(?:a+)+|b"))
def test_sqlserver_search_pattern_certificate_refuses_ambiguous_alternatives(pattern):
    CountingPattern(LexicalTokenizer("", spec=SQLSERVER_SPEC)._opener_re, Meter())
    with pytest.raises(AssertionError, match="uncertified regex"):
        CountingPattern(re.compile(pattern), Meter())


def test_sqlserver_source_guard_sees_the_divide_rescan_the_meter_cannot(monkeypatch):
    source = textwrap.dedent(inspect.getsource(batch_division.divide))
    anchor = "    division = rules.division\n"
    assert source.count(anchor) == 1
    mutant = source.replace(
        anchor,
        "    for _ in range(len(source)):\n"
        "        source.count('never-present', batch_start, batch_end)\n" + anchor,
    )
    namespace = dict(vars(batch_division))
    exec(mutant, namespace)  # noqa: S102 - test-owned mutation
    monkeypatch.setattr(batch_script, "divide", namespace["divide"])
    make = SHAPES["one lexeme across many lines"]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert large <= BOUND * small  # the plain-string helper hides this scan from the meter
    assert loop_findings(ast.parse(mutant), plain_source=True) != []


@pytest.mark.parametrize(
    "function",
    (
        LexicalEngine._parser,
        LexicalTokenizer.__init__,
        batch_commands.read_command,
        batch_commands.find_lone_cr,
        batch_commands.refuse_variable_in_code,
        batch_commands.refuse_variable_in_lexeme,
        batch_division.code_positions,
        batch_division._events,
        batch_division.divide,
    ),
    ids=lambda function: function.__qualname__,
)
def test_sqlserver_plain_source_helpers_do_not_rescan_the_source_in_a_loop(function):
    source = textwrap.dedent(inspect.getsource(function))
    assert loop_findings(ast.parse(source), plain_source=True) == [], function.__qualname__
