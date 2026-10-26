"""Count the work of splitting SQL Server scripts through the public lexical engine.

Native-regex helpers are charged for their bounded input spans before receiving plain strings.
A source check rejects repeated whole-source method calls inside the listed helpers; native VM
steps remain outside the counter.
"""

import ast
import inspect
import re
import shutil
import textwrap
from pathlib import Path
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
    CountingPlainText,
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


def counted(script: str, *, lone_cr=None, variable_in_code=None) -> int:
    meter = Meter()
    original_command = tokenizer_module.read_command
    original_lone_cr = lone_cr or tokenizer_module.find_lone_cr
    original_code = variable_in_code or tokenizer_module.refuse_variable_in_code
    original_lexeme = tokenizer_module.refuse_variable_in_lexeme
    original_positions = batch_script.code_positions
    original_divide = batch_script.divide

    def read_command(rules, client_name, source, pos, line, commented):
        newline = source.find("\n", pos)
        meter.add((len(source) if newline < 0 else newline) - pos)
        return original_command(rules, client_name, source._value, pos, line, commented)

    def find_lone_cr(rules, source, start, end):
        meter.add(end - start)
        return original_lone_cr(rules, CountingPlainText(source._value, meter), start, end)

    def refuse_variable_in_code(rules, client_name, source, start, end, line):
        meter.add(end - start)
        return original_code(
            rules, client_name, CountingPlainText(source._value, meter), start, end, line
        )

    def refuse_variable_in_lexeme(rules, client_name, source, start, end, line):
        meter.add(end - start)
        return original_lexeme(
            rules, client_name, CountingPlainText(source._value, meter), start, end, line
        )

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


@pytest.mark.parametrize("helper", ("lone_cr", "variable_in_code"))
def test_sqlserver_cost_counts_a_plain_helper_rescan(helper):
    if helper == "lone_cr":

        def rescanning(rules, source, start, end):
            source.count("\n")
            return batch_commands.find_lone_cr(rules, source, start, end)

    else:

        def rescanning(rules, client_name, source, start, end, line):
            source.count("\n")
            return batch_commands.refuse_variable_in_code(
                rules, client_name, source, start, end, line
            )

    make = SHAPES["many GO batches"]
    keyword = {helper: rescanning}
    small, large = counted(make(SMALL), **keyword), counted(make(LARGE), **keyword)
    assert large > BOUND * small, (helper, small, large)


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
    (batch_commands.find_lone_cr, batch_commands.refuse_variable_in_code),
    ids=lambda function: function.__name__,
)
def test_sqlserver_cost_detects_a_whole_source_scan_outside_a_loop(function, monkeypatch):
    source = textwrap.dedent(inspect.getsource(function))
    anchor = "    match = _patterns(rules)."
    assert source.count(anchor) == 1
    mutant = source.replace(anchor, "    source.count('\\n')\n    visits.append(1)\n" + anchor, 1)
    namespace = {**vars(batch_commands), "visits": []}
    exec(mutant, namespace)  # noqa: S102 - test-owned mutation
    monkeypatch.setattr(tokenizer_module, function.__name__, namespace[function.__name__])
    make = SHAPES["many GO batches"]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert namespace["visits"]  # the injected scan ran through the public split path
    assert large > BOUND * small
    assert loop_findings(ast.parse(mutant), plain_source=True) != [], (
        function.__name__,
        small,
        large,
    )


@pytest.mark.parametrize("renamed_parameter", (False, True), ids=("alias", "renamed parameter"))
def test_sqlserver_cost_detects_a_whole_source_scan_through_a_local_name(
    renamed_parameter, monkeypatch
):
    source = textwrap.dedent(inspect.getsource(batch_commands.find_lone_cr))
    anchor = "    match = _patterns(rules).lone_cr.search(source, start, end)"
    assert source.count(anchor) == 1
    if renamed_parameter:
        mutant = source.replace("source: str", "payload: str").replace(
            anchor,
            "    payload.count('\\n')\n    visits.append(1)\n"
            "    match = _patterns(rules).lone_cr.search(payload, start, end)",
        )
    else:
        mutant = source.replace(
            anchor, "    text = source\n    text.count('\\n')\n    visits.append(1)\n" + anchor
        )
    namespace = {**vars(batch_commands), "visits": []}
    exec(mutant, namespace)  # noqa: S102 - test-owned mutation
    monkeypatch.setattr(tokenizer_module, "find_lone_cr", namespace["find_lone_cr"])
    make = SHAPES["many GO batches"]
    small, large = counted(make(SMALL)), counted(make(LARGE))
    assert namespace["visits"]
    assert large > BOUND * small
    assert (
        loop_findings(
            ast.parse(mutant),
            plain_source=True,
            source_parameter=1 if renamed_parameter else None,
        )
        != []
    ), (small, large)


def test_sqlserver_source_guard_accepts_renamed_advancing_line_search():
    source = textwrap.dedent(inspect.getsource(batch_division._events))
    renamed = source.replace("cursor", "scan_position").replace("offset", "word_position")
    assert renamed != source
    assert loop_findings(ast.parse(renamed), plain_source=True) == []


