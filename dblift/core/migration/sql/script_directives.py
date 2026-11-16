"""Directives a migration script declares in its leading comments."""

_NO_TRANSACTION = "dblift:no-transaction"


def opts_out_of_transaction(content: str) -> bool:
    """Whether a leading ``--`` comment of the script is the no-transaction directive."""
    i, n = 0, len(content)
    while i < n:
        if content[i].isspace():
            i += 1
        elif content.startswith("--", i):
            end = content.find("\n", i)
            end = n if end < 0 else end
            if content[i + 2 : end].strip().casefold() == _NO_TRANSACTION:
                return True
            i = end
        elif content.startswith("/*", i):
            depth, i = 1, i + 2
            while depth and i < n:
                if content.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif content.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                return False
        else:
            return False
    return False
