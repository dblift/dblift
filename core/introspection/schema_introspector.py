"""Back-compat shim — :class:`SchemaIntrospector` is now :class:`BaseIntrospector`.

F.3.h merged the orchestration code that used to live here into
:class:`core.introspection.base_introspector.BaseIntrospector`. This module
exists so historical imports (``from core.introspection.schema_introspector
import SchemaIntrospector``) keep working; new code should import
:class:`BaseIntrospector` directly.
"""

from core.introspection.base_introspector import BaseIntrospector

# Alias for back-compat — tests and a few extractor fallback paths still
# reference ``SchemaIntrospector`` by name.
SchemaIntrospector = BaseIntrospector

__all__ = ["SchemaIntrospector"]
