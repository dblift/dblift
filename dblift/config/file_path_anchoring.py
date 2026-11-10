"""Resolve the relative paths of raw configuration-file data from the file's folder."""

import re
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs

import sqlalchemy
from sqlalchemy.exc import ArgumentError

from dblift.config.database_config import _file_dialect

_IN_MEMORY = ":memory:"
_SCHEME = r"[A-Za-z][A-Za-z0-9+.-]*"
URL_SCHEME = re.compile(rf"^({_SCHEME})://")
_REFERENCE = re.compile(rf"^{_SCHEME}://|\$\{{")


def anchorer(base_dir: Path) -> Callable[[object], str]:
    """Return a function that anchors relative paths to ``base_dir``."""
    base = Path(base_dir).expanduser().resolve()

    def anchor(value: object) -> str:
        if _REFERENCE.search(str(value)):
            return str(value)
        path = Path(str(value)).expanduser()
        return str(path if path.is_absolute() else (base / path).resolve())

    return anchor


def left_relative(database: str, locator: Optional[str]) -> bool:
    """Whether *database* is a relative file that the anchoring would resolve."""
    return bool(
        database
        and database != _IN_MEMORY
        and not (locator and re.match(locator, database))
        and not _REFERENCE.search(database)
        and not Path(database).expanduser().is_absolute()
    )


def _anchor_database_file(
    database: str, locator: Optional[str], anchor: Callable[[object], str], declined: bool = False
) -> str:
    """Anchor a relative database file; ``:memory:`` and a *locator* match are kept.

    With *declined* a relative file is kept too: a SQLAlchemy URL cannot carry the anchored
    path when the folder holds a '?', and ``refuse_unusable_file_paths`` refuses it if selected.
    """
    if not database or database == _IN_MEMORY or (locator and re.match(locator, database)):
        return database
    if declined and left_relative(database, locator):
        return database
    return anchor(database)


def file_url(url: str) -> Optional[Tuple[sqlalchemy.engine.URL, str, str]]:
    """Return the parsed *url*, its database (``""`` if none) and its dialect's locator pattern
    for a file-based dialect URL, else ``None``."""
    try:
        parsed = sqlalchemy.engine.make_url(url)
    except ArgumentError:
        return None
    dialect = _file_dialect(parsed.drivername.split("+", 1)[0])
    return (parsed, parsed.database or "", dialect[1]) if dialect else None


def render_file_url(drivername: str, target: str) -> str:
    """Render the URL of file *target*; a ``?query`` written after the file stays a query."""
    database, _, query = target.partition("?")
    if database == _IN_MEMORY:  # SQLAlchemy 2.1 would escape the colons
        return f"{drivername}:///{target}"
    url = sqlalchemy.engine.URL.create(
        drivername, database=database, query=parse_qs(query, keep_blank_values=True)
    )
    return url.render_as_string(hide_password=False)


def _anchor_file_url(url: str, anchor: Callable[[object], str], declined: bool) -> str:
    """Anchor the file of a relative file-based dialect URL; any other URL is returned as is."""
    found = file_url(url)
    if not found or not found[1]:
        return url
    parsed, database, locator = found
    anchored = _anchor_database_file(database, locator, anchor, declined)
    if anchored == database:
        return url
    return parsed.set(database=anchored).render_as_string(hide_password=False)


def _anchor_directory_entry(entry: object, anchor: Callable[[object], str]) -> object:
    if isinstance(entry, str):
        return anchor(entry) if entry else entry
    if isinstance(entry, dict):
        key = "path" if entry.get("path") else "directory"
        if isinstance(entry.get(key), str) and entry[key]:
            return {**entry, key: anchor(entry[key])}
    return entry


def anchor_file_data(data: Dict[str, object], base_dir: Path) -> None:
    """Rewrite, in place, the relative paths of raw configuration-file *data* under *base_dir*.

    Covers the migration directories, the file of a file-based database
    (``database.url`` or ``database.path``) and the log directory, in the root
    sections and in each ``environments`` block. Runs on the file's own data, before environment
    variables and command-line values are merged over it, so those stay
    relative to the working directory.
    """
    anchor = anchorer(base_dir)
    qmark = "?" in str(Path(base_dir).expanduser().resolve())
    environments = data.get("environments")
    blocks = [data]
    if isinstance(environments, dict):
        blocks.extend(b for b in environments.values() if isinstance(b, dict))
    root_database = data.get("database")
    root_type = root_database.get("type") if isinstance(root_database, dict) else None
    for block in blocks:
        migrations = block.get("migrations")
        if isinstance(migrations, dict):
            if isinstance(migrations.get("directory"), str) and migrations["directory"]:
                migrations["directory"] = anchor(migrations["directory"])
            entries = migrations.get("directories")
            if isinstance(entries, list):
                migrations["directories"] = [_anchor_directory_entry(e, anchor) for e in entries]
        database = block.get("database")
        if isinstance(database, dict):
            if isinstance(database.get("url"), str):
                database["url"] = _anchor_file_url(database["url"], anchor, qmark)
            name = database.get("database")
            dialect = _file_dialect(str(database.get("type") or root_type or ""))
            if dialect and isinstance(name, str):
                database["database"] = _anchor_database_file(
                    name, dialect[1], anchor, qmark and dialect[2]
                )
            path = database.get("path")
            if isinstance(path, str):
                database["path"] = _anchor_database_file(
                    path,
                    dialect[1] if dialect else None,
                    anchor,
                    bool(qmark and dialect and dialect[2]),
                )
        logging = block.get("logging")
        if isinstance(logging, dict) and isinstance(logging.get("directory"), str):
            logging["directory"] = anchor(logging["directory"]) if logging["directory"] else ""
        if isinstance(block.get("log_dir"), str) and block["log_dir"]:
            block["log_dir"] = anchor(block["log_dir"])
