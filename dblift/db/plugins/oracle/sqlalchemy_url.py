"""SQLAlchemy URL construction for the Oracle plugin."""

from typing import Any, Dict

from sqlalchemy.engine import URL, make_url

from dblift.core.constants import ORACLE_DEFAULT_PORT
from dblift.db.sqlalchemy_url_utils import merge_config_credentials
from dblift.db.value_utils import string_mapping


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = string_mapping(base_query)
    query.update(string_mapping(database_config.extra_params))
    query.update(string_mapping(database_config.options))

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
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("oracle://", "oracle+")):
            url = make_url(raw_url)
            if url.drivername == "oracle":
                url = url.set(drivername="oracle+oracledb")
            url = merge_config_credentials(url, database_config)
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
        username=database_config.username or None,
        password=database_config.password or None,
        host=database_config.host or "localhost",
        port=database_config.port or ORACLE_DEFAULT_PORT,
        query=query,
    ).render_as_string(hide_password=False)
