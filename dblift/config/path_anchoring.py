"""Resolve the relative paths of a loaded configuration from a chosen folder."""

from pathlib import Path
from typing import Any, Dict, List, Union

from dblift.config.dblift_config import DbliftConfig, DirectoryConfig

_IN_MEMORY = ":memory:"


def anchor_config_paths(config: DbliftConfig, base_dir: Path) -> None:
    """Rewrite *config*'s relative paths as absolute paths under *base_dir*.

    Covers the migration directories, a file-based database path, and the log
    directory. Absolute paths are left untouched. When no log directory is
    configured, logs go to ``<base_dir>/logs`` so nothing is written to the
    process working directory.
    """
    base = Path(base_dir).expanduser().resolve()

    def anchor(value: Any) -> str:
        path = Path(str(value)).expanduser()
        return str(path if path.is_absolute() else (base / path).resolve())

    migrations = config.migrations
    anchored: List[Union[str, DirectoryConfig]] = []
    entry: Union[str, DirectoryConfig, Dict[str, Any]]
    for entry in migrations.directories or []:
        if isinstance(entry, dict):
            # A hand-built config may still hold the raw ``{path, recursive}``
            # mapping; normalise it the way ``get_directory_configs`` would.
            entry = DirectoryConfig.from_dict(entry)
        if isinstance(entry, DirectoryConfig):
            entry.path = anchor(entry.path)
            anchored.append(entry)
        else:
            anchored.append(anchor(entry))
    migrations.directories = anchored
    migrations.directory = anchor(migrations.directory)

    database_path = getattr(config.database, "path", None)
    if isinstance(database_path, str) and database_path and database_path != _IN_MEMORY:
        # Only file-based engines (e.g. SQLite) define ``path``.
        setattr(config.database, "path", anchor(database_path))

    if getattr(config, "log_dir", None):
        config.log_dir = anchor(config.log_dir)
    elif getattr(config.logging, "directory", None):
        config.logging.directory = anchor(config.logging.directory)
    else:
        config.log_dir = str(base / "logs")
