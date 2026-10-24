"""Oracle SQL parser package — PL/SQL DDL parsing for the Oracle dialect.

Script splitting is done by
the shared lexical engine driven by ``ORACLE_SPEC``, which also owns the SQL*Plus
directives and substitution variables (``docs/sql-parsing/oracle.md``). ``sqlplus_context``
extracts the ``SET SERVEROUTPUT`` / ``PROMPT`` context the executor reads.
"""

from .sqlplus_context import SqlplusContext, extract_sqlplus_context

__all__ = ["SqlplusContext", "extract_sqlplus_context"]
