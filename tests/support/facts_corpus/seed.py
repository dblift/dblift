"""Harvest the SQL inputs of the parser tests into ``inputs.jsonl`` (append-only)."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from tests.support.facts_corpus import FAMILIES, read_rows, statement_id
from tests.support.facts_corpus.canonical import dumps

ENTRY_POINTS = re.compile(r"parse_sql\(|extract_objects\(")
MAX_CHARS = 4000
_COMMENTS = re.compile(r"\A(?:\s+|--[^\n]*|/\*.*?\*/)*", re.DOTALL)
_VERB = re.compile(
    r"(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|MERGE|SELECT|WITH|TRUNCATE|GRANT|REVOKE|"
    r"COMMENT|RENAME|SET|USE|BEGIN|DECLARE|CALL|EXEC|EXECUTE|REPLACE|EXPLAIN|VACUUM|ANALYZE|"
    r"COPY|PRAGMA|ATTACH|DETACH|REINDEX|LOCK|COMMIT|ROLLBACK|SAVEPOINT|VALUES|SHOW|DESCRIBE|"
    r"REFRESH|OPTIMIZE|UNDROP|PURGE|FLASHBACK|AUDIT|CLUSTER|DO|LOAD|IMPORT|EXPORT)(?=[\s;]|\Z)",
    re.IGNORECASE,
)
_DIALECT_TOKENS = tuple(FAMILIES) + ("mariadb", "tsql", "postgres", "cockroachdb")
HAND_CORPORA = (
    ("tests/unit/core/sql_parser/duckdb_statement_facts_corpus.json", "cases", "sql", "id"),
    ("tests/unit/core/sql_parser/sqlite_extractor_facts_corpus.json", "cases", "sql", None),
    ("tests/unit/core/sql_parser/legacy_facts_baseline.json", "cases", "script", None),
)


def source_files(root: Path) -> List[str]:
    """List the test files that call ``parse_sql(`` or ``extract_objects(``."""
    found = []
    for path in sorted((root / "tests").rglob("*.py")):
        if path.name.startswith("test_facts_corpus"):
            continue
        if ENTRY_POINTS.search(path.read_text(encoding="utf-8", errors="replace")):
            found.append(path.relative_to(root).as_posix())
    return found


def _is_sql(text: str) -> bool:
    return len(text) < MAX_CHARS and bool(_VERB.match(text, _COMMENTS.match(text).end()))


def _dialects(*texts: str) -> List[str]:
    blob = " ".join(texts).lower()
    return sorted({token for token in _DIALECT_TOKENS if token in blob})


def _constants(tree: ast.AST):
    """Yield string constants that are not pieces of an f-string."""
    fstring_parts = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in fstring_parts:
                yield node


def _enclosing_literals(tree: ast.AST) -> Dict[int, List[str]]:
    """Map each line to the dialect-bearing literals of its enclosing function."""
    out: Dict[int, List[str]] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            literals = [
                n.value
                for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 40
            ]
            for line in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1):
                out[line] = literals
    return out


def _add(
    rows: Dict[str, Dict[str, Any]], sql: str, file: str, line: int, dialects: List[str]
) -> None:
    row = rows.setdefault(statement_id(sql), {"id": statement_id(sql), "sql": sql, "origins": []})
    row["origins"].append({"file": file, "line": line, "dialects": dialects})


def harvest(root: Path) -> List[Dict[str, Any]]:
    """Return one input row per distinct SQL script found in the source files."""
    rows: Dict[str, Dict[str, Any]] = {}
    for rel in source_files(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        literals = _enclosing_literals(tree)
        for node in sorted(_constants(tree), key=lambda n: (n.lineno, n.col_offset)):
            if _is_sql(node.value):
                dialects = _dialects(rel, *literals.get(node.lineno, []))
                _add(rows, node.value, rel, node.lineno, dialects)
    for rel, key, field, ident in HAND_CORPORA:
        path = root / rel
        if not path.exists():
            continue
        for index, case in enumerate(json.loads(path.read_text(encoding="utf-8"))[key]):
            if isinstance(case.get(field), str) and case[field].strip():
                label = f"{rel}#{case[ident] if ident else index}"
                _add(rows, case[field], label, 0, _dialects(rel))
    return [rows[key] for key in sorted(rows)]


def merge_inputs(
    existing: List[Dict[str, Any]], found: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge harvested inputs into the existing ones; nothing is ever removed."""
    merged = {row["id"]: row for row in existing}
    for row in found:
        merged[row["id"]] = row
    return [merged[key] for key in sorted(merged)]


def assert_only_added(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> None:
    """Raise when an input present before is missing after."""
    lost = {row["id"] for row in before} - {row["id"] for row in after}
    if lost:
        raise ValueError(f"inputs are only ever added; removed: {sorted(lost)}")


def split(family: str, sql: str) -> List[str]:
    """Split a script into statements with the family's analysis splitter."""
    from dblift.core.sql_parser.parser_factory import SqlParserFactory

    return list(SqlParserFactory(family).get_parser().split_for_analysis(sql))


def seed(root: Path, inputs_path: Path, sources_path: Path) -> int:
    """Write ``inputs.jsonl`` and ``SOURCES.md``; return the number of inputs."""
    before = read_rows(inputs_path)
    after = merge_inputs(before, harvest(root))
    assert_only_added(before, after)
    inputs_path.write_text("".join(dumps(row) + "\n" for row in after), encoding="utf-8")
    sources = source_files(root)
    lines = [
        "# Sources of the corpus inputs",
        "",
        "Test files calling `parse_sql(` or `extract_objects(`; their SQL string constants",
        "(not f-string parts, under 4000 characters, starting with an SQL verb) are the inputs,",
        "plus the statements of the three hand-written facts corpora listed last.",
        "Regenerate with `python -m tests.support.facts_corpus seed`.",
        "",
    ]
    lines += [f"- `{rel}`" for rel in sources]
    lines += ["", "Hand-written corpora:", ""]
    lines += [f"- `{rel}`" for rel, *_ in HAND_CORPORA if (root / rel).exists()]
    sources_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(after)
