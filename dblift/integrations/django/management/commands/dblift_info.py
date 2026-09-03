"""``manage.py dblift_info`` -- print dblift migration status."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from dblift.integrations.django._client import get_client


class Command(BaseCommand):
    help = "Show dblift migration status."
    requires_system_checks: list[str] = []

    def handle(self, *args: Any, **options: Any) -> None:
        client = get_client()
        try:
            info = client.info()
        finally:
            client.close()
        pending = getattr(info, "pending_migrations", []) or []
        self.stdout.write(f"dblift: {len(pending)} pending migration(s)")
        for migration in pending:
            self.stdout.write(f"  - {getattr(migration, 'script', migration)}")
