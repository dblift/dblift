"""Resolve the relative paths of raw configuration-file data from the file's folder."""

import re
from pathlib import Path
from typing import Callable, Dict, Optional

import sqlalchemy
from sqlalchemy.exc import ArgumentError

from dblift.config.database_config import _file_dialect

_IN_MEMORY = ":memory:"
_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://|\$\{")


def anchorer(base_dir: Path) -> Callable[[object], str]:
    base = Path(base_dir).expanduser().resolve()

    def anchor(value: object) -> str:
        if _REFERENCE.search(str(value)):
            return str(value)
        path = Path(str(value)).expanduser()
        return str(path if path.is_absolute() else (base / path).resolve())

    return anchor


def _anchor_database_file(
    database: str, locator: Optional[str], anchor: Callable[[object], str]
) -> str:
    """Anchor a relative database file; ``:memory:`` and a *locator* match are kept."""
    if not database or database == _IN_MEMORY or (locator and re.match(locator, database)):
        return database
    return anchor(database)


def _anchor_file_url(url: str, anchor: Callable[[object], str]) -> str:
    """Anchor the file of a relative file-based dialect URL; any other URL is returned as is."""
    try:
        parsed = sqlalchemy.engine.make_url(url)
    except ArgumentError:
        return url
    dialect = _file_dialect(parsed.drivername.split("+", 1)[0])
    if not dialect or not parsed.database:
        return url
    anchored = _anchor_database_file(parsed.database, dialect[1], anchor)
    if anchored == parsed.database:
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
                database["url"] = _anchor_file_url(database["url"], anchor)
            name = database.get("database")
            dialect = _file_dialect(str(database.get("type") or root_type or ""))
            if dialect and isinstance(name, str):
                database["database"] = _anchor_database_file(name, dialect[1], anchor)
            path = database.get("path")
            if isinstance(path, str):
                database["path"] = _anchor_database_file(
                    path, dialect[1] if dialect else None, anchor
                )
        logging = block.get("logging")
        if isinstance(logging, dict) and isinstance(logging.get("directory"), str):
            logging["directory"] = anchor(logging["directory"]) if logging["directory"] else ""
        if isinstance(block.get("log_dir"), str) and block["log_dir"]:
            block["log_dir"] = anchor(block["log_dir"])
