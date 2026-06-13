"""No-op license guard for the OSS package."""

from typing import Optional

_cli_token: Optional[str] = None


def _set_token(token: Optional[str]) -> None:
    global _cli_token
    _cli_token = token


def _refresh_state() -> None:
    """OSS builds do not require a license token."""
    return None
