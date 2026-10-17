"""Splitting a DuckDB script costs a bounded number of operations per character, counted not timed.

The stages are handed counting objects through the attributes production reads: the tokenizer's text and
its five compiled patterns, the assembly's source, and the token list (``len()`` and ``tokens[i]`` only).
A shape grows the script fourfold; the count may grow at most fivefold. The counters are those of the Db2
cost test (``tests/support/splitting_cost.py``).

What no counter sees is caught by a source check over the segment path: open-ended slices of a text and
rebuilds of a string from itself inside loops. Known limits: a rebuild through ``str.replace``, an f-string,
``m = m + text[a:b]`` or a helper call is not seen; an accumulator that is re-joined or re-sliced per cut
(the masked-text accumulator of the Db2 pass has the same blind spot) is not seen either; a rescan that happens once per script (the command word
of a refusal, which raises at once) is linear by construction and not measured.
"""

import ast
import inspect
from pathlib import Path
from typing import List

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser import segment_script as segment_module
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
PATTERNS = ("_seg_word", "_seg_number", "_seg_tag", "_seg_parameter", "_seg_comment")
UNICODE_BLANK = chr(0x3000)


def counted(script: str, refusal: bool = False) -> int:
    """Operations of the lexeme pass and of the assembly, for both views, on ``script``."""
    meter = Meter()
    tokenizer = LexicalTokenizer(script, spec=DUCKDB_SPEC)
    tokenizer.sql = CountingText(tokenizer.sql, meter)
    for name in PATTERNS:
        setattr(tokenizer, name, CountingPattern(getattr(tokenizer, name), meter))
    try:
        tokens = tokenizer.tokenize()
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError):
        assert refusal, "only a refusal shape may end the pass early"
        return meter.count
    for analysis in (False, True):
        SegmentScript(DUCKDB_RULES, CountingText(script, meter), tokenizer.origin).records(
            CountingTokens(tokens, meter), analysis
        )
    return meter.count


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
}


REFUSAL_SHAPES = {"a refusal after many statements"}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_duckdb_splitting_cost_grows_linearly(shape):
    refusal = shape in REFUSAL_SHAPES
    small, large = counted(SHAPES[shape](SMALL), refusal), counted(SHAPES[shape](LARGE), refusal)
    assert small > 0 and large <= BOUND * small, (shape, small, large)


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


SEGMENT_METHODS = {
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
    found += _methods(package / "lexical_engine.py", {"blank_comments"})
    assert len(found) == len(SEGMENT_METHODS) + 2
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
