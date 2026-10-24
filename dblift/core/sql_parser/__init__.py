"""SQL parser package."""

import logging

from dblift.core.sql_parser.statement import Statement, StatementKind

__all__ = ["Statement", "StatementKind"]

# sqlglot logs a warning, quoting the statement, for each one it cannot parse. A client with no
# logging configured must stay silent: without any handler Python prints those records to stderr.
logging.getLogger("sqlglot").addHandler(logging.NullHandler())
