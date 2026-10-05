"""The config form: what the browser edits, and how it becomes a config file and back."""

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple, cast
from urllib.parse import quote, unquote

from dblift_ui.masking import mask_passwords
from dblift_ui.scripts import yaml_problem
from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import YAMLError

MASK = "********"
ENV_DEFAULT = "DBLIFT_DB_PASSWORD"

_HOST = re.compile(r"^[A-Za-z0-9._-]+\Z")
_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")
_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")
_ENVIRONMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_PLAIN_URL = re.compile(
    r"^(?P<scheme>[a-z0-9]+)://(?P<host>[A-Za-z0-9._-]+)(?::(?P<port>\d+))?/(?P<name>[^/?#@]*)(?:\?(?P<query>[^#]*))?\Z"
)
_LOOSE_KEYS = ("host", "port", "database", "service_name", "account", "warehouse")
_LEVELS = ("DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL")


class ConfigError(Exception):
    """The form or the file cannot be used; the message is for the user."""


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    scheme: str
    port: Optional[int]
    fields: Tuple[str, ...]


_SERVER = ("host", "port", "database", "username", "password")
ENGINES: List[Engine] = [
    Engine("postgresql", "PostgreSQL", "postgresql", 5432, (*_SERVER, "schema")),
    Engine("mysql", "MySQL", "mysql", 3306, _SERVER),
    Engine("mariadb", "MariaDB", "mariadb", 3306, _SERVER),
    Engine("sqlserver", "SQL Server", "mssql", 1433, (*_SERVER, "schema")),
    Engine(
        "oracle",
        "Oracle",
        "oracle",
        1521,
        ("host", "port", "service_name", "username", "password", "schema"),
    ),
    Engine("db2", "DB2", "db2", 50000, (*_SERVER, "schema")),
    Engine("sqlite", "SQLite", "sqlite", None, ("path",)),
    Engine("cockroachdb", "CockroachDB", "cockroachdb", 26257, (*_SERVER, "schema")),
    Engine("redshift", "Redshift", "redshift", 5439, (*_SERVER, "schema")),
    Engine(
        "snowflake",
        "Snowflake",
        "snowflake",
        None,
        ("account", "database", "warehouse", "schema", "username", "password"),
    ),
    Engine("mongodb", "MongoDB", "mongodb", 27017, _SERVER),
]
_BY_ID = {engine.id: engine for engine in ENGINES}
_BY_SCHEME = {engine.scheme: engine for engine in ENGINES}


class Password(BaseModel):
    mode: Literal["env", "literal", "keep", "none"] = "env"
    value: str = ""


class Connection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["fields", "url"] = "fields"
    url: str = ""
    host: str = ""
    port: Optional[int] = None
    database: str = ""
    service_name: str = ""
    account: str = ""
    warehouse: str = ""
    path: str = ""
    username: str = ""
    schema_: str = Field(default="", alias="schema")
    password: Password = Field(default_factory=lambda: Password(mode="env", value=ENV_DEFAULT))


class EnvironmentForm(BaseModel):
    name: str
    connection: Connection


class ConfigForm(BaseModel):
    engine: str
    connection: Connection
    migrations_directory: str = "./migrations"
    recursive: bool = True
    log_level: str = "INFO"
    strict_mode: bool = False
    clean_disabled: bool = True
    environments: List[EnvironmentForm] = Field(default_factory=list)


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _load(text: str) -> CommentedMap:
    try:
        data = _yaml().load(text)
    except DuplicateKeyError as exc:
        # Its problem text quotes both values of the key, which may be passwords.
        mark = exc.problem_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        raise ConfigError(f"{where}a key appears twice") from exc
    except YAMLError as exc:
        # yaml_problem reads only ``problem`` and ``problem_mark``, which ruamel's errors share.
        raise ConfigError(yaml_problem(cast(Any, exc))) from exc
    if not isinstance(data, CommentedMap):
        raise ConfigError("the file is not a mapping")
    return data


def build_url(engine: str, connection: Connection) -> str:
    spec = _BY_ID.get(engine)
    if spec is None:
        raise ConfigError(f"unknown engine: {engine}")
    if spec.id == "snowflake":
        if not _HOST.match(connection.account):
            raise ConfigError("the account is required (letters, digits, dots and dashes)")
        if not connection.database:
            raise ConfigError("the database is required")
        tail = f"?warehouse={quote(connection.warehouse, safe='')}" if connection.warehouse else ""
        return f"snowflake://{connection.account}/{quote(connection.database, safe='')}{tail}"
    if not _HOST.match(connection.host):
        raise ConfigError("the host is required (letters, digits, dots and dashes)")
    where = connection.host + (f":{connection.port}" if connection.port else "")
    if spec.id == "oracle":
        if not connection.service_name:
            raise ConfigError("the service name is required")
        return f"oracle://{where}/?service_name={quote(connection.service_name, safe='')}"
    if not connection.database:
        raise ConfigError("the database is required")
    return f"{spec.scheme}://{where}/{quote(connection.database, safe='')}"


