"""Pure data constants for SQL type normalization. No project dependencies."""

from typing import Dict, Set

# Comprehensive type mappings: canonical -> variants
CANONICAL_TO_VARIANTS: Dict[str, Set[str]] = {
    # Integer types
    "INTEGER": {
        "INTEGER",
        "INT",
        "INT4",
        "INTEGER4",
        "NUMBER",  # Oracle/DB2 (when scale=0)
        "NUMERIC",  # When scale=0
        "DECIMAL",  # When scale=0
    },
    "SMALLINT": {
        "SMALLINT",
        "INT2",
        "INTEGER2",
        "TINYINT",
        "SHORT",  # Some databases
    },
    "BIGINT": {
        "BIGINT",
        "INT8",
        "INTEGER8",
        "LONG",
        "NUMBER",  # Oracle/DB2 (large precision)
    },
    # Character types
    "VARCHAR": {
        "VARCHAR",
        "VARCHAR2",
        "CHARACTER VARYING",
        "CHAR VARYING",
        "NVARCHAR",
        "NVARCHAR2",
        "NATIONAL VARCHAR",
        "VARCHARACTER",  # MySQL variant
    },
    "CHAR": {
        "CHAR",
        "CHARACTER",
        "NCHAR",
        "NATIONAL CHAR",
        "NATIONAL CHARACTER",
    },
    "TEXT": {
        "TEXT",
        "CLOB",
        "NCLOB",
        "LONGTEXT",
        "MEDIUMTEXT",
        "TINYTEXT",
        "NTEXT",
        "LONG",
        "STRING",
    },
    # Binary types
    "BLOB": {
        "BLOB",
        "BYTEA",
        "VARBINARY",
        "BINARY VARYING",
        "IMAGE",
        "LONG RAW",
        "RAW",
        "BINARY LARGE OBJECT",
    },
    # Numeric types
    "NUMERIC": {
        "NUMERIC",
        "DECIMAL",
        "NUMBER",
        "DEC",
    },
    "REAL": {
        "REAL",
        "FLOAT4",
        "FLOAT",
        "SINGLE",
    },
    "DOUBLE": {
        "DOUBLE",
        "DOUBLE PRECISION",
        "FLOAT8",
        "FLOAT",
    },
    # Boolean
    "BOOLEAN": {
        "BOOLEAN",
        "BOOL",
        "BIT",
        "TINYINT",  # MySQL uses TINYINT(1)
    },
    # Date/Time
    "DATE": {
        "DATE",
    },
    "TIME": {
        "TIME",
        "TIME WITHOUT TIME ZONE",
        "TIME WITH TIME ZONE",
        "TIMETZ",
    },
    "TIMESTAMP": {
        "TIMESTAMP",
        "TIMESTAMP WITHOUT TIME ZONE",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMPTZ",
        "DATETIME",
        "DATETIME2",
        "SMALLDATETIME",
    },
    "INTERVAL": {
        "INTERVAL",
        "INTERVAL YEAR TO MONTH",
        "INTERVAL DAY TO SECOND",
    },
    # UUID
    "UUID": {
        "UUID",
        "UNIQUEIDENTIFIER",
        "GUID",
    },
    # JSON
    "JSON": {
        "JSON",
        "JSONB",
    },
    # XML
    "XML": {
        "XML",
        "XMLTYPE",
    },
    # Geometric types (PostgreSQL)
    "POINT": {
        "POINT",
        "GEOMETRY",
        "GEOGRAPHY",
    },
    # Network types (PostgreSQL)
    "INET": {
        "INET",
        "CIDR",
        "MACADDR",
    },
    # Array types
    "ARRAY": {
        "ARRAY",
        "[]",  # PostgreSQL array syntax
    },
}
