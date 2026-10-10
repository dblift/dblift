"""Execution splitting results captured from the unchanged D1 baseline."""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, get_type_hints

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

_ROWS = json.loads((Path(__file__).parent / "fixtures/splitting.json").read_text())


@pytest.mark.unit
def test_execution_contract_has_the_expected_public_import_and_signatures():
    from dblift.core.migration.sql.execution_contracts import ExecutionSqlParser

    assert get_type_hints(ExecutionSqlParser.get_statement_type) == {
        "sql": str,
        "return": str,
    }
    assert get_type_hints(ExecutionSqlParser.split_statements) == {
        "sql": str,
        "strict_tokenizer": bool,
        "return": List[str],
    }


@pytest.mark.unit
@pytest.mark.parametrize("row", _ROWS)
def test_execution_splitting_stays_identical(row):
    analyzer = SqlAnalyzer(row["dialect"])
    if row["error_type"]:
        with pytest.raises(Exception) as captured:
            analyzer.split_statements(row["sql"], strict_tokenizer=row["strict"])
        assert type(captured.value).__name__ == row["error_type"]
    else:
        assert (
            analyzer.split_statements(row["sql"], strict_tokenizer=row["strict"])
            == row["statements"]
        )


@pytest.mark.unit
def test_execution_contract_module_needs_no_analysis_or_presentation_packages():
    code = """
import importlib.abc
import importlib.util
import sys
from pathlib import Path
from typing import List, get_type_hints

class BlockedPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'rich', 'jinja2', 'sqlglot'}:
            raise AssertionError(f'unexpected import: {fullname}')
        return None

sys.meta_path.insert(0, BlockedPackages())
source = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('execution_contracts', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ExecutionSqlParser = module.ExecutionSqlParser

assert get_type_hints(ExecutionSqlParser.get_statement_type) == {
    'sql': str, 'return': str,
}
assert get_type_hints(ExecutionSqlParser.split_statements) == {
    'sql': str, 'strict_tokenizer': bool, 'return': List[str],
}
assert not {'rich', 'jinja2', 'sqlglot'} & set(sys.modules)
"""
    source = (
        Path(__file__).resolve().parents[3] / "dblift/core/migration/sql/execution_contracts.py"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(source)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
