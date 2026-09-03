"""MariaDB native provider."""

from __future__ import annotations

from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.provider_interfaces import DroppableObject


class MariadbProvider(MySqlProvider):
    """MariaDB-specific native provider."""

    canonical_dialect_key = "mariadb"

    def list_droppable_objects(self, schema: str) -> list[DroppableObject]:
        """Return MariaDB objects in the same order as clean preview."""
        preview = self.get_clean_preview(schema)
        objects = [
            DroppableObject(name=obj.name, object_type=obj.object_type, drop_sql=drop_sql)
            for obj, drop_sql in zip(preview.objects, preview.statements)
        ]
        if objects:
            return [
                DroppableObject(
                    name="foreign_key_checks_off",
                    object_type="clean_control",
                    drop_sql="SET FOREIGN_KEY_CHECKS = 0",
                    record_result=False,
                ),
                *objects,
                DroppableObject(
                    name="foreign_key_checks_on",
                    object_type="clean_control",
                    drop_sql="SET FOREIGN_KEY_CHECKS = 1",
                    record_result=False,
                ),
            ]
        return objects


__all__ = ["MariadbProvider"]
