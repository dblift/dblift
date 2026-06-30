"""ADR-26 E6 parity tests: the last three non-model dialect literals in
framework code are replaced by registry/quirks capabilities.

Pins the exact behaviour of three capabilities introduced to eliminate the
remaining ``# lint: allow-dialect-string`` annotations:

1. ``BaseQuirks.is_default_sqlglot_read_fallback`` — exactly one native
   plugin (PostgreSQL) flags itself as the permissive sqlglot read-dialect
   fallback. The undo-script generators resolve their fallback from it
   instead of hardcoding ``"postgres"``. The resolved value must remain
   ``"postgres"`` (behaviour parity).
2. ``BaseQuirks.is_sqlserver_family`` — only the SQL Server plugin (and its
   aliases ``mssql``/``tsql``/``sql_server``) flags this True. Used by
   ``ExecutionEngine._parse_sql_statements`` to canonicalise *only* the SQL
   Server dialect key, leaving other aliases (``postgres``) untouched.
3. ``BaseQuirks.requires_cloud_account_auth`` — only the CosmosDB plugin
   flags this True. Gates the Azure account_endpoint/account_key/managed
   -identity validation in ``DbliftConfig.validate_complete_data``.
"""

import pytest

from db.provider_registry import ProviderRegistry


@pytest.mark.unit
class TestDefaultSqlglotReadFallbackCapability:
    def test_exactly_one_native_plugin_flags_the_fallback(self):
        flagged = [
            p.name
            for p in ProviderRegistry.list_plugins()
            if ProviderRegistry.is_native_dialect(p.name)
            and ProviderRegistry.get_quirks(p.name).is_default_sqlglot_read_fallback
        ]
        assert flagged == ["postgresql"]

    def test_fallback_quirks_sqlglot_dialect_is_postgres(self):
        flagged = [
            p.name
            for p in ProviderRegistry.list_plugins()
            if ProviderRegistry.is_native_dialect(p.name)
            and ProviderRegistry.get_quirks(p.name).is_default_sqlglot_read_fallback
        ]
        assert ProviderRegistry.get_quirks(flagged[0]).sqlglot_dialect == "postgres"

    def test_base_default_is_false(self):
        from db.base_quirks import BaseQuirks

        assert BaseQuirks().is_default_sqlglot_read_fallback is False


@pytest.mark.unit
class TestIsSqlserverFamilyCapability:
    @pytest.mark.parametrize("alias", ["sqlserver", "mssql", "tsql", "sql_server"])
    def test_sqlserver_aliases_flag_true(self, alias):
        assert ProviderRegistry.get_quirks(alias).is_sqlserver_family is True

    @pytest.mark.parametrize(
        "alias", ["postgres", "postgresql", "mysql", "oracle", "db2", "sqlite"]
    )
    def test_non_sqlserver_flag_false(self, alias):
        assert ProviderRegistry.get_quirks(alias).is_sqlserver_family is False

    def test_base_default_is_false(self):
        from db.base_quirks import BaseQuirks

        assert BaseQuirks().is_sqlserver_family is False


@pytest.mark.unit
class TestRequiresCloudAccountAuthCapability:
    def test_cosmosdb_flags_true(self):
        assert ProviderRegistry.get_quirks("cosmosdb").requires_cloud_account_auth is True

    @pytest.mark.parametrize(
        "alias", ["postgres", "postgresql", "mysql", "oracle", "db2", "sqlite", "sqlserver"]
    )
    def test_relational_flag_false(self, alias):
        assert ProviderRegistry.get_quirks(alias).requires_cloud_account_auth is False

    def test_base_default_is_false(self):
        from db.base_quirks import BaseQuirks

        assert BaseQuirks().requires_cloud_account_auth is False


@pytest.mark.unit
class TestValidateCompleteDataCosmosAuthGate:
    """Site 3: ``DbliftConfig.validate_complete_data`` gates Azure account
    auth on ``requires_cloud_account_auth`` (was ``== "cosmosdb"``)."""

    def _validate(self, database):
        from config.dblift_config import DbliftConfig

        DbliftConfig.validate_complete_data({"database": database})

    def test_cosmosdb_missing_account_key_raises(self):
        from config.dblift_config import ConfigurationError

        with pytest.raises(ConfigurationError, match="account_key"):
            self._validate(
                {
                    "type": "cosmosdb",
                    "account_endpoint": "https://acc.documents.azure.com",
                    "database_name": "db",
                }
            )

    def test_cosmosdb_missing_endpoint_raises(self):
        from config.dblift_config import ConfigurationError

        with pytest.raises(ConfigurationError, match="account_endpoint or url"):
            self._validate({"type": "cosmosdb", "account_key": "k", "database_name": "db"})

    def test_cosmosdb_missing_database_name_raises(self):
        from config.dblift_config import ConfigurationError

        with pytest.raises(ConfigurationError, match="database_name or database"):
            self._validate(
                {
                    "type": "cosmosdb",
                    "account_endpoint": "https://acc.documents.azure.com",
                    "account_key": "k",
                }
            )

    def test_cosmosdb_managed_identity_skips_account_key(self):
        # use_managed_identity=true allows omitting account_key.
        self._validate(
            {
                "type": "cosmosdb",
                "account_endpoint": "https://acc.documents.azure.com",
                "use_managed_identity": "true",
                "database_name": "db",
            }
        )

    def test_cosmosdb_full_config_validates(self):
        self._validate(
            {
                "type": "cosmosdb",
                "account_endpoint": "https://acc.documents.azure.com",
                "account_key": "k",
                "database_name": "db",
            }
        )

    def test_relational_dialect_does_not_trigger_cosmos_gate(self):
        # A postgres config without account_key must NOT raise the cosmos
        # auth error — it goes through the generic connection-identifier path.
        self._validate({"type": "postgresql", "url": "postgresql://u:p@localhost/db"})


@pytest.mark.unit
class TestUndoSqlglotFallbackParity:
    """Site 1: undo-script fallback read-dialect stays ``postgres`` and is
    derived from the registry capability, not a hardcoded literal."""

    def test_unknown_dialect_falls_back_to_postgres(self):
        from core.migration.scripting.undo_script_generator._helpers import (
            resolve_sqlglot_read_dialect,
        )

        assert resolve_sqlglot_read_dialect("") == "postgres"
        assert resolve_sqlglot_read_dialect("totally-unknown") == "postgres"
        # db2/cosmosdb declare no sqlglot_dialect → they hit the same fallback.
        assert resolve_sqlglot_read_dialect("db2") == "postgres"
        assert resolve_sqlglot_read_dialect("cosmosdb") == "postgres"

    def test_known_dialects_use_their_own(self):
        from core.migration.scripting.undo_script_generator._helpers import (
            resolve_sqlglot_read_dialect,
        )

        assert resolve_sqlglot_read_dialect("oracle") == "oracle"
        assert resolve_sqlglot_read_dialect("sqlserver") == "tsql"
        assert resolve_sqlglot_read_dialect("mysql") == "mysql"
