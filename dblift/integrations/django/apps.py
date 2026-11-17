"""Django AppConfig for the dblift integration."""

from __future__ import annotations

from django.apps import AppConfig


class DbliftAppConfig(AppConfig):
    """Django application configuration for DBLift."""

    name = "dblift.integrations.django"
    label = "dblift"
    verbose_name = "DBLift"

    def ready(self) -> None:
        """Import the system checks once the application registry is ready."""
        from . import checks  # noqa: F401
