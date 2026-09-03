"""SQLAlchemy URL construction for the DB2 plugin."""

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

    schema = getattr(database_config, "schema", None)
    if schema:
        query["currentSchema"] = str(schema)

    collection = getattr(database_config, "collection", None)
    if collection:
        query["collection"] = str(collection)

    connection_timeout = getattr(database_config, "connection_timeout", None)
    if connection_timeout:
        query["connectTimeout"] = str(connection_timeout)

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the DB2 SQLAlchemy URL from the plugin config object."""
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("ibm_db_sa://", "db2://", "db2+")):
            url = make_url(raw_url)
            if url.drivername == "db2":
                url = url.set(drivername="ibm_db_sa")
            elif url.drivername.startswith("db2+"):
                url = url.set(drivername=url.drivername.split("+", 1)[1])
            username = getattr(database_config, "username", None) or url.username or None
            password = getattr(database_config, "password", None) or url.password or None
            if username != url.username or password != url.password:
                url = url.set(username=username, password=password)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("DB2 native connections require a SQLAlchemy URL")

    return URL.create(
        "ibm_db_sa",
        username=getattr(database_config, "username", None) or None,
        password=getattr(database_config, "password", None) or None,
        host=getattr(database_config, "host", None) or "localhost",
        port=getattr(database_config, "port", None),
        database=getattr(database_config, "database", None),
        query=_query_mapping(database_config),
    ).render_as_string(hide_password=False)
