"""SQL Server SQL parser package — T-SQL DDL parsing for the MSSQL dialect.

The SQL Server plugin's quirks route ``"hybrid"`` and ``"regex"``
parser-factory requests through :class:`SqlServerRegexParser` and
``"sqlglot"`` through the shared sqlglot parser using its ``"tsql"``
dialect (see :mod:`dblift.db.plugins.sqlserver.quirks`). The parser modules
in this package own T-SQL-specific recognition (e.g. CLUSTERED /
NONCLUSTERED PK qualifiers, ``GO`` batch separators) per ADR-0007.
"""
