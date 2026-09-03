"""``manage.py dblift_migrate`` -- apply pending dblift migrations."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from dblift.integrations.django._client import get_client


class Command(BaseCommand):
    help = "Apply pending dblift migrations."
    requires_system_checks: list[str] = []

    def handle(self, *args: Any, **options: Any) -> None:
        client = get_client()
        try:
            result = client.migrate()
        finally:
            client.close()
        if not getattr(result, "success", False):
            raise CommandError(getattr(result, "error_message", "dblift migrate failed"))
        self.stdout.write(self.style.SUCCESS("dblift: migrations applied"))
