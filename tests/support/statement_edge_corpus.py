"""Scripts that put one character at the edges of a statement, and what the splitters return for them.

``record_dialect`` runs every script of a dialect through the three views a caller reads: the execution
split (what the driver receives), the analysis split, and the scanner's records. The result is plain
JSON data; ``tests.support.statement_edge_comparator`` compares two such recordings.

Run ``python -m tests.support.statement_edge_corpus <directory>`` to write one canonical JSON file per
dialect and a ``MANIFEST.sha256`` listing their digests.
"""

import dataclasses
import hashlib
import json
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.parser_factory import SqlParserFactory

DIALECTS: Tuple[str, ...] = (
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

# Every code point ``str.isspace()`` accepts, then two zero-width characters it does not.
EDGE_CHARACTERS: Tuple[str, ...] = tuple(chr(i) for i in range(0x110000) if chr(i).isspace()) + (
    "​",
    "﻿",
)

PSQL_FAMILY = ("postgresql", "redshift", "cockroachdb", "yugabytedb")
MYSQL_FAMILY = ("mysql", "mariadb")

Scripts = List[Tuple[str, str]]


def character_name(char: str) -> str:
    return f"U+{ord(char):04X}"


def _common(c: str) -> List[Tuple[str, str]]:
    return [
        ("before_terminator", f"DROP TABLE t{c};\nSELECT 1;"),
        ("end_of_file", f"SELECT 1;\nDROP TABLE t{c}"),
        ("end_of_file_newline", f"SELECT 1;\nDROP TABLE t{c}\n"),
        ("leading_first", f"{c}DROP TABLE t;\nSELECT 1;"),
        ("leading_later", f"SELECT 1;\n{c}DROP TABLE t;"),
        ("both_edges", f"SELECT 1;\n{c}DROP TABLE t{c};\nSELECT 2;"),
    ]


def _specific(dialect: str, c: str) -> List[Tuple[str, str]]:
    if dialect in PSQL_FAMILY:
        return [
            ("psql_combined", f"SELECT 1{c}\\;SELECT 2{c};\nSELECT 3;"),
            ("psql_combined_leading", f"SELECT 1\\;{c}SELECT 2;\nSELECT 3;"),
        ]
    if dialect in MYSQL_FAMILY:
        return [
            (
                "delimiter_block",
                f"DELIMITER //\nSELECT 1{c}//\n{c}SELECT 2//\nDELIMITER ;\nSELECT 3{c};",
            )
        ]
    if dialect == "sqlserver":
        return [
            ("batch", f"SELECT 1;\nDROP TABLE t{c}\nGO\n{c}SELECT 2\nGO\nSELECT 3{c}"),
            ("batch_division", f"SELECT 1{c};\n{c}SELECT 2{c};\nGO\n"),
        ]
    return []


def corpus_for(dialect: str) -> Scripts:
    """The ``(script id, script)`` pairs of one dialect, in a fixed order."""
    scripts: Scripts = []
    for char in EDGE_CHARACTERS:
        for position, script in _common(char) + _specific(dialect, char):
            scripts.append((f"{position}-{character_name(char)}", script))
    return scripts


def _outcome(call: Any) -> Any:
    try:
        return call()
    except Exception as error:  # noqa: BLE001 - the class and text are what is recorded
        return {"error": [type(error).__name__, str(error)]}


def _records(dialect: str, script: str) -> Any:
    parser: Any = SqlParserFactory(dialect, parser_type="regex").get_parser()
    return [dataclasses.asdict(r) for r in parser.split(script)]


def record_script(dialect: str, script: str) -> Dict[str, Any]:
    """The three views of one script, as plain JSON data."""
    views = {
        "script": script,
        "execution": _outcome(lambda: StatementSplitter(dialect).split_statements(script)),
        "analysis": _outcome(lambda: SqlAnalyzer(dialect).split_statements_for_analysis(script)),
        "records": _outcome(lambda: _records(dialect, script)),
    }
    loaded: Dict[str, Any] = json.loads(json.dumps(views))
    return loaded


def record_dialect(dialect: str, *, commit: str) -> Dict[str, Any]:
    """Every script of ``dialect`` with its views, stamped with the commit it was recorded from."""
    return {
        "dialect": dialect,
        "commit": commit,
        "scripts": {sid: record_script(dialect, script) for sid, script in corpus_for(dialect)},
    }


def to_canonical_json(recording: Mapping[str, Any]) -> str:
    """The recording as sorted, ASCII-only JSON, so equal recordings are equal bytes."""
    return json.dumps(recording, sort_keys=True, indent=1, ensure_ascii=True) + "\n"


def manifest(texts: Mapping[str, str]) -> Dict[str, str]:
    """The sha256 of each canonical JSON text, by dialect."""
    return {name: hashlib.sha256(text.encode("ascii")).hexdigest() for name, text in texts.items()}


def write_recordings(directory: Path, *, commit: str) -> Dict[str, str]:
    """Write ``<dialect>.json`` per dialect and ``MANIFEST.sha256`` into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    texts = {d: to_canonical_json(record_dialect(d, commit=commit)) for d in DIALECTS}
    for dialect, text in texts.items():
        (directory / f"{dialect}.json").write_text(text, encoding="ascii")
    digests = manifest(texts)
    lines = "".join(f"{digests[d]}  {d}.json\n" for d in DIALECTS)
    (directory / "MANIFEST.sha256").write_text(lines, encoding="ascii")
    return digests


def load_recordings(directory: Path) -> Dict[str, Dict[str, Any]]:
    """The recordings ``write_recordings`` wrote, by dialect."""
    return {d: json.loads((directory / f"{d}.json").read_text(encoding="ascii")) for d in DIALECTS}


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tests.support.statement_edge_corpus <directory>", file=sys.stderr)
        return 2
    warnings.simplefilter("ignore")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    write_recordings(Path(argv[1]), commit=commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
