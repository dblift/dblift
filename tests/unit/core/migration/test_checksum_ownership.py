"""Script checksums are computed by MigrationScriptManager and handed to Migration."""

import ast
from pathlib import Path

import pytest

import dblift
from dblift.core.logger import DbliftLogger
from dblift.core.migration.migration import (
    AppliedMigration,
    Migration,
    MigrationType,
    ResolvedMigration,
    calculate_migration_script_checksum,
)
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager

_PACKAGE_ROOT = Path(dblift.__file__).parent


@pytest.fixture
def manager():
    return MigrationScriptManager(DbliftLogger())


def test_checksums_unchanged_after_move(manager, tmp_path):
    """Literals were captured by running the code before checksum computation moved."""
    (tmp_path / "V1__create.sql").write_text(
        "CREATE TABLE t (id INT);\nINSERT INTO t VALUES (1);\n"
    )
    (tmp_path / "V2__py.py").write_text("def migrate(ctx):\n    ctx.execute('select 1')\n")
    (tmp_path / "R__view.sql").write_text("CREATE OR REPLACE VIEW v AS SELECT 1;\n")

    assert manager.load_migration_script(tmp_path / "V1__create.sql").checksum == 194980085
    assert manager.load_migration_script(tmp_path / "V2__py.py").checksum == -1494958093
    assert manager.load_migration_script(tmp_path / "R__view.sql").checksum == 537954288

    row = AppliedMigration.from_history_row(
        {
            "script": "V3__x.sql",
            "version": "3",
            "description": "x",
            "type": "SQL",
            "checksum": 3272252829,
        }
    )
    assert row.to_migration().checksum == -1022714467

    assert manager.baseline_marker("5", "init").checksum == 1273090183
    assert manager.delete_marker("V9__gone.sql", "9", "gone", "SQL").checksum == 1686304053


def test_baseline_marker_fields(manager):
    marker = manager.baseline_marker("5", "init")

    assert marker.script_name == "B5__init.sql"
    assert marker.content == "-- Baseline migration for version 5"
    assert marker.version == "5"
    assert marker.description == "init"
    assert marker.type == MigrationType.BASELINE
    assert marker.checksum == calculate_migration_script_checksum(marker.content)


def test_delete_marker_fields(manager):
    marker = manager.delete_marker("V9__gone.sql", "9", "gone", "SQL")

    assert marker.script_name == "V9__gone.sql"
    assert marker.content == "-- Delete operation: [DELETE:SQL] gone"
    assert marker.version == "9"
    assert marker.description == "[DELETE:SQL] gone"
    assert marker.type == MigrationType.DELETE
    assert marker.tags == []
    assert marker.checksum == calculate_migration_script_checksum(marker.content)


def test_deprecated_factories_keep_their_output():
    baseline = Migration.create_baseline_migration("-- baseline", "2", "baselined")
    assert (baseline.script_name, baseline.content, baseline.version) == (
        "Base Migration",
        "-- baseline",
        "2",
    )
    assert baseline.type == MigrationType.BASELINE
    assert baseline.checksum == -1914276400

    deleted = Migration.create_delete_migration("V1_2__removed[tag].sql", version="1.2")
    assert deleted.content == "-- Delete operation: Marked as deleted via repair command"
    assert deleted.description == "Marked as deleted via repair command"
    assert deleted.type == MigrationType.DELETE
    assert deleted.checksum == 2015665797


def test_explicit_checksum_is_used_as_is():
    migration = Migration(script_name="V1__a.sql", content="SELECT 1;", checksum=7)

    assert migration.checksum == 7


def test_omitted_checksum_is_computed_from_content():
    migration = Migration(script_name="V1__a.sql", content="SELECT 1;")

    assert migration.checksum == calculate_migration_script_checksum("SELECT 1;")


def test_history_row_checksum_is_passed_through():
    applied = AppliedMigration(
        script_name="V1__a.sql",
        version="1",
        description="a",
        type=MigrationType.SQL,
        checksum=-123,
    )

    assert applied.to_migration().checksum == -123


def test_resolved_checksum_is_passed_through():
    resolved = ResolvedMigration(
        script_name="V1__a.sql",
        content="SELECT 1;",
        version="1",
        description="a",
        type=MigrationType.SQL,
        checksum=-123,
    )

    assert resolved.to_migration().checksum == -123


def test_missing_history_checksum_stays_missing():
    applied = AppliedMigration(
        script_name="V1__a.sql",
        version="1",
        description="a",
        type=MigrationType.SQL,
        checksum=None,
    )

    assert applied.to_migration().checksum is None


def _call_name(node: ast.Call):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class _CallCollector(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.compute_calls = []
        self.migration_calls = []
        self.migration_calls_without_checksum = []

    def _enter(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _enter
    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def visit_Call(self, node):
        name = _call_name(node)
        if name == "calculate_migration_script_checksum":
            self.compute_calls.append(".".join(self.scope))
        elif name == "Migration":
            self.migration_calls.append(node.lineno)
            if not any(kw.arg == "checksum" for kw in node.keywords):
                self.migration_calls_without_checksum.append(node.lineno)
        self.generic_visit(node)


def test_only_script_manager_computes_checksums():
    """Only the script manager and Migration's compat branch compute checksums, and
    every Migration(...) built under dblift/ is handed its checksum."""
    computing = {}
    unchecked = []
    builders = {}
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(_PACKAGE_ROOT).as_posix()
        collector = _CallCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=rel))
        if collector.compute_calls:
            computing[rel] = collector.compute_calls
        if collector.migration_calls:
            builders[rel] = collector.migration_calls
        unchecked += [f"{rel}:{line}" for line in collector.migration_calls_without_checksum]

    assert set(computing) <= {
        "core/migration/migration.py",
        "core/migration/scripting/migration_script_manager.py",
    }
    assert computing.get("core/migration/migration.py", []) == ["Migration.__init__"]
    assert unchecked == []
    assert "core/migration/commands/baseline_command.py" not in builders
    assert "core/migration/commands/repair_command.py" not in builders
