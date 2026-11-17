"""SQLAlchemy URL construction for the Snowflake plugin."""

from typing import Any, Dict, Optional

from sqlalchemy.engine import URL, make_url

from dblift.db.value_utils import string_mapping


def _database_path(database_config: Any) -> Optional[str]:
    database = database_config.database
    schema = database_config.schema
    if database and schema:
        return f"{database}/{schema}"
    if database:
        return str(database)
    return None


def _account(database_config: Any) -> Optional[str]:
    account = getattr(database_config, "account", None)
    if account:
        return str(account)
    host = database_config.host
    return str(host) if host else None


def _query_mapping(cfg: Any, base_query: Any = None) -> Dict[str, str]:
    query = string_mapping(base_query)
    query.update(string_mapping(cfg.extra_params))
    query.update(string_mapping(cfg.options))

    for attr in ("warehouse", "role", "authenticator"):
        value = getattr(cfg, attr, None)
        if value:
            query[attr] = str(value)

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build a Snowflake SQLAlchemy URL from plugin config fields."""
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        url = make_url(raw_url)
        if not url.drivername.startswith("snowflake"):
            message = "Snowflake connections require snowflake:// URL"
            raise ValueError(message)

        config_username = database_config.username
        config_password = database_config.password
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
        username=database_config.username or None,
        password=database_config.password or None,
        host=account,
        database=_database_path(database_config),
        query=_query_mapping(database_config),
    ).render_as_string(hide_password=False)
    return created_url
