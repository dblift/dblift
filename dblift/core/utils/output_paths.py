"""Small safeguards for files created as command output."""

from pathlib import Path
from typing import Optional, Union


def refuse_symlink_output(path: Path) -> None:
    """Refuse an existing output leaf that would redirect a file write."""
    if path.is_symlink():
        raise OSError(f"Refusing to write through symlinked output path: {path}")


def anchor_output_file(path: Union[str, Path], base_dir: Path) -> str:
    """Anchor an output's parent without resolving away its requested leaf."""
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = base_dir / requested
    return str(requested.parent.resolve() / requested.name)


def requested_log_dir(
    log_dir: Optional[Union[str, Path]],
    log_file: Optional[Union[str, Path]],
    configured_dir: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """The directory log files go to, or ``None`` when no file was requested.

    Absolute filenames select their parent. Otherwise ``log_dir`` wins, then
    ``configured_dir``, then the working directory when
    only ``log_file`` is given: a file name with its own directory part is
    expanded and created by the file sink, never taken literally here.
    """
    if log_file and Path(log_file).is_absolute():
        return Path(log_file).parent
    chosen = log_dir or configured_dir
    if chosen:
        return Path(chosen)
    return Path(".") if log_file else None
