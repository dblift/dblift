"""Non-dialect ``BaseDatabaseConfig`` subclass modules.

The per-dialect configuration classes that used to live here have moved into
their plugin packages (``db/plugins/<dialect>/config.py``, ADR-26 D /
story 26-11): each plugin declares ``config_class=XxxConfig`` on its
``PluginInfo`` and registers via plugin discovery, so adding a dialect no
longer requires editing ``config/``.

What remains is :mod:`config._subclasses.dummy_config` — a generic/test config
that is **not** a plugin and therefore has no plugin to register through. It
imports :class:`config.database_config.BaseDatabaseConfig` and uses
``@register_database_type`` so its class is wired into the
``BaseDatabaseConfig._registry`` at import time. The :mod:`config.database_config`
facade eager-imports it to keep that registration eager.
"""
