"""Database schema introspection using plugin-owned vendor metadata queries."""

# Import base classes first to avoid circular import issues
from .base_introspector import BaseIntrospector

# Import factory
from .introspector_factory import IntrospectorFactory

# Import concrete implementations
from .schema_introspector import SchemaIntrospector
from .vendor_queries_factory import VendorQueriesFactory, register_vendor_queries

# Database-specific introspectors are reached through
# ``IntrospectorFactory.create()``; some rich implementations are
# registered by an installed extension package.

__all__ = [
    "BaseIntrospector",
    "IntrospectorFactory",
    "SchemaIntrospector",
    "VendorQueriesFactory",
    "register_vendor_queries",
]
