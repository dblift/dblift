"""SQLAlchemy URL pieces shared by the host/user/password plugin URL builders."""

from typing import Any, Dict

from sqlalchemy.engine import URL


def merge_config_credentials(url: URL, database_config: Any) -> URL:
    """Return *url* with the config's username/password taking precedence over the URL's."""
    username = database_config.username or url.username or None
    password = database_config.password or url.password or None
    if username != url.username or password != url.password:
        url = url.set(username=username, password=password)
    return url


def render_url_from_config(drivername: str, database_config: Any, query: Dict[str, str]) -> str:
    """Render ``drivername://`` from the config's host/port/database and credentials."""
    return URL.create(
        drivername,
        username=database_config.username or None,
        password=database_config.password or None,
        host=database_config.host or "localhost",
        port=database_config.port,
        database=database_config.database,
        query=query,
    ).render_as_string(hide_password=False)
