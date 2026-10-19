"""Parser and analysis coverage for SQL kept in the historical input corpus."""

import json
from pathlib import Path

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script

INPUTS = Path(__file__).resolve().parents[4] / "support" / "facts_corpus" / "inputs.jsonl"
EXPECTED = json.loads(
    Path(__file__).with_name("retained_script_analysis_expected.json").read_text(encoding="utf-8")
)
RETIRED_SUITES = {
    "tests/unit/core/migration/test_undo_script_generator.py",
    "tests/unit/core/migration/scripting/test_undo_script_generator.py",
}


def _cases():
    cases = []
    for line in INPUTS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        origins = [origin for origin in row["origins"] if origin["file"] in RETIRED_SUITES]
        if not origins:
            continue
        dialects = {dialect for origin in origins for dialect in origin["dialects"]}
        for dialect in sorted(dialects or {"postgresql"}):
            cases.append(pytest.param(row["sql"], dialect, id=f"{row['id']}-{dialect}"))
    return cases


@pytest.mark.parametrize("sql,dialect", _cases())
def test_retained_sql_keeps_its_analysis_observation(sql, dialect):
    analysis = analyse_script(sql, dialect)
    from tests.support.facts_corpus import statement_id

    assert {
        "statements": [
            [
                statement.operation,
                statement.kind,
                [[obj.type, obj.name, obj.schema] for obj in statement.objects],
                statement.full_table,
            ]
            for statement in analysis.statements
        ],
        "cautions": [[c.level, c.statement, c.code] for c in analysis.cautions],
        "refused": bool(analysis.errors),
    } == EXPECTED[f"{statement_id(sql)}-{dialect}"]
