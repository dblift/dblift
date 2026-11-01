"""Resolve the relative paths of raw configuration-file data from the file's folder."""

from pathlib import Path
from typing import Callable, Dict

import sqlalchemy
from sqlalchemy.exc import ArgumentError

_IN_MEMORY = ":memory:"


def anchorer(base_dir: Path) -> Callable[[object], str]:
    base = Path(base_dir).expanduser().resolve()

    def anchor(value: object) -> str:
        path = Path(str(value)).expanduser()
        return str(path if path.is_absolute() else (base / path).resolve())

    return anchor


def _anchor_sqlite_url(url: str, anchor: Callable[[object], str]) -> str:
    """Anchor the file of a relative ``sqlite:`` URL; any other URL is returned as is."""
    if not url.lower().startswith(("sqlite:", "sqlite3:")):
        return url
    try:
        parsed = sqlalchemy.engine.make_url(f"sqlite:{url.split(':', 1)[1]}")
    except ArgumentError:
        return url
    database = parsed.database
    if not database or database == _IN_MEMORY or database.startswith("file:"):
        return url
    return parsed.set(database=anchor(database)).render_as_string(hide_password=False)


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

    Covers the migration directories, a SQLite file (``database.url`` or
    ``database.path``) and the log directory, in the root sections and in each
    ``environments`` block. Runs on the file's own data, before environment
    variables and command-line values are merged over it, so those stay
    relative to the working directory.
    """
    anchor = anchorer(base_dir)
    environments = data.get("environments")
    blocks = [data]
    if isinstance(environments, dict):
        blocks.extend(b for b in environments.values() if isinstance(b, dict))
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
                database["url"] = _anchor_sqlite_url(database["url"], anchor)
            path = database.get("path")
            if isinstance(path, str) and path and path != _IN_MEMORY:
                database["path"] = anchor(path)
        logging = block.get("logging")
        if isinstance(logging, dict) and isinstance(logging.get("directory"), str):
            logging["directory"] = anchor(logging["directory"]) if logging["directory"] else ""
        if isinstance(block.get("log_dir"), str) and block["log_dir"]:
            block["log_dir"] = anchor(block["log_dir"])
