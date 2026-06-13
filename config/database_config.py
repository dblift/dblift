import re
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, Optional, Type

from config._credential_masking import mask_credentials
from config._url_builder_mixin import UrlBuilderMixin

# Constants will be ported separately if needed
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30
ORACLE_DEFAULT_PORT = 1521


def _detect_dialect_from_url(url: str) -> str:
    """Resolve dialect from the URL scheme only (B10-BUG-22).

    Returns the dialect's canonical name (resolved through the plugin
    registry — aliases like ``postgres`` / ``sqlite3`` map to their
    canonical primary names) or ``""`` when the scheme is unknown.

    Story 26-11: dropped the hardcoded ``_SCHEME_TO_DIALECT`` dict in
    favour of ``ProviderRegistry.canonical_dialect_name``. Adding a
    new dialect = drop a plugin folder; the URL-scheme lookup
    follows automatically.
    """
    if not url:
        return ""
    url_lower = url.strip().lower()
    if url_lower.startswith("jdbc:"):
        return ""
    if url_lower.startswith("ibm_db_sa://"):
        vendor = "ibm_db_sa"
    else:
        vendor = urllib.parse.urlparse(url_lower).scheme.split("+", 1)[0]
    from db.provider_registry import ProviderRegistry

    return ProviderRegistry.canonical_dialect_name(vendor) or ""


def register_database_type(
    db_type: str,
) -> Callable[[Type["BaseDatabaseConfig"]], Type["BaseDatabaseConfig"]]:
    """Decorator to register a database type with its configuration class."""

    def decorator(cls: Type["BaseDatabaseConfig"]) -> Type["BaseDatabaseConfig"]:
        BaseDatabaseConfig._registry[db_type] = cls
        return cls

    return decorator


# ---------------------------------------------------------------------------
# ``BaseDatabaseConfig.create`` decomposition helpers (PR-H14).
#
# Each helper covers one phase of the previously F-ranked monolith so the
# orchestrator can read top-to-bottom as a sequence of named steps. They are
# module-level (matching the G6 / G7 pattern) and private — the public entry
# point remains ``BaseDatabaseConfig.create`` / ``.from_dict``.
# ---------------------------------------------------------------------------


def _infer_type_from_url_scheme(data: Dict[str, Any]) -> None:
    """Phase 1: infer a missing ``type`` from well-known URL prefixes.

    No-op when ``type`` is already set, no URL is supplied, or the URL uses an
    unsupported legacy scheme.
    """
    db_type = data.get("type", "").lower()
    url = data.get("url")
    if not db_type and url:
        _normalize_sqlite_url_alias(data)
        url = str(data.get("url") or "")
        url_lower = url.lower()
        if url_lower.startswith(("sqlite:", "sqlite3:")):
            data["type"] = "sqlite"  # lint: allow-dialect-string: URL-scheme inference
            return
        scheme = url_lower.split(":", 1)[0].split("+", 1)[0]
        if scheme:
            canonical = _native_canonical_from_scheme(scheme)
            if canonical:
                data["type"] = canonical


def _native_canonical_from_scheme(scheme: str) -> Optional[str]:
    """Return the canonical dialect for native plugin URL schemes only."""
    if not scheme:
        return None
    from db.provider_registry import ProviderRegistry

    canonical = ProviderRegistry.canonical_dialect_name(scheme)
    if canonical and ProviderRegistry.is_native_dialect(canonical):
        return canonical
    return None


def _normalize_sqlite_url_alias(data: Dict[str, Any]) -> None:
    """Normalize sqlite3: URL aliases to sqlite: before SQLiteConfig is built."""
    url = data.get("url")
    if isinstance(url, str) and url.strip().lower().startswith("sqlite3:"):
        data["url"] = f"sqlite:{url.strip()[len('sqlite3:'):]}"


def _infer_type_from_uri(data: Dict[str, Any], url: str) -> None:
    """Handle bare ``sqlite:`` / ``sqlite3:`` URIs (PEP-249 / RFC 8085 style).

    Unknown schemes are left for normal validation so secret/offline URLs can
    still flow through the incomplete-config path when requested.
    """
    _normalize_sqlite_url_alias(data)
    url = str(data.get("url") or url)
    url_l = (url or "").strip().lower()
    if url_l.startswith("sqlite3:"):
        data["type"] = "sqlite"  # lint: allow-dialect-string: URL-scheme inference
    elif url_l.startswith("sqlite:"):
        data["type"] = "sqlite"  # lint: allow-dialect-string: URL-scheme inference
    else:
        scheme = url_l.split(":", 1)[0].split("+", 1)[0]
        canonical = _native_canonical_from_scheme(scheme)
        if canonical:
            data["type"] = canonical
            return


