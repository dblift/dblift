"""Regression tests for BUG-05: DbliftConfig.merge() must not clobber file credentials.

Root cause: merge() iterated over current_db (self) and only back-filled keys that
were absent from db_data (other_config). When ConfigBuilder.merge(file_config, default_config)
was called, the default config's empty strings ("", "") for username/password were
already present in db_data, so the guard `if key not in db_data` silently kept the
empty strings instead of letting the file's real credentials win.

Fix: guard changed to `if key not in db_data or not db_data[key]`.
"""

import textwrap

import pytest

from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import DbliftConfig


@pytest.mark.unit
class TestMergePreservesFileCredentials:
    """BUG-05: merge() must not overwrite non-empty values with empty strings."""

    def test_merge_preserves_username_when_other_has_empty(self):
        """Merging empty override values onto a file config must keep the file username."""
        file_config = DbliftConfig.from_dict(
            {
                "database": {
                    "type": "postgresql",
                    "url": "postgresql+psycopg://localhost/mydb",
                    "username": "alice",
                    "password": "s3cr3t",
                    "schema": "public",
                }
            }
        )
        assert file_config.database.username == "alice"

        file_config.merge({"database": {"username": "", "password": ""}})

        assert (
            file_config.database.username == "alice"
        ), "merge() must not overwrite a non-empty username with an empty string"
        assert (
            file_config.database.password == "s3cr3t"
        ), "merge() must not overwrite a non-empty password with an empty string"

    def test_merge_still_fills_absent_keys(self):
        """Keys genuinely absent from other_config are back-filled from self."""
        base = DbliftConfig.from_dict(
            {
                "database": {
                    "type": "postgresql",
                    "url": "postgresql+psycopg://localhost/mydb",
                    "username": "bob",
                    "password": "pw",
                    "schema": "public",
                }
            }
        )
        # Merge a dict that has url but lacks username (absent, not empty)
        base.merge({"database": {"url": "postgresql+psycopg://other/db"}})

        # url overwritten (present in other), username preserved (absent in other)
        assert base.database.url == "postgresql+psycopg://other/db"
        assert base.database.username == "bob"

    def test_build_file_credentials_survive_env_merge(self, tmp_path, monkeypatch):
        """ConfigBuilder.build() must keep file credentials when no DBLIFT_* env vars are set."""
        for var in ("DBLIFT_DB_URL", "DBLIFT_DB_USER", "DBLIFT_DB_PASSWORD"):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                database:
                  type: postgresql
                  url: postgresql+psycopg://localhost/testdb
                  username: carol
                  password: secret123
                  schema: public
                """),
            encoding="utf-8",
        )

        config = ConfigBuilder.build(file_path=str(config_file), env_overrides=True)

        assert (
            config.database.username == "carol"
        ), "from_config_file() must preserve username from file when no env vars are set"
        assert config.database.password == "secret123"
        assert config.database.url == "postgresql+psycopg://localhost/testdb"

    def test_env_var_takes_precedence_over_file(self, tmp_path, monkeypatch):
        """When DBLIFT_DB_USER IS set, the env value wins over the file value."""
        monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://localhost/envdb")
        monkeypatch.setenv("DBLIFT_DB_USER", "env_user")
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", "env_pass")

        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                database:
                  type: postgresql
                  url: postgresql+psycopg://localhost/filedb
                  username: file_user
                  password: file_pass
                  schema: public
                """),
            encoding="utf-8",
        )

        config = ConfigBuilder.build(file_path=str(config_file), env_overrides=True)

        assert (
            config.database.username == "env_user"
        ), "env var must override file when both are present"
        assert config.database.password == "env_pass"

    def test_partial_env_user_only_does_not_clobber_file_url(self, tmp_path, monkeypatch):
        """DBLIFT_DB_USER alone must not cause an implicit SQL Server URL to replace the file URL.

        BUG: guard used from_env_dict() (any DBLIFT_DB_* var) but from_env()
        required DBLIFT_DB_URL or it used non-empty SQL Server placeholders,
        clobbering the file's PostgreSQL URL.
        """
        monkeypatch.setenv("DBLIFT_DB_USER", "override_user")
        monkeypatch.delenv("DBLIFT_DB_URL", raising=False)
        monkeypatch.delenv("DBLIFT_DB_PASSWORD", raising=False)

        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                database:
                  type: postgresql
                  url: postgresql+psycopg://localhost/mydb
                  username: file_user
                  password: file_pass
                  schema: public
                """),
            encoding="utf-8",
        )

        config = ConfigBuilder.build(file_path=str(config_file), env_overrides=True)

        assert (
            config.database.username == "override_user"
        ), "DBLIFT_DB_USER must override file username"
        assert (
            "postgresql" in config.database.url
        ), "file URL must not be clobbered by SQL Server default when only DBLIFT_DB_USER is set"
        assert (
            config.database.password == "file_pass"
        ), "file password must be preserved when DBLIFT_DB_PASSWORD is not set"
