"""The statement-edge corpus: which scripts it holds, and that recording them is deterministic."""

import json
from typing import Dict

import pytest

from tests.support.statement_edge_corpus import (
    DIALECTS,
    EDGE_CHARACTERS,
    corpus_for,
    manifest,
    record_dialect,
    to_canonical_json,
)


def test_the_characters_are_every_whitespace_code_point_plus_two_zero_width_ones() -> None:
    whitespace = [chr(i) for i in range(0x110000) if chr(i).isspace()]
    assert len(whitespace) == 29
    assert EDGE_CHARACTERS == tuple(whitespace) + ("​", "﻿")


def test_the_dialects_are_the_twelve_the_splitter_serves() -> None:
    assert DIALECTS == (
        "postgresql",
        "redshift",
        "cockroachdb",
        "yugabytedb",
        "mysql",
        "mariadb",
        "db2",
        "oracle",
        "sqlserver",
        "snowflake",
        "sqlite",
        "duckdb",
    )


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_script_id_is_unique_and_every_character_reaches_every_position(
    dialect: str,
) -> None:
    scripts = corpus_for(dialect)
    assert len({sid for sid, _ in scripts}) == len(scripts)
    positions = {sid.rsplit("-", 1)[0] for sid, _ in scripts}
    assert {
        "before_terminator",
        "end_of_file",
        "end_of_file_newline",
        "leading_first",
        "leading_later",
        "both_edges",
    } <= positions
    for position in positions:
        assert sum(1 for sid, _ in scripts if sid.startswith(position + "-")) == len(
            EDGE_CHARACTERS
        )


@pytest.mark.parametrize(
    "dialect, position",
    [
        ("postgresql", "psql_combined"),
        ("redshift", "psql_combined"),
        ("cockroachdb", "psql_combined"),
        ("yugabytedb", "psql_combined"),
        ("mysql", "delimiter_block"),
        ("mariadb", "delimiter_block"),
        ("sqlserver", "batch"),
    ],
)
def test_the_dialect_specific_positions_exist_only_where_the_dialect_has_them(
    dialect: str, position: str
) -> None:
    assert position in {sid.rsplit("-", 1)[0] for sid, _ in corpus_for(dialect)}
    for other in ("db2", "oracle", "snowflake", "sqlite", "duckdb"):
        assert position not in {sid.rsplit("-", 1)[0] for sid, _ in corpus_for(other)}


def test_a_recording_holds_the_three_views_of_every_script_and_is_deterministic() -> None:
    first = record_dialect("sqlite", commit="c" * 40)
    second = record_dialect("sqlite", commit="c" * 40)
    assert to_canonical_json(first) == to_canonical_json(second)
    assert first["dialect"] == "sqlite" and first["commit"] == "c" * 40
    scripts: Dict[str, Dict[str, object]] = first["scripts"]
    assert len(scripts) == len(corpus_for("sqlite"))
    one = scripts["end_of_file-U+00A0"]
    assert set(one) == {"script", "execution", "analysis", "records"}
    assert one["execution"] == ["SELECT 1", "DROP TABLE t\xa0"]


def test_the_canonical_json_is_ascii_and_the_manifest_is_its_sha256() -> None:
    recording = record_dialect("sqlite", commit="c" * 40)
    text = to_canonical_json(recording)
    assert text.isascii()
    assert json.loads(text) == recording
    import hashlib

    assert manifest({"sqlite": text})["sqlite"] == hashlib.sha256(text.encode("ascii")).hexdigest()
