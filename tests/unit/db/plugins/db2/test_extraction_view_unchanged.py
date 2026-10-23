"""What Db2 masking, comment stripping and object extraction return does not move with the splitter.

``extraction_golden.json`` holds, per input text, what the readers returned before the shared lexical engine
cut Db2 scripts: the token stream of the nesting-comment tokenizer, the masked and the described statement,
the stripped comments, the extracted objects, the parse and validation results. The expected values are
literals; this module only recomputes them.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import warnings
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.db.plugins.db2.parser.statement_facts import Db2StatementFactsReader
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

GOLDEN = json.loads(Path(__file__).with_name("extraction_golden.json").read_text(encoding="utf-8"))
CASES = GOLDEN["cases"]
IDS = [case["id"] for case in CASES]


def guard(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception as error:  # the refusal is part of the recorded behaviour
        return ["error", type(error).__name__, str(error)]


def ser(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: ser(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, (list, tuple)):
        return [ser(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((ser(item) for item in value), key=repr)
    if isinstance(value, dict):
        return {str(key): ser(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {
        "_class": type(value).__name__,
        **{k: ser(v) for k, v in sorted(vars(value).items()) if not k.startswith("_")},
    }


def masking(text: str) -> Dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {
            "mask": guard(lambda: mask_string_literals(text, "db2")),
            "describe": guard(lambda: describe_statement(text, "db2")),
        }


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_masking_unchanged(case):
    assert masking(case["text"]) == case["masking"]


def test_placeholder_is_code_for_db2():
    parser = facts_parser("db2")
    assert guard(lambda: parser.split("VALUES ${a;b};\n"))[:2] == [
        "error",
        "UnsafeStatementSplitError",
    ]
    assert "code after a ';'" in guard(lambda: parser.split("VALUES ${a;b};\n"))[2]
    assert [r.text for r in parser.split("VALUES ${a}, ${b:c};\n")] == ["VALUES ${a}, ${b:c}"]


def test_statement_facts_reader_for_db2():
    quirks = ProviderRegistry.get_quirks("db2")
    assert quirks.statement_facts_class is Db2StatementFactsReader
    assert quirks.statement_facts("SELECT 1").operation == "SELECT"