@pytest.mark.parametrize(
    "tail",
    (
        "        position = 0\n        break\n",
        "        if False:\n            position = 0\n        position = 0\n        break\n",
    ),
)
def test_sqlserver_source_guard_rejects_an_advancing_search_reset(tail):
    source = (
        "def helper(source, end):\n"
        "    position = 0\n"
        "    while position < end:\n"
        "        hit = source.find('\\n', position, end)\n"
        "        if hit < 0:\n"
        "            position = end\n"
        "        else:\n"
        "            position = hit + 1\n" + tail
    )
    assert loop_findings(ast.parse(source), plain_source=True) != []


def test_sqlserver_source_guard_rejects_dead_advancement():
    source = (
        "def helper(source, end):\n"
        "    position = 0\n"
        "    while position < end:\n"
        "        hit = source.find('\\n', position, end)\n"
        "        if hit < 0:\n"
        "            position = end\n"
        "            break\n"
        "        if False:\n"
        "            position = hit + 1\n"
        "        position = end\n"
    )
    assert loop_findings(ast.parse(source), plain_source=True) != []


def test_sqlserver_source_guard_rejects_while_else_reset():
    source = (
        "def helper(source, ends):\n"
        "    position = 0\n"
        "    for end in ends:\n"
        "        while position < end:\n"
        "            hit = source.find('\\n', position, end)\n"
        "            if hit < 0:\n"
        "                position = end\n"
        "                break\n"
        "            position = hit + 1\n"
        "        else:\n"
        "            position = 0\n"
    )
    assert loop_findings(ast.parse(source), plain_source=True) != []


@pytest.mark.parametrize(
    "scan",
    (
        "source.count('\\n', 0, len(source))",
        "source.count('\\n', 0, offset)",
    ),
)
def test_sqlserver_source_guard_rejects_full_or_prefix_counts_in_a_loop(scan):
    source = f"def helper(source):\n    for offset in range(len(source)):\n        {scan}\n"
    assert loop_findings(ast.parse(source), plain_source=True) != []


def test_sqlserver_source_guard_rejects_explicit_whole_source_bounds_outside_a_loop():
    source = "def helper(source):\n    source.count('\\n', 0, len(source))\n"
    assert loop_findings(ast.parse(source), plain_source=True) != []


def test_sqlserver_source_guard_rejects_native_regex_whole_source_scan():
    source = "def helper(source):\n    re.search('never-present', source)\n"
    assert loop_findings(ast.parse(source), plain_source=True) != []


def test_sqlserver_source_guard_keeps_bounded_native_regex_search():
    source = "def helper(source, start, end):\n    pattern.search(source, start, end)\n"
    assert loop_findings(ast.parse(source), plain_source=True) == []


@pytest.mark.parametrize(
    "slice_text", ("source[:]", "source[:offset]", "source[offset:]", "source[0:len(source)]")
)
def test_sqlserver_source_guard_rejects_unbounded_helper_slices(slice_text):
    source = f"def helper(source, offset):\n    {slice_text}\n"
    assert loop_findings(ast.parse(source), plain_source=True) != []


def _batch_functions(root: Path) -> dict[str, dict[str, ast.AST]]:
    inventory = {}
    for path in root.glob("batch_*.py"):
        functions = {}

        def visit(node, parents=()):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                parents += (node.name,)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[".".join(parents)] = node
            for child in ast.iter_child_nodes(node):
                visit(child, parents)

        visit(ast.parse(path.read_text(encoding="utf-8")))
        inventory[path.name] = functions
    return inventory


def _batch_inventory(root: Path) -> dict[str, set[str]]:
    return {name: set(functions) for name, functions in _batch_functions(root).items()}


# Every batch module and callable needs a cost decision when added or removed.
BATCH_COST_DECISIONS = {
    "batch_cache.py": {
        "RulesCache.__init__": "no script input: rules cache setup",
        "RulesCache.get": "no script input: rules lookup",
    },
    "batch_commands.py": {
        "_patterns": "no script input: rules cache lookup",
        "_compile": "no script input: compile rules patterns",
        "read_command": "plain source: line scan charged by wrapper",
        "_command_message": "no script input: format scalar values",
        "_tail_message": "no script input: format scalar values",
        "find_lone_cr": "plain source: bounded regex charged by wrapper",
        "refuse_lone_cr": "no script input: raise from scalar values",
        "refuse_variable_in_code": "plain source: bounded regex charged by wrapper",
        "refuse_variable_in_lexeme": "plain source: bounded regex charged by wrapper",
        "_variable_message": "no script input: format scalar values",
    },
    "batch_division.py": {
        "code_spans": "counted source: receives CountingText",
        "code_positions": "plain source: bounded spans charged by wrapper",
        "has_code": "no script input: positions only",
        "_events": "plain source: batch span charged by divide wrapper",
        "divide": "plain source: batch span charged by wrapper",
    },
    "batch_script.py": {
        "BatchScript.__init__": "counted source: stores CountingText",
        "BatchScript.split": "counted source: reads CountingText",
        "BatchScript._add": "counted source: reads CountingText",
        "BatchScript._comment_nests": "counted source: reads CountingText",
        "BatchScript._server_has_code": "counted source: reads CountingText",
    },
}
BATCH_INVENTORY = {name: set(decisions) for name, decisions in BATCH_COST_DECISIONS.items()}
BATCH_SOURCE_PARAMETER = {
    "batch_commands.py": {
        "read_command": 2,
        "find_lone_cr": 1,
        "refuse_variable_in_code": 2,
        "refuse_variable_in_lexeme": 2,
    },
    "batch_division.py": {"code_positions": 1, "_events": 1, "divide": 1},
}


