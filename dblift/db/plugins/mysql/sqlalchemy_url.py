"""SQLAlchemy URL construction for the MySQL-family plugin."""

from typing import Any, Dict

from sqlalchemy.engine import URL, make_url


def _string_mapping(values: Any) -> Dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = _string_mapping(base_query)
    query.update(_string_mapping(getattr(database_config, "extra_params", None)))
    query.update(_string_mapping(getattr(database_config, "options", None)))
    session_variables = _string_mapping(getattr(database_config, "session_variables", None))
    if session_variables and "init_command" not in query:
        parts = []
        for key, value in session_variables.items():
            # Quote non-numeric values so SET SESSION time_zone='+00:00' is safe.
            try:
                float(value)
                parts.append(f"{key}={value}")
            except ValueError:
                escaped = value.replace("'", "''")
                parts.append(f"{key}='{escaped}'")
        query["init_command"] = f"SET SESSION {', '.join(parts)}"

    connection_timeout = getattr(database_config, "connection_timeout", None)
    if connection_timeout:
        query["connect_timeout"] = str(connection_timeout)

    if getattr(database_config, "ssl_enabled", False):
        query["ssl"] = "true"

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the MySQL SQLAlchemy URL from the plugin config object."""
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("mysql://", "mysql+", "mariadb://", "mariadb+")):
            url = make_url(raw_url)
            if url.drivername in ("mysql", "mariadb") or url.drivername.startswith("mariadb+"):
                url = url.set(drivername="mysql+pymysql")
            username = getattr(database_config, "username", None) or url.username or None
            password = getattr(database_config, "password", None) or url.password or None
            if username != url.username or password != url.password:
                url = url.set(username=username, password=password)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("MySQL native connections require a SQLAlchemy URL")

    return URL.create(
        "mysql+pymysql",
        username=getattr(database_config, "username", None) or None,
        password=getattr(database_config, "password", None) or None,
        host=getattr(database_config, "host", None) or "localhost",
        port=getattr(database_config, "port", None),
        database=getattr(database_config, "database", None),
        query=_query_mapping(database_config),
    ).render_as_string(hide_password=False)
