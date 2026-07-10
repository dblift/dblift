"""SQLAlchemy URL construction for the Redshift plugin."""

from typing import Any, Dict, cast

from sqlalchemy.engine import URL, make_url


def _string_mapping(values: Any) -> Dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = _string_mapping(base_query)
    query.update(_string_mapping(getattr(database_config, "extra_params", None)))
    query.update(_string_mapping(getattr(database_config, "options", None)))

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build a Redshift SQLAlchemy URL using the Amazon Redshift connector."""
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        url = make_url(raw_url)
        if url.drivername.startswith(("postgresql", "postgres", "redshift")):
            url = url.set(drivername="redshift+redshift_connector")
            username = getattr(database_config, "username", None) or url.username or None
            password = getattr(database_config, "password", None) or url.password or None
            if username != url.username or password != url.password:
                url = url.set(username=username, password=password)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return cast(str, url.render_as_string(hide_password=False))
        raise ValueError("Redshift native connections require a SQLAlchemy URL")

    return cast(
        str,
        URL.create(
            "redshift+redshift_connector",
            username=getattr(database_config, "username", None) or None,
            password=getattr(database_config, "password", None) or None,
            host=getattr(database_config, "host", None) or "localhost",
            port=getattr(database_config, "port", None),
            database=getattr(database_config, "database", None),
            query=_query_mapping(database_config),
        ).render_as_string(hide_password=False),
    )
