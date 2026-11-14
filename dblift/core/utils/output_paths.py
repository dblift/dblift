"""Small safeguards for files created as command output."""

from pathlib import Path
from typing import Optional, Union


def refuse_symlink_output(path: Path) -> None:
    """Refuse an existing output leaf that would redirect a file write."""
    if path.is_symlink():
        raise OSError(f"Refusing to write through symlinked output path: {path}")


def requested_log_dir(
    log_dir: Optional[Union[str, Path]],
    log_file: Optional[Union[str, Path]],
    configured_dir: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """The directory log files go to, or ``None`` when no file was requested.

    ``log_dir`` wins, then ``configured_dir``, then the parent of ``log_file``
    (the working directory for a bare file name).
    """
    chosen = log_dir or configured_dir
    if chosen:
        return Path(chosen)
    if log_file:
        return Path(log_file).parent
    return None
