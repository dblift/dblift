"""Read a Flyway project's settings into the configuration form. Read-only.

A password the Flyway file holds, alone or inside its URL, is never copied: not into
the form, not into a note, not into an error.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote

from dblift_ui.configs import ENGINES, ENV_DEFAULT, ConfigForm, Connection, Password

MARKERS = ("flyway.conf", "flyway.toml")
DEFAULT_TABLE = "flyway_schema_history"
MAX_BYTES = 200_000

TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}\Z")
# Every pattern below is anchored and has no nested quantifier that can match the same
# text two ways, so a hostile line costs linear time.
_HOST = r"(?P<host>[A-Za-z0-9._-]+)(?::(?P<port>\d{1,5}))?"
_SERVER = re.compile(
    rf"^jdbc:(?P<scheme>postgresql|mysql|mariadb|redshift|db2|mongodb)://{_HOST}"
    r"/(?P<name>[^?;:/@]+)(?P<options>[?;:].*)?\Z"
)
_SQLSERVER = re.compile(rf"^jdbc:sqlserver://{_HOST}(?P<options>(?:;[^;]*)*)\Z")
_ORACLE = re.compile(
    rf"^jdbc:oracle:thin:@(?://)?{_HOST}(?P<separator>[/:])(?P<name>[A-Za-z0-9_.$#-]+)\Z"
)
_SNOWFLAKE = re.compile(r"^jdbc:snowflake://(?P<host>[A-Za-z0-9._-]+)/?(?:\?(?P<query>.*))?\Z")
_SNOWFLAKE_DOMAIN = ".snowflakecomputing.com"
_SQLITE = re.compile(r"^jdbc:sqlite:(?P<path>[^?]+)\Z")
_SCHEME = re.compile(r"^jdbc:[a-z0-9]{1,30}")
_TOML_PLACE = re.compile(r"\(at (line \d+, column \d+|end of document)\)\Z")
_CLASSPATH_ROOT = "src/main/resources"
_FIELDS = {engine.id: engine.fields for engine in ENGINES}


class FlywayError(Exception):
    """The Flyway file cannot be used; the message is for the user."""


@dataclass(frozen=True)
class FlywayProject:
    folder: str
    form: ConfigForm
    table: str
    notes: List[str]


def _properties(text: str) -> Dict[str, str]:
    """The ``flyway.*`` keys of a Java properties file, without the prefix."""
    found: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#!":
            continue
        key, separator, value = line.partition("=")
        if not separator:
            key, _, value = line.partition(":")
        key = key.strip()
        if key.startswith("flyway."):
            found[key[7:]] = value.strip()
    return found


def _text(value: object) -> Optional[str]:
    """A TOML value as text: a scalar, or a list of scalars joined by commas. Else None."""
    if isinstance(value, list):
        if all(isinstance(item, (str, int, float)) for item in value):
            return ",".join(map(str, value))
        return None
    return str(value) if isinstance(value, (str, int, float)) else None


def _toml(text: str) -> Dict[str, str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # Only the place is kept: some messages quote the text they stumbled on.
        place = _TOML_PLACE.search(str(exc))
        raise FlywayError(
            "flyway.toml is not valid TOML" + (f" (at {place[1]})" if place else "")
        ) from exc
    section = data.get("flyway")
    section = section if isinstance(section, dict) else {}
    environments = data.get("environments")
    environments = environments if isinstance(environments, dict) else {}
    environment = environments.get(_text(section.get("environment")) or "default")
    merged = {**section, **(environment if isinstance(environment, dict) else {})}
    # Tables and other structures are dropped: they could hold anything, a password included.
    found = {key: _text(value) for key, value in merged.items()}
    return {key: value for key, value in found.items() if value is not None}


def _port(value: Optional[str]) -> Optional[int]:
    return int(value) if value else None


def _connection(url: str) -> Tuple[Optional[str], Connection, List[str]]:
    """The engine and form fields a JDBC URL names; None when it cannot be translated.

    Only the fields below are taken from the URL; its options, credentials among them,
    are dropped.
    """
    notes: List[str] = []
    dropped = "The Flyway connection URL has options that were not copied. Check the connection."
    if match := _SQLITE.match(url):
        path = match["path"]
        relative = (
            path if path.startswith(("/", ".")) or re.match(r"[A-Za-z]:", path) else f"./{path}"
        )
        return "sqlite", Connection(path=relative), notes
    if match := _SERVER.match(url):
        if match["options"]:
            notes.append(dropped)
        return (
            match["scheme"],
            Connection(
                host=match["host"], port=_port(match["port"]), database=unquote(match["name"])
            ),
            notes,
        )
    # A value in braces may hold a ";", so splitting on ";" would cut a password in two.
    if (match := _SQLSERVER.match(url)) and "{" not in match["options"]:
        options = [part.partition("=") for part in match["options"].split(";") if part]
        named = {key.strip().lower(): value for key, _, value in options}
        database = named.get("databasename") or named.get("database") or ""
        if set(named) - {"databasename", "database"}:
            notes.append(dropped)
        return (
            "sqlserver",
            Connection(host=match["host"], port=_port(match["port"]), database=database),
            notes,
        )
    if match := _ORACLE.match(url):
        if match["separator"] == ":":
            notes.append(
                "The Flyway URL names an Oracle SID; it was put in the service name field. Check it."
            )
        return (
            "oracle",
            Connection(host=match["host"], port=_port(match["port"]), service_name=match["name"]),
            notes,
        )
    if match := _SNOWFLAKE.match(url):
        host = match["host"]
        if host.lower().endswith(_SNOWFLAKE_DOMAIN):
            host = host[: -len(_SNOWFLAKE_DOMAIN)]
        query = {key.lower(): values[0] for key, values in parse_qs(match["query"] or "").items()}
        if set(query) - {"db", "warehouse"}:
            notes.append(dropped)
        return (
            "snowflake",
            Connection(
                account=host, database=query.get("db", ""), warehouse=query.get("warehouse", "")
            ),
            notes,
        )
    # Only the driver is named: the rest of the URL may hold a password.
    scheme = _SCHEME.match(url) if "${" not in url else None
    notes.append(
        "The Flyway connection could not be translated"
        + (f" ({scheme[0]}…)" if scheme else "")
        + ". Fill in the connection."
    )
    return None, Connection(), notes


def _migrations(locations: str, folder: Path) -> Tuple[str, Optional[str]]:
    """The migrations folder Flyway's locations name, and a note when it needs checking."""
    entries = [entry.strip() for entry in locations.split(",") if entry.strip()]
    candidates: List[str] = []
    for entry in entries or ["classpath:db/migration"]:
        # Flyway reads a location without a prefix as a classpath one.
        kind, _, path = entry.partition(":") if ":" in entry else ("classpath", "", entry)
        path = path.strip()
        if not path or "${" in path:
            continue
        if kind == "filesystem":
            candidates.append(path)
        elif kind == "classpath" and (folder / _CLASSPATH_ROOT / path).is_dir():
            candidates.append(f"{_CLASSPATH_ROOT}/{path}")
    if not candidates:
        return (
            "./migrations",
            "The migrations folder could not be told from the Flyway locations. Check it.",
        )
    first = candidates[0]
    chosen = first if first.startswith(("/", "./", "../")) else f"./{first}"
    note = (
        "Flyway lists several locations; only the first is used as the migrations folder. "
        "Check it."
        if len(candidates) > 1
        else None
    )
    return chosen, note


