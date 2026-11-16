"""SQLAlchemy URL construction for the PostgreSQL plugin."""

from typing import Any, Dict

from sqlalchemy.engine import make_url

from dblift.db.plugins.postgresql.search_path import search_path_option
from dblift.db.sqlalchemy_url_utils import merge_config_credentials, render_url_from_config
from dblift.db.value_utils import string_mapping


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = string_mapping(base_query)
    query.update(string_mapping(database_config.extra_params))
    query.update(string_mapping(database_config.options))

    connection_timeout = database_config.connection_timeout
    if connection_timeout:
        query["connect_timeout"] = str(connection_timeout)

    ssl_mode = getattr(database_config, "ssl_mode", None)
    if ssl_mode:
        query["sslmode"] = str(ssl_mode)

    schema = database_config.schema
    if schema:
        schema_option = search_path_option(str(schema))
        query["options"] = (
            f"{query['options']} {schema_option}" if query.get("options") else schema_option
        )

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the PostgreSQL SQLAlchemy URL from the plugin config object."""
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("postgresql://", "postgresql+", "postgres://", "postgres+")):
            url = make_url(raw_url)
            if url.drivername in ("postgresql", "postgres"):
                url = url.set(drivername="postgresql+psycopg")
            elif url.drivername.startswith("postgres+"):
                url = url.set(drivername=f"postgresql+{url.drivername.split('+', 1)[1]}")
            url = merge_config_credentials(url, database_config)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("PostgreSQL native connections require a SQLAlchemy URL")

    return render_url_from_config(
        "postgresql+psycopg", database_config, _query_mapping(database_config)
    )
