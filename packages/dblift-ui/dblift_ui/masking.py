"""Mask the passwords a database URL or a connection string may hold."""

import re

# The password of a ``scheme://user:password@host`` URL. URL parsers disagree on where
# it ends: at the last ``@`` before the path, or at the first ``@`` even past a ``/``.
# Both readings are masked, and the user may itself hold an ``@``. The second reading
# stops at the next ``://``, so a long run of ``://x:`` without an ``@``, as a whole
# run log may hold, costs linear time, not quadratic.
_URL_PASSWORD = re.compile(r"(://[^:/\s]*:)(?:[^/?#\s]*|(?:[^@\s:]|:(?!//))*)@")
_PASSWORD_PARAMETER = re.compile(r"((?:password|pwd)=)[^&;\s]*", re.IGNORECASE)


def mask_passwords(text: str, marker: str) -> str:
    """*text* with every URL password and ``password=`` / ``pwd=`` value replaced by *marker*."""
    text = _URL_PASSWORD.sub(lambda match: f"{match[1]}{marker}@", text)
    return _PASSWORD_PARAMETER.sub(lambda match: f"{match[1]}{marker}", text)
