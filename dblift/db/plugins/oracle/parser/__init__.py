"""Oracle SQL parser package — PL/SQL DDL parsing for the Oracle dialect.

The Oracle plugin's quirks route ``"hybrid"`` and ``"regex"`` parser-factory
requests through :class:`OracleParser` and ``"sqlglot"`` through the shared
sqlglot parser using its ``"oracle"`` dialect (see
:mod:`dblift.db.plugins.oracle.quirks`). Script splitting is
:class:`OracleStatementParser`, which also owns the SQL*Plus directives and
substitution variables (``docs/sql-parsing/oracle.md``). ``sqlplus_context``
extracts the ``SET SERVEROUTPUT`` / ``PROMPT`` context the executor reads.
"""

from .sqlplus_context import SqlplusContext, extract_sqlplus_context

__all__ = ["SqlplusContext", "extract_sqlplus_context"]
