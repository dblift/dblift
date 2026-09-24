"""Extension seams: the points where an installed add-on package can plug in.

Every seam is a small registry or an entry-point lookup. With nothing
registered each one is a no-op and the tool behaves as a plain
open-source install. Add-on packages register through ``dblift.*``
entry-point groups. Most are declared empty in ``pyproject.toml``;
``dblift.client`` is read by ``client_factory`` without a declaration.

Seam map — module, entry-point group, and where the core calls it:

``feature_loading``
    Group ``dblift.features``. Loads every registered no-arg callable once
    per process; those callables register into the other seams below.
    Called from ``cli/main.py`` (startup), ``api/client.py`` (client
    construction), ``cli/mcp/server.py`` and the two SQL generator
    factories (``core/sql_generator/generator_factory.py``,
    ``core/sql_generator/alter/alter_generator_factory.py``).
    ``DBLIFT_DISABLE_CLI_EXTENSIONS=1`` skips it.

``runtime_checks``
    In-process registry keyed by check point. ``run_checks("migration.pre_execution")``
    in ``core/migration/executor/execution_engine.py`` and
    ``run_checks("command.pre_migrate")`` in
    ``core/migration/commands/migrate_command.py``. A check raises to abort.

``capabilities``
    ``CapabilityDeniedError``, the neutral base exception that
    ``cli/_command_handlers.py`` and ``cli/mcp/runner.py`` catch when an
    invocation is not entitled to a command, and that the stub methods in
    ``api/client.py`` raise.

``tier_resolver``
    Single-slot registry; ``resolve_tier(args)`` returns an opaque value the
    core only stores on ``CliCommandContext.license_tier``
    (``cli/_command_handlers.py``, ``cli/mcp/runner.py``). ``None`` when
    nothing is registered.

``license_info``
    Single-slot registry; ``get_license_info(args)`` feeds the optional log
    banner (``cli/main.py`` → ``core/logger/_formatters.py``). ``None`` when
    nothing is registered, and no banner renders.

``client_factory``
    Group ``dblift.client``. ``resolve_client_class()`` returns the
    registered ``DBLiftClient`` subclass or the built-in one; used by
    ``cli/main.py`` and ``api/client.py``.

``event_listeners``
    Group ``dblift.event_listeners``. ``attach_registered_listeners(emitter)``
    subscribes registered listeners to the client's event bus
    (``api/client.py``).

``introspection``
    Group ``dblift.introspection``. ``attach_registered_introspection()`` runs
    registrars that extend the schema introspectors
    (``core/introspection/introspector_factory.py``,
    ``core/introspection/vendor_queries_factory.py``).

``sql_generators``
    In-process registry filled by ``dblift.features`` callables;
    ``attach_registered_sql_generators()`` runs them from the two SQL
    generator factories.

Related hooks outside this package: ``cli/extensions.py`` (groups
``dblift.commands``, ``dblift.command_handlers``, ``dblift.terminal_commands``),
``cli/mcp/registry.py`` (group ``dblift.mcp_tools``) and
``core/premium_manifest.py`` (the catalogue behind the command stubs that
``cli/_parser_setup.py`` and ``api/client.py`` create when no add-on
registered the command). ``pyproject.toml`` also declares ``dblift.differ``,
which nothing in this tree reads. ``docs/developer-guide/forking.md``
explains how to remove all of them.
"""
