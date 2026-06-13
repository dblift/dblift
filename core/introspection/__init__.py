"""Database schema introspection using plugin-owned vendor metadata queries."""

# Import base classes first to avoid circular import issues
from .base_introspector import BaseIntrospector

# Import factory
from .introspector_factory import IntrospectorFactory

# Import concrete implementations
from .schema_introspector import SchemaIntrospector
from .vendor_queries_factory import VendorQueriesFactory, register_vendor_queries

# Database-specific introspectors live with their plugin under
# ``db/plugins/<dialect>/introspection/`` and are reached through
# ``IntrospectorFactory.create()`` (preferred) or imported directly,
# e.g. ``from db.plugins.postgresql.introspection.postgresql_introspector
# import PostgreSQLIntrospector``.

__all__ = [
    "BaseIntrospector",
    "IntrospectorFactory",
    "SchemaIntrospector",
    "VendorQueriesFactory",
    "register_vendor_queries",
]
