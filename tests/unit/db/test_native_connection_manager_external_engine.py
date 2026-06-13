"""External SQLAlchemy Engine must not be disposed by dblift."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from db.native_connection_manager import NativeConnectionManager


def test_external_engine_not_disposed_on_close():
    engine = create_engine("sqlite:///:memory:")
    config = MagicMock()
    config.database = MagicMock()
    mgr = NativeConnectionManager(config, engine=engine, owns_engine=False)
    _ = mgr.engine  # same object
    assert mgr.engine is engine
    mgr.close()
    # Engine still usable after close
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


def test_owned_engine_disposed_on_close():
    config = MagicMock()
    config.database = MagicMock()
    config.database.type = "sqlite"
    # Use the real creation path (ProviderRegistry) rather than a non-existent
    # _create_engine_from_config. Manually seed _engine after construction
    # (matching the spirit of the plan-provided test) to verify owns flag.
    mgr = NativeConnectionManager(config, owns_engine=True)
    mock_engine = create_engine("sqlite:///:memory:")
    mgr._engine = mock_engine
    mgr.close()
    # After dispose, pool is closed — verify _engine cleared (only for owned)
    assert mgr._engine is None
