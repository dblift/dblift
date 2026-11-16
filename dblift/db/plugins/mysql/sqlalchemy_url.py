"""SQLAlchemy URL construction for the MySQL-family plugin."""

import re
from typing import Any, Dict

from sqlalchemy.engine import make_url

from dblift.db.plugins.mysql.sql_literals import string_literal
from dblift.db.sqlalchemy_url_utils import merge_config_credentials, render_url_from_config
from dblift.db.value_utils import string_mapping


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = string_mapping(base_query)
    query.update(string_mapping(database_config.extra_params))
    query.update(string_mapping(database_config.options))
    session_variables = string_mapping(database_config.session_variables)
    if session_variables and "init_command" not in query:
        parts = []
        for key, value in session_variables.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid MySQL session variable name: {key!r}")
            # Keep numeric SET values numeric; encode strings independently of sql_mode.
            numeric = value.strip()
            if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", numeric):
                parts.append(f"{key}={numeric}")
            else:
                parts.append(f"{key}={string_literal(value)}")
        query["init_command"] = f"SET SESSION {', '.join(parts)}"

    connection_timeout = database_config.connection_timeout
    if connection_timeout:
        query["connect_timeout"] = str(connection_timeout)

    if getattr(database_config, "ssl_enabled", False):
        query["ssl"] = "true"

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the MySQL SQLAlchemy URL from the plugin config object."""
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("mysql://", "mysql+", "mariadb://", "mariadb+")):
            url = make_url(raw_url)
            if url.drivername in ("mysql", "mariadb") or url.drivername.startswith("mariadb+"):
                url = url.set(drivername="mysql+pymysql")
            url = merge_config_credentials(url, database_config)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("MySQL native connections require a SQLAlchemy URL")

    return render_url_from_config("mysql+pymysql", database_config, _query_mapping(database_config))
