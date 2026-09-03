"""PostgreSQL SQL parser package — DDL parsing for the PostgreSQL dialect.

The PostgreSQL plugin's quirks route ``"hybrid"`` and ``"regex"``
parser-factory requests through :class:`PostgreSQLRegexParser` and
``"sqlglot"`` through the shared sqlglot parser using its ``"postgres"``
dialect (see :mod:`dblift.db.plugins.postgresql.quirks`). Modules in this
package own PostgreSQL-specific recognition (dollar-quoted function
bodies, ``DROP TRIGGER ... ON table``, partial / GIN / GiST indexes)
per ADR-0007.
"""
