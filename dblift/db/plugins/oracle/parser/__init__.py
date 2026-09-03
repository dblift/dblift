"""Oracle SQL parser package — PL/SQL DDL parsing for the Oracle dialect.

The Oracle plugin's quirks route ``"hybrid"`` and ``"regex"`` parser-factory
requests through :class:`OracleRegexParser` and ``"sqlglot"`` through the
shared sqlglot parser using its ``"oracle"`` dialect (see
:mod:`dblift.db.plugins.oracle.quirks`). Modules in this package own
Oracle-specific recognition (PL/SQL block bodies, SQL*Plus DEFINE
substitution, ``WHENEVER SQLERROR`` filtering) per ADR-0007.
"""

from .sqlplus_context import SqlplusContext, apply_define_substitution, extract_sqlplus_context

__all__ = ["SqlplusContext", "apply_define_substitution", "extract_sqlplus_context"]