def _hydrate_from_native_url(data: Dict[str, Any], url: str) -> None:
    """Merge generic SQLAlchemy URL fields into ``data`` in place."""
    try:
        from sqlalchemy.engine import make_url

        parsed_url = make_url(url)
        if parsed_url.host:
            data["host"] = parsed_url.host
        if parsed_url.port is not None:
            data["port"] = parsed_url.port
        if parsed_url.database:
            data["database"] = parsed_url.database
        if parsed_url.username and not data.get("username"):
            data["username"] = parsed_url.username
        if parsed_url.password and not data.get("password"):
            data["password"] = parsed_url.password
        query = {key: [str(value)] for key, value in dict(parsed_url.query).items()}
    except Exception:
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname:
            data["host"] = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is not None:
            data["port"] = port
        database = parsed.path.lstrip("/")
        if database:
            data["database"] = urllib.parse.unquote(database)

        username = urllib.parse.unquote(parsed.username) if parsed.username else None
        password = urllib.parse.unquote(parsed.password) if parsed.password else None
        if username and not data.get("username"):
            data["username"] = username
        if password and not data.get("password"):
            data["password"] = password

        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if query:
        if not data.get("extra_params") or not isinstance(data.get("extra_params"), dict):
            data["extra_params"] = {}
        from db.provider_registry import ProviderRegistry

        schema_param_names = {
            str(param).lower()
            for param in getattr(
                ProviderRegistry.get_quirks((data.get("type") or "").lower()),
                "native_url_schema_params",
                ("currentSchema",),
            )
        }
        for key, values in query.items():
            value = values[-1] if values else ""
            if key == "user" and not data.get("username"):
                data["username"] = value
            elif key == "password" and not data.get("password"):
                data["password"] = value
            elif key.lower() in schema_param_names and not data.get("schema"):
                data["schema"] = value
                if isinstance(data["extra_params"], dict):
                    data["extra_params"][key] = value
            elif isinstance(data["extra_params"], dict):
                data["extra_params"][key] = value


def _apply_url_overrides(cls: Type["BaseDatabaseConfig"], data: Dict[str, Any]) -> None:
    """Phase 2: hydrate ``data`` from the URL or enforce the URL requirement.

    When no URL is supplied and the dialect is not native, raises unless the
    caller has opted into ``_allow_incomplete``.
    """
    from db.provider_registry import ProviderRegistry

    url = data.get("url")
    db_type = (data.get("type") or "").lower()
    if url:
        _normalize_sqlite_url_alias(data)
        url = str(data.get("url") or "")
        url_text = str(url)
        url_lower = url_text.lower()
        if url_lower.startswith("jdbc:"):
            raise ValueError("Legacy database URLs are no longer supported; use a SQLAlchemy URL")
        # _allow_incomplete is set when the URL could not be parsed (e.g. an
        # unresolved secret URI in offline mode). Skip hydration/inference so that
        # `dblift plan` with `database.url: vault://...` doesn't mutate fields from
        # the secret URI before a connection is opened.
        if data.get("_allow_incomplete"):
            return
        if ProviderRegistry.is_native_dialect(db_type):
            _hydrate_from_native_url(data, url_text)
            return
        _infer_type_from_uri(data, url)
        return

    if not data.get("_allow_incomplete") and not (
        data.get("host") or data.get("database") or data.get("path") or data.get("database_name")
    ):
        if ProviderRegistry.is_native_dialect(db_type):
            return
        raise ValueError("Database URL is required (use --db-url)")


