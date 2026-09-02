"""``MongodbQuirks`` — the capability declarations that route MongoDB."""

from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.mongodb.quirks import MongodbQuirks


def test_declares_itself_nosql():
    assert MongodbQuirks().is_nosql is True


def test_rejects_sql_migrations():
    """Drives the DBLIFT-NOSQL-001 guard in the executor factory."""
    assert MongodbQuirks().supports_sql_migrations is False


def test_no_transactions_claimed():
    """pymongo requires an explicit session= on every call, so dblift cannot
    wrap a user's own driver calls in a transaction it owns."""
    assert MongodbQuirks().supports_transactions is False
    assert MongodbQuirks().supports_transactional_ddl is False


def test_schema_is_not_required():
    assert MongodbQuirks().schema_required is False


def test_identifiers_are_not_quoted():
    """Collection names are strings passed to the driver, never interpolated
    into a statement — quoting them would corrupt the name."""
    quirks = MongodbQuirks()
    assert quirks.quote_open == ""
    assert quirks.quote_close == ""


def test_uses_ordinary_credentials():
    """Unlike an account-key cloud API, MongoDB has real user/password auth —
    and a local mongod may have none at all."""
    quirks = MongodbQuirks()
    assert quirks.requires_cloud_account_auth is False
    assert quirks.requires_credentials is False


def test_no_generators_or_parsers():
    quirks = MongodbQuirks()
    assert quirks.ddl_generator_class() is None
    assert quirks.alter_generator_class() is None
    assert quirks.parser_class("hybrid") is None
    assert quirks.parser_class("regex") is None
    assert quirks.parser_class("sqlglot") is None
    assert quirks.introspector_class() is None


def test_default_dialect_name():
    assert MongodbQuirks().dialect_name == "mongodb"


def test_alias_dialect_name_is_accepted():
    assert MongodbQuirks(dialect_name="mongo").dialect_name == "mongo"


def test_is_a_base_quirks():
    assert isinstance(MongodbQuirks(), BaseQuirks)
