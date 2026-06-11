"""Dialect-specific options for ``Table``, regrouped into immutable dataclasses.

SIMP-48
-------
``core.sql_model.table.Table.__init__`` now exposes only base/structural
parameters. All dialect-specific properties (MySQL ``storage_engine``,
SQL Server ``memory_optimized``, PostgreSQL ``row_security``,
Oracle/DB2 ``pctfree``, ...) are grouped into four small frozen
dataclasses plus this ``TableOptions`` aggregate, and applied via
``Table.from_options(name, columns, options=TableOptions(...))``.
The reverse extraction is ``Table.to_options()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class MySqlTableOptions:
    """MySQL/MariaDB specific table options."""

    storage_engine: Optional[str] = None
    row_format: Optional[str] = None
    table_collation: Optional[str] = None
    next_auto_increment: Optional[int] = None
    create_options: Optional[str] = None


@dataclass(frozen=True, slots=True)
class SqlServerTableOptions:
    """SQL Server (T-SQL grammar-based) table options."""

    filegroup: Optional[str] = None
    memory_optimized: bool = False
    system_versioned: bool = False
    history_table: Optional[str] = None
    history_schema: Optional[str] = None
    period_start_column: Optional[str] = None
    period_end_column: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PostgresTableOptions:
    """PostgreSQL specific table options."""

    row_security: bool = False
    force_row_security: bool = False
    policies: List[Dict[str, Any]] = field(default_factory=list)
    inherits: List[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OracleStorageOptions:
    """Oracle / DB2 storage parameters for SQL generation."""

    pctfree: Optional[int] = None
    pctused: Optional[int] = None
    initial: Optional[int] = None
    next: Optional[int] = None


@dataclass(frozen=True, slots=True)
class TableOptions:
    """Aggregated dialect-specific options for ``core.sql_model.table.Table``."""

    mysql: MySqlTableOptions = field(default_factory=MySqlTableOptions)
    sqlserver: SqlServerTableOptions = field(default_factory=SqlServerTableOptions)
    postgres: PostgresTableOptions = field(default_factory=PostgresTableOptions)
    oracle_storage: OracleStorageOptions = field(default_factory=OracleStorageOptions)
    derived_from: Optional[str] = None
    raw_ddl: Optional[str] = None