def _resolve_config_class(
    cls: Type["BaseDatabaseConfig"], db_type: str
) -> Optional[Type["BaseDatabaseConfig"]]:
    """Look up the registered config subclass for ``db_type``.

    Resolution order (first hit wins):

    1. The legacy ``BaseDatabaseConfig._registry`` dict — populated by the
       ``@register_database_type`` decorator on first-party config subclasses.
    2. ``PluginInfo.config_class`` declared directly on the plugin metadata
       (roadmap action #11). Lets third-party plugins ship a config class
       without modifying ``config/_subclasses/``.
    3. The plugin's ``config_dialect`` pointer, which falls back to the
       parent dialect's registry entry (e.g. ``mariadb`` → ``mysql``).

    Returns ``None`` when no class is found — the caller decides between the
    incomplete-stub path and ``ValueError``.
    """
    config_class = cls._registry.get(db_type)
    if config_class:
        return config_class

    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    plugin = ProviderRegistry._plugins.get(db_type)
    if plugin is None:
        return None

    # Path 2: direct plugin-declared config class. Validate the runtime
    # type so a misconfigured plugin doesn't silently swap the contract.
    direct = getattr(plugin, "config_class", None)
    if direct is not None and isinstance(direct, type) and issubclass(direct, BaseDatabaseConfig):
        plugin_cls: Type[BaseDatabaseConfig] = direct
        return plugin_cls

    # Path 3: alias to a parent dialect's registration.
    parent = getattr(plugin, "config_dialect", None)
    if parent:
        return cls._registry.get(parent)
    return None


def _build_incomplete_stub(data: Dict[str, Any], db_type: str) -> "BaseDatabaseConfig":
    """Return a ``_IncompleteDatabaseConfig`` stub for ``_allow_incomplete`` callers.

    The stub carries the partial data without crashing on missing required
    fields; callers that set ``_allow_incomplete`` are expected to merge this
    result into a full config and must not attempt to connect with it directly.
    """
    base_fields = set(f.name for f in BaseDatabaseConfig.__dataclass_fields__.values())
    filtered = {k: v for k, v in data.items() if k in base_fields}
    filtered.setdefault("type", db_type or "")
    return _IncompleteDatabaseConfig(**filtered)


def _coerce_port_to_int(data: Dict[str, Any]) -> None:
    """Phase 5: coerce ``data["port"]`` to ``int`` if present.

    Raises ``ValueError`` with the original ``Invalid port value:`` message on
    a failed cast so error-text contracts stay byte-identical.
    """
    port = data.get("port")
    if port is not None:
        try:
            data["port"] = int(port)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid port value: {port}")


def _validate_required_fields(data: Dict[str, Any], db_type: str) -> None:
    """Phase 6: enforce required-field invariants for non-native, non-incomplete configs.

    Skips validation entirely for native dialects and ``_allow_incomplete``
    callers. Preserves the original error-message wording verbatim:
    - ``Missing required fields: url``
    - ``Database username is required (either in config or in URL)``
    - ``Database password is required (either in config or in URL)``
    """
    from db.provider_registry import ProviderRegistry

    if data.get("_allow_incomplete"):
        return

    if ProviderRegistry.is_native_dialect(db_type):
        quirks = ProviderRegistry.get_quirks(db_type)
        if not quirks.has_connection_identifier(data):
            raise ValueError(quirks.missing_connection_identifier_hint)
        if quirks.requires_credentials:
            if not data.get("username"):
                raise ValueError("Database username is required (either in config or in URL)")
            if not data.get("password"):
                raise ValueError("Database password is required (either in config or in URL)")
        return

    required_fields = ["url"]
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

    if not data.get("username"):
        raise ValueError("Database username is required (either in config or in URL)")
    if not data.get("password"):
        raise ValueError("Database password is required (either in config or in URL)")


def _ensure_properties_dict(data: Dict[str, Any]) -> None:
    """Phase 3: normalise ``data['properties']`` to an empty dict if missing or non-dict."""
    if not data.get("properties") or not isinstance(data.get("properties"), dict):
        data["properties"] = {}
    if not data.get("extra_params") or not isinstance(data.get("extra_params"), dict):
        data["extra_params"] = {}


def _apply_native_default_schema(data: Dict[str, Any], db_type: str) -> None:
    """Apply plugin-owned native default schema when no schema was supplied."""
    if data.get("schema"):
        return
    from db.provider_registry import ProviderRegistry

    if not ProviderRegistry.is_native_dialect(db_type):
        return
    default_schema = getattr(ProviderRegistry.get_quirks(db_type), "default_schema_name", "")
    if default_schema:
        data["schema"] = default_schema


