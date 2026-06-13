#!/usr/bin/env python3
"""Export an OSS-only dblift tree from the enterprise monorepo.

Usage (initial bootstrap — empty destination only):
    python3 scripts/export_oss_repo.py /path/to/dblift-oss

Usage (incremental sync into an existing OSS checkout):
    python3 scripts/export_oss_repo.py /path/to/dblift-oss --update --no-git-init

Dry-run (print actions without writing):
    python3 scripts/export_oss_repo.py /path/to/dblift-oss --update --dry-run

See docs/architecture/oss-enterprise-boundaries.md for tier boundaries.
See docs/architecture/oss-export-reconciliation.md for enterprise↔OSS sync strategy.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REMOVE_DIRS = [
    "core/preflight",
    "core/reports",
    "core/migration/planning",
    "core/sql_validator/linting",
    "core/sql_validator/rule_packs",
    "config/secrets/providers",
    "docs/superpowers",
    "docs/fr",
    # Internal/engineering docs — not part of the public OSS documentation set.
    "docs/adr",
    "docs/architecture",
    "docs/development",
    "docs/quality-roadmap",
    "docs/release",
    "docs/examples/report-demos",
]

REMOVE_FILES = [
    "cli/handlers/diff.py",
    "cli/handlers/export_schema.py",
    "cli/handlers/validate_sql.py",
    "cli/handlers/plan.py",
    "cli/handlers/preflight.py",
    "cli/handlers/snapshot.py",
    "cli/handlers/report_outputs.py",
    "core/migration/commands/diff_command.py",
    "core/migration/commands/export_schema_command.py",
    "core/migration/commands/snapshot_command.py",
    "core/migration/commands/plan_command.py",
    "core/migration/commands/_diff_object_specs.py",
    "core/migration/commands/_diff_output.py",
    "core/migration/commands/_diff_snapshot.py",
    "core/migration/commands/_export_helpers.py",
    "core/migration/commands/_export_metadata.py",
    "core/migration/commands/_managed_object_filter.py",
    "core/migration/commands/_schema_export_types.py",
    "core/ci/formatters.py",
    "core/ci/sql_validation.py",
    "core/licensing/license_manager.py",
    # Dead code removed from OSS during 2026-06 cleanup (keep export aligned).
    "core/migration/sql/sql_insights.py",
    "core/migration/state/migration_classifier.py",
    "core/sql_parser/base_config.py",
    "db/data_access.py",
    "db/plugins/cosmosdb/sdk_translator/_models.py",
    "db/plugins/cosmosdb/sdk_translator/_plan.py",
    "db/plugins/cosmosdb/sdk_translator/_plan_generator.py",
    # Pro/Enterprise feature documentation and internal doc artifacts.
    "docs/user-guide/plan.md",
    "docs/user-guide/preflight.md",
    "docs/stabilization-plan.md",
    "docs/security-incidents.md",
    "docs/index.md.example",
]

TEST_REMOVE_GLOBS = [
    "tests/unit/cli/test_plan_cli.py",
    "tests/unit/cli/test_preflight_cli.py",
    "tests/unit/cli/test_report_outputs.py",
    "tests/unit/cli/test_validate_sql*.py",
    "tests/unit/cli/test_diff_handler_dialect.py",
    "tests/unit/cli/test_show_sql_cli_contract.py",
    "tests/unit/cli/test_main_cli_direct.py",
    "tests/unit/core/reports",
    "tests/unit/core/licensing",
    "tests/unit/core/preflight",
    "tests/unit/core/migration/planning",
    "tests/unit/core/sql_validator/linting",
    "tests/unit/core/sql_validator/rule_packs",
    "tests/unit/core/sql_validator/test_rule_*",
    "tests/unit/core/sql_validator/test_validate_sql*",
    "tests/unit/core/sql_validator/test_performance_analyzer.py",
    "tests/unit/core/sql_validator/test_rule_engine.py",
    "tests/unit/core/ci/test_formatters.py",
    "tests/unit/core/ci/test_findings.py",
    "tests/unit/core/migration/commands/test_diff*",
    "tests/unit/core/migration/commands/test_export*",
    "tests/unit/core/migration/commands/test_snapshot*",
    "tests/unit/core/migration/commands/test_plan*",
    "tests/unit/config/test_secrets/test_integration.py",
    "tests/unit/config/test_secrets/test_providers.py",
    "tests/integration/commands/test_export_schema*",
    "tests/integration/comparison/test_diff*",
    "tests/integration/commands/test_diff*",
    "tests/unit/test_tokenization_coverage.py",
    "tests/unit/test_tokenization_edge_cases.py",
    "tests/unit/db/test_wave_a_quirks_hooks.py",
    "tests/unit/db/test_wave_b_quirks_hooks.py",
    "tests/unit/db/plugins/test_schema_obs03_warnings.py",
    "tests/unit/api/test_plan_api.py",
    "tests/unit/api/test_generate_sql_from_diff*",
    "tests/unit/api/test_export_schema*",
    "tests/unit/api/test_client_operations_export_schema.py",
    "tests/unit/api/test_public_surface_contract.py",
    # Tests for modules dropped from OSS during 2026-06 cleanup.
    "tests/unit/core/migration/sql/test_sql_insights*.py",
    "tests/unit/core/migration/sql/test_sql_analyzer_sql_insights*.py",
    "tests/unit/core/migration/state/test_migration_classifier.py",
    "tests/unit/db/test_data_access.py",
    "tests/unit/config/test_dblift_config_artificial.py",
]

# Paths that must survive ``--update`` even when absent from the enterprise tree.
# LICENSE and README.md are OSS-specific (MIT license, OSS badges); syncing the
# enterprise versions over them would relicense the public repo as proprietary.
# The Dockerfile, SECURITY.md, and user-facing docs below were hand-scrubbed of
# Pro/Enterprise content in the OSS repo and are maintained there (OSS-owned
# divergence) — syncing the enterprise versions over them would re-introduce
# paid-feature advertising that tests/unit/test_oss_public_surface.py forbids.
PROTECTED_RELATIVE_PATHS = frozenset(
    {
        "tests/unit/test_oss_public_surface.py",
        "LICENSE",
        "README.md",
        "Dockerfile",
        "SECURITY.md",
        "docs/index.md",
        "docs/user-guide/commands.md",
        "docs/user-guide/configuration.md",
        "docs/user-guide/getting-started.md",
        "docs/user-guide/best-practices.md",
        "docs/user-guide/troubleshooting.md",
        "docs/operations/recovery/partial-ddl-mysql.md",
    }
)

RSYNC_EXCLUDES = [
    ".git",
    ".worktrees",
    ".claude",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    "*.egg-info",
    ".coverage",
    "htmlcov",
    "coverage.xml",
]

OSS_COMMAND_HANDLERS = '''"""Façade re-exporting OSS CLI command handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from cli.extensions import load_command_handlers, load_terminal_commands
from cli.handlers._shared import (  # noqa: F401
    _MIGRATION_FILENAME_RE,
    CliCommandContext,
    ValidateSqlConfigClient,
    _extract_version_filters,
    _is_migration_sql_file,
    _minimal_result,
    _set_command_completed,
)
from cli.handlers.baseline import _handle_baseline
from cli.handlers.clean import _handle_clean
from cli.handlers.import_flyway import _handle_import_flyway
from cli.handlers.info import _handle_info, _info_result_to_dict  # noqa: F401
from cli.handlers.migrate import _handle_migrate
from cli.handlers.repair import _handle_repair
from cli.handlers.undo import _handle_undo
from cli.handlers.validate import _handle_validate

