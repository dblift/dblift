"""Provider implementation for {{cookiecutter.dialect_name}}.

Start here with SqlAlchemyProvider for relational / SQLAlchemy-native
drivers. For pure-SDK databases (e.g. CosmosDB style) inherit from
BaseProvider instead and implement the five component managers.
"""

from db.sqlalchemy_provider import SqlAlchemyProvider


class {{cookiecutter.dialect_name.capitalize()}}Provider(SqlAlchemyProvider):
    """{{cookiecutter.dialect_name.capitalize()}} provider using SQLAlchemy Core + native driver."""

    canonical_dialect_key = "{{cookiecutter.dialect_name}}"

    def __init__(self, config, log=None):
        super().__init__(config=config, log=log)
        # If you need custom connection/query/schema/locking/history managers,
        # pass the _class kwargs to super, e.g.:
        # super().__init__(
        #     config=config,
        #     log=log,
        #     connection_manager_class=...,
        #     ...
        # )
