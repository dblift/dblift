"""Django AppConfig for the dblift integration."""

from __future__ import annotations

from django.apps import AppConfig


class DbliftAppConfig(AppConfig):
    name = "dblift.integrations.django"
    label = "dblift"
    verbose_name = "DBLift"

    def ready(self) -> None:
        from . import checks  # noqa: F401
