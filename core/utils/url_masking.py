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
    # Mask password parameter (multiple patterns). The delimiter is optional so
    # that ODBC/DB2-style strings starting with "password=..." are covered too.
    masked_url = re.sub(r"([&?;]?password=)[^&;]*", r"\1***", masked_url, flags=re.IGNORECASE)
    masked_url = re.sub(r"([&?;]?\bpwd=)[^&;]*", r"\1***", masked_url, flags=re.IGNORECASE)
    # Mask CosmosDB account key
    masked_url = re.sub(r"(AccountKey=)[^;]*", r"\1***", masked_url, flags=re.IGNORECASE)
    return masked_url
