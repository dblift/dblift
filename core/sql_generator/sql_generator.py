"""OSS fallback SQL generator.

Paid dialect-specific generators are registered by higher-tier packages. When no
paid generator is registered, OSS keeps only basic table DDL and generic drops.
"""

from __future__ import annotations

from typing import Optional

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
from core.sql_model.base import SqlObject, get_object_type_name


class SqlGenerator(BaseSqlGenerator):
    """Dialect-neutral fallback used when no paid generator is registered."""

    def generate_create_statement(self, obj: SqlObject) -> str:
        """Generate basic table DDL; non-table objects have no OSS renderer."""
        from core.sql_model.table import Table

        if isinstance(obj, Table):
            return BasicTableDdlGenerator(obj).generate_create_statement()
        return ""

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """Generate a conservative generic DROP statement."""
        schema_prefix = f"{obj.format_identifier(obj.schema)}." if obj.schema else ""
        obj_name = obj.format_identifier(obj.name)
        obj_type = get_object_type_name(obj)
        table_name: Optional[str] = getattr(obj, "table_name", None)

        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks((dialect or "").lower())
        custom = quirks.render_drop_for_object(obj_type, obj_name, schema_prefix, table_name)
        if custom is not None:
            return custom

        drop_statement = getattr(obj, "drop_statement", None)
        if isinstance(drop_statement, str) and drop_statement:
            return drop_statement

        if_exists = "IF EXISTS " if quirks.drop_supports_if_exists else ""
        cascade = " CASCADE" if obj_type == "TABLE" and quirks.drop_table_default_cascade else ""
        return f"DROP {obj_type} {if_exists}{schema_prefix}{obj_name}{cascade}"


__all__ = ["SqlGenerator"]