def _read_password(section: Dict[str, Any]) -> Password:
    if "password" not in section or section["password"] in (None, ""):
        return Password(mode="none")
    placeholder = _PLACEHOLDER.match(str(section["password"]))
    return Password(mode="env", value=placeholder[1]) if placeholder else Password(mode="keep")


def _read_connection(
    section: Dict[str, Any], engine: Optional[Engine]
) -> Tuple[Connection, Optional[Engine]]:
    """A database mapping as form fields. *engine* is the base engine, when reading an environment."""
    common: Dict[str, Any] = dict(
        username=str(section.get("username") or ""),
        schema=str(section.get("schema") or ""),
        password=_read_password(section),
    )
    url = str(section.get("url") or "")
    declared = _BY_ID.get(str(section.get("type") or "").lower())
    if not url:
        spec = declared or engine
        if spec and spec.id == "sqlite":
            return Connection(path=str(section.get("path") or ""), **common), spec
        return (
            Connection(
                host=str(section.get("host") or ""),
                port=int(section["port"]) if str(section.get("port") or "").isdigit() else None,
                database=str(section.get("database") or ""),
                service_name=str(section.get("service_name") or ""),
                account=str(section.get("account") or ""),
                warehouse=str(section.get("warehouse") or ""),
                **common,
            ),
            spec,
        )
    plain = _PLAIN_URL.match(url)
    spec = _BY_SCHEME.get(plain["scheme"]) if plain else None
    if plain and spec and spec.id != "sqlite":
        query = plain["query"] or ""
        port = int(plain["port"]) if plain["port"] else None
        name = unquote(plain["name"])
        if spec.id == "oracle" and not name and re.fullmatch(r"service_name=[^&]+", query):
            return (
                Connection(
                    host=plain["host"], port=port, service_name=unquote(query[13:]), **common
                ),
                spec,
            )
        if (
            spec.id == "snowflake"
            and name
            and not port
            and re.fullmatch(r"(warehouse=[^&]+)?", query)
        ):
            return (
                Connection(
                    account=plain["host"], database=name, warehouse=unquote(query[10:]), **common
                ),
                spec,
            )
        if spec.id not in ("oracle", "snowflake") and name and not query:
            return Connection(host=plain["host"], port=port, database=name, **common), spec
    # Anything else is edited as one raw URL; a password inside it is not shown.
    scheme = _BY_SCHEME.get(url.split("://", 1)[0].split("+", 1)[0])
    return (
        Connection(mode="url", url=mask_passwords(url, MASK), **common),
        declared or scheme or engine,
    )


def read_form(text: str) -> Tuple[ConfigForm, List[str]]:
    data = _load(text)
    database = data.get("database")
    if not isinstance(database, dict):
        raise ConfigError("the file has no database section")
    notes: List[str] = []
    connection, engine = _read_connection(database, None)
    environments: List[EnvironmentForm] = []
    declared = data.get("environments")
    for name, block in (declared.items() if isinstance(declared, dict) else []):
        section = block.get("database") if isinstance(block, dict) else None
        found, _ = _read_connection(section if isinstance(section, dict) else {}, engine)
        environments.append(EnvironmentForm(name=str(name), connection=found))
    if any(c.mode == "url" for c in [connection, *[e.connection for e in environments]]):
        notes.append(
            "A connection has options this form does not cover, so it is edited as one URL."
        )
    if "secrets" in data:
        notes.append(
            "This config uses a secrets section; it is kept as it is and not checked here."
        )
    migrations = data.get("migrations") if isinstance(data.get("migrations"), dict) else {}
    logging = data.get("logging") if isinstance(data.get("logging"), dict) else {}
    return (
        ConfigForm(
            engine=engine.id if engine else "postgresql",
            connection=connection,
            migrations_directory=str(migrations.get("directory") or "./migrations"),
            recursive=bool(migrations.get("recursive", True)),
            log_level=str(logging.get("level") or "INFO").upper(),
            strict_mode=bool(data.get("strict_mode", False)),
            clean_disabled=bool(data.get("clean_disabled", True)),
            environments=environments,
        ),
        notes,
    )


