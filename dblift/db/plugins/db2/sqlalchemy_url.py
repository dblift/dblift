"""SQLAlchemy URL construction for the DB2 plugin."""

from typing import Any, Dict

from sqlalchemy.engine import make_url

from dblift.db.sqlalchemy_url_utils import merge_config_credentials, render_url_from_config
from dblift.db.value_utils import string_mapping


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = string_mapping(base_query)
    query.update(string_mapping(database_config.extra_params))
    query.update(string_mapping(database_config.options))

    schema = database_config.schema
    if schema:
        query["currentSchema"] = str(schema)

    collection = getattr(database_config, "collection", None)
    if collection:
        query["collection"] = str(collection)

    connection_timeout = database_config.connection_timeout
    if connection_timeout:
        query["connectTimeout"] = str(connection_timeout)

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the DB2 SQLAlchemy URL from the plugin config object."""
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("ibm_db_sa://", "db2://", "db2+")):
            url = make_url(raw_url)
            if url.drivername == "db2":
                url = url.set(drivername="ibm_db_sa")
            elif url.drivername.startswith("db2+"):
                url = url.set(drivername=url.drivername.split("+", 1)[1])
            url = merge_config_credentials(url, database_config)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("DB2 native connections require a SQLAlchemy URL")

    return render_url_from_config("ibm_db_sa", database_config, _query_mapping(database_config))
