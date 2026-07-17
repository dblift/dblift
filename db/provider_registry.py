"""Provider registry for auto-discovery and registration of database provider plugins."""

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Tuple, Type

if TYPE_CHECKING:
    from config import DbliftConfig
    from core.logger import Log

from db.base_provider import BaseProvider
from db.base_quirks import BaseQuirks

ProviderTransport = Literal["native"]

_logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Metadata for a database provider plugin."""

    name: str
    version: str
    description: str
    dialects: List[str]  # Supported database dialects
    provider_class: Type[BaseProvider]
    transport: ProviderTransport = "native"
    # Epic 26: per-dialect behaviour-overlay class. None means use
    # ``BaseQuirks`` (no overrides). Plugins that need to customise
    # rendering/parsing/comparison declare a subclass here.
    quirks_class: Optional[Type[BaseQuirks]] = None
    # When set, ``BaseDatabaseConfig.create()`` resolves this dialect's
    # config class by looking up ``config_dialect`` in the registry instead
    # of the plugin's own name.  Use for dialects that share a parent config
    # (e.g. MariaDB → MySQL).  ``None`` means the plugin registers its own
    # config class or relies on one of its ``dialects`` aliases being registered.
    config_dialect: Optional[str] = None
    # Roadmap action #11: the config subclass this plugin owns. When set,
    # ``BaseDatabaseConfig.create()`` resolves the config class directly from
    # the plugin metadata (no need for the legacy ``@register_database_type``
    # decorator path or the eager-import block at the bottom of
    # ``config/database_config.py``). First-party plugins keep the decorator
    # path for compatibility — the field is the modern entry point for
    # third-party plugins that want to ship a config class without modifying
    # ``config/_subclasses/``. Stored as ``Type[Any]`` to dodge the circular
    # import between ``db.provider_registry`` and ``config.database_config``;
    # callers narrow at use site (see ``_resolve_config_class``).
    config_class: Optional[Type[Any]] = None
    # Native-driver URL construction belongs to the plugin, not to a
    # central dialect map. The callable receives the plugin-owned database
    # config instance and returns the SQLAlchemy URL for ``create_engine``.
    sqlalchemy_url_builder: Optional[Callable[[Any], str]] = None
    native_driver_module: Optional[str] = None


class NativeDriverManager:
    """Checks availability of plugin-declared native Python drivers."""

    @staticmethod
    def get_available_drivers(plugins: List[PluginInfo]) -> Dict[str, bool]:
        """Return native driver import availability for registered plugins."""
        return {
            plugin.name: NativeDriverManager.check_driver_installed(plugin) for plugin in plugins
        }

    @staticmethod
    def check_driver_installed(plugin: PluginInfo) -> bool:
        """Return whether the plugin's optional native driver can be imported."""
        if not plugin.native_driver_module:
            return True
        try:
            return importlib.util.find_spec(plugin.native_driver_module) is not None
        except ModuleNotFoundError:
            return False

    @staticmethod
    def validate_driver_for_type(
        db_type: str, plugin_info: Optional[PluginInfo]
    ) -> Tuple[bool, Optional[str]]:
        """Validate plugin-declared native driver availability."""
        if plugin_info and not NativeDriverManager.check_driver_installed(plugin_info):
            module = plugin_info.native_driver_module or "unknown"
            return False, f"Native driver module '{module}' is not installed for {db_type}"
        return True, None


