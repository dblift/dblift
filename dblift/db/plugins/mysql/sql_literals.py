"""String literals shared by MySQL metadata and connection initialization SQL."""


def string_literal(value: str) -> str:
    """Render UTF-8 text without depending on the session's backslash escape mode."""
    return f"_utf8mb4 X'{value.encode('utf-8').hex()}'"