def _settings(path: Path) -> Dict[str, str]:
    try:
        # The read itself is bounded: the size on disk may change after it is measured.
        with open(path, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError as exc:
        raise FlywayError(exc.strerror or "the file cannot be read") from exc
    if len(raw) > MAX_BYTES:
        raise FlywayError("the file is too large to read")
    text = raw.decode("utf-8", errors="replace")
    return _toml(text) if path.name == "flyway.toml" else _properties(text)


def _inside(folder: Path, name: str) -> Optional[Path]:
    """The real path of *folder*/*name* when it is a regular file inside *folder*."""
    try:
        top = folder.resolve()
        path = (top / name).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if top not in path.parents or not path.is_file() or path.name not in MARKERS:
        return None
    return path


def read_project(root: str, relative: str) -> FlywayProject:
    base = Path(str(root or "").strip()).expanduser()
    if not str(root or "").strip() or not base.is_absolute() or not base.is_dir():
        raise FlywayError("give the full path of a folder")
    if not relative or Path(relative).is_absolute() or Path(relative).name not in MARKERS:
        raise FlywayError("that is not a Flyway settings file")
    path = _inside(base, relative)
    if path is None:
        raise FlywayError("that is not a Flyway settings file")

    settings = _settings(path)
    engine, connection, notes = _connection(settings.get("url", ""))
    engine = engine or "postgresql"
    fields = _FIELDS[engine]
    if "password" in fields:
        connection.password = Password(mode="env", value=ENV_DEFAULT)
        if settings.get("password"):
            notes.append(
                "The Flyway file holds a password. It is not copied: "
                "set the variable below, or choose another way."
            )
    else:
        connection.password = Password(mode="none")
    user = settings.get("user", "")
    if "username" in fields and user and "${" not in user:
        if ":" in user:
            # Looks like "user:password": nothing of it is copied.
            notes.append("The Flyway user could not be used. Fill in the user name.")
        else:
            connection.username = user
    schema = (settings.get("defaultSchema") or settings.get("schemas", "").split(",")[0]).strip()
    if "schema" in fields and "${" not in schema:
        connection.schema_ = schema

    directory, note = _migrations(settings.get("locations", ""), path.parent)
    if note:
        notes.append(note)
    table = settings.get("table") or DEFAULT_TABLE
    if not TABLE_NAME.match(table):
        notes.append(
            "The Flyway history table name could not be used; the default name is assumed."
        )
        table = DEFAULT_TABLE
    return FlywayProject(
        folder=str(path.parent),
        form=ConfigForm(engine=engine, connection=connection, migrations_directory=directory),
        table=table,
        notes=notes,
    )


def table_beside(config_path: str) -> Optional[str]:
    """The history table a Flyway file in the config's folder declares.

    ``DEFAULT_TABLE`` when it declares none or cannot be read, None when there is no
    Flyway file.
    """
    folder = Path(config_path).parent
    for name in MARKERS:
        if not (folder / name).is_file():
            continue
        path = _inside(folder, name)
        try:
            table = _settings(path).get("table") if path else None
        except FlywayError:
            return DEFAULT_TABLE
        return table if table and TABLE_NAME.match(table) else DEFAULT_TABLE
    return None