def _resolve_config_or_stub(
    cls: Type["BaseDatabaseConfig"], data: Dict[str, Any], db_type: str
) -> Any:
    """Phase 4: resolve the config subclass for ``db_type``.

    Returns one of:
    - a ``Type[BaseDatabaseConfig]`` when the dialect is registered,
    - a built ``_IncompleteDatabaseConfig`` instance when the dialect is
      unknown and ``_allow_incomplete`` is set,
    - raises ``ValueError("Unsupported database type: ...")`` otherwise.
    """
    config_class = _resolve_config_class(cls, db_type)
    if config_class:
        return config_class
    if data.get("_allow_incomplete"):
        return _build_incomplete_stub(data, db_type)
    raise ValueError(f"Unsupported database type: {db_type}")


def _instantiate_config(
    config_class: Type["BaseDatabaseConfig"], data: Dict[str, Any]
) -> "BaseDatabaseConfig":
    """Phase 7: filter ``data`` to ``config_class``'s dataclass fields and instantiate."""
    config_fields = set(f.name for f in config_class.__dataclass_fields__.values())
    filtered_data = {k: v for k, v in data.items() if k in config_fields}
    # NOTE: Debug logging omitted - filtered_data contains sensitive credentials
    return config_class(**filtered_data)


@dataclass
class BaseDatabaseConfig(UrlBuilderMixin, ABC):
    """Base class for all database configurations."""

    # Registry of database types to their config classes
    _registry: ClassVar[Dict[str, Type["BaseDatabaseConfig"]]] = {}

    @staticmethod
    def _safe_str(value: Optional[str], default: str = "") -> str:
        """Safely handle optional string values."""
        return value if value is not None else default

    # Common parameters across all database types
    type: str
    url: str = ""
    username: str = ""
    password: str = ""
    schema: str = ""
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None  # Keep this for backward compatibility
    connection_timeout: int = DEFAULT_CONNECTION_TIMEOUT_SECONDS

    # Dblift-specific parameters (not used in database connection)
    installed_by: Optional[str] = None

    # Additional database parameters
    extra_params: Dict[str, str] = field(default_factory=dict)
    properties: Dict[str, str] = field(default_factory=dict)
    # Cross-dialect typed options and session variables
    options: Dict[str, Any] = field(default_factory=dict)
    session_variables: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize the database config."""
        if not hasattr(self, "type"):
            raise ValueError("Database type is required")

        if self.schema and not re.match(r"^[a-zA-Z0-9_]+$", self.schema):
            raise ValueError(
                f"Invalid schema name: {self.schema!r}. "
                "Schema names must contain only ASCII letters, digits, and underscores."
            )

        # Convert port to int if needed
        if isinstance(self.port, str):
            # mypy unreachable workaround: do not attempt conversion here
            pass

    @classmethod
    def from_url(cls, url: str) -> "BaseDatabaseConfig":
        """Create a database config from a URL.

        Legacy vendor transport URLs are intentionally rejected in v2.
        """
        if url.startswith("jdbc:"):
            raise ValueError("Legacy database URLs are no longer supported; use a SQLAlchemy URL")
        return cls.create({"url": url})

    @classmethod
    def create(cls, data: Dict[str, Any]) -> "BaseDatabaseConfig":
        # NOTE: per-dialect subclasses register themselves at the bottom of this
        # module via eager imports of ``config._subclasses.*_config``; the
        # ``BaseDatabaseConfig._registry`` lookup below depends on those
        # registrations being in place by the time ``create()`` runs.
        # Phase 1: infer a missing ``type`` from well-known URL schemes.
        _infer_type_from_url_scheme(data)

        # Phase 2: hydrate ``data`` from the URL or raise if URL is mandatory and missing.
        _apply_url_overrides(cls, data)

        # Phase 3: ensure ``properties`` is always a dict.
        _ensure_properties_dict(data)

        # Phase 4: resolve the registered config subclass (with stub fallback
        # for ``_allow_incomplete``). May short-circuit out of ``create``.
        db_type = (data.get("type") or "").lower()
        config_class = _resolve_config_or_stub(cls, data, db_type)
        if not isinstance(config_class, type):
            return config_class  # type: ignore[no-any-return]  # already a fully-built stub instance

        # Phase 5: coerce port to int once a config class is in scope.
        _coerce_port_to_int(data)

        # Phase 6: final required-field validation.
        _validate_required_fields(data, db_type)

        _apply_native_default_schema(data, db_type)

        # Phase 7: filter unknown fields and instantiate the config class.
        return _instantiate_config(config_class, data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseDatabaseConfig":
        """Create a database config from a dictionary."""
        return cls.create(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary.

        WARNING: This method includes sensitive credentials in plain text.
        Use to_safe_dict() for logging or display purposes.
        """
        result: Dict[str, Any] = {
            "type": self.type,
            "url": self.url,
            "username": self.username,
            "password": self.password,
            "schema": self.schema,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "connection_timeout": self.connection_timeout,
            "installed_by": self.installed_by,
            # Add maps
            "extra_params": self.extra_params or {},
            "properties": self.properties or {},
            "options": self.options or {},
            "session_variables": self.session_variables or {},
        }
        return result

    def to_safe_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with sensitive values masked.

        Use this method for logging, debugging, or display purposes
        to prevent credential exposure.

        Returns:
            Dictionary with password, account_key, and URL credentials masked.
        """
        return mask_credentials(self.to_dict())

    def __repr__(self) -> str:
        """Return a safe string representation that doesn't expose credentials."""
        safe_dict = self.to_safe_dict()
        return f"{self.__class__.__name__}({safe_dict})"

    @abstractmethod
    def build_connection_string(self) -> str:
        """Build a native connection string (native).

        All concrete subclasses must override this method.
        Implementations that store a pre-built URL should return ``self.url`` directly.

        Returns:
            str: The native database connection string.
        """

    def get_connection_props(self) -> Dict[str, str]:
        """Get driver connection properties.

        Returns:
            Dict[str, str]: Dictionary of driver connection properties.

        Note:
            Dblift-specific parameters (like installed_by) are not included.
            Username and password are not included as they are passed separately to get_connection.
        """
        props = {
            "loginTimeout": str(self.connection_timeout),
        }

        if self.extra_params:
            for key, value in self.extra_params.items():
                # Also skip username and password as they are passed separately
                if key.lower() not in ["installed_by", "user", "username", "password"]:
                    props[key] = value

        return props