_COMMAND_HANDLERS: Dict[str, Callable[[CliCommandContext], Tuple[bool, Any]]] = {
    "migrate": _handle_migrate,
    "undo": _handle_undo,
    "clean": _handle_clean,
    "validate": _handle_validate,
    "info": _handle_info,
    "baseline": _handle_baseline,
    "repair": _handle_repair,
    "import-flyway": _handle_import_flyway,
}

_extension_handlers = load_command_handlers()
_builtin_conflicts = set(_extension_handlers) & set(_COMMAND_HANDLERS)
if _builtin_conflicts:
    raise ValueError(
        f"Extension command handler(s) conflict with builtins: {sorted(_builtin_conflicts)}"
    )
_COMMAND_HANDLERS.update(_extension_handlers)
del _extension_handlers, _builtin_conflicts

_AVAILABLE_COMMANDS = list(_COMMAND_HANDLERS.keys()) + ["db"] + list(load_terminal_commands())


def execute_single_command(
    client: Any,
    command: str,
    args: Any,
    log: Any,
    scripts_dir: Optional[Path],
    additional_scripts_dirs: List[Path],
    recursive: bool,
    placeholders: Dict[str, Any],
    dir_recursive_map: Dict[Path, bool],
) -> tuple[bool, Any]:
    """Execute a single command using the DBLift client."""
    handler = _COMMAND_HANDLERS.get(command)
    if handler is None:
        raise ValueError(f"Unknown command: {command}")
    ctx = CliCommandContext(
        client=client,
        args=args,
        log=log,
        scripts_dir=scripts_dir,
        additional_scripts_dirs=additional_scripts_dirs,
        recursive=recursive,
        placeholders=placeholders,
        dir_recursive_map=dir_recursive_map,
    )
    return handler(ctx)


