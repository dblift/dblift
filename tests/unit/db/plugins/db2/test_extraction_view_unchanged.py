"""What Db2 masking, comment stripping and object extraction return does not move with the splitter.

``extraction_golden.json`` holds, per input text, what the readers returned before the shared lexical engine
cut Db2 scripts: the token stream of the nesting-comment tokenizer, the masked and the described statement,
the stripped comments, the extracted objects, the parse and validation results. The expected values are
literals; this module only recomputes them.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import warnings
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from dblift.core.sql_parser import redaction
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.db.plugins.db2.parser.db2_regex_parser import (
    DB2RegexParser,
    _DB2NestingCommentTokenizer,
)
from dblift.db.provider_registry import ProviderRegistry

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


def stream(text: str) -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tokens = _DB2NestingCommentTokenizer(text).tokenize()
    return [[t.type.name, t.text, t.pos, t.line, t.col] for t in tokens]


def masking(text: str) -> Dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {
            "mask": guard(lambda: mask_string_literals(text, "db2")),
            "describe": guard(lambda: describe_statement(text, "db2")),
        }


def extraction(text: str) -> Dict[str, Any]:
    parser = DB2RegexParser()

    def parse() -> Any:
        result = parser.parse_sql(text)
        return {
            "success": result.success,
            "errors": list(result.errors),
            "statements": [
                [s.sql_text, ser(s.statement_type), ser(s.objects)] for s in result.statements
            ],
        }

    return {
        "clean": guard(lambda: parser._clean_db2_comments(text)),
        "empty": guard(lambda: parser._is_empty_or_comment(text)),
        "strip": guard(
            lambda: strip_comments_preserving_quotes(
                text, line_prefixes=["--"], has_block_comments=True, nested_block_comments=True
            )
        ),
        "utility": guard(lambda: parser.is_utility_statement(text)),
        "objects": guard(lambda: ser(parser.extract_objects(text))),
        "parse": guard(parse),
        "validate": guard(lambda: parser.validate_sql(text)),
    }


def digest_of_patterns() -> str:
    from dblift.db.plugins.db2.parser.parser_config import DB2Config

    config = DB2Config()
    shape = {
        name: sorted(
            (str(key), value.pattern, value.flags) for key, value in getattr(config, name).items()
        )
        for name in ("_ddl_patterns", "_dml_patterns", "_query_patterns", "_object_patterns")
    }
    for name in ("_comment_patterns", "_batch_separators"):
        shape[name] = [
            [getattr(p, "pattern", p), getattr(p, "flags", 0)] for p in getattr(config, name)
        ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_tokenizer_streams_unchanged(case):
    assert guard(lambda: stream(case["text"])) == case["tokens"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_masking_unchanged(case):
    assert masking(case["text"]) == case["masking"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_object_extraction_unchanged(case):
    assert extraction(case["text"]) == case["extraction"]


def test_the_parser_patterns_are_unchanged():
    assert digest_of_patterns() == GOLDEN["pattern_digest"]


def test_extraction_comment_reading_is_not_re_pointed():
    parser = DB2RegexParser()
    assert getattr(parser, "lexical_spec", None) is None
    assert parser.tokenizer_class is _DB2NestingCommentTokenizer
    assert parser.tokenizer_class.NESTED_BLOCK_COMMENTS is True
    assert parser._clean_db2_comments("SELECT 1 /* a /* b */ c */ FROM t") == "SELECT 1  FROM t"


def test_redaction_keeps_the_db2_tokenizer():
    spec = ProviderRegistry.get_quirks("db2").lexical_spec()
    assert spec is None or spec.redaction_reads_engine is False
    assert redaction._dialect_tokenizer("db2") is _DB2NestingCommentTokenizer
    delta = [case for case in CASES if case["id"].startswith("lexeme-")]
    assert len(delta) >= 6
    assert [masking(case["text"]) for case in delta] == [case["masking"] for case in delta]


def test_strict_tokenizer_has_no_effect_for_db2():
    parser = DB2RegexParser()
    for text in (
        "VALUES 'a`b' `c` \\ 1;\nVALUES 2;\n",
        "VALUES 1;\x00\n",
        "CREATE TABLE t (id INT);\n",
    ):
        assert guard(lambda: parser.split_statements(text, strict_tokenizer=True)) == guard(
            lambda: parser.split_statements(text)
        )
        assert guard(lambda: parser.split_for_extraction(text, strict_tokenizer=True)) == guard(
            lambda: parser.split_for_extraction(text)
        )


def test_placeholder_is_code_for_db2():
    parser = DB2RegexParser()
    assert guard(lambda: parser.split("VALUES ${a;b};\n"))[:2] == [
        "error",
        "UnsafeStatementSplitError",
    ]
    assert "code after a ';'" in guard(lambda: parser.split("VALUES ${a;b};\n"))[2]
    assert [r.text for r in parser.split("VALUES ${a}, ${b:c};\n")] == ["VALUES ${a}, ${b:c}"]


def test_statement_facts_have_no_reader_for_db2():
    quirks = ProviderRegistry.get_quirks("db2")
    assert quirks.statement_facts_class is None
    with pytest.raises(NotImplementedError):
        quirks.statement_facts("SELECT 1")
