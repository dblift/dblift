"""String utility functions."""


def safe_split_first(text: str, separator: str, default: str = "") -> str:
    """Safely split a string on the first occurrence of a separator.

    Args:
        text: The string to split
        separator: The separator to split on
        default: Default value to return if separator is not found

    Returns:
        The part before the separator, or default if separator not found
    """
    if not text:
        return default

    if separator in text:
        return text.split(separator, 1)[0]

    return default