class ProviderRegistry:
    """Registry for database provider plugins with auto-discovery."""

    _plugins: Dict[str, PluginInfo] = {}
    _discovered: bool = False
    # Story 26-3 / PR #241 Bugbot: cache resolved Quirks instances per
    # dialect string. Quirks subclasses are stateless behaviour
    # overlays (no per-call state), so reusing a single instance per
    # dialect avoids re-instantiating on every framework call site
    # (``_quirks_for`` is hit several times per ``generate_ddl``).
    _quirks_cache: Dict[str, BaseQuirks] = {}

    ENTRY_POINT_GROUP = "dblift.providers"

    @classmethod
    def discover_plugins(cls) -> None:
        """Auto-discover provider plugins.

        Story 26-12: discovery happens in two passes.

        1. Entry-point pass — reads ``importlib.metadata.entry_points
           (group="dblift.providers")``. First-party plugins are
           registered here when the wheel is installed (``pip install
           dblift``); third-party plugins (``pip install
           dblift-snowflake``) are registered the same way without
           modifying ``core/``.

        2. Filesystem fallback — scans ``db/plugins/<X>/`` for any
           dialect not already registered. Covers in-tree development
           (e.g. running tests against a source checkout without
           installing the package) and old plugin layouts that
           predate the entry-point group.
        """
        if cls._discovered:
            return

        cls._discover_via_entry_points()
        cls._discover_via_filesystem()

        cls._discovered = True

    @classmethod
    def _discover_via_entry_points(cls) -> None:
        """Read ``dblift.providers`` entry-points and register each one."""
        try:
            from importlib import metadata
        except ImportError:  # pragma: no cover - Python < 3.8
            return

        try:
            entry_points: List[Any] = list(metadata.entry_points(group=cls.ENTRY_POINT_GROUP))
        except TypeError:
            # Python < 3.10 didn't accept the keyword form; fall back.
            all_eps = metadata.entry_points()
            getter = getattr(all_eps, "get", None)
            entry_points = list(getter(cls.ENTRY_POINT_GROUP, [])) if getter else []
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning(f"Failed to read entry-points for {cls.ENTRY_POINT_GROUP}: {exc}")
            return

        for ep in entry_points:
            try:
                plugin_info = ep.load()
            except Exception as exc:
                _logger.warning(f"Failed to load plugin entry-point {ep.name!r}: {exc}")
                continue
            if not isinstance(plugin_info, PluginInfo):
                _logger.warning(
                    f"Entry-point {ep.name!r} returned {type(plugin_info).__name__}, "
                    "expected PluginInfo; ignoring."
                )
                continue
            cls.register_plugin(plugin_info)

    @classmethod
    def _discover_via_filesystem(cls) -> None:
        """Scan ``db/plugins/<X>/`` for plugins not already registered.

        Used as a fallback in source-checkout scenarios where
        entry-points are not available. Plugins already registered by
        the entry-point pass are skipped.
        """
        plugins_dir = Path(__file__).parent / "plugins"
        if not plugins_dir.exists():
            return

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
                continue
            # Skip when already registered (by entry-point or earlier scan).
            if plugin_dir.name.lower() in cls._plugins:
                continue

            try:
                plugin_info = cls._load_plugin(plugin_dir)
                if plugin_info:
                    cls.register_plugin(plugin_info)
            except Exception as e:
                _logger.warning(f"Failed to load plugin from {plugin_dir}: {e}")

    @classmethod
    def _load_plugin(cls, plugin_dir: Path) -> Optional[PluginInfo]:
        """Load plugin metadata from a plugin directory.

        Args:
            plugin_dir: Path to plugin directory

        Returns:
            PluginInfo if plugin is valid, None otherwise
        """
        init_file = plugin_dir / "__init__.py"
        if not init_file.exists():
            return None

        plugin_name = plugin_dir.name

        # Use ``importlib.import_module`` rather than
        # ``importlib.util.spec_from_file_location`` so the plugin
        # ends up in ``sys.modules`` once. The spec-from-file path
        # creates an isolated module instance — call sites that
        # later ``import db.plugins.<X>`` get a *different* class
        # object with the same name, breaking ``isinstance`` /
        # ``is`` checks downstream (story 26-13 mariadb tests).
        import importlib

        try:
            module = importlib.import_module(f"db.plugins.{plugin_name}")
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning(f"Failed to import db.plugins.{plugin_name}: {exc}")
            return None

        # Extract metadata
        name = getattr(module, "__plugin_name__", plugin_name)
        version = getattr(module, "__plugin_version__", "1.0.0")
        description = getattr(module, "__plugin_description__", f"{name} database provider")
        dialects = getattr(module, "__plugin_dialects__", [name])
        transport: ProviderTransport = "native"

        # Epic 27 + action #11: read the exported ``plugin.py:PLUGIN`` constant
        # (entry-point-style declaration) up front. Importing plugin.py also
        # triggers any ``@register_database_type`` decorators on the config
        # class so the legacy ``BaseDatabaseConfig._registry`` lookup keeps
        # working. This declaration is also the fallback source for the
        # provider/quirks classes below, so factory-built engines that ship no
        # ``provider.py`` / ``quirks.py`` (the PostgreSQL-compatible family) are
        # discovered identically to how the entry-point path loads them.
        declared: Optional[PluginInfo] = None
        plugin_py = plugin_dir / "plugin.py"
        if plugin_py.exists():
            try:
                import importlib as _il

                pm = _il.import_module(f"db.plugins.{plugin_name}.plugin")
                candidate = getattr(pm, "PLUGIN", None)
                if isinstance(candidate, PluginInfo):
                    declared = candidate
            except Exception:
                declared = None

        # Get provider class: prefer ``__plugin_class__`` / ``__all__`` /
        # naming convention from the package, then fall back to the class
        # declared on ``PLUGIN``.
        provider_class: Optional[Type[BaseProvider]] = None
        provider_class_name = getattr(module, "__plugin_class__", None)
        if provider_class_name:
            provider_class = getattr(module, provider_class_name, None)
        elif hasattr(module, "__all__") and module.__all__:
            provider_class = getattr(module, module.__all__[0], None)
        else:
            for attr_name in dir(module):
                if attr_name.endswith("Provider") and not attr_name.startswith("_"):
                    maybe = getattr(module, attr_name)
                    if isinstance(maybe, type) and issubclass(maybe, BaseProvider):
                        provider_class = maybe
                        break

        if not (isinstance(provider_class, type) and issubclass(provider_class, BaseProvider)):
            provider_class = declared.provider_class if declared else None

        if provider_class is None or not (
            isinstance(provider_class, type) and issubclass(provider_class, BaseProvider)
        ):
            return None

        # Epic 26: optional quirks class. Resolve by importing
        # ``db/plugins/<X>/quirks.py`` and picking the first class whose name
        # ends in ``Quirks``; fall back to the quirks class declared on
        # ``PLUGIN`` (factory-built engines carry it there and ship no
        # ``quirks.py``). Plugins declaring neither fall back to BaseQuirks.
        quirks_class = cls._discover_quirks_class(plugin_dir, plugin_name)
        if quirks_class is None and declared is not None:
            quirks_class = declared.quirks_class

        config_dialect: Optional[str] = declared.config_dialect if declared else None
        config_class: Optional[Type[Any]] = declared.config_class if declared else None
        sqlalchemy_url_builder: Optional[Callable[[Any], str]] = (
            declared.sqlalchemy_url_builder if declared else None
        )
        native_driver_module: Optional[str] = declared.native_driver_module if declared else None

        return PluginInfo(
            name=name,
            version=version,
            description=description,
            dialects=dialects,
            provider_class=provider_class,
            transport=transport,
            quirks_class=quirks_class,
            config_dialect=config_dialect,
            config_class=config_class,
            sqlalchemy_url_builder=sqlalchemy_url_builder,
            native_driver_module=native_driver_module,
        )

    @classmethod
    def _discover_quirks_class(
        cls, plugin_dir: Path, plugin_name: str
    ) -> Optional[Type[BaseQuirks]]:
        """Locate the plugin's ``Quirks`` subclass if present (Epic 26).

        Returns ``None`` when the plugin has not yet declared a
        ``quirks.py``; the registry then serves a vanilla
        :class:`BaseQuirks` instance to callers.
        """
        quirks_file = plugin_dir / "quirks.py"
        if not quirks_file.exists():
            return None

        # Same reasoning as ``_load_plugin``: import via the public
        # module name so there's only one class object in
        # ``sys.modules``. ``spec_from_file_location`` creates an
        # isolated module whose classes don't compare ``is``-equal to
        # the same class imported normally elsewhere.
        import importlib

        try:
            module = importlib.import_module(f"db.plugins.{plugin_name}.quirks")
        except Exception as exc:
            _logger.warning(f"Failed to load quirks for plugin {plugin_name}: {exc}")
            return None

        # Respect an explicit ``__all__`` declaration — including an
        # explicit empty list, which means "export nothing". The
        # naive ``getattr(...) or dir(module)`` collapses ``[]`` to
        # ``dir(module)`` because empty lists are falsy, defeating
        # an intentional opt-out.
        declared = getattr(module, "__all__", None)
        attr_names = declared if declared is not None else dir(module)
        for attr_name in attr_names:
            if not attr_name.endswith("Quirks") or attr_name.startswith("_"):
                continue
            candidate = getattr(module, attr_name, None)
            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseQuirks)
                and candidate is not BaseQuirks
            ):
                return candidate
        return None

    @classmethod
    def register_plugin(cls, plugin_info: PluginInfo) -> None:
        """Register a provider plugin.

        Args:
            plugin_info: Plugin metadata
        """
        # Register by primary name
        cls._plugins[plugin_info.name.lower()] = plugin_info

        # Register by all dialects
        for dialect in plugin_info.dialects:
            cls._plugins[dialect.lower()] = plugin_info

    @classmethod
    def get_provider_transport(cls, db_type: str) -> ProviderTransport:
        """Return the registered transport family for a database type.

        Unknown providers still return ``"native"`` because v2 has a single
        provider transport family.
        """
        if not cls._discovered:
            cls.discover_plugins()
        return "native"

    @classmethod
    def get_provider_class(cls, db_type: str) -> Optional[Type[BaseProvider]]:
        """Get provider class for a database type.

        Args:
            db_type: Database type (e.g., "postgresql", "mysql")

        Returns:
            Provider class if found, None otherwise
        """
        # Ensure plugins are discovered
        if not cls._discovered:
            cls.discover_plugins()

        plugin_info = cls._plugins.get(db_type.lower())
        if plugin_info:
            return plugin_info.provider_class

        return None

    @classmethod
    def get_provider_by_url(cls, database_url: str) -> Optional[Type[BaseProvider]]:
        """Get provider class for a native database URL scheme."""
        if not database_url:
            return None
        if database_url.strip().lower().startswith("jdbc:"):
            return None
        import urllib.parse

        url = database_url.strip().lower()
        if url.startswith("ibm_db_sa://"):
            scheme = "ibm_db_sa"
        else:
            scheme = urllib.parse.urlparse(url).scheme.split("+", 1)[0]
        dialect = cls.canonical_dialect_name(scheme)
        return cls.get_provider_class(dialect) if dialect else None

    @classmethod
    def get_quirks(cls, db_type: str) -> BaseQuirks:
        """Return the :class:`DialectQuirks` instance for a database type (Epic 26).

        Plugins without a declared ``quirks_class`` get a vanilla
        :class:`BaseQuirks` keyed by ``db_type``; plugins with one
        get an instance of that subclass. Framework code calling
        ``provider.quirks.<hook>`` always gets a real object —
        never ``None`` — so call sites stay branch-free.

        Instances are cached per dialect string so that hot paths
        (e.g. ``SqlGenerator.generate_ddl`` calls ``_quirks_for``
        ~5x per object) reuse a single instance instead of
        re-instantiating on every call.
        """
        normalized = db_type.lower()
        cached = cls._quirks_cache.get(normalized)
        if cached is not None:
            return cached
        if not cls._discovered:
            cls.discover_plugins()
        plugin_info = cls._plugins.get(normalized)
        if plugin_info is not None and plugin_info.quirks_class is not None:
            # Pass the caller's normalized db_type so aliases
            # (e.g. ``"postgres"`` for the postgresql plugin) preserve
            # the invariant
            # ``provider.config.database.type == provider.quirks.dialect_name``.
            instance: BaseQuirks = plugin_info.quirks_class(dialect_name=normalized)
        else:
            instance = BaseQuirks(dialect_name=normalized)
        cls._quirks_cache[normalized] = instance
        return instance

    @classmethod
    def canonical_dialect_name(cls, alias: str) -> Optional[str]:
        """Resolve an alias to the plugin's canonical primary name.

        ``"postgres"`` -> ``"postgresql"``, ``"sqlite3"`` -> ``"sqlite"``,
        ``"mssql"`` -> ``"sqlserver"``, etc. Returns ``None`` for
        unknown aliases.

        Replaces hand-rolled alias maps in ``cli/`` and other top-level
        layers (Epic 26 followup).
        """
        if not cls._discovered:
            cls.discover_plugins()
        plugin_info = cls._plugins.get((alias or "").lower())
        if plugin_info is None:
            return None
        return plugin_info.name

    @classmethod
    def reference_dialect_name(cls) -> str:
        """Return the canonical name of the ANSI/generic reference dialect.

        This is the single registered plugin whose quirks set
        :attr:`db.base_quirks.BaseQuirks.is_ansi_reference_dialect` True
        (PostgreSQL today). dblift renders dialect-agnostic models — those
        with ``dialect is None`` — through this dialect's generator, so the
        no-dialect render default is a registry/plugin decision rather than a
        ``"postgresql"`` literal in ``core/``.

        Exactly one plugin must declare it (a first-party invariant); zero or
        more than one is a registration error and raises ``RuntimeError``.
        """
        winners = sorted(
            p.name for p in cls.list_plugins() if cls.get_quirks(p.name).is_ansi_reference_dialect
        )
        if len(winners) != 1:
            raise RuntimeError(
                "Exactly one plugin must set is_ansi_reference_dialect=True; " f"found {winners!r}."
            )
        return winners[0]

    @classmethod
    def canonical_dialect_name_for_capability(cls, capability: str) -> Optional[str]:
        """Return the canonical name of the plugin whose quirks set *capability*.

        ``capability`` is the name of a boolean :class:`db.base_quirks.BaseQuirks`
        attribute that uniquely identifies one plugin (e.g.
        ``"table_uses_filegroup_syntax"`` → SQL Server,
        ``"table_supports_inherits"`` → PostgreSQL,
        ``"table_supports_storage_params"`` → Oracle,
        ``"table_uses_storage_engine_clause"`` → MySQL). Lets framework code
        resolve a ``dialect_options`` namespace from the registry instead of
        hardcoding a dialect string literal (ADR-26 E story 26-5).

        Returns the single matching plugin's canonical name, or ``None`` when
        zero or more than one plugin advertise the capability (so callers can
        fall back without raising). Mirrors :meth:`reference_dialect_name` but
        is non-raising because the namespace lookup is best-effort.

        Only plugins whose *quirks class declares the attribute in its own
        class body* count — an inheriting plugin (e.g. MariaDB extends MySQL's
        quirks) does not become a second owner of an inherited capability, so
        the MySQL/MariaDB family resolves to the single canonical owner.
        """
        winners = []
        for plugin in cls.list_plugins():
            quirks_class = type(cls.get_quirks(plugin.name))
            # The owner is the plugin whose quirks class sets the flag truthy
            # in its *own* class body — an inheriting subclass (MariaDB ←
            # MySQL) that merely inherits the flag is not a second owner.
            if vars(quirks_class).get(capability):
                winners.append(plugin.name)
        winners = sorted(set(winners))
        if len(winners) != 1:
            return None
        return winners[0]

    @classmethod
    def is_native_dialect(cls, db_type: str) -> bool:
        """True when the dialect's plugin advertises ``transport='native'``.

        Used by config/loader paths that need to identify first-class native
        providers (CosmosDB, SQLite, and SQLAlchemy-backed dialects).
        """
        if not cls._discovered:
            cls.discover_plugins()
        plugin_info = cls._plugins.get((db_type or "").lower())
        if plugin_info is None:
            return False
        return getattr(plugin_info, "transport", "native") == "native"

    @classmethod
    def build_sqlalchemy_url(cls, database_config: Any) -> str:
        """Build a SQLAlchemy URL through the owning plugin metadata."""
        db_type = (getattr(database_config, "type", "") or "").lower()
        if not db_type:
            raise ValueError("Database type is required to build a SQLAlchemy URL")
        if not cls._discovered:
            cls.discover_plugins()
        plugin_info = cls._plugins.get(db_type)
        builder = plugin_info.sqlalchemy_url_builder if plugin_info is not None else None
        if builder is None:
            raise ValueError(
                f"{db_type} plugin must declare sqlalchemy_url_builder for native connections"
            )
        return builder(database_config)

    @classmethod
    def list_plugins(cls) -> List[PluginInfo]:
        """List all registered plugins.

        Returns:
            List of plugin metadata
        """
        # Ensure plugins are discovered
        if not cls._discovered:
            cls.discover_plugins()

        # Return unique plugins (by name)
        seen = set()
        plugins = []
        try:
            if isinstance(cls._plugins, dict):
                plugin_values = cls._plugins.values()
                for plugin_info in plugin_values:
                    if hasattr(plugin_info, "name") and plugin_info.name not in seen:
                        seen.add(plugin_info.name)
                        plugins.append(plugin_info)
        except (TypeError, AttributeError):
            # Handle case where _plugins is not a dict or is a Mock
            pass

        return plugins

    @classmethod
    def is_supported(cls, db_type: str) -> bool:
        """Check if a database type is supported.

        Args:
            db_type: Database type

        Returns:
            True if supported, False otherwise
        """
        return cls.get_provider_class(db_type) is not None

    @classmethod
    def create_provider(cls, config: "DbliftConfig", log: Optional["Log"] = None) -> "BaseProvider":
        """Create and return the appropriate database provider based on configuration.

        This method combines provider discovery and instantiation.

        Args:
            config: Application configuration containing database settings
            log: Optional logger for the provider

        Returns:
            The appropriate database provider instance

        Raises:
            ValueError: If the database type is not supported or configuration is invalid
        """
        if not config or not config.database or not config.database.type:
            raise ValueError("Invalid configuration: database type not specified")

        db_type = config.database.type.lower()

        # Use plugin registry to get provider class
        provider_class = cls.get_provider_class(db_type)

        if provider_class is None:
            try:
                plugins = cls.list_plugins()
                supported_types = [p.name for p in plugins] if plugins else []
            except (TypeError, AttributeError, Exception):
                # Handle case where plugins is not iterable or items don't have .name
                supported_types = []
            raise ValueError(
                f"Unsupported database type: {db_type}. "
                f"Supported types: {', '.join(supported_types) if supported_types else 'none available'}"
            )

        return provider_class(config, log)

    @classmethod
    def get_available_drivers(cls) -> Dict[str, bool]:
        """Get native Python driver availability for supported database types.

        Returns:
            Dictionary mapping database types to boolean availability status
        """
        return NativeDriverManager.get_available_drivers(cls.list_plugins())

    @classmethod
    def check_driver_installed(cls, db_type: str) -> bool:
        """Return whether the native driver for *db_type* is importable."""
        if not cls._discovered:
            cls.discover_plugins()
        plugin_info = cls._plugins.get(db_type.lower())
        if plugin_info is None:
            return False
        return NativeDriverManager.check_driver_installed(plugin_info)

    @classmethod
    def validate_database_configuration(cls, config: "DbliftConfig") -> Tuple[bool, Optional[str]]:
        """Validate database configuration.

        Args:
            config: Database configuration to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Préoccupation REGISTRE : validation config + lookup provider
        if not config or not config.database or not config.database.type:
            return False, "Database type not specified"

        db_type = config.database.type.lower()

        if db_type == "dummy":
            return True, None

        # Require *some* connection identifier — which attributes count is dialect-
        # specific and declared on the plugin's quirks (``connection_identifier_attrs``).
        # Native SQL providers default to ``("url",)``; CosmosDB also accepts
        # ``account_endpoint``; SQLite also accepts ``path``/``database``.
        quirks = cls.get_quirks(db_type)
        if not quirks.has_connection_identifier(config.database):
            return False, quirks.missing_connection_identifier_hint

        provider_class = cls.get_provider_class(db_type)
        if provider_class is None:
            try:
                plugins = cls.list_plugins()
                supported_types = [p.name for p in plugins] if plugins else []
            except (TypeError, AttributeError):
                supported_types = []
            joined = ", ".join(supported_types) if supported_types else "none available"
            return (
                False,
                f"Unsupported database type: {db_type}. Supported types: {joined}",
            )

        # O(1) direct lookup — db_type is already lowercase and is a valid _plugins key
        plugin_info = cls._plugins.get(db_type)

        return NativeDriverManager.validate_driver_for_type(db_type, plugin_info)
