"""Small safeguards for files created as command output."""

from pathlib import Path


def refuse_symlink_output(path: Path) -> None:
    """Refuse an existing output leaf that would redirect a file write."""
    if path.is_symlink():
        raise OSError(f"Refusing to write through symlinked output path: {path}")
