"""PostgreSQL plugin-side introspection (F.3.a).

Hosts :class:`PostgreSQLIntrospector`, the dialect-located entry point
for ``IntrospectorFactory``. The actual orchestration code lives in
:class:`BaseIntrospector` (post-H.2: dialect-agnostic by design;
extractor calls route every dialect decision through quirks). This
package exists so a developer reading ``db/plugins/postgresql/`` sees
the introspection wiring without leaving the plugin directory.
"""

from db.plugins.postgresql.introspection.postgresql_introspector import (
    PostgreSQLIntrospector,
)

__all__ = ["PostgreSQLIntrospector"]
