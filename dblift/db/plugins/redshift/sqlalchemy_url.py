"""SQLAlchemy URL construction for the Redshift plugin."""

from typing import Any, Dict

from sqlalchemy.engine import make_url

from dblift.db.sqlalchemy_url_utils import merge_config_credentials, render_url_from_config
from dblift.db.value_utils import string_mapping


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = string_mapping(base_query)
    query.update(string_mapping(database_config.extra_params))
    query.update(string_mapping(database_config.options))

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build a Redshift SQLAlchemy URL using the Amazon Redshift connector."""
    raw_url = database_config.url
    if isinstance(raw_url, str) and raw_url:
        url = make_url(raw_url)
        if url.drivername.startswith(("postgresql", "postgres", "redshift")):
            url = url.set(drivername="redshift+redshift_connector")
            url = merge_config_credentials(url, database_config)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError("Redshift native connections require a SQLAlchemy URL")

    return render_url_from_config(
        "redshift+redshift_connector", database_config, _query_mapping(database_config)
    )
