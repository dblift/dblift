"""Single source of truth for every persistent dblift property.

Each :class:`PropertySpec` mechanically derives its environment variable and
CLI flag from its dotted config name, so a property can never be added to one
surface and silently missing from another. See
``tests/unit/config/test_property_parity.py`` (added in a later task) for the
invariant that enforces this across ``from_env_dict`` / ``from_args_dict`` /
``to_dict`` / the CLI parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional


def env_name(name: str) -> str:
    """Derive the env var: ``database.username`` -> ``DBLIFT_DB_USERNAME``."""
    if name.startswith("database."):
        name = "db_" + name[len("database.") :]
    return "DBLIFT_" + name.replace(".", "_").upper()


def cli_flag(name: str) -> str:
    """Derive the CLI flag: ``database.username`` -> ``--db-username``."""
    if name.startswith("database."):
        name = "db_" + name[len("database.") :]
    return "--" + name.replace(".", "_").replace("_", "-")


@dataclass(frozen=True)
class PropertySpec:
    name: str  # dotted config key; "database.<field>" for nested db config
    type: str  # "str" | "int" | "float" | "bool" | "dict" | "list"
    default: object = None
    cli_only: bool = False  # runtime meta-flags (version/quiet/...) — no env/config
    cli_exempt: bool = False  # has env+config but intentionally no CLI flag
    cli_aliases: tuple = ()  # legacy flag names that already provide this CLI surface
    coerce: Optional[Callable[[str], object]] = None
    help: str = ""

    @property
    def env(self) -> str:
        return env_name(self.name)

    @property
    def cli(self) -> str:
        return cli_flag(self.name)


def _bool(v: str) -> bool:
    return v.lower() in ("1", "true", "yes")


# NOTE: keep this list the ONLY place persistent properties are declared.
# Structured db fields (extra_params, properties, options, session_variables)
# and CosmosDB-specific fields keep their existing bespoke env/arg parsing and
# are intentionally EXCLUDED here.
PROPERTY_REGISTRY: List[PropertySpec] = [
    # --- dblift-managed tables ---
    PropertySpec(
        "history_table",
        "str",
        "dblift_schema_history",
        cli_aliases=("--table",),
        help="dblift schema-history table name",
    ),
    PropertySpec(
        "snapshot_table",
        "str",
        "dblift_schema_snapshots",
        help="dblift schema-snapshots table name",
    ),
    PropertySpec("max_snapshots", "int", 1, coerce=int, help="Max snapshots to retain"),
    # --- audit / execution ---
    PropertySpec(
        "installed_by",
        "str",
        None,
        help="Value recorded in the installed_by column (default: db username)",
    ),
    PropertySpec("baseline_version", "str", None),
    PropertySpec("target_version", "str", None),
    PropertySpec("mark_as_executed", "bool", False, coerce=_bool),
    PropertySpec("strict_mode", "bool", False, coerce=_bool, cli_aliases=("--strict",)),
    PropertySpec("clean_disabled", "bool", True, coerce=_bool),
    PropertySpec("dry_run", "bool", False, coerce=_bool),
    # --- migration selection ---
    PropertySpec("tags", "str", None),
    PropertySpec("exclude_tags", "str", None),
    PropertySpec("versions", "str", None),
    PropertySpec("exclude_versions", "str", None),
    # --- retry / error handling (config+env, no CLI flag) ---
    PropertySpec("error_handling_enabled", "bool", True, coerce=_bool, cli_exempt=True),
    PropertySpec("max_retries", "int", 3, coerce=int, cli_exempt=True),
    PropertySpec("retry_delay", "float", 1.0, coerce=float, cli_exempt=True),
    PropertySpec("retry_backoff", "float", 2.0, coerce=float, cli_exempt=True),
    PropertySpec("retry_jitter", "float", 0.2, coerce=float, cli_exempt=True),
    # --- logging ---
    PropertySpec("log_level", "str", None),
    PropertySpec("log_format", "str", None),
    PropertySpec("log_file", "str", None),
    PropertySpec("log_dir", "str", None),
    # --- database connection (nested under database.*) ---
    # NOTE: the env/args generators skip dotted (database.*) names. These fields
    # are read by the pre-existing DBLIFT_DB_* machinery in DbliftConfig
    # (_DB_ALIASES / _ALLOWED), which also handles the structured/aliased/CosmosDB
    # cases the registry does not model. Listing them here is NOT redundant: the
    # parity tests validate each one's surfaces, so adding a new database.* field
    # without a corresponding DBLIFT_DB_* allowlist entry fails CI loudly rather
    # than silently dropping the surface. Drift is detected, not eliminated, for
    # these fields.
    PropertySpec("database.url", "str", ""),
    PropertySpec("database.type", "str", None, cli_exempt=True),
    PropertySpec("database.username", "str", ""),
    PropertySpec("database.password", "str", ""),
    PropertySpec("database.schema", "str", ""),
    PropertySpec("database.host", "str", None, cli_exempt=True),
    PropertySpec("database.port", "int", None, coerce=int, cli_exempt=True),
    PropertySpec("database.database", "str", None, cli_exempt=True),
    PropertySpec("database.connection_timeout", "int", 30, coerce=int, cli_exempt=True),
]


def spec_for(name: str) -> Optional[PropertySpec]:
    """Return the :class:`PropertySpec` for ``name``, or ``None`` if unknown.

    Runtime-only meta flags (``--version``, ``--quiet``, ``--config`` …) are not
    persistent properties and are intentionally absent from the registry, so
    ``spec_for("version")`` returns ``None`` by design.
    """
    for spec in PROPERTY_REGISTRY:
        if spec.name == name:
            return spec
    return None
