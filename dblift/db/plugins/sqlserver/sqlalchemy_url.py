"""SQLAlchemy URL construction for the SQL Server plugin (pymssql)."""

from typing import Any, Dict

from sqlalchemy.engine import URL, make_url


def _string_mapping(values: Any) -> Dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


#: Values pymssql's ``encryption`` connect kwarg actually accepts
#: (``pymssql._mssql.TDS_ENCRYPTION_LEVEL``). Anything else raises a
#: ``ValueError`` deep in the driver, so a boolean-ish value typed directly
#: into a URL (e.g. ``?encryption=true``, the ODBC/JDBC convention) must be
#: normalized here rather than forwarded as-is.
_VALID_ENCRYPTION_VALUES = {"default", "off", "request", "require"}


def _pop_case_insensitive(query: Dict[str, str], names: set[str]) -> str | None:
    for key in list(query):
        if key.lower() in names:
            return query.pop(key)
    return None


def _query_mapping(database_config: Any, base_query: Any = None) -> Dict[str, str]:
    query = _string_mapping(base_query)
    query.update(_string_mapping(getattr(database_config, "extra_params", None)))
    query.update(_string_mapping(getattr(database_config, "options", None)))

    integrated_keys = {
        "integrated_security",
        "integratedsecurity",
        "trusted_connection",
        "trustedconnection",
    }
    integrated_value = _pop_case_insensitive(query, integrated_keys)
    if integrated_value is not None and _truthy(integrated_value):
        raise ValueError(
            "SQL Server native pymssql connections do not support integrated_security. "
            "Provide username/password credentials instead."
        )
    if getattr(database_config, "integrated_security", False):
        raise ValueError(
            "SQL Server native pymssql connections do not support integrated_security. "
            "Provide username/password credentials instead."
        )

    trust_value = _pop_case_insensitive(
        query, {"trust_server_certificate", "trustservercertificate"}
    )
    if trust_value is not None and _truthy(trust_value):
        raise ValueError(
            "SQL Server native pymssql connections do not support trust_server_certificate. "
            "Configure certificate trust in FreeTDS or disable encryption explicitly."
        )
    if getattr(database_config, "trust_server_certificate", False):
        raise ValueError(
            "SQL Server native pymssql connections do not support trust_server_certificate. "
            "Configure certificate trust in FreeTDS or disable encryption explicitly."
        )

    encrypt_value = _pop_case_insensitive(query, {"encrypt"})
    if encrypt_value is not None:
        query.setdefault("encryption", "require" if _truthy(encrypt_value) else "off")
    elif "encryption" in query:
        if str(query["encryption"]).strip().lower() not in _VALID_ENCRYPTION_VALUES:
            query["encryption"] = "require" if _truthy(query["encryption"]) else "off"
    elif hasattr(database_config, "encrypt"):
        query["encryption"] = "require" if getattr(database_config, "encrypt") else "off"

    connection_timeout = getattr(database_config, "connection_timeout", None)
    if connection_timeout:
        query["login_timeout"] = str(connection_timeout)

    return query


def build_sqlalchemy_url(database_config: Any) -> str:
    """Build the SQL Server SQLAlchemy URL from the plugin config object.

    Handles three cases:
    - Native SQLAlchemy URL (starts with ``mssql+`` or ``mssql://``) — normalized
      to pymssql when needed, with credentials and query options merged from config.
    - Legacy ``jdbc:`` URL — rejected with ValueError.
    - No URL — built from host/port/database/username/password/instance fields.
      When ``instance`` is set it is encoded as ``host\\INSTANCE`` in the host
      portion (pymssql convention).
    """
    raw_url = getattr(database_config, "url", None)
    if isinstance(raw_url, str) and raw_url:
        if raw_url.startswith(("mssql+", "mssql://")):
            url = make_url(raw_url)
            if url.drivername == "mssql":
                url = url.set(drivername="mssql+pymssql")
            username = getattr(database_config, "username", None) or url.username or None
            password = getattr(database_config, "password", None) or url.password or None
            if username != url.username or password != url.password:
                url = url.set(username=username, password=password)
            query = _query_mapping(database_config, url.query)
            if query != dict(url.query):
                url = url.set(query=query)
            return url.render_as_string(hide_password=False)
        raise ValueError(
            f"SQL Server native connections require a SQLAlchemy URL "
            f"(mssql+pymssql://...), got: {raw_url!r}"
        )

    host = getattr(database_config, "host", None) or "localhost"
    instance = getattr(database_config, "instance", None)
    if instance:
        host = f"{host}\\{instance}"

    return URL.create(
        "mssql+pymssql",
        username=getattr(database_config, "username", None) or None,
        password=getattr(database_config, "password", None) or None,
        host=host,
        port=getattr(database_config, "port", None),
        database=getattr(database_config, "database", None),
        query=_query_mapping(database_config),
    ).render_as_string(hide_password=False)
