"""Derive DbliftConfig from an existing SQLAlchemy Engine (for from_sqlalchemy)."""

from pathlib import Path
from typing import Any, List, Optional, Union

from sqlalchemy.engine import Engine

from config import DbliftConfig
from config.errors import ConfigurationError
from db.provider_registry import ProviderRegistry


def config_from_engine(
    engine: Engine,
    *,
    schema: Optional[str] = None,
    migrations_dir: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
) -> DbliftConfig:
    """Build a DbliftConfig from a SQLAlchemy Engine for runtime integration.

    Validates that the engine's dialect is supported by a first-party (or
    registered) provider. The resulting config can be passed to
    DBLiftClient or used to construct a provider that re-uses the engine.

    Raises:
        ConfigurationError: if no matching dblift provider supports the
            engine's dialect (user should install the matching extra).
    """
    url = engine.url.render_as_string(hide_password=False)
    provider_cls = ProviderRegistry.get_provider_by_url(url)
    if provider_cls is None:
        raise ConfigurationError(
            f"Unsupported SQLAlchemy dialect for dblift: {engine.url.drivername!r}. "
            "Install the matching dblift extra (e.g. dblift[postgresql]) or "
            "use DBLiftClient.from_config()."
        )

    # Derive canonical db type from the matched provider key if possible.
    # Fall back to the URL scheme (canonicalized) — the config layer will
    # also normalize on construction.
    db_type = None
    # ProviderRegistry keeps plugins by canonical key; try to reverse-lookup
    # a stable name from the class if the registry exposes it, else use scheme.
    try:
        # Best-effort: many plugins register under the primary name.
        # We canonicalize the scheme portion.
        scheme = engine.url.drivername.split("+", 1)[0]
        db_type = ProviderRegistry.canonical_dialect_name(scheme) or scheme
    except Exception:
        db_type = "postgresql"  # lint: allow-dialect-string: safe fallback only; real type comes from URL scheme + ProviderRegistry.canonical_dialect_name above  # noqa: E501

    db_dict: dict[str, Any] = {"url": url, "type": db_type}
    if schema is not None:
        db_dict["schema"] = schema

    payload: dict[str, Any] = {"database": db_dict}

    config = DbliftConfig.from_dict(payload)

    # ``migrations_dir`` accepts str / Path / list (matching the rest of the
    # client API), but ``DbliftConfig.from_dict`` treats ``migrations.directory``
    # as a plain string (os.path.isabs / startswith). Passing a Path or list into
    # the dict would raise during construction, so normalize via the shared
    # helper instead, which handles all three shapes (and multi-dir lists).
    if migrations_dir is not None:
        from api._client_factory import normalize_migrations_dirs

        normalize_migrations_dirs(config, migrations_dir)

    return config
