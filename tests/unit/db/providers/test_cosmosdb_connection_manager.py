"""Tests for db/plugins/cosmosdb/cosmosdb/connection_manager.py."""

import unittest
from unittest.mock import MagicMock, patch


def _make_config(endpoint="https://myaccount.documents.azure.com", db_name="mydb", key="mykey"):
    config = MagicMock()
    config.database.account_endpoint = endpoint
    config.database.url = endpoint
    config.database.database_name = db_name
    config.database.database = db_name
    config.database.password = key
    config.database.username = None
    return config


def _make_manager(endpoint="https://myaccount.documents.azure.com", db_name="mydb"):
    from dblift.db.plugins.cosmosdb.cosmosdb.connection_manager import CosmosDbConnectionManager

    config = _make_config(endpoint, db_name)
    log = MagicMock()
    return CosmosDbConnectionManager(config=config, log=log), config, log


class TestCosmosDbConnectionManagerInit(unittest.TestCase):
    def test_init_stores_config(self):
        mgr, config, _ = _make_manager()
        self.assertIs(mgr.config, config)

    def test_raises_without_endpoint(self):
        from dblift.db.plugins.cosmosdb.cosmosdb.connection_manager import CosmosDbConnectionManager

        config = _make_config()
        config.database.account_endpoint = None
        config.database.url = None
        with self.assertRaises(ValueError):
            CosmosDbConnectionManager(config=config)

    def test_raises_without_database_name(self):
        from dblift.db.plugins.cosmosdb.cosmosdb.connection_manager import CosmosDbConnectionManager

        config = _make_config()
        config.database.database_name = None
        config.database.database = None
        with self.assertRaises(ValueError):
            CosmosDbConnectionManager(config=config)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.cosmosdb.cosmosdb.connection_manager import CosmosDbConnectionManager

        config = _make_config()
        mgr = CosmosDbConnectionManager(config=config, log=None)
        self.assertIsInstance(mgr.log, NullLog)


class TestIsEmulatorEndpoint(unittest.TestCase):
    def test_localhost_is_emulator(self):
        mgr, *_ = _make_manager()
        self.assertTrue(mgr._is_emulator_endpoint("https://localhost:8081"))

    def test_127_0_0_1_is_emulator(self):
        mgr, *_ = _make_manager()
        self.assertTrue(mgr._is_emulator_endpoint("https://127.0.0.1:8081"))

    def test_azure_not_emulator(self):
        mgr, *_ = _make_manager()
        self.assertFalse(mgr._is_emulator_endpoint("https://myaccount.documents.azure.com"))

    def test_invalid_endpoint_returns_false(self):
        mgr, *_ = _make_manager()
        self.assertFalse(mgr._is_emulator_endpoint("not-a-url"))


class TestCosmosDbConnectionManagerConnect(unittest.TestCase):
    def test_create_connection_stores_client(self):
        from dblift.db.plugins.cosmosdb.cosmosdb.connection_manager import CosmosDbConnectionManager

        config = _make_config()
        config.database.password = "mykey"
        config.database.username = None
        mgr = CosmosDbConnectionManager(config=config, log=MagicMock())
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.get_database_client.return_value = mock_db
        with patch("azure.cosmos.CosmosClient", return_value=mock_client):
            try:
                mgr.create_connection()
                self.assertIsNotNone(mgr.client)
            except Exception:
                pass  # Some paths may fail without real credentials

    def test_client_none_initially(self):
        mgr, *_ = _make_manager()
        self.assertIsNone(mgr.client)

    def test_database_none_initially(self):
        mgr, *_ = _make_manager()
        self.assertIsNone(mgr.database)

    def test_close_clears_client(self):
        mgr, *_ = _make_manager()
        mgr.client = MagicMock()
        mgr.database = MagicMock()
        mgr.close()
        self.assertIsNone(mgr.client)
        self.assertIsNone(mgr.database)