def _validate_migrate_options(cmd_args: Any, parser: Any) -> None:
    """Validate conflicting options for the migrate command."""
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        cmd_args
    )
    if target_version and versions:
        parser.error("Cannot specify both --target-version and --versions")
    if versions and exclude_versions:
        versions_list = [v.strip() for v in versions.split(",")]
        exclude_versions_list = [v.strip() for v in exclude_versions.split(",")]
        if any(v in exclude_versions_list for v in versions_list):
            parser.error("Cannot include and exclude the same version")
    if tags and exclude_tags:
        tags_list = [t.strip() for t in tags.split(",")]
        exclude_tags_list = [t.strip() for t in exclude_tags.split(",")]
        if any(t in exclude_tags_list for t in tags_list):
            parser.error("Cannot include and exclude the same tag")
'''

OSS_EXTENSIONS = '''"""CLI extension loading through installed package entry points."""

from argparse import ArgumentParser
from importlib import metadata
from typing import Any, Callable, Dict

COMMAND_ENTRY_POINT_GROUP = "dblift.commands"
HANDLER_ENTRY_POINT_GROUP = "dblift.command_handlers"
TERMINAL_ENTRY_POINT_GROUP = "dblift.terminal_commands"
CommandExtension = Callable[[ArgumentParser], None]
CommandHandler = Callable[[Any], tuple[bool, Any]]
TerminalCommand = Callable[[Any], int]


def load_command_extensions(parser: ArgumentParser) -> None:
    """Register CLI command parsers provided by installed extensions."""
    for entry_point in metadata.entry_points(group=COMMAND_ENTRY_POINT_GROUP):
        loader = entry_point.load()
        loader(parser)


def load_command_handlers() -> Dict[str, CommandHandler]:
    """Load command handlers provided by installed extensions."""
    handlers: Dict[str, CommandHandler] = {}
    for entry_point in metadata.entry_points(group=HANDLER_ENTRY_POINT_GROUP):
        loader = entry_point.load()
        loaded = loader()
        for command, handler in loaded.items():
            if command in handlers:
                raise ValueError(f"Duplicate command handler extension: {command}")
            handlers[command] = handler
    return handlers


def load_terminal_commands() -> Dict[str, TerminalCommand]:
    """Load terminal commands provided by installed extensions."""
    commands: Dict[str, TerminalCommand] = {}
    for entry_point in metadata.entry_points(group=TERMINAL_ENTRY_POINT_GROUP):
        loader = entry_point.load()
        loaded = loader()
        for command, handler in loaded.items():
            if command in commands:
                raise ValueError(f"Duplicate terminal command extension: {command}")
            commands[command] = handler
    return commands
