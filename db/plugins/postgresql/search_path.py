"""The ``search_path`` dblift gives a PostgreSQL session.

PostgreSQL extensions install their callable API into ``public``: pgcrypto
(``gen_random_uuid``, ``digest``), PostGIS (``ST_MakePoint``), uuid-ossp
(``uuid_generate_v4``), hstore, TimescaleDB (``create_hypertable``,
``by_range``). Every other client resolves those unqualified because the
server default ``search_path`` — ``"$user", public`` — ends in ``public``.

dblift used to set a *schema-only* ``search_path``, so a hand-written migration
or an exported schema calling any of them failed with ``function ... does not
exist`` under dblift while replaying cleanly under ``psql``. Appending
``public`` removes that divergence.

``public`` comes *after* the target schema, never before, so an object in the
target schema still shadows a same-named object in ``public``. Nothing about
where new objects are created changes either: an unqualified ``CREATE`` lands
in the first schema on the path, which is still the target. Only the
resolution *fallback* is new, and it only applies to names that would
otherwise not resolve at all.

This module is the single source of truth for that policy. Sites differ in how
they render it — a libpq ``-c`` option takes bare names, a ``SET`` statement
takes quoted identifiers — so they format :func:`search_path_schemas`
themselves rather than sharing a formatted string.
"""

from __future__ import annotations

from typing import List

#: Schema appended so extension APIs installed outside the target stay callable.
EXTENSION_FALLBACK_SCHEMA = "public"


def search_path_schemas(schema: str) -> List[str]:
    """Return the ``search_path`` entries for *schema*, most specific first.

    A ``public`` target is returned on its own: listing it twice would be
    harmless but says nothing.
    """
    if schema == EXTENSION_FALLBACK_SCHEMA:
        return [schema]
    return [schema, EXTENSION_FALLBACK_SCHEMA]


def search_path_option(schema: str) -> str:
    """Return the libpq ``options`` fragment setting the search path."""
    return f"-csearch_path={','.join(search_path_schemas(schema))}"


__all__ = ["EXTENSION_FALLBACK_SCHEMA", "search_path_option", "search_path_schemas"]