@dataclass
class _IncompleteDatabaseConfig(BaseDatabaseConfig):
    """Concrete stub returned when _allow_incomplete=True and no registered type is found.

    Carries whatever partial data was provided. Raises on build_connection_string()
    since a partial config cannot open a real connection.
    """

    def build_connection_string(self) -> str:
        raise NotImplementedError(
            "Cannot connect with incomplete configuration. "
            "Provide 'type' and 'url' to create a complete database config."
        )


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------


class DatabaseConfig:
    """Public factory facade for database configuration objects."""

    def __new__(cls, **kwargs: Any) -> BaseDatabaseConfig:  # type: ignore[misc]
        return BaseDatabaseConfig.create(kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BaseDatabaseConfig:
        return BaseDatabaseConfig.create(data)

    @classmethod
    def from_url(cls, url: str) -> BaseDatabaseConfig:
        return BaseDatabaseConfig.from_url(url)


# ---------------------------------------------------------------------------
# Re-export per-dialect subclasses so the legacy
# ``from config.database_config import XxxConfig`` import path keeps working
# (used by ~25 test modules and a couple of production sites).
#
# These imports are intentionally at the bottom of the module: each subclass
# module imports ``BaseDatabaseConfig`` (and ``register_database_type``) from
# this file, so the symbols above must be fully defined before we load them.
# Importing the modules registers their classes via ``@register_database_type``.
#
# Roadmap action #11: third-party plugins do **not** need to add to this list
# — they declare ``config_class=MyConfig`` on their ``PluginInfo`` and
# ``_resolve_config_class`` (above) picks it up via the plugin registry. The
# eager imports below stay only because removing them would break the legacy
# import path; they aren't the modern entry point for new dialects.
# ---------------------------------------------------------------------------

from config._subclasses.cosmosdb_config import CosmosDbConfig  # noqa: E402, F401
from config._subclasses.db2_config import Db2Config  # noqa: E402, F401
from config._subclasses.dummy_config import DummyDatabaseConfig  # noqa: E402, F401
from config._subclasses.mysql_config import MySqlConfig  # noqa: E402, F401
from config._subclasses.oracle_config import OracleConfig  # noqa: E402, F401
from config._subclasses.postgresql_config import PostgreSqlConfig  # noqa: E402, F401
from config._subclasses.sqlite_config import SQLiteConfig  # noqa: E402, F401
from config._subclasses.sqlserver_config import SqlServerConfig  # noqa: E402, F401