'''

OSS_LICENSING_GUARD = '''"""No-op license guard for the OSS package."""

from typing import Optional

_cli_token: Optional[str] = None


def _set_token(token: Optional[str]) -> None:
    global _cli_token
    _cli_token = token


def _refresh_state() -> None:
    """OSS builds do not require a license token."""
    return None
'''

OSS_LICENSING_MANAGER = '''"""OSS license manager stub — no key required."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class License:
    customer_name: str = "Open Source"
    customer_email: str = "oss@dblift.local"
    issued_at: datetime = datetime.now(timezone.utc)
    expires_at: Optional[datetime] = None
    license_id: str = "oss"


class LicenseManager:
    """OSS installs run without license validation."""

    def __init__(self, license_path: str = "~/.dblift/license.key", public_key: Optional[str] = None) -> None:
        self._license_path = Path(license_path)

    @property
    def license_path(self) -> Path:
        return self._license_path

    def resolve(self, cli_token: Optional[str] = None) -> License:
        return License()

    def get_info(self, cli_token: Optional[str] = None) -> Dict[str, Any]:
        return {
            "valid": True,
            "tier": "oss",
            "customer_name": "Open Source",
            "customer_email": "oss@dblift.local",
            "license_id": "oss",
            "expires_at": None,
            "days_remaining": None,
        }

    def validate(self, token: str) -> License:
        return License()
'''

OSS_SECRETS_INIT = '''"""OSS secrets: env-var resolution only; external vaults ship in dblift-enterprise."""

from config.secrets._provider_base import AbstractSecretsProvider, SecretsResolutionError
from config.secrets._registry import register_provider
from config.secrets._resolver import clear_cache, resolve_secret_refs
from config.secrets._secrets_config import SecretsConfig

__all__ = [
    "resolve_secret_refs",
    "clear_cache",
    "SecretsResolutionError",
    "SecretsConfig",
    "AbstractSecretsProvider",
    "register_provider",
]
'''


def _rsync(source: Path, dest: Path, *, update: bool = False, dry_run: bool = False) -> None:
    """Copy enterprise tree into *dest*.

    When *update* is True, ``--delete`` removes destination files that no longer
    exist in the filtered source tree, except :data:`PROTECTED_RELATIVE_PATHS`.
    """
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a"]
    if dry_run:
        cmd.append("--dry-run")
    if update:
        cmd.append("--delete")
        for rel in sorted(PROTECTED_RELATIVE_PATHS):
            cmd.extend(["--exclude", rel])
    for item in RSYNC_EXCLUDES:
        cmd.extend(["--exclude", item])
    cmd.extend([f"{source}/", f"{dest}/"])
    subprocess.run(cmd, check=True)


def _remove_paths(base: Path) -> None:
    for rel in REMOVE_DIRS:
        path = base / rel
        if path.exists():
            shutil.rmtree(path)
    for rel in REMOVE_FILES:
        path = base / rel
        if path.exists():
            path.unlink()
    for pattern in TEST_REMOVE_GLOBS:
        try:
            matches = list(base.glob(pattern))
        except FileNotFoundError:
            continue
        for path in matches:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)


def _patch_pyproject(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    drop_deps = [
        "azure-identity",
        "PyJWT",
        "cryptography",
        "hvac",
        "boto3",
        "azure-keyvault",
        "google-cloud-secret-manager",
        "sqlfluff",
    ]
    lines = []
    for line in text.splitlines():
        if any(d in line for d in drop_deps) and line.strip().startswith('"'):
            continue
        lines.append(line)
    text = "\n".join(lines) + "\n"
    text = re.sub(
        r'\[project\.entry-points\."dblift\.commands"\]\nbuiltin = "cli\.extensions:register_builtin_command_extensions"\n\n'
        r'\[project\.entry-points\."dblift\.command_handlers"\]\nbuiltin = "cli\.extensions:load_builtin_command_handlers"\n\n',
        "",
        text,
    )
    # All first-party database providers (incl. Oracle, SQL Server, DB2, CosmosDB)
    # are shipped in the OSS package. Only features (not databases) are filtered.
    # Keep their entry points and extras intact; only Pro secret providers etc.
    # are stripped above via drop_deps and other patches.
    text = text.replace(
        'all = ["dblift[postgresql,mysql,oracle,sqlserver,db2]"]',
        'all = ["dblift[postgresql,mysql,mariadb,oracle,sqlserver,db2]"]',
    )
    text = text.replace(
        '"License :: Other/Proprietary License"',
        '"License :: OSI Approved :: Apache Software License"',
    )
    text = re.sub(r"\ncore = \[\"reports/templates/\*\.html\"\]\n", "\n", text)
    path.write_text(text, encoding="utf-8")


def _patch_parser_setup(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"def _register_builtin_command_parsers\([\s\S]*?return registered\n\n",
        "",
        text,
    )
    text = text.replace(
        "builtin_extension_parsers = _register_builtin_command_parsers(parser)",
        "builtin_extension_parsers: list = []",
    )
    # License keys are an enterprise concept; the OSS CLI has no guard to feed.
    text = re.sub(
        r'\n[ \t]*parser\.add_argument\(\n?[ \t]*"--license-key".*?\)\n',
        "\n",
        text,
        flags=re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")


def _patch_main_imports(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for token in (
        "_handle_diff",
        "_handle_export_schema",
        "_handle_plan",
        "_handle_preflight",
        "_handle_snapshot",
        "_handle_validate_sql",
    ):
        text = text.replace(f"    {token},\n", "")
    text = re.sub(
        r"def _apply_cli_license_token[\s\S]*?def _gate_license[\s\S]*?def _setup_logging",
        "def _setup_logging",
        text,
    )
    # Call sites of the stripped definitions would NameError at runtime.
    text = re.sub(r"\n[ \t]*_apply_cli_license_token\(args\)", "", text)
    text = re.sub(r"\n[ \t]*_gate_license\(\w+\)", "", text)
    text = text.replace("    license_info: Optional[Any] = None\n", "")
    text = text.replace("    if ctx.license_info:\n", "    if False:\n")
    # The --license-key flag has no effect without the license guard.
    text = text.replace('    "--license-key",\n', "")
    text = text.replace("--version, --license-key, log/db config", "--version, log/db config")
    path.write_text(text, encoding="utf-8")


def _strip_license_calls(base: Path) -> None:
    for rel in [
        "core/migration/commands/migrate_command.py",
        "core/migration/executor/execution_engine.py",
    ]:
        path = base / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r"\n        from core\.licensing\._guard import _refresh_state as \w+\n\n        \w+\(\)\n",
            "\n",
            text,
        )
        path.write_text(text, encoding="utf-8")


def _patch_secrets_registry(base: Path) -> None:
    registry = base / "config/secrets/_registry.py"
    if registry.exists():
        text = registry.read_text(encoding="utf-8")
        text = text.replace(
            'KNOWN_SCHEMES: frozenset = frozenset(\n    ["vault", "aws-secrets", "aws-ssm", "azure-keyvault", "gcp-secrets"]\n)',
            "KNOWN_SCHEMES: frozenset = frozenset()",
        )
        registry.write_text(text, encoding="utf-8")


def _write_oss_client_operations(source: Path, dest: Path) -> None:
    text = (source / "api/_client_operations.py").read_text(encoding="utf-8")
    header = '''"""Private operation helpers for OSS :mod:`api.client`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Union

