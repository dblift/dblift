"""A corpus of MySQL and MariaDB scripts with the exact outputs of the scanner the shared engine replaced.

Each entry records, for both engines, what the public views returned for a script: the records (all
nine fields, offsets included), the execution strings, the analysis statements, the masked and
described text of every record, or the refusal (class and message). The recording was made from the
scanner that preceded the shared lexical engine, except that the unterminated string, quoted
identifier and block comment refusals, and the refusal of a DELIMITER line without an argument,
carry the engine's wording. The scripts were chosen by branch coverage of the delimiter path of the
engine, plus a named shape for every defect found while the engine was written (see ``name``).
"""

import dataclasses
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Type

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals


def recorded(record):
    """The fields the corpus records; ``execution_text`` is pinned by the string comparison."""
    return {k: v for k, v in dataclasses.asdict(record).items() if k != "execution_text"}


CORPUS = Path(__file__).with_name("mysql_golden_corpus.json")
CHUNK = 50


@lru_cache(maxsize=None)
def entries() -> List[Dict[str, Any]]:
    loaded: List[Dict[str, Any]] = json.loads(CORPUS.read_text())
    return loaded


def test_the_corpus_is_small_and_named() -> None:
    assert 50 <= len(entries()) <= 500, len(entries())
    assert all(e["name"] for e in entries())
    assert len({e["script"] for e in entries()}) == len(entries())
