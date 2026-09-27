"""Live MySQL check: ``clean`` must fail when it cannot see the events.

``information_schema.EVENTS`` hides the events of a database on which the
user lacks the EVENT privilege instead of raising, so ``clean`` used to drop
everything else, report success and leave the events behind.
"""

import uuid
from typing import Any

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.integration

USER_PASSWORD = "clean_evt_pw"


def _provider(mysql: dict[str, Any], database: str, username: str, password: str):
    return ProviderRegistry.create_provider(
        DbliftConfig(
            database=MySqlConfig(
                type="mysql",
                host=mysql["host"],
                port=mysql["port"],
                database=database,
                username=username,
                password=password,
                schema=database,
            )
        )
    )


@pytest.fixture
def populated_database(db_configs: dict[str, Any]):
    database = f"dblift_clean_evt_{uuid.uuid4().hex[:8]}"
    user = database
    mysql = db_configs["mysql"]
    admin = _provider(mysql, mysql["database"], mysql["username"], mysql["password"])
    admin.create_connection()
    for statement in (
        f"CREATE DATABASE `{database}`",
        f"CREATE USER '{user}'@'%' IDENTIFIED BY '{USER_PASSWORD}'",
        f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'%'",
    ):
        admin.execute_statement(statement)
    # The user owns the objects, as after a migrate: an event whose definer
    # is root could not be dropped by it whatever its privileges.
    owner = _provider(mysql, database, user, USER_PASSWORD)
    owner.create_connection()
    try:
        for statement in (
            "CREATE TABLE `orders` (id INT)",
            "CREATE TRIGGER `orders_bi` BEFORE INSERT ON `orders` "
            "FOR EACH ROW SET NEW.id = NEW.id",
            "CREATE EVENT `nightly` ON SCHEDULE EVERY 1 DAY DISABLE DO SELECT 1",
        ):
            owner.execute_statement(statement)
    finally:
        owner.close()

    def objects() -> list:
        rows = admin.execute_query(
            "SELECT TABLE_NAME AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? "
            "UNION ALL SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
            "WHERE TRIGGER_SCHEMA = ? "
            "UNION ALL SELECT EVENT_NAME FROM information_schema.EVENTS WHERE EVENT_SCHEMA = ?",
            [database, database, database],
        )
        return sorted(row["n"] for row in rows)

    try:
        yield {
            "mysql": mysql,
            "admin": admin,
            "database": database,
            "user": user,
            "objects": objects,
        }
    finally:
        admin.execute_statement(f"DROP DATABASE IF EXISTS `{database}`")
        admin.execute_statement(f"DROP USER IF EXISTS '{user}'@'%'")
        admin.close()


def _clean(populated_database, tmp_path):
    provider = _provider(
        populated_database["mysql"],
        populated_database["database"],
        populated_database["user"],
        USER_PASSWORD,
    )
    try:
        return DBLiftClient(provider=provider, migrations_dir=tmp_path).clean(clean_enabled=True)
    finally:
        provider.close()


def test_clean_without_event_privilege_fails_and_drops_nothing(
    populated_database, tmp_path
) -> None:
    db = populated_database
    db["admin"].execute_statement(f"REVOKE EVENT ON `{db['database']}`.* FROM '{db['user']}'@'%'")

    result = _clean(db, tmp_path)

    assert result.success is False
    assert "EVENT privilege" in result.error_message
    assert db["objects"]() == ["nightly", "orders", "orders_bi"]


def test_clean_with_event_privilege_drops_everything(populated_database, tmp_path) -> None:
    result = _clean(populated_database, tmp_path)

    assert result.success is True
    assert populated_database["objects"]() == []


def test_clean_without_trigger_privilege_still_drops_everything(
    populated_database, tmp_path
) -> None:
    # information_schema.TRIGGERS also hides triggers from a user without the
    # TRIGGER privilege, but DROP TABLE removes a table's triggers with it, so
    # clean still empties the database and must not fail.
    db = populated_database
    db["admin"].execute_statement(f"REVOKE TRIGGER ON `{db['database']}`.* FROM '{db['user']}'@'%'")

    result = _clean(db, tmp_path)

    assert result.success is True
    assert db["objects"]() == []
