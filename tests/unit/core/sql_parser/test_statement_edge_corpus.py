"""The statement-edge corpus: which scripts it holds, and that recording them is deterministic."""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from typing import Dict

import pytest

from tests.support import statement_edge_corpus
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
        "comment_end_of_file",
        "comment_then_statement",
        "block_comment_before_terminator",
        "quoted_identifier",
        "two_character_run",
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
        ("postgresql", "psql_combined_leading"),
        ("yugabytedb", "psql_combined_leading"),
        ("mysql", "delimiter_block"),
        ("mariadb", "delimiter_block"),
        ("sqlserver", "batch"),
        ("sqlserver", "batch_division"),
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
    assert manifest({"sqlite": text})["sqlite"] == hashlib.sha256(text.encode("ascii")).hexdigest()


@pytest.mark.parametrize(
    "dialect, quoted",
    [
        ("postgresql", 'DROP TABLE "t"\u00a0;'),
        ("oracle", 'DROP TABLE "t"\u00a0;'),
        ("db2", 'DROP TABLE "t"\u00a0;'),
        ("mysql", "DROP TABLE `t`\u00a0;"),
        ("mariadb", "DROP TABLE `t`\u00a0;"),
        ("sqlserver", "DROP TABLE [t]\u00a0;"),
    ],
)
def test_a_quoted_identifier_uses_the_dialects_own_quote(dialect: str, quoted: str) -> None:
    assert dict(corpus_for(dialect))["quoted_identifier-U+00A0"] == quoted


def test_the_comment_and_run_shapes_are_written_as_documented() -> None:
    scripts = dict(corpus_for("postgresql"))
    assert scripts["comment_end_of_file-U+00A0"] == "SELECT 1 -- c\u00a0"
    assert scripts["comment_then_statement-U+00A0"] == "SELECT 1 -- c\u00a0\nSELECT 2;"
    assert scripts["block_comment_before_terminator-U+00A0"] == "SELECT 1 /* c */\u00a0;"
    assert scripts["two_character_run-U+00A0"] == "DROP TABLE t\u00a0 ;"


def test_a_recording_names_the_sqlglot_version_it_was_made_with() -> None:
    assert record_dialect("sqlite", commit="c" * 40)["sqlglot"] == version("sqlglot")


def test_a_dirty_tree_is_refused_unless_the_commit_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(statement_edge_corpus, "_git", lambda *args: " M dblift/x.py\n")
    with pytest.raises(RuntimeError, match="uncommitted"):
        statement_edge_corpus.write_recordings(tmp_path)
    monkeypatch.setattr(statement_edge_corpus, "DIALECTS", ("sqlite",))
    digests = statement_edge_corpus.write_recordings(tmp_path, commit="d" * 40)
    assert list(digests) == ["sqlite"]
    assert json.loads((tmp_path / "sqlite.json").read_text())["commit"] == "d" * 40


def test_a_clean_tree_is_stamped_with_its_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    answers = {
        ("status", "--porcelain", "--untracked-files=no"): "",
        ("rev-parse", "HEAD"): "e" * 40,
    }
    monkeypatch.setattr(statement_edge_corpus, "_git", lambda *args: answers[args])
    monkeypatch.setattr(statement_edge_corpus, "DIALECTS", ("sqlite",))
    statement_edge_corpus.write_recordings(tmp_path)
    assert json.loads((tmp_path / "sqlite.json").read_text())["commit"] == "e" * 40


@pytest.mark.parametrize("flag", ["--help", "-h", "--bogus"])
def test_a_flag_is_not_a_directory_to_write_into(
    flag: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = []
    monkeypatch.setattr(
        statement_edge_corpus, "write_recordings", lambda directory, **kw: written.append(directory)
    )
    monkeypatch.chdir(tmp_path)
    status = statement_edge_corpus.main(["statement_edge_corpus", flag])
    assert status == (0 if flag in ("--help", "-h") else 2)
    assert written == []
    assert list(tmp_path.iterdir()) == []
