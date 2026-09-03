"""``manage.py dblift_validate`` -- validate migrations against history."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from dblift.integrations.django._client import get_client


class Command(BaseCommand):
    help = "Validate dblift migrations (checksums / order / applied state)."
    requires_system_checks: list[str] = []

    def handle(self, *args: Any, **options: Any) -> None:
        client = get_client()
        try:
            result = client.validate()
        finally:
            client.close()
        if not getattr(result, "success", False):
            raise CommandError(getattr(result, "error_message", "dblift validate failed"))
        self.stdout.write(self.style.SUCCESS("dblift: validation passed"))
