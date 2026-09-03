"""DB2 SQL parser package — regex-only DDL parsing for the Db2 dialect.

``sqlglot`` does not ship a Db2 dialect, so the Db2 plugin's quirks
expose :class:`DB2RegexParser` for both the ``"hybrid"`` and ``"regex"``
parser-factory routes (see :mod:`dblift.db.plugins.db2.quirks`). The parser
modules in this package own all Db2-specific DDL recognition; the
shared :mod:`dblift.core.sql_parser` framework drives the dispatch (per
ADR-0007).
"""
