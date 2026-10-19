"""The scripts whose execution strings must not change, and what the splitter returns for them.

``observe`` is the string API a caller reads (``StatementSplitter.split_statements``) and the
engine's own (``LexicalEngine.split_statements``) for every input.
``tests/unit/core/sql_parser/split_statements_snapshot.json`` holds what they returned before the
strings became a projection of the records; ``python -m tests.support.split_statements_inputs
<file>`` writes a snapshot.
"""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.provider_registry import ProviderRegistry
from tests.support import statement_edge_corpus
from tests.support.splitter_spec.spec_tables import load_conformance_rows
from tests.support.statement_list_parity import CELLS, DIALECTS, PSQL_WIRE

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "docs" / "sql-parsing"
CORPORA = ROOT / "tests" / "unit" / "core" / "sql_parser"
SNAPSHOT = CORPORA / "split_statements_snapshot.json"

Inputs = List[Tuple[str, str]]

# The sets small enough to keep in full; the others (the golden corpora hold two scripts of 100 MB
# of output, the edge corpus is thousands of near-identical scripts) are held by their digest.
KEPT = frozenset({"shapes", "spec_rows", "postgres_family", "snowflake"})

# Statements whose execution string keeps the terminator the record drops.
POSTGRES_EXTRA: Tuple[str, ...] = (
    "SELECT 1;",
    "SELECT 1",
    "SELECT 1;\nSELECT 2;\n",
    "SELECT 1 ;  \nSELECT 2   ;",
    "SELECT 1; -- tail\nSELECT 2; /* c */",
    "SELECT 1\\;SELECT 2;\nSELECT 3;",
    "CREATE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;\nSELECT 2;",
    "DO $do$ BEGIN PERFORM 1; END $do$;",
    "COPY t FROM STDIN;\n1\t2\n\\.\nSELECT 2;",
    "COPY t FROM STDIN;\n1\t2\n\\.\n",
    "SELECT 'a;b';\nSELECT \"c;d\";",
    "SELECT 1;\n\\restrict k\nSELECT 2;\n\\unrestrict k",
    "CREATE TABLE t (a int);\nINSERT INTO t VALUES (1);\n-- end",
    "BEGIN;\nSELECT 1;\nCOMMIT;",
    "SELECT $$a;b$$;\nSELECT 2",
    "﻿SELECT 1;",
    "SELECT 1;\r\nSELECT 2;\r\n",
)
SNOWFLAKE_EXTRA: Tuple[str, ...] = (
    "SELECT 1;",
    "SELECT 1;\nSELECT 2",
    "CREATE PROCEDURE p() RETURNS int LANGUAGE sql AS $$ BEGIN RETURN 1; END; $$;\nSELECT 2;",
    "-- c\nSELECT 1; /* c */ SELECT 2;",
    "SELECT 'a;b';",
)


def _golden() -> Inputs:
    out: Inputs = []
    for name in ("oracle", "db2", "duckdb", "sqlserver", "mysql"):
        entries = json.loads((CORPORA / f"{name}_golden_corpus.json").read_text())
        for entry in entries:
            for dialect in ("mysql", "mariadb") if name == "mysql" else (name,):
                out.append((dialect, entry["script"]))
    return out


def _spec_rows() -> Inputs:
    rows = load_conformance_rows(SPEC_DIR)
    out: Inputs = [(row.dialect, row.script) for row in rows]
    # The PostgreSQL family and Redshift share the PostgreSQL spec.
    out += [(d, row.script) for row in rows if row.dialect == "postgresql" for d in PSQL_WIRE[1:]]
    return out


def input_sets() -> Dict[str, Inputs]:
    """Every named set of ``(dialect, script)`` pairs, in a fixed order."""
    sets: Dict[str, Inputs] = {
        "shapes": [(dialect, shape.script) for dialect, shape in CELLS],
        "golden": _golden(),
        "spec_rows": _spec_rows(),
        "postgres_family": [(d, s) for d in PSQL_WIRE for s in POSTGRES_EXTRA],
        "snowflake": [("snowflake", s) for s in SNOWFLAKE_EXTRA],
    }
    for dialect in DIALECTS:
        sets[f"edge_{dialect}"] = [
            (dialect, script) for _, script in statement_edge_corpus.corpus_for(dialect)
        ]
    return sets


def _outcome(call: Any) -> Any:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return list(call())
    except Exception as exc:  # noqa: BLE001 - the class and message are the contract
        return ["error", type(exc).__name__, str(exc)]


def observe(dialect: str, script: str) -> Dict[str, Any]:
    """The strings the splitter and (where the dialect has a spec) the engine return, and the
    analysis list."""
    seen: Dict[str, Any] = {
        "splitter": _outcome(lambda: StatementSplitter(dialect).split_statements(script))
    }
    seen["analysis"] = _outcome(lambda: SqlAnalyzer(dialect).split_statements_for_analysis(script))
    spec = ProviderRegistry.get_quirks(dialect).lexical_spec()
    if spec is not None:
        seen["engine"] = _outcome(lambda: LexicalEngine(spec).split_statements(script))
    return seen


def record(name: str, inputs: Inputs) -> Dict[str, Any]:
    """Count and digest of everything ``observe`` returns for a set; small sets keep it too."""
    observed = [[dialect, script, observe(dialect, script)] for dialect, script in inputs]
    text = json.dumps(observed, sort_keys=True, ensure_ascii=True)
    return {
        "count": len(observed),
        "sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        "observed": observed if name in KEPT else None,
    }


def snapshot() -> Dict[str, Any]:
    return {name: record(name, inputs) for name, inputs in input_sets().items()}


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(
        json.dumps(snapshot(), sort_keys=True, indent=0, ensure_ascii=True) + "\n", encoding="ascii"
    )
