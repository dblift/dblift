"""Live PostgreSQL regression: reuse history without a rank default.

Set DBLIFT_TEST_POSTGRESQL_URL and run this file with --noconftest to use
an existing PostgreSQL instance without the Docker integration harness.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.api._engine_config import config_from_engine

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]


@pytest.fixture
def flyway_client(tmp_path):
    url = os.environ.get("DBLIFT_TEST_POSTGRESQL_URL")
    if not url:
        pytest.skip("DBLIFT_TEST_POSTGRESQL_URL is not configured")
    engine = create_engine(url)
    schema = "flyway_reuse_" + uuid.uuid4().hex[:12]
    scripts = tmp_path / "sql"
    scripts.mkdir()
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f"""CREATE TABLE "{schema}".flyway_schema_history (
            installed_rank INT NOT NULL PRIMARY KEY, version VARCHAR(50),
            description VARCHAR(200) NOT NULL, type VARCHAR(20) NOT NULL,
            script VARCHAR(1000) NOT NULL, checksum INT, installed_by VARCHAR(100) NOT NULL,
            installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            execution_time INT NOT NULL, success BOOLEAN NOT NULL
        )"""))
    config = config_from_engine(engine, schema=schema, migrations_dir=scripts)
    config.history_table = "flyway_schema_history"
    client = DBLiftClient.from_sqlalchemy(
        engine, schema=schema, migrations_dir=scripts, config=config
    )
    try:
        yield client, scripts, engine, schema
    finally:
        client.close()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_migrate_records_rank_in_existing_flyway_table(flyway_client):
    client, scripts, engine, schema = flyway_client
    imported = client.import_flyway(flyway_table="flyway_schema_history")
    assert imported.success, imported.error_message
    (scripts / "V1__create.sql").write_text(f'CREATE TABLE "{schema}".t (id INT);')
    result = client.migrate()
    assert result.success, result.error_message
    (scripts / "V2__alter.sql").write_text(f'ALTER TABLE "{schema}".t ADD name TEXT;')
    result = client.migrate()
    assert result.success, result.error_message
    with engine.connect() as conn:
        ranks = (
            conn.execute(
                text(
                    f'SELECT installed_rank FROM "{schema}".flyway_schema_history ORDER BY installed_rank'
                )
            )
            .scalars()
            .all()
        )
        assert ranks == [1, 2]


def test_history_insert_failure_rolls_back_migration_ddl(flyway_client):
    client, scripts, engine, schema = flyway_client
    with engine.begin() as conn:
        conn.execute(
            text(
                f'ALTER TABLE "{schema}".flyway_schema_history ADD CONSTRAINT reject_history CHECK (installed_rank < 0)'
            )
        )
    (scripts / "V1__create.sql").write_text(f'CREATE TABLE "{schema}".must_rollback (id INT);')
    result = client.migrate()
    assert not result.success
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT to_regclass(:name)"), {"name": f"{schema}.must_rollback"}
            ).scalar()
            is None
        )


@pytest.mark.parametrize("owned", [False, True])
def test_native_history_keeps_its_sequence_in_sync(flyway_client, owned):
    client, scripts, engine, schema = flyway_client
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SEQUENCE "{schema}".history_rank'))
        if owned:
            conn.execute(
                text(
                    f'ALTER SEQUENCE "{schema}".history_rank OWNED BY "{schema}".flyway_schema_history.installed_rank'
                )
            )
        conn.execute(text(f"""ALTER TABLE "{schema}".flyway_schema_history
            ALTER installed_rank SET DEFAULT nextval('"{schema}".history_rank')"""))
    (scripts / "V1__create.sql").write_text(f'CREATE TABLE "{schema}".t (id INT);')
    result = client.migrate()
    assert result.success, result.error_message
    with engine.begin() as conn:
        rank = conn.execute(text(f"""INSERT INTO "{schema}".flyway_schema_history
            (version, description, type, script, installed_by, execution_time, success)
            VALUES ('2', 'external', 'SQL', 'V2__external.sql', 'external', 0, TRUE)
            RETURNING installed_rank""")).scalar()
        assert rank == 2


def test_generated_always_identity_history_remains_supported(flyway_client):
    client, scripts, engine, schema = flyway_client
    with engine.begin() as conn:
        conn.execute(text(f"""ALTER TABLE "{schema}".flyway_schema_history
            ALTER installed_rank ADD GENERATED ALWAYS AS IDENTITY"""))
    (scripts / "V1__create.sql").write_text(f'CREATE TABLE "{schema}".t (id INT);')
    result = client.migrate()
    assert result.success, result.error_message