def test_sqlserver_batch_helper_inventory_is_explicit():
    root = Path(batch_commands.__file__).parent
    assert _batch_inventory(root) == BATCH_INVENTORY
    plain_source = {
        filename: {
            name for name, decision in decisions.items() if decision.startswith("plain source:")
        }
        for filename, decisions in BATCH_COST_DECISIONS.items()
        if any(decision.startswith("plain source:") for decision in decisions.values())
    }
    assert {
        filename: set(positions) for filename, positions in BATCH_SOURCE_PARAMETER.items()
    } == plain_source


def test_sqlserver_all_classified_plain_source_helpers_are_guarded():
    root = Path(batch_commands.__file__).parent
    assert _plain_source_findings(root) == {}


def _plain_source_findings(root: Path) -> dict[str, list[str]]:
    functions = _batch_functions(root)
    findings = {}
    for filename, decisions in BATCH_COST_DECISIONS.items():
        for name, decision in decisions.items():
            if decision.startswith("plain source:"):
                found = loop_findings(
                    functions[filename][name],
                    plain_source=True,
                    source_parameter=BATCH_SOURCE_PARAMETER[filename][name],
                )
                if found:
                    findings[f"{filename}:{name}"] = found
    return findings


def test_sqlserver_inventory_guard_detects_changed_helper_with_same_name(tmp_path):
    root = Path(batch_commands.__file__).parent
    for name in BATCH_INVENTORY:
        shutil.copyfile(root / name, tmp_path / name)
    path = tmp_path / "batch_commands.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "find_lone_cr"
    )
    function.body.insert(1, ast.parse("source.count('\\n')").body[0])
    path.write_text(ast.unparse(ast.fix_missing_locations(tree)), encoding="utf-8")
    assert _batch_inventory(tmp_path) == BATCH_INVENTORY
    assert _plain_source_findings(tmp_path)["batch_commands.py:find_lone_cr"]


def test_sqlserver_no_script_classification_does_not_read_the_script():
    root = Path(batch_commands.__file__).parent
    functions = _batch_functions(root)
    for filename, decisions in BATCH_COST_DECISIONS.items():
        for name, decision in decisions.items():
            if decision.startswith("no script input:"):
                assert not any(
                    isinstance(node, ast.Name)
                    and node.id in {"source", "sql", "script"}
                    or isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr in {"source", "sql", "script"}
                    for node in ast.walk(functions[filename][name])
                ), name


def test_sqlserver_batch_helper_inventory_rejects_new_helper_and_module(tmp_path):
    root = Path(batch_commands.__file__).parent
    for name in BATCH_INVENTORY:
        shutil.copyfile(root / name, tmp_path / name)
    assert _batch_inventory(tmp_path) == BATCH_INVENTORY
    with (tmp_path / "batch_commands.py").open("a", encoding="utf-8") as source:
        source.write("\ndef new_helper(source):\n    return source.count('\\n')\n")
    assert _batch_inventory(tmp_path) != BATCH_INVENTORY
    shutil.copyfile(root / "batch_commands.py", tmp_path / "batch_commands.py")
    with (tmp_path / "batch_commands.py").open("a", encoding="utf-8") as source:
        source.write(
            "\nclass NewBatch:\n    def helper(self, source):\n        return source.count('\\n')\n"
        )
    assert "NewBatch.helper" in _batch_inventory(tmp_path)["batch_commands.py"]
    assert _batch_inventory(tmp_path) != BATCH_INVENTORY
    shutil.copyfile(root / "batch_commands.py", tmp_path / "batch_commands.py")
    path = tmp_path / "batch_commands.py"
    code = path.read_text(encoding="utf-8")
    anchor = "    match = _patterns(rules).lone_cr.search(source, start, end)"
    assert code.count(anchor) == 1
    code = code.replace(
        anchor, "    def hidden_helper():\n        return source.count('\\n')\n" + anchor
    )
    path.write_text(code, encoding="utf-8")
    assert "find_lone_cr.hidden_helper" in _batch_inventory(tmp_path)["batch_commands.py"]
    assert _batch_inventory(tmp_path) != BATCH_INVENTORY
    shutil.copyfile(root / "batch_commands.py", path)
    (tmp_path / "batch_new.py").write_text(
        "def new_helper(source):\n    return source.count('\\n')\n"
    )
    assert _batch_inventory(tmp_path) != BATCH_INVENTORY


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