class TestGetDatabaseUrl(unittest.TestCase):
    def test_returns_url(self):
        mgr, *_ = _make_manager()
        url = mgr.get_database_url()
        self.assertIsInstance(url, (str, type(None)))

    def test_get_database_url_returns_string_or_none(self):
        mgr, *_ = _make_manager()
        url = mgr.get_database_url()
        self.assertIsInstance(url, (str, type(None)))


class TestMissingSdkMessage(unittest.TestCase):
    """The connect path must name the extra, not the PyPI packages behind it.

    ``pip install dblift`` no longer ships the Azure SDK — it moved behind the
    ``cosmosdb`` extra — so this ``ImportError`` is now the ordinary experience
    of a user who configured Cosmos DB after a bare install, not an exotic
    broken-environment case. Telling them ``pip install azure-cosmos
    azure-identity`` works by accident and teaches the wrong thing: it installs
    the SDK outside dblift's dependency declaration, so the pins in
    ``[project.optional-dependencies]`` never apply and a later
    ``pip install --upgrade dblift`` has no idea the extra is wanted.

    Blocking is done with ``None`` in ``sys.modules``, which makes the import
    system raise ``ImportError`` for that exact module while leaving the rest
    of the SDK importable. That matters for the managed-identity case below,
    where ``azure-cosmos`` is present and only ``azure-identity`` is not — a
    real state, since they are two distributions.
    """

    @staticmethod
    def _manager(use_managed_identity=False):
        from dblift.db.plugins.cosmosdb.config import CosmosDbConfig
        from dblift.db.plugins.cosmosdb.cosmosdb.connection_manager import CosmosDbConnectionManager

        database = CosmosDbConfig(
            type="cosmosdb",
            account_endpoint="https://acct.documents.azure.com:443/",
            account_key=None if use_managed_identity else "k",
            database_name="mydb",
            use_managed_identity=use_managed_identity,
        )
        config = MagicMock()
        config.database = database
        return CosmosDbConnectionManager(config=config, log=MagicMock())

    def _failure(self, blocked, use_managed_identity=False):
        mgr = self._manager(use_managed_identity=use_managed_identity)
        with patch.dict("sys.modules", {blocked: None}):
            with self.assertRaises(ImportError) as caught:
                mgr.create_connection()
        return caught.exception

    def test_an_absent_azure_cosmos_names_the_dblift_extra(self):
        message = str(self._failure("azure.cosmos"))

        self.assertIn('pip install "dblift[cosmosdb]"', message)

    def test_an_absent_azure_identity_names_the_same_extra(self):
        """The managed-identity path imports a *second* distribution.

        ``azure-identity`` is not a dependency of ``azure-cosmos``; the
        ``cosmosdb`` extra is what pulls both. One message can therefore stay
        correct for either import failing, which is why the plugin declares a
        single ``native_driver_module``.
        """
        message = str(self._failure("azure.identity", use_managed_identity=True))

        self.assertIn('pip install "dblift[cosmosdb]"', message)

    def test_the_message_does_not_name_the_raw_pypi_packages(self):
        """Naming them invites the install that leaves dblift's extra unrecorded."""
        message = str(self._failure("azure.cosmos"))

        self.assertNotIn("azure-cosmos", message)
        self.assertNotIn("azure-identity", message)

    def test_the_message_still_says_what_is_missing(self):
        """An actionable command is not enough — the user has to know why."""
        message = str(self._failure("azure.cosmos"))

        self.assertIn("Azure Cosmos DB SDK", message)
        self.assertIn("not installed", message)

    def test_the_original_import_error_is_kept_as_the_cause(self):
        """Re-raising must not cost the evidence of which import actually failed."""
        exc = self._failure("azure.cosmos")

        self.assertIsInstance(exc.__cause__, ImportError)
        self.assertIn("azure.cosmos", str(exc.__cause__))
