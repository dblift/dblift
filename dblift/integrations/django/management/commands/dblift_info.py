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
        failed = getattr(info, "failed_migrations", []) or []
        # Pending and failed are separate dimensions. Printing only
        # "0 pending" looks clean after a success=0 history row.
        self.stdout.write(f"dblift: {len(pending)} pending migration(s)")
        for migration in pending:
            self.stdout.write(f"  - {getattr(migration, 'script', migration)}")
        failed_line = f"dblift: {len(failed)} failed migration(s)"
        if failed:
            self.stdout.write(self.style.ERROR(failed_line))
            for migration in failed:
                self.stdout.write(f"  - {getattr(migration, 'script', migration)}")
        else:
            self.stdout.write(failed_line)
