"""SQLAlchemy URL construction for the Snowflake plugin."""

from typing import Any, Dict, Optional

from sqlalchemy.engine import URL, make_url


def _string_mapping(values: Any) -> Dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def _database_path(database_config: Any) -> Optional[str]:
    database = getattr(database_config, "database", None)
    schema = getattr(database_config, "schema", None)
    if database and schema:
        return f"{database}/{schema}"
    if database:
        return str(database)
    return None


def _account(database_config: Any) -> Optional[str]:
    account = getattr(database_config, "account", None)
    if account:
        return str(account)
    host = getattr(database_config, "host", None)
    return str(host) if host else None


def _query_mapping(cfg: Any, base_query: Any = None) -> Dict[str, str]:
    query = _string_mapping(base_query)
    extra_params = getattr(cfg, "extra_params", None)
    options = getattr(cfg, "options", None)
    query.update(_string_mapping(extra_params))
    query.update(_string_mapping(options))

    for attr in ("warehouse", "role", "authenticator"):
        value = getattr(cfg, attr, None)
        if value:
            query[attr] = str(value)

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build a Snowflake SQLAlchemy URL from plugin config fields."""
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        url = make_url(raw_url)
        if not url.drivername.startswith("snowflake"):
            message = "Snowflake connections require snowflake:// URL"
            raise ValueError(message)

        config_username = getattr(database_config, "username", None)
        config_password = getattr(database_config, "password", None)
        username = config_username or url.username or None
        password = config_password or url.password or None
        account = _account(database_config)
        database = _database_path(database_config) or url.database
        query = _query_mapping(database_config, url.query)

        rendered: str = url.set(
            drivername="snowflake",
            username=username,
            password=password,
            host=account or url.host,
            database=database,
            query=query,
        ).render_as_string(hide_password=False)
        return rendered

    account = _account(database_config)
    created_url: str = URL.create(
        "snowflake",
        username=getattr(database_config, "username", None) or None,
        password=getattr(database_config, "password", None) or None,
        host=account,
        database=_database_path(database_config),
        query=_query_mapping(database_config),
    ).render_as_string(hide_password=False)
    return created_url