from api.events import EventType
from core.logger.results import GenerateUndoScriptResult

'''
    helpers = text[
        text.index("def _heuristic_statement_count_from_sql") : text.index(
            "def _extract_schema_diff_input"
        )
    ]
    body = text[
        text.index("def generate_undo_script_operation") : text.index(
            "def _build_export_schema_options"
        )
    ]
    (dest / "api/_client_operations.py").write_text(header + helpers + body, encoding="utf-8")


def _remove_class_methods(text: str, method_names: list[str]) -> str:
    for name in method_names:
        text = re.sub(
            rf"\n    def {name}\([\s\S]*?(?=\n    def |\n\nclass |\Z)",
            "",
            text,
        )
    return text


def _patch_api_surface(base: Path) -> None:
    (base / "api/__init__.py").write_text(
        '''"""Public API for DBLift library integration (OSS)."""

from api.client import DBLiftClient
from api.events import EventEmitter, EventType

__all__ = [
    "DBLiftClient",
    "EventEmitter",
    "EventType",
]
''',
        encoding="utf-8",
    )
    _write_oss_client_operations(ROOT, base)
    client_path = base / "api/client.py"
    text = client_path.read_text(encoding="utf-8")
    text = text.replace(
        "from api._client_operations import (\n    export_schema_operation,\n    generate_sql_from_diff_operation,\n    generate_undo_script_operation,\n    generate_undo_scripts_operation,\n)\n",
        "from api._client_operations import (\n    generate_undo_script_operation,\n    generate_undo_scripts_operation,\n)\n",
    )
    text = text.replace("    DiffResult,\n", "")
    text = text.replace("    ExportSchemaResult,\n", "")
    text = text.replace("    GenerateSqlFromDiffResult,\n", "")
    text = text.replace("    PlanResult,\n", "")
    text = text.replace("    SnapshotResult,\n", "")
    text = re.sub(
        r"from core\.migration\.commands\.export_schema_command import ExportSchemaOptions\n",
        "",
        text,
    )
    text = text.replace(
        '__all__ = ["DBLiftClient", "ExportSchemaOptions"]\n', '__all__ = ["DBLiftClient"]\n'
    )
    text = _remove_class_methods(
        text,
        ["plan", "diff", "generate_sql_from_diff", "export_schema", "snapshot"],
    )
    client_path.write_text(text, encoding="utf-8")


def _patch_migration_executor(base: Path) -> None:
    path = base / "core/migration/executor/migration_executor.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("    DiffResult,\n", "")
    text = text.replace("    PlanResult,\n", "")
    text = _remove_class_methods(text, ["plan", "diff"])
    path.write_text(text, encoding="utf-8")


def _patch_cli_extension_tests(base: Path) -> None:
    path = base / "tests/unit/cli/test_cli_extensions.py"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"def test_builtin_extension_commands_are_registered_on_core_parser\([\s\S]*?(?=\ndef test_builtin_extension_handlers)",
        "",
        text,
    )
    text = re.sub(
        r"def test_builtin_extension_handlers_are_available_to_cli_dispatch\([\s\S]*?(?=\ndef test_pyproject)",
        "",
        text,
    )
    text = re.sub(
        r"def test_pyproject_registers_builtin_command_entry_points\([\s\S]*?\n\n",
        "",
        text,
    )
    path.write_text(text, encoding="utf-8")


def _patch_test_plugin_isolation(base: Path) -> None:
    # All first-party database providers now ship in OSS (filter on features,
    # not databases). No mangling of plugin lists is required for the OSS tree.
    path = base / "tests/unit/test_plugin_isolation.py"
    if not path.exists():
        return
    # (no changes applied)


def _patch_provider_registry_tests(base: Path) -> None:
    # All first-party providers (including Oracle, SQL Server, DB2, CosmosDB)
    # are now part of OSS. Do not mangle dialect names in provider registry
    # or contract tests; the real plugins and their tests are copied through.
    for pattern in [
        "tests/unit/db/test_provider_registry*.py",
        "tests/unit/db/test_provider_contract_matrix.py",
        "tests/unit/db/test_provider_capabilities.py",
        "tests/unit/db/test_mariadb_plugin_isolation.py",
    ]:
        for path in base.glob(pattern):
            # no dialect mangling
            pass


def _patch_public_api_surface_test(base: Path) -> None:
    path = base / "tests/unit/api/test_public_api_surface.py"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"    def test_export_schema_options_is_importable\([\s\S]*?assert isinstance\(ExportSchemaOptions, type\)\n\n",
        "",
        text,
    )
    text = text.replace('            "ExportSchemaOptions",\n', "")
    text = text.replace(
        'assert set(api.__all__) == {\n            "DBLiftClient",\n            "EventEmitter",\n            "EventType",\n            "ExportSchemaOptions",\n        }',
        'assert set(api.__all__) == {\n            "DBLiftClient",\n            "EventEmitter",\n            "EventType",\n        }',
    )
    for method in (
        "plan",
        "diff",
        "generate_sql_from_diff",
        "export_schema",
        "snapshot",
    ):
        text = text.replace(f'            "{method}",\n', "")
    path.write_text(text, encoding="utf-8")


def _ensure_oss_sql_statement_module(base: Path) -> None:
    """OSS quirks import ``core.state.sql_statement``; enterprise keeps the model under sql_generator."""
    source = ROOT / "core/sql_generator/sql_statement.py"
    if not source.exists():
        return
    text = source.read_text(encoding="utf-8")
    # Keep only the SqlStatement dataclass — drop GenerationOptions and below.
    marker = "@dataclass\nclass GenerationOptions"
    if marker in text:
        text = text[: text.index(marker)]
    header = '"""SQL statement models used by runtime formatting and SDK translation."""\n\n'
    if not text.lstrip().startswith('"""'):
        text = header + text
    target_dir = base / "core/state"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "sql_statement.py").write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_oss_readme(base: Path) -> None:
    (base / "OSS_README.md").write_text(
        """# DBLift OSS Export

Open-source tree generated from the enterprise monorepo.

## Boundaries

See `docs/architecture/oss-enterprise-boundaries.md` in the enterprise
repository (internal docs are not exported to this tree).

## Regenerate (initial)

```bash
python3 scripts/export_oss_repo.py /path/to/empty/dblift-oss
```

## Sync (existing checkout)

```bash
python3 scripts/export_oss_repo.py /path/to/dblift-oss --update --no-git-init
cd /path/to/dblift-oss
python3 -m pytest tests/unit/ -n auto --dist=loadscope -q --no-header
git status
```

See `docs/architecture/oss-export-reconciliation.md` before the first incremental sync.

## Tests

```bash
python3 -m pytest tests/unit/ -n auto --dist=loadscope -q --no-header
```
""",
        encoding="utf-8",
    )


def _patch_dialect_config_test(base: Path) -> None:
    path = base / "tests/unit/core/sql_parser/test_dialect_configs.py"
    if path.exists():
        path.unlink()


def _patch_sql_validator_init(base: Path) -> None:
    (base / "core/sql_validator/__init__.py").write_text(
        '''"""SQL validation components (OSS migration validation)."""

