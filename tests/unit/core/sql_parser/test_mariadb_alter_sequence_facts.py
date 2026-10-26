"""MariaDB ALTER SEQUENCE facts must follow its own documented grammar."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks


@pytest.mark.parametrize(
    "tail",
    [
        "RESTART WITH 100",
        "RESTART",
        "RESTART=100",
        "RESTART 10",
        "AS BIGINT RESTART 10",
        "AS INT UNSIGNED INCREMENT BY 2",
        "AS TINYINT UNSIGNED",
        "RESTART WITH 5 AS INT",
        "MINVALUE 10 START 10 RESTART 10",
        "INCREMENT BY -2 MINVALUE=-10 MAXVALUE 100 START WITH 1 CACHE=5 NO CYCLE",
        "NO MINVALUE NO MAXVALUE CYCLE",
        "NOMINVALUE NOMAXVALUE NOCYCLE",
        "CACHE 0 INCREMENT=3 START=7",
    ],
)
def test_mariadb_alter_sequence_documented_options_are_read(tail):
    facts = MariadbQuirks().statement_facts(f"ALTER SEQUENCE s {tail}")

    assert (facts.operation, facts.kind, facts.diagnostic, facts.error) == (
        "ALTER",
        "DDL",
        None,
        None,
    )
    assert [(o.name, o.type, o.role, o.schema) for o in facts.objects] == [
        ("s", SqlObjectType.SEQUENCE, "altered", None)
    ]


@pytest.mark.parametrize(
    ("sql", "name", "schema"),
    [
        ("ALTER SEQUENCE IF EXISTS `my s` RESTART WITH 8", "my s", None),
        ("ALTER SEQUENCE `my db`.`a``b` CACHE=0", "a`b", "my db"),
        ("ALTER SEQUENCE db.s START WITH 9 RESTART", "s", "db"),
    ],
)
def test_mariadb_alter_sequence_quoted_and_qualified_names(sql, name, schema):
    facts = MariadbQuirks().statement_facts(sql)

    assert not facts.opaque
    assert [(o.name, o.schema) for o in facts.objects] == [(name, schema)]


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER SEQUENCE s",
        "ALTER SEQUENCE s RESTART WITH",
        "ALTER SEQUENCE s RESTART WITH 1 EXTRA",
        "ALTER SEQUENCE s INCREMENT BY 1.5",
        "ALTER SEQUENCE s CACHE x",
        "ALTER SEQUENCE s NO CACHE",
        "ALTER SEQUENCE s AS VARCHAR",
        "ALTER SEQUENCE s AS INT ZEROFILL",
        "ALTER SEQUENCE s AS INT UNSIGNED SIGNED",
        "ALTER SEQUENCE s CYCLE NOCYCLE",
        "ALTER SEQUENCE s 'RESTART'",
        "ALTER SEQUENCE s RESTART /* unproven gap */ WITH 3",
        "ALTER SEQUENCE a.b.c RESTART",
    ],
)
def test_mariadb_alter_sequence_unknown_or_malformed_options_remain_opaque(sql):
    assert MariadbQuirks().statement_facts(sql).opaque


def test_mysql_does_not_claim_mariadb_alter_sequence_grammar():
    facts = MysqlQuirks().statement_facts("ALTER SEQUENCE s RESTART WITH 100")

    assert facts.opaque
