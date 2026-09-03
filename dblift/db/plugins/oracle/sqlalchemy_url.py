"""SQLAlchemy URL construction for the Oracle plugin."""

from typing import Any, Dict

from sqlalchemy.engine import URL, make_url

from dblift.core.constants import ORACLE_DEFAULT_PORT


def _string_mapping(values: Any) -> Dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = _string_mapping(base_query)
    query.update(_string_mapping(getattr(database_config, "extra_params", None)))
    query.update(_string_mapping(getattr(database_config, "options", None)))

    service_name = getattr(database_config, "service_name", None)
    sid = getattr(database_config, "sid", None)
    if service_name:
        query.pop("sid", None)
        query["service_name"] = str(service_name)
    elif sid:
        query.pop("service_name", None)
        query["sid"] = str(sid)
    elif query.get("service_name"):
        query.pop("sid", None)
    elif query.get("sid"):
        query.pop("service_name", None)
    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the Oracle SQLAlchemy URL from the plugin config object."""
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("oracle://", "oracle+")):
            url = make_url(raw_url)
            if url.drivername == "oracle":
                url = url.set(drivername="oracle+oracledb")
            username = getattr(database_config, "username", None) or url.username or None
            password = getattr(database_config, "password", None) or url.password or None
            if username != url.username or password != url.password:
                url = url.set(username=username, password=password)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("Oracle native connections require a SQLAlchemy URL")

    query = _query_mapping(database_config)
    if not query.get("service_name") and not query.get("sid"):
        raise ValueError("Oracle native connections require service_name or sid")

    return URL.create(
        "oracle+oracledb",
        username=getattr(database_config, "username", None) or None,
        password=getattr(database_config, "password", None) or None,
        host=getattr(database_config, "host", None) or "localhost",
        port=getattr(database_config, "port", None) or ORACLE_DEFAULT_PORT,
        query=query,
    ).render_as_string(hide_password=False)