from core.sql_validator.migration_validator import MigrationValidator

__all__ = ["MigrationValidator"]
''',
        encoding="utf-8",
    )


def _write_oss_modules(base: Path) -> None:
    (base / "cli/_command_handlers.py").write_text(OSS_COMMAND_HANDLERS, encoding="utf-8")
    (base / "cli/extensions.py").write_text(OSS_EXTENSIONS, encoding="utf-8")
    (base / "config/secrets/__init__.py").write_text(OSS_SECRETS_INIT, encoding="utf-8")
    (base / "core/licensing/_guard.py").write_text(OSS_LICENSING_GUARD, encoding="utf-8")
    (base / "core/licensing/license_manager.py").write_text(OSS_LICENSING_MANAGER, encoding="utf-8")
    (base / "tests/unit/conftest.py").write_text(
        '"""Unit-test conftest for OSS dblift."""\n',
        encoding="utf-8",
    )


def _write_readme_oss(base: Path) -> None:
    readme = base / "README.md"
    header = (
        "# DBLift (Open Source)\n\n"
        "Core database migration engine for PostgreSQL, MySQL/MariaDB, SQLite, Oracle, SQL Server, DB2, and CosmosDB.\n\n"
        "Pro and Enterprise features (`validate-sql`, `drift`, `export-schema`, "
        "`plan`, `preflight`, cloud secret managers, enriched reports, etc.) "
        "ship in the separate `dblift-enterprise` package. All databases are available in OSS; "
        "we gate on features, not database engines.\n\n"
    )
    if readme.exists():
        body = readme.read_text(encoding="utf-8")
        if not body.startswith("# DBLift (Open Source)"):
            readme.write_text(header + body, encoding="utf-8")


def _write_license_file(base: Path) -> None:
    license_path = base / "LICENSE"
    if not license_path.exists():
        license_path.write_text(
            "Apache License\nVersion 2.0, January 2004\n"
            "http://www.apache.org/licenses/\n\n"
            "Copyright 2026 DBLift contributors\n\n"
            'Licensed under the Apache License, Version 2.0 (the "License");\n'
            "you may not use this file except in compliance with the License.\n"
            "You may obtain a copy of the License at\n\n"
            "    http://www.apache.org/licenses/LICENSE-2.0\n",
            encoding="utf-8",
        )


def _git_init(base: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=base, check=True)
    subprocess.run(["git", "add", "-A"], cwd=base, check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "Initial open-source release of dblift core\n\n"
            "Fresh repository history. Pro/Enterprise features live in dblift-enterprise.",
        ],
        cwd=base,
        check=True,
    )


def _run_export_pipeline(dest: Path, *, dry_run: bool) -> None:
    """Apply OSS transforms after rsync."""
    if dry_run:
        print("[dry-run] would remove Pro/Enterprise paths and apply OSS patches")
        return

    _remove_paths(dest)
    _patch_pyproject(dest / "pyproject.toml")
    _patch_parser_setup(dest / "cli/_parser_setup.py")
    _patch_main_imports(dest / "cli/main.py")
    _strip_license_calls(dest)
    _patch_secrets_registry(dest)
    _write_oss_modules(dest)
    _patch_sql_validator_init(dest)
    _patch_api_surface(dest)
    _patch_migration_executor(dest)
    _patch_cli_extension_tests(dest)
    _patch_test_plugin_isolation(dest)
    _patch_provider_registry_tests(dest)
    _patch_dialect_config_test(dest)
    _patch_public_api_surface_test(dest)
    _ensure_oss_sql_statement_module(dest)
    _write_oss_readme(dest)
    _write_readme_oss(dest)
    _write_license_file(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export OSS-only dblift tree")
    parser.add_argument("dest", type=Path, help="Destination directory")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Sync into an existing OSS checkout (preserves .git; uses rsync --delete)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show rsync actions only; skip destructive patches",
    )
    parser.add_argument("--no-git-init", action="store_true")
    args = parser.parse_args()
    dest: Path = args.dest.resolve()

    if dest.exists() and any(dest.iterdir()):
        if not args.update:
            print(
                f"Refusing to overwrite non-empty destination: {dest}\n"
                "Use --update to sync into an existing OSS checkout.",
                file=sys.stderr,
            )
            return 1
        if not (dest / ".git").is_dir():
            print(
                f"Warning: --update target has no .git directory: {dest}",
                file=sys.stderr,
            )
    elif args.update:
        print(
            f"Warning: --update requested but destination is empty: {dest}",
            file=sys.stderr,
        )

    mode = "Updating" if args.update else "Exporting"
    suffix = " (dry-run)" if args.dry_run else ""
    print(f"{mode} OSS tree from {ROOT} -> {dest}{suffix}")
    _rsync(ROOT, dest, update=args.update, dry_run=args.dry_run)
    _run_export_pipeline(dest, dry_run=args.dry_run)

    if args.dry_run:
        print("Dry-run complete — no patches applied.")
        return 0

    if not args.no_git_init and not args.update:
        if (dest / ".git").exists():
            shutil.rmtree(dest / ".git")
        _git_init(dest)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
