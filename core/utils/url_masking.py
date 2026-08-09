"""URL masking utilities for database credentials."""

import re


def mask_database_url(url: str) -> str:
    """Mask sensitive information in database URLs for logging.

    Args:
        url: Database URL

    Returns:
        Masked URL with passwords and keys hidden
    """
    masked_url = str(url)
    # Mask standard //user:password@host URL authority.
    # Use [^@]+ for password to handle passwords containing : or / (stops at @ delimiter)
    masked_url = re.sub(r"(//[^/:]+:)([^@]+)(@)", r"\1***\3", masked_url)
    # Mask the password parameter. The delimiter is optional so that
    # ODBC/DB2-style strings opening with "password=..." are covered, but the
    # parameter name must start where a name can start — otherwise
    # "oldpassword=", "old_password=" and the path "/home/pwd=" all match and
    # a non-secret value is corrupted in operator-facing output.
    masked_url = re.sub(
        r"(?<![A-Za-z0-9_/\\.-])([&?;]?(?:password|pwd)=)[^&;]*",
        r"\1***",
        masked_url,
        flags=re.IGNORECASE,
    )
    # Mask CosmosDB account key
    masked_url = re.sub(r"(AccountKey=)[^;]*", r"\1***", masked_url, flags=re.IGNORECASE)
    return masked_url
