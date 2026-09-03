"""CLI entry-point package — argparse setup and command dispatch.

The user-facing executable is ``cli/main.py::main``. Per-command handlers
live under ``cli/handlers/``; output routing (machine-readable vs. status)
goes through ``cli/_output.py::CommandOutput`` per ADR-0008. Modules in
this package may not import from ``db/`` directly — programmatic access
to provider internals routes through ``api/_cli_support`` to keep the
``cli/`` → ``db/`` coupling boundary clean (enforced by
``flake8-tidy-imports`` in ``.flake8``).
"""