def _section(parent: CommentedMap, key: str) -> CommentedMap:
    section = parent.get(key)
    if not isinstance(section, CommentedMap):
        section = parent[key] = CommentedMap()
    return section


def _put(section: CommentedMap, key: str, value: Any, default: Any) -> None:
    """Write *value*, unless it is the default and the key is not there already."""
    if value != default or key in section:
        section[key] = value


def _write_connection(
    section: CommentedMap, engine: str, connection: Connection, base: bool
) -> None:
    filled = connection.host or connection.account or connection.path
    if connection.mode == "url":
        if MASK in connection.url:
            # The browser only ever saw the masked form: unchanged means "keep what is stored".
            if mask_passwords(str(section.get("url") or ""), MASK) != connection.url:
                raise ConfigError(
                    "the URL still holds a masked password: type the real one or use the password field"
                )
        elif connection.url:
            section["url"] = connection.url
        elif base:
            raise ConfigError("the URL is required")
        else:
            section.pop("url", None)
    elif engine == "sqlite":
        if connection.path:
            section["type"] = "sqlite"
            section["path"] = connection.path
            for key in ("url", *_LOOSE_KEYS):
                section.pop(key, None)
        elif base:
            raise ConfigError("the database file path is required")
    elif filled or base:
        section["url"] = build_url(engine, connection)
        for key in ("path", *_LOOSE_KEYS):
            section.pop(key, None)
        # The URL's scheme names the engine; a ``type`` naming another one would contradict it.
        if str(section.get("type", engine)).lower() != engine:
            del section["type"]
    else:
        section.pop("url", None)
    for key, value in (("username", connection.username), ("schema", connection.schema_)):
        if value:
            section[key] = value
        else:
            section.pop(key, None)
    password = connection.password
    if password.mode == "env":
        if not _VARIABLE.match(password.value):
            raise ConfigError("the password variable must be a name such as DBLIFT_DB_PASSWORD")
        section["password"] = "${" + password.value + "}"
    elif password.mode == "literal":
        if not password.value:
            raise ConfigError("the password is empty")
        section["password"] = password.value
    elif password.mode == "none":
        section.pop("password", None)
    elif "password" not in section:
        raise ConfigError("there is no saved password to keep: choose a variable or type one")


def _mask(section: Any) -> None:
    if not isinstance(section, dict):
        return
    if section.get("password") not in (None, "") and not _PLACEHOLDER.match(
        str(section["password"])
    ):
        section["password"] = MASK
    if section.get("url"):
        section["url"] = mask_passwords(str(section["url"]), MASK)


def render(form: ConfigForm, existing: Optional[str] = None, mask: bool = False) -> str:
    if form.engine not in _BY_ID:
        raise ConfigError(f"unknown engine: {form.engine}")
    if not form.migrations_directory.strip():
        raise ConfigError("the migrations folder is required")
    names = [environment.name for environment in form.environments]
    for name in names:
        if not _ENVIRONMENT.match(name) or name == "resolve":
            raise ConfigError(f"'{name}' is not a usable environment name")
        if names.count(name) > 1:
            raise ConfigError(f"the environment '{name}' is listed twice")

    document = _load(existing) if existing else CommentedMap()
    _write_connection(_section(document, "database"), form.engine, form.connection, base=True)
    migrations = _section(document, "migrations")
    migrations["directory"] = form.migrations_directory.strip()
    _put(migrations, "recursive", form.recursive, True)
    level = form.log_level.upper()
    logging = document.get("logging")
    written = logging.get("level") if isinstance(logging, dict) else None
    # An unchanged level stays as written, even one this form does not offer.
    if written is None or str(written).upper() != level:
        if level not in _LEVELS:
            raise ConfigError("unknown log level")
        if level != "INFO" or isinstance(logging, dict):
            _put(_section(document, "logging"), "level", level, "INFO")
    _put(document, "strict_mode", form.strict_mode, False)
    _put(document, "clean_disabled", form.clean_disabled, True)

    if names or "environments" in document:
        environments = _section(document, "environments")
        for stale in [name for name in environments if name not in names]:
            del environments[stale]
        for environment in form.environments:
            block = _section(environments, environment.name)
            _write_connection(
                _section(block, "database"), form.engine, environment.connection, base=False
            )
            # An environment that only inherits keeps its (empty) block: dblift refuses
            # an environment name the file does not declare.
            if not block["database"]:
                del block["database"]
        if not names:
            del document["environments"]

    if mask:
        _mask(document.get("database"))
        for block in (document.get("environments") or {}).values():
            _mask(block.get("database") if isinstance(block, dict) else None)
    out = io.StringIO()
    _yaml().dump(document, out)
    return out.getvalue()
