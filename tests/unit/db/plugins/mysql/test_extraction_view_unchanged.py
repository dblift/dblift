"""Pin what the MySQL readers that are not the splitter produce: tokens, masking, comment stripping, objects.

Statement splitting moves onto the shared lexical engine; masking, object extraction and comment
stripping keep the MySQL tokenizer, and these tests hold their outputs to values recorded before
that move (``extraction_golden.json``, recorded from the code as it was, not from the engine).
"""

import dataclasses
import enum
import hashlib
import json
import re
import warnings
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.core.sql_parser.sqlglot_statement_facts import (
    _MYSQL_QUOTES_AND_COMMENTS,
    read_statement_facts,
)
from dblift.db.plugins.mariadb.regex_parser import MariaDbRegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig
from dblift.db.provider_registry import ProviderRegistry

GOLDEN = json.loads((Path(__file__).parent / "extraction_golden.json").read_text())
STATEMENTS = GOLDEN["statements"]
IDS = [f"s{i}" for i in range(len(STATEMENTS))]
MYSQL = MySqlRegexParser()
MARIADB = MariaDbRegexParser()
#: the wording of an unterminated-lexeme refusal differs between the old scanner and the engine
WORDING = re.compile(
    r"unterminated (?:string literal|string|quoted identifier|block comment) (?:starting|opened) at"
)

warnings.simplefilter("ignore")


