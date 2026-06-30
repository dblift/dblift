import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

import yaml

from config.database_config import BaseDatabaseConfig
from config.errors import ConfigurationError
from config.secrets import SecretsConfig, resolve_secret_refs

ENV_PLACEHOLDER_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")

# Exceptions raised by YAML loading + the merge step (KeyError / TypeError on
# malformed dict shapes). Volontairement étroit : on ne capture pas
# Exception/RuntimeError pour ne pas masquer un bug de logique.
_CONFIG_LOAD_EXC: Tuple[Type[Exception], ...] = (
    yaml.YAMLError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    IndexError,
)


def _placeholder_tokens(raw_placeholders: Any) -> List[str]:
    if not raw_placeholders:
        return []
    # `--placeholders` uses ``nargs="+"`` + ``action="append"``, so argparse yields a
    # list-of-lists: ``[["k1=v1", "k2=v2"], ["k3=v3"]]``. Flatten one level so each
    # element becomes a single ``key=value`` (or comma-joined) token.
    values = raw_placeholders if isinstance(raw_placeholders, list) else [raw_placeholders]
    flat: List[Any] = []
    for value in values:
        if isinstance(value, list):
            flat.extend(value)
        else:
            flat.append(value)
    tokens: List[str] = []
    for value in flat:
        tokens.extend(part.strip() for part in str(value).split(",") if part.strip())
    return tokens


@dataclass
class ConfigEnvDiagnostics:
    """Optional diagnostics collected while reading DBLIFT_* environment vars."""

    ignored_db_vars: List[str] = field(default_factory=list)
    invalid_int_vars: List[str] = field(default_factory=list)
    invalid_structured_vars: List[str] = field(default_factory=list)


def _resolve_env_placeholders(data: Any) -> Any:
    """Recursively resolve ${VAR} or ${VAR:-default} placeholders using environment variables."""

    if isinstance(data, dict):
        return {key: _resolve_env_placeholders(value) for key, value in data.items()}

    if isinstance(data, list):
        return [_resolve_env_placeholders(item) for item in data]

    if isinstance(data, str):

        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            return default if default is not None else ""

        return ENV_PLACEHOLDER_PATTERN.sub(replace, data)

    return data


def load_config(config_file_path: Optional[str], args: Optional[Any] = None) -> "DbliftConfig":
    """
    Load configuration from a file and override with command line arguments

    Args:
        config_file_path: Path to the configuration file
        args: Optional command line arguments

    Returns:
        DbliftConfig object with merged configuration
    """
    config_data: Dict[str, Any] = {}

    # If a config path was provided explicitly, it must exist and be loadable. Silently
    # falling back to defaults hides typos in --config and produces surprising downstream errors.
    if config_file_path:
        if not os.path.exists(config_file_path):
            raise FileNotFoundError(f"Config file not found: {config_file_path}")
        try:
            file_data = DbliftConfig.load_config_data_from_yaml(config_file_path)
            config_data = DbliftConfig.merge_config_data(config_data, file_data)
        except _CONFIG_LOAD_EXC as e:
            raise RuntimeError(f"Error loading config file {config_file_path}: {e}") from e

    # Override with environment variables.
    # Env vars are partial overrides — merge them directly into the already-typed
    # config so that the type/URL from the file are inherited when missing from env.
    # Using config.merge() is correct here: it fills any absent field from current
    # config.database before calling create(), so a lone DBLIFT_DB_SCHEMA never
    # triggers an "Unsupported database type" crash.
    env_dict = DbliftConfig.from_env_dict()
    if env_dict:
        config_data = DbliftConfig.merge_config_data(config_data, env_dict)

    # Override with command line arguments if provided
    if args:
        args_dict = DbliftConfig.from_args_dict(args)
        if args_dict:
            config_data = DbliftConfig.merge_config_data(config_data, args_dict)

    if not config_data:
        raise ConfigurationError(
            "No configuration source provided. Pass --config, --db-url, or set DBLIFT_DB_URL."
        )

    is_offline_cmd = False
    config = DbliftConfig.from_dict(config_data, resolve_secrets=not is_offline_cmd)
    if args:
        installed_by = getattr(args, "installed_by", None)
        if installed_by:
            config.database.installed_by = installed_by
        elif not config.database.installed_by and config.database.username:
            config.database.installed_by = config.database.username
    return config


def deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries, with override taking precedence for non-empty, non-None values."""
    result = base.copy()
    for k, v in override.items():
        if isinstance(v, dict) and k in result and isinstance(result[k], dict):
            result[k] = deep_merge_dicts(result[k], v)
        elif v not in (None, ""):
            result[k] = v
        # else: skip empty/None override, keep base value
    return result


@dataclass
class DirectoryConfig:
    """Configuration for a single migration directory with optional recursive setting."""

    path: str
    recursive: bool = True  # Whether to scan subdirectories for this directory

    @classmethod
    def from_dict(cls, data: Union[str, Dict[str, Any]]) -> "DirectoryConfig":
        """Create DirectoryConfig from either a string (path) or dict (path + recursive)."""
        if isinstance(data, str):
            return cls(path=data, recursive=True)
        elif isinstance(data, dict):
            return cls(
                path=data.get("path", ""),
                recursive=data.get("recursive", True),
            )
        else:
            raise ValueError(f"Invalid directory config format: {data}")

    def to_dict(self) -> Union[str, Dict[str, Any]]:
        """Convert to dictionary format."""
        if self.recursive is True:
            # For backward compatibility, return just the path string if recursive is True
            return self.path
        else:
            # Return dict format if recursive is False
            return {"path": self.path, "recursive": self.recursive}


class MigrationsConfig:
    """Configuration for migrations."""

    def __init__(
        self,
        directory: str = "migrations",
        directories: Optional[List[Union[str, DirectoryConfig]]] = None,
        table: str = "schema_version",
        recursive: bool = True,
        script_encoding: str = "utf-8",
        detect_encoding: bool = False,
    ) -> None:
        """Initialize MigrationsConfig.

        Args:
            directory: Main migrations directory (deprecated, use directories)
            directories: Migration directories (can be strings or DirectoryConfig objects)
            table: Schema history table name
            recursive: Global recursive setting (used as default for directories without explicit recursive)
            script_encoding: Encoding for reading migration script files
            detect_encoding: Detect migration script encoding before reading
        """
        self.directory = directory
        self.directories = directories if directories is not None else []
        self.table = table
        self.recursive = recursive
        self.script_encoding = script_encoding
        self.detect_encoding = detect_encoding

    def get_directory_configs(self) -> List[DirectoryConfig]:
        """Get normalized list of DirectoryConfig objects."""
        configs = []

        # If 'directories' is explicitly provided, use only those (ignore 'directory' field)
        if self.directories:
            # Handle 'directories' field
            for dir_entry in self.directories:
                if isinstance(dir_entry, DirectoryConfig):
                    configs.append(dir_entry)
                elif isinstance(dir_entry, str):
                    configs.append(DirectoryConfig(path=dir_entry, recursive=self.recursive))
                elif isinstance(dir_entry, dict):
                    configs.append(DirectoryConfig.from_dict(dir_entry))
                else:
                    raise ValueError(f"Invalid directory entry format: {dir_entry}")
        else:
            # Handle legacy 'directory' field (only if 'directories' not provided)
            if self.directory and self.directory != "migrations":
                configs.append(DirectoryConfig(path=self.directory, recursive=self.recursive))
            elif self.directory == "migrations" and not self.directories:
                # Use default only if nothing else is configured
                configs.append(DirectoryConfig(path="migrations", recursive=self.recursive))

        # If no directories configured at all, use default
        if not configs:
            configs.append(DirectoryConfig(path="migrations", recursive=self.recursive))

        return configs


@dataclass
class LoggingConfig:
    """Configuration for logging."""

    level: str = "INFO"
    file: Optional[str] = None
    directory: Optional[str] = None


@dataclass
class DbliftConfig:
    """Main configuration class for dblift."""

    database: BaseDatabaseConfig
    migrations: MigrationsConfig = field(default_factory=MigrationsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    baseline_version: Optional[str] = None
    target_version: Optional[str] = None
    dry_run: bool = False
    undo: bool = False
    installed_by: Optional[str] = None
    extra_params: Optional[Dict[str, Any]] = None

    # Migration selection criteria
    tags: Optional[str] = None
    exclude_tags: Optional[str] = None
    versions: Optional[str] = None
    exclude_versions: Optional[str] = None

    # Migration execution options
    mark_as_executed: bool = False

    # Migration validation options
    strict_mode: bool = False  # When enabled, enforces Flyway-compatible strict validation rules

    # Destructive operation guardrails
    clean_disabled: bool = True

    # SQL Placeholders for variable substitution in migrations
    placeholders: Optional[Dict[str, str]] = None

    # Migration history and journal configuration
    history_table: str = "dblift_schema_history"
    snapshot_table: str = "dblift_schema_snapshots"
    max_snapshots: int = (
        1  # Maximum number of snapshots to keep (oldest are deleted when limit exceeded)
    )
    journal_enabled: bool = True
    journal_dir: Optional[str] = None

    # Error handling and retry configuration
    error_handling_enabled: bool = True
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    retry_jitter: float = 0.2
    retryable_error_categories: Optional[List[str]] = None

    # Secrets providers configuration
    secrets: SecretsConfig = field(default_factory=SecretsConfig)

    # Logging fields for CLI overrides
    log_file: Optional[str] = None
    log_format: Optional[str] = None
    log_level: Optional[str] = None
    log_dir: Optional[str] = None

    def merge(self, other_config: Dict[str, Any]) -> None:
        """Merge another configuration into this one.

        Args:
            other_config: Configuration dictionary to merge
        """
        other_config = dict(other_config)
        if other_config.get("migrations_dir"):
            import warnings

            warnings.warn(
                "Configuration key 'migrations_dir' is deprecated. "
                "Please use 'migrations.directory' instead. "
                "Example:\n"
                "migrations:\n"
                "  directory: migrations\n"
                "  recursive: true",
                DeprecationWarning,
                stacklevel=2,
            )
            m_block = other_config.get("migrations")
            m_dict = dict(m_block) if isinstance(m_block, dict) else {}
            m_dict["directory"] = other_config["migrations_dir"]
            other_config["migrations"] = m_dict

        if "database" in other_config:
            raw_db = other_config["database"]
            # YAML ``database: null`` — do not replace the current database with empty config.
            if raw_db is not None and isinstance(raw_db, dict):
                from config.config_builder import ConfigBuilder

                db_overrides = {
                    key: value for key, value in raw_db.items() if value not in (None, "")
                }
                self.database = ConfigBuilder.merge_database_overrides(self.database, db_overrides)

        if "migrations" in other_config:
            migrations = other_config["migrations"]
            if isinstance(migrations, dict):
                self.migrations.directory = migrations.get("directory", self.migrations.directory)
                self.migrations.table = migrations.get("table", self.migrations.table)
                self.migrations.script_encoding = migrations.get(
                    "script_encoding", self.migrations.script_encoding
                )
                self.migrations.detect_encoding = migrations.get(
                    "detect_encoding", self.migrations.detect_encoding
                )

                # Update directories if provided
                # Support both old format (list of strings) and new format (list of dicts with path/recursive)
                if "directories" in migrations:
                    dirs = migrations.get("directories", [])
                    normalized_dirs: List[Union[str, DirectoryConfig]] = []
                    for dir_entry in dirs:
                        if isinstance(dir_entry, str):
                            normalized_dirs.append(dir_entry)
                        elif isinstance(dir_entry, dict):
                            normalized_dirs.append(DirectoryConfig.from_dict(dir_entry))
                        else:
                            raise ValueError(f"Invalid directory entry format: {dir_entry}")
                    self.migrations.directories = normalized_dirs

                if "recursive" in migrations:
                    self.migrations.recursive = migrations.get("recursive", True)

        if "history_table" in other_config and other_config["history_table"]:
            self.history_table = other_config["history_table"]
        if "snapshot_table" in other_config and other_config["snapshot_table"]:
            self.snapshot_table = other_config["snapshot_table"]
        if "max_snapshots" in other_config:
            self.max_snapshots = other_config["max_snapshots"]

        if "logging" in other_config:
            logging_raw = other_config["logging"]
            if isinstance(logging_raw, dict):
                self.logging.level = logging_raw.get("level", self.logging.level)
                self.logging.file = logging_raw.get("file", self.logging.file)
                self.logging.directory = logging_raw.get("directory", self.logging.directory)
        if "log_dir" in other_config:
            self.log_dir = other_config.get("log_dir", self.log_dir)

        # Fields that must use ``key in other_config`` so falsy values (False, 0) are not dropped.
        for scalar_key in (
            "strict_mode",
            "clean_disabled",
            "journal_enabled",
            "error_handling_enabled",
            "max_retries",
            "retry_delay",
            "retry_backoff",
            "retry_jitter",
        ):
            if scalar_key in other_config:
                setattr(self, scalar_key, other_config[scalar_key])

        if "retryable_error_categories" in other_config:
            self.retryable_error_categories = other_config["retryable_error_categories"]

        if "secrets" in other_config:
            raw = other_config["secrets"]
            if isinstance(raw, dict):
                self.secrets = SecretsConfig.from_dict(raw)

        for cli_log_key in ("log_file", "log_format", "log_level"):
            if cli_log_key in other_config:
                setattr(self, cli_log_key, other_config[cli_log_key])

        # Update other fields if present
        self.baseline_version = other_config.get("baseline_version", self.baseline_version)
        self.target_version = other_config.get("target_version", self.target_version)
        self.dry_run = other_config.get("dry_run", self.dry_run)
        self.undo = other_config.get("undo", self.undo)
        self.installed_by = other_config.get("installed_by", self.installed_by)
        self.extra_params = other_config.get("extra_params", self.extra_params)
        self.tags = other_config.get("tags", self.tags)
        self.exclude_tags = other_config.get("exclude_tags", self.exclude_tags)
        self.versions = other_config.get("versions", self.versions)
        self.exclude_versions = other_config.get("exclude_versions", self.exclude_versions)
        self.mark_as_executed = other_config.get("mark_as_executed", self.mark_as_executed)
        self.placeholders = other_config.get("placeholders", self.placeholders)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], resolve_secrets: bool = True) -> "DbliftConfig":
        """Create a DbliftConfig instance from a dictionary.

        Args:
            data: Configuration dictionary
            resolve_secrets: When False, skip secret-URI resolution (used for
                offline commands that never open a DB connection and must not
                require secret-manager credentials to be available).

        Returns:
            A DbliftConfig instance
        """
        data = _resolve_env_placeholders(data or {})

        if resolve_secrets:
            # Two-phase secret resolution:
            # Phase 1 — resolve the secrets block itself (bootstraps provider credentials).
            #   e.g. secrets.vault.token: "aws-secrets://prod/vault-token" uses AWS ambient
            #   credentials to fetch the Vault token before any Vault lookups happen.
            secrets_raw = data.get("secrets")
            secrets_config_initial = SecretsConfig.from_dict(
                secrets_raw if isinstance(secrets_raw, dict) else {}
            )
            secrets_raw_resolved = resolve_secret_refs(
                secrets_raw if isinstance(secrets_raw, dict) else {}, secrets_config_initial
            )
            secrets_config = SecretsConfig.from_dict(secrets_raw_resolved)
            # Phase 2 — resolve the full config tree using bootstrapped credentials.
            data = resolve_secret_refs(data, secrets_config)
            # Rebuild once more so DbliftConfig.secrets holds the fully resolved values.
            secrets_final = data.get("secrets")
            secrets_config = SecretsConfig.from_dict(
                secrets_final if isinstance(secrets_final, dict) else {}
            )
        else:
            secrets_raw = data.get("secrets")
            secrets_config = SecretsConfig.from_dict(
                secrets_raw if isinstance(secrets_raw, dict) else {}
            )

        cls.validate_complete_data(data)
        database_data = dict(data.get("database", {}))
        db_type = str(database_data.get("type") or "").strip().lower()
        url = str(database_data.get("url") or "").strip()
        if url and not db_type:
            from db.provider_registry import ProviderRegistry

            url_lower = url.lower()
            scheme = url_lower.split(":", 1)[0].split("+", 1)[0]
            db_type = ProviderRegistry.canonical_dialect_name(scheme) or ""
            if not db_type:
                from config.secrets._registry import is_secret_uri as _is_secret_uri_inline

                if _is_secret_uri_inline(url):
                    database_data["_allow_incomplete"] = True
                # Non-secret unparseable URLs are left as-is so _apply_url_overrides
                # raises a focused URL error immediately rather than producing a
                # silently broken config.
        # When secrets are not resolved (offline commands),
        # a secret URI in database.url must not be validated as a database URL — the
        # type may already be known from database.type but the URL is still raw.
        # This covers the case where database.type is set explicitly, which skips
        # the `if url and not db_type` block above.
        if not resolve_secrets and url:
            from config.secrets._registry import is_secret_uri as _is_secret_uri

            if _is_secret_uri(url):
                database_data["_allow_incomplete"] = True
        if url:
            from db.provider_registry import ProviderRegistry

            if ProviderRegistry.get_quirks(db_type).url_optional_when_file_path_given:
                database_data.pop("path", None)
                database_data.pop("database", None)

        # Create database config
        try:
            database_config = BaseDatabaseConfig.create(database_data)
        except ValueError as e:
            raise ConfigurationError(str(e)) from e

        # Extract migrations config - support both old and new formats
        migrations = data.get("migrations", {})

        # Check for old format (migrations_dir at root level) - DEPRECATED
        old_migrations_dir = data.get("migrations_dir")
        if old_migrations_dir:
            import warnings

            warnings.warn(
                "Configuration key 'migrations_dir' is deprecated. "
                "Please use 'migrations.directory' instead. "
                "Example:\n"
                "migrations:\n"
                "  directory: migrations\n"
                "  recursive: true",
                DeprecationWarning,
                stacklevel=2,
            )
            migrations_dir = old_migrations_dir
        else:
            migrations_dir = migrations.get("directory", "migrations")

        migrations_table = migrations.get("table", "schema_version")
        migrations_script_encoding = migrations.get("script_encoding", "utf-8")
        migrations_detect_encoding = migrations.get("detect_encoding", False)

        # Normalize migrations_dir
        if not os.path.isabs(migrations_dir) and not migrations_dir.startswith("./"):
            migrations_dir = f"./{migrations_dir}"

        # Extract logging config
        logging = data.get("logging", {})
        log_level = logging.get("level", "INFO")
        log_file = logging.get("file") or data.get("log_file")
        # Normalize log_file if present
        if log_file and not os.path.isabs(log_file) and not log_file.startswith("./"):
            log_file = f"./{log_file}"

        log_directory = logging.get("directory")
        if (
            log_directory
            and not os.path.isabs(log_directory)
            and not str(log_directory).startswith("./")
        ):
            log_directory = f"./{log_directory}"

        root_log_dir = data.get("log_dir")
        if (
            root_log_dir
            and not os.path.isabs(root_log_dir)
            and not str(root_log_dir).startswith("./")
        ):
            root_log_dir = f"./{str(root_log_dir)}"

        # Validate log level (case-insensitive)
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        log_level_upper = log_level.upper() if isinstance(log_level, str) else log_level
        if log_level_upper not in valid_levels:
            raise ValueError(f"Invalid log level: {log_level}. Must be one of {valid_levels}")
        log_level = log_level_upper  # Normalize to uppercase

        # Extract additional migration directories and recursive flag
        migrations_directories = migrations.get("directories", [])
        migrations_recursive = migrations.get("recursive", True)

        # Journal settings are always in-memory only - ignore journal_dir if set in config files
        # journal_enabled defaults to True, journal_dir defaults to None (will be enforced in cli/main.py)
        config = cls(
            database=database_config,
            migrations=MigrationsConfig(
                directory=migrations_dir,
                directories=migrations_directories,
                table=migrations_table,
                recursive=migrations_recursive,
                script_encoding=migrations_script_encoding,
                detect_encoding=migrations_detect_encoding,
            ),
            logging=LoggingConfig(level=log_level, file=log_file, directory=log_directory),
            baseline_version=data.get("baseline_version"),
            target_version=data.get("target_version"),
            dry_run=data.get("dry_run", False),
            undo=data.get("undo", False),
            installed_by=data.get("installed_by"),
            extra_params=data.get("extra_params"),
            tags=data.get("tags"),
            exclude_tags=data.get("exclude_tags"),
            versions=data.get("versions"),
            exclude_versions=data.get("exclude_versions"),
            mark_as_executed=data.get("mark_as_executed", False),
            strict_mode=data.get("strict_mode", False),
            clean_disabled=data.get("clean_disabled", True),
            placeholders=data.get("placeholders"),
            history_table=data.get("history_table", "dblift_schema_history"),
            snapshot_table=data.get("snapshot_table", "dblift_schema_snapshots"),
            max_snapshots=data.get("max_snapshots", 1),
            journal_enabled=data.get("journal_enabled", True),
            error_handling_enabled=data.get("error_handling_enabled", True),
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
            retry_backoff=data.get("retry_backoff", 2.0),
            retry_jitter=data.get("retry_jitter", 0.2),
            retryable_error_categories=data.get("retryable_error_categories"),
            log_file=data.get("log_file"),
            log_format=data.get("log_format"),
            log_level=data.get("log_level"),
            secrets=secrets_config,
        )
        # Explicitly ensure journal_dir is None (journal is always in-memory only)
        config.journal_dir = None
        config.log_dir = root_log_dir
        return config

    @staticmethod
    def merge_config_data(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Merge raw config dictionaries before constructing typed config objects."""
        return deep_merge_dicts(base or {}, override or {})

    @classmethod
    def validate_complete_data(cls, data: Dict[str, Any]) -> None:
        """Validate that merged raw config data can produce a usable database config."""
        database = data.get("database")
        if not isinstance(database, dict) or not database:
            raise ConfigurationError(
                "Database configuration is required. Provide database.type and connection settings."
            )

        from db.provider_registry import ProviderRegistry

        db_type = str(database.get("type") or "").strip().lower()
        url = str(database.get("url") or "").strip()
        if not db_type and url:
            url_lower = url.lower()
            scheme = url_lower.split(":", 1)[0].split("+", 1)[0]
            db_type = ProviderRegistry.canonical_dialect_name(scheme) or ""

        if not db_type:
            if url:
                return
            raise ConfigurationError("Database type is required in configuration")

        _quirks = ProviderRegistry.get_quirks(db_type)
        # Cloud-account auth validation: account_endpoint + account_key (or
        # use_managed_identity). Gated on the ``requires_cloud_account_auth``
        # quirks capability (CosmosDB sets it True) rather than a hardcoded
        # dialect name. ``is_nosql`` is deliberately not reused — it is too
        # generic, so future NoSQL dialects don't inherit Azure-specific rules.
        if _quirks.requires_cloud_account_auth:
            has_endpoint = bool(database.get("account_endpoint") or database.get("url"))
            if not has_endpoint:
                raise ConfigurationError("Cosmos DB configuration requires account_endpoint or url")
            raw_mi = database.get("use_managed_identity")
            use_managed_identity = (
                raw_mi.lower() in ("1", "true", "yes") if isinstance(raw_mi, str) else bool(raw_mi)
            )
            if not use_managed_identity and not database.get("account_key"):
                raise ConfigurationError(
                    "Cosmos DB configuration requires account_key unless use_managed_identity is true"
                )
            if not (database.get("database_name") or database.get("database")):
                raise ConfigurationError(
                    "Cosmos DB configuration requires database_name or database"
                )
            return

        if _quirks.url_optional_when_file_path_given:
            if not (database.get("path") or database.get("database") or url):
                raise ConfigurationError(
                    f"'{db_type}' configuration requires path, database, or url"
                )
            return

        if not _quirks.has_connection_identifier(database):
            raise ConfigurationError(_quirks.missing_connection_identifier_hint)

    @classmethod
    def from_env_dict(cls, diagnostics: Optional[ConfigEnvDiagnostics] = None) -> Dict[str, Any]:
        """Load config from environment variables and map to config fields.

        Convention: DBLIFT_DB_<SUFFIX> maps to database.<suffix.lower()>.
        Special cases: USER -> username, OPTIONS and SESSION_VARS accept JSON or k=v CSV.
        Top-level keys: DBLIFT_SNAPSHOT_TABLE, DBLIFT_HISTORY_TABLE, DBLIFT_MAX_SNAPSHOTS.
        Pass ``diagnostics`` to collect ignored/coercion issues without changing
        the default silent-merge behavior.
        """
        env = os.environ
        db: Dict[str, Any] = {}

        # Explicit allowlist: only recognised DBLIFT_DB_* suffixes are accepted.
        # Unknown suffixes (e.g. from CI tooling) are silently ignored so they
        # cannot pollute or shadow legitimate config fields.
        #
        # Names whose env-var suffix differs from the config field name
        _DB_ALIASES: Dict[str, str] = {"USER": "username", "SESSION_VARS": "session_variables"}
        # Suffixes that require structured (JSON / k=v CSV) parsing into a dict
        _STRUCTURED = {"OPTIONS", "SESSION_VARS", "EXTRA_PARAMS", "PROPERTIES"}
        # Suffixes whose value must be coerced to int
        _INT_FIELDS = {"PORT", "CONNECTION_TIMEOUT"}
        # Suffixes whose value must be coerced to bool ("true"/"1"/"yes" → True)
        _BOOL_FIELDS = {
            "ENCRYPT",
            "TRUST_SERVER_CERTIFICATE",
            "INTEGRATED_SECURITY",
            "USE_MANAGED_IDENTITY",
        }
        # All accepted suffixes — union of every category plus plain string fields
        _ALLOWED = (
            _STRUCTURED
            | _INT_FIELDS
            | _BOOL_FIELDS
            | {
                "URL",
                "USER",
                "PASSWORD",
                "SCHEMA",
                "HOST",
                "DATABASE",
                "TYPE",
                "INSTANCE",
                # CosmosDB: account_endpoint / account_key map 1:1 by lowercasing.
                "ACCOUNT_ENDPOINT",
                "ACCOUNT_KEY",
                "DATABASE_NAME",
                "CONTAINER_NAME",
            }
        )

        for var_name, var_value in env.items():
            if not var_name.startswith("DBLIFT_DB_") or not var_value:
                continue
            suffix = var_name[len("DBLIFT_DB_") :]
            if suffix not in _ALLOWED:
                if diagnostics is not None:
                    diagnostics.ignored_db_vars.append(var_name)
                continue
            field = _DB_ALIASES.get(suffix, suffix.lower())
            if suffix in _STRUCTURED:
                try:
                    db[field] = json.loads(var_value)
                except json.JSONDecodeError:
                    # Intentional: not valid JSON; fall back to k=v CSV parsing
                    parsed = {}
                    for pair in var_value.split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            parsed[k.strip()] = v.strip()
                    if parsed:
                        db[field] = parsed
                    elif diagnostics is not None:
                        diagnostics.invalid_structured_vars.append(var_name)
            elif suffix in _INT_FIELDS:
                try:
                    db[field] = int(var_value)
                except ValueError:
                    if diagnostics is not None:
                        diagnostics.invalid_int_vars.append(var_name)
                    pass  # leave invalid; create() will raise with context
            elif suffix in _BOOL_FIELDS:
                db[field] = var_value.lower() in ("1", "true", "yes")
            else:
                db[field] = var_value

        # Only emit "database" when env actually contributed something. Packing
        # an empty ``{"database": {}}`` would make ``if env_dict:`` truthy at
        # every caller and trigger a no-op ``config.merge()`` that still runs
        # ``BaseDatabaseConfig.create()`` and could alter an otherwise-correct
        # file-loaded config (see Cursor finding 2026-04-22).
        config: Dict[str, Any] = {}
        if db:
            config["database"] = db
        if env.get("DBLIFT_SNAPSHOT_TABLE"):
            config["snapshot_table"] = env["DBLIFT_SNAPSHOT_TABLE"]
        if env.get("DBLIFT_HISTORY_TABLE"):
            config["history_table"] = env["DBLIFT_HISTORY_TABLE"]
        if env.get("DBLIFT_MAX_SNAPSHOTS"):
            try:
                config["max_snapshots"] = int(env["DBLIFT_MAX_SNAPSHOTS"])
            except ValueError:
                if diagnostics is not None:
                    diagnostics.invalid_int_vars.append("DBLIFT_MAX_SNAPSHOTS")
                pass  # Ignore invalid values
        if env.get("DBLIFT_CLEAN_DISABLED"):
            config["clean_disabled"] = env["DBLIFT_CLEAN_DISABLED"].lower() in ("1", "true", "yes")
        return config

    @classmethod
    def collect_env_diagnostics(cls) -> ConfigEnvDiagnostics:
        """Return diagnostics for current DBLIFT_* env without changing config output."""
        diagnostics = ConfigEnvDiagnostics()
        cls.from_env_dict(diagnostics=diagnostics)
        return diagnostics

    @classmethod
    def from_args_dict(cls, args: Any) -> Dict[str, Any]:
        """Return config dict from command line arguments (for merging)."""
        if hasattr(args, "items"):
            args = dict(args or {})
        else:
            args = {
                key: getattr(args, key)
                for key in dir(args)
                if not key.startswith("_") and not callable(getattr(args, key))
            }
        db_cfg = {}
        aliases = {
            "url": ("db_url", "database_url"),
            "type": ("db_type", "database_type"),
            "username": ("db_username", "database_username"),
            "password": ("db_password", "database_password"),
            "schema": ("db_schema", "database_schema"),
            "options": ("db_options", "database_options"),
            "session_variables": ("db_session_vars", "database_session_vars"),
            "account_endpoint": ("account_endpoint", "db_account_endpoint"),
            "account_key": ("account_key", "db_account_key"),
            "database": ("database", "db_database"),
            "database_name": ("database_name", "db_database_name"),
            "container_name": ("container_name", "db_container_name"),
            "use_managed_identity": ("use_managed_identity", "db_use_managed_identity"),
        }
        for db_field, names in aliases.items():
            for name in names:
                value = args.get(name)
                if value not in (None, ""):
                    db_cfg[db_field] = value
                    break

        if db_cfg.get("url") and not db_cfg.get("type"):
            url_val = str(db_cfg["url"])
            from config.secrets._registry import is_secret_uri as _is_secret_uri_args

            if not _is_secret_uri_args(url_val):
                from db.provider_registry import ProviderRegistry

                url_lower = url_val.strip().lower()
                scheme = url_lower.split(":", 1)[0].split("+", 1)[0]
                inferred_type = ProviderRegistry.canonical_dialect_name(scheme) or ""
                if inferred_type:
                    db_cfg["type"] = inferred_type

        config: Dict[str, Any] = {}
        if db_cfg:
            config["database"] = db_cfg

        for key in (
            "snapshot_table",
            "history_table",
            "max_snapshots",
            "baseline_version",
            "target_version",
            "dry_run",
            "undo",
            "installed_by",
            "mark_as_executed",
            "strict_mode",
            "clean_disabled",
            "journal_enabled",
            "error_handling_enabled",
            "max_retries",
            "retry_delay",
            "retry_backoff",
            "retry_jitter",
            "retryable_error_categories",
            "tags",
            "exclude_tags",
            "versions",
            "exclude_versions",
            "log_file",
            "log_dir",
            "log_format",
            "log_level",
        ):
            if key in args and args[key] not in (None, ""):
                config[key] = args[key]

        placeholders: Dict[str, str] = {}
        for placeholder in _placeholder_tokens(args.get("placeholders")):
            if "=" in placeholder:
                key, value = placeholder.split("=", 1)
                placeholders[key.strip()] = value.strip()
        if placeholders:
            config["placeholders"] = placeholders

        if args.get("migrations_dir"):
            config["migrations"] = {"directory": args["migrations_dir"]}
        if args.get("migrations_table"):
            migrations = dict(config.get("migrations", {}))
            migrations["table"] = args["migrations_table"]
            config["migrations"] = migrations

        return config

    @classmethod
    def from_all_sources(cls, cli_args: Dict[str, Any]) -> "DbliftConfig":
        """Load config from file, env, and CLI args, with correct precedence (args > env > file > defaults)."""
        # Load from file if specified
        config_file = cli_args.get("config_file")
        file_config = {}
        if config_file:
            file_config = cls._load_yaml_file(config_file)
        # Load from env
        env_config = cls.from_env_dict()
        # Load from args
        args_config = cls.from_args_dict(cli_args)
        # Merge precedence: args > env > file.
        merged = cls.merge_config_data(file_config, env_config)
        merged = cls.merge_config_data(merged, args_config)
        return cls.from_dict(merged)

    @classmethod
    def from_file(cls, config_file: Union[str, Path]) -> "DbliftConfig":
        """Load configuration from a YAML file.

        Args:
            config_file: Path to the configuration file

        Returns:
            A DbliftConfig instance

        Raises:
            FileNotFoundError: If the config file does not exist
            yaml.YAMLError: If the config file is not valid YAML
        """
        try:
            with open(config_file, "r") as f:
                config_data = yaml.safe_load(f)
                config_data = _resolve_env_placeholders(config_data)
                if not config_data:
                    raise yaml.YAMLError("Empty or invalid YAML file")
                return cls.from_dict(config_data)
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file not found: {config_file}")
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Invalid YAML in config file: {e}")

    @classmethod
    def load_config_data_from_yaml(cls, config_file: Union[str, Path]) -> Dict[str, Any]:
        """Load YAML as a dict with env placeholders resolved (for merge onto defaults).

        When building config, merging this dict preserves keys omitted from the file
        (e.g. no ``database:`` section keeps :meth:`default` database settings).
        """
        with open(config_file, "r") as f:
            data = yaml.safe_load(f)
        if not data:
            return {}
        resolved = _resolve_env_placeholders(data)
        return resolved if isinstance(resolved, dict) else {}

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "database": self.database.to_dict(),
            "migrations": {
                "directory": self.migrations.directory,
                "table": self.migrations.table,
                "recursive": self.migrations.recursive,
                "script_encoding": self.migrations.script_encoding,
                "detect_encoding": self.migrations.detect_encoding,
            },
            "logging": {
                "level": self.logging.level,
                "file": self.logging.file,
                **(
                    {"directory": self.logging.directory}
                    if getattr(self.logging, "directory", None)
                    else {}
                ),
            },
            "baseline_version": self.baseline_version,
            "target_version": self.target_version,
            "dry_run": self.dry_run,
            "undo": self.undo,
            "installed_by": self.installed_by,
            "mark_as_executed": self.mark_as_executed,
            "strict_mode": self.strict_mode,
            "clean_disabled": self.clean_disabled,
            "history_table": self.history_table,
            "snapshot_table": self.snapshot_table,
            "max_snapshots": self.max_snapshots,
            "journal_enabled": self.journal_enabled,
            # Error handling configuration
            "error_handling_enabled": self.error_handling_enabled,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "retry_backoff": self.retry_backoff,
            "retry_jitter": self.retry_jitter,
        }

        # Include optional fields if they have values
        if self.extra_params:
            result["extra_params"] = self.extra_params

        # Include additional migration directories if available
        if self.migrations.directories:
            from typing import cast

            migrations_dict = cast(Dict[str, Any], result["migrations"])
            migrations_dict["directories"] = self.migrations.directories

        if self.tags:
            result["tags"] = self.tags

        if self.exclude_tags:
            result["exclude_tags"] = self.exclude_tags

        if self.versions:
            result["versions"] = self.versions

        if self.exclude_versions:
            result["exclude_versions"] = self.exclude_versions

        if self.placeholders:
            result["placeholders"] = self.placeholders

        if self.journal_dir:
            result["journal_dir"] = self.journal_dir

        if self.log_dir:
            result["log_dir"] = self.log_dir

        if self.retryable_error_categories:
            from typing import cast

            result["retryable_error_categories"] = cast(Any, self.retryable_error_categories)

        return result

    @classmethod
    def from_args(cls, args: Any) -> "DbliftConfig":
        """Create a DbliftConfig instance from argparse.Namespace or dict-like args.
        Args:
            args: argparse.Namespace or dict with CLI arguments
        Returns:
            DbliftConfig instance
        """
        # Convert Namespace to dict if needed
        if hasattr(args, "__dict__"):
            args_dict = vars(args)
        else:
            args_dict = dict(args)
        return cls.from_all_sources(args_dict)

    @staticmethod
    def _load_yaml_file(path: Union[str, Path]) -> Dict[str, Any]:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return cast(Dict[str, Any], data)
