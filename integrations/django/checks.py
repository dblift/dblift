"""System check that warns when dblift migrations are pending."""

from __future__ import annotations

from typing import Any

from django.core.checks import Warning as DjangoWarning
from django.core.checks import register


@register()
def pending_migrations_check(app_configs: Any, **kwargs: Any) -> list[Any]:
    """Return a warning for pending dblift migrations, or [] on no pending work.

    A check that cannot run reports ``dblift.W002`` rather than ``[]``: an
    empty result means "no pending migrations", so swallowing a connection
    or configuration failure would hand the operator a clean bill of health
    for a check that never actually ran.
    """
    from integrations.django._client import get_client
    from integrations.fastapi import _pending_ids_from_info

    try:
        client = get_client()
        try:
            info = client.info()
        finally:
            client.close()
        pending = _pending_ids_from_info(info)
    except Exception as exc:
        # Broad by necessity: a system check must never abort `manage.py`,
        # and any failure mode here is equally undiagnosable to the operator
        # unless it is surfaced.
        return [
            DjangoWarning(
                f"dblift: could not check for pending migrations: {exc}",
                hint=(
                    "Verify DBLIFT_MIGRATIONS_DIR and the default database "
                    "connection, then re-run `python manage.py check`."
                ),
                id="dblift.W002",
            )
        ]

    if not pending:
        return []
    return [
        DjangoWarning(
            f"dblift: {len(pending)} pending migration(s): {pending}",
            hint="Apply with `python manage.py dblift_migrate`.",
            id="dblift.W001",
        )
    ]