def guard(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as error:  # noqa: BLE001 - the class and text are what is recorded
        return ["error", type(error).__name__, WORDING.sub("unterminated LEXEME at", str(error))]


def ser(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: ser(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [ser(x) for x in items]
    if isinstance(value, dict):
        return {str(k): ser(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        public = {k: ser(v) for k, v in sorted(vars(value).items()) if not k.startswith("_")}
        return {"_class": type(value).__name__, **public}
    return repr(value)


def parsed(parser: Any, sql: str, objects: bool) -> Any:
    result = guard(lambda: parser.parse_sql(sql))
    if isinstance(result, list):
        return result
    statements = [
        [s.sql_text, ser(s.statement_type)] + ([ser(s.objects)] if objects else [])
        for s in result.statements
    ]
    errors = [WORDING.sub("unterminated LEXEME at", e) for e in result.errors]
    return {"success": result.success, "errors": errors, "statements": statements}


@pytest.mark.parametrize("case", STATEMENTS, ids=IDS)
def test_tokenizer_streams_unchanged(case: Dict[str, Any]) -> None:
    sql = case["sql"]
    tokens = guard(
        lambda: [
            [t.type.name, t.text, t.pos, t.line, t.col] for t in MySQLTokenizer(sql).tokenize()
        ]
    )
    assert tokens == _normalised(case["tokens"])


@pytest.mark.parametrize("case", STATEMENTS, ids=IDS)
def test_masking_unchanged(case: Dict[str, Any]) -> None:
    sql = case["sql"]
    for dialect in ("mysql", "mariadb"):
        assert guard(lambda: mask_string_literals(sql, dialect)) == case["mask"][dialect]
        assert guard(lambda: describe_statement(sql, dialect)) == case["describe"][dialect]


@pytest.mark.parametrize("case", STATEMENTS, ids=IDS)
def test_object_extraction_unchanged(case: Dict[str, Any]) -> None:
    sql = case["sql"]
    assert (
        guard(lambda: ser(MYSQL.extract_objects(MYSQL._clean_mysql_comments(sql))))
        == case["objects"]
    )
    recorded = dict(case["parse"]) if isinstance(case["parse"], dict) else case["parse"]
    assert parsed(MYSQL, sql, objects=True) == _normalised(recorded)
    recorded_mariadb = case["parse_mariadb"]
    assert parsed(MARIADB, sql, objects=False) == _normalised(recorded_mariadb)


def _normalised(recorded: Any) -> Any:
    if isinstance(recorded, dict):
        errors = [WORDING.sub("unterminated LEXEME at", e) for e in recorded["errors"]]
        return {**recorded, "errors": errors}
    return [WORDING.sub("unterminated LEXEME at", x) if isinstance(x, str) else x for x in recorded]


@pytest.mark.parametrize("case", STATEMENTS, ids=IDS)
def test_comment_stripping_unchanged(case: Dict[str, Any]) -> None:
    sql = case["sql"]
    prefixes, block = MYSQL._comment_markers()
    assert guard(lambda: MYSQL._clean_mysql_comments(sql)) == case["clean"]
    assert guard(lambda: MYSQL._strip_comments_preserving_quotes(sql)) == case["strip"]
    assert (
        guard(
            lambda: strip_comments_preserving_quotes(
                sql,
                line_prefixes=prefixes,
                has_block_comments=block,
                nested_block_comments=MySQLTokenizer.NESTED_BLOCK_COMMENTS,
            )
        )
        == case["generic_strip"]
    )
    assert [m.group() for m in _MYSQL_QUOTES_AND_COMMENTS.finditer(sql)] == case[
        "quotes_and_comments"
    ]
    if "facts" in case:
        assert guard(lambda: ser(read_statement_facts(sql, dialect="mysql"))) == case["facts"]


def test_the_object_patterns_of_the_mysql_config_are_unchanged() -> None:
    config = MySqlConfig()
    patterns = sorted(
        [name, pattern.pattern, pattern.flags]
        for group in (
            config.ddl_patterns,
            config.dml_patterns,
            config.query_patterns,
            config.object_patterns,
        )
        for name, pattern in group.items()
    ) + sorted([p.pattern, p.flags] for p in config.comment_patterns)
    assert hashlib.sha256(json.dumps(patterns).encode()).hexdigest() == GOLDEN["config_digest"]


def test_extraction_comment_reading_is_not_re_pointed() -> None:
    """A parser attribute named lexical_spec would send object extraction through the engine."""
    for parser in (MYSQL, MARIADB):
        assert getattr(parser, "lexical_spec", None) is None


def test_redaction_keeps_the_mysql_tokenizer() -> None:
    """Masking reads the text as the MySQL tokenizer does, which differs from the splitter's reading.

    A literal inside an executable comment stays visible and a doubled quote is one literal; reading
    them as the splitter does would mask the first and cut the second in two.
    """
    recorded = {c["sql"]: c for c in STATEMENTS}
    for sql in ("SELECT 1 # 'x'", "SELECT 1 -- 'x'", "SELECT /*!50000 'x' */ 1"):
        for dialect in ("mysql", "mariadb"):
            assert mask_string_literals(sql, dialect) == recorded[sql]["mask"][dialect]
    assert mask_string_literals("SELECT /*!50000 'x' */ 1", "mysql") == "SELECT /*!50000 'x' */ 1"
    assert mask_string_literals("SELECT 1 /*!50000 'a' */ 'b'", "mysql") == (
        "SELECT 1 /*!50000 'a' */ '?'"
    )
    assert mask_string_literals("SELECT 'a''b'", "mysql") == "SELECT '?'"
    assert mask_string_literals("SELECT 1 --'x'", "mysql") == "SELECT 1 --'x'"
    assert mask_string_literals("SELECT 1 #\n'x'", "mysql") == "SELECT 1 #\n'?'"
    spec = ProviderRegistry.get_quirks("mysql").lexical_spec()
    assert spec is None or not spec.redaction_reads_engine


def test_strict_tokenizer_has_no_effect_for_mysql() -> None:
    for sql, expected in GOLDEN["strict_samples"]:
        assert guard(lambda: MYSQL.split_statements(sql, strict_tokenizer=True)) == expected
        assert MYSQL.split_statements(sql) == MYSQL.split_statements(sql, strict_tokenizer=True)


def test_placeholder_is_code_for_mysql() -> None:
    assert MYSQL.split_statements("SELECT ${a;\nSELECT 2}") == ["SELECT ${a", "SELECT 2}"]
    assert MARIADB.split_statements("SELECT ${a;\nSELECT 2}") == ["SELECT ${a", "SELECT 2}"]
