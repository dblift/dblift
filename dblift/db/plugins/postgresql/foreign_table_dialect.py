"""PostgreSQL foreign-table DDL missing from SQLGlot's PostgreSQL grammar.

Only forms whose complete tail is represented in the AST are accepted. Other forms
remain Commands and therefore opaque to statement facts.
"""

from __future__ import annotations

from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.parsers.postgres import PostgresParser
from sqlglot.tokens import TokenType


class ForeignTableOption(exp.Expression):
    """One parsed table or column option and its optional alteration verb."""

    arg_types = {"this": True, "value": False, "action": False}


class ForeignTableCreate(exp.Create):
    """A foreign-table creation with parsed server and inherited parents."""

    arg_types = {**exp.Create.arg_types, "server": True, "options": False, "inherits": False}


class ForeignColumnOptions(exp.Expression):
    """Options attached to a column definition or ALTER COLUMN action."""

    arg_types = {"expressions": True, "this": False}


_COLUMN_CONSTRAINTS = (
    exp.NotNullColumnConstraint,
    exp.CheckColumnConstraint,
    exp.DefaultColumnConstraint,
    exp.ComputedColumnConstraint,
    exp.CollateColumnConstraint,
    ForeignColumnOptions,
)
_LIKE_OPTIONS = frozenset({"COMMENTS", "CONSTRAINTS", "DEFAULTS", "GENERATED", "STATISTICS", "ALL"})


def _foreign_definition_supported(node: exp.Expr) -> bool:
    if isinstance(node, exp.AddConstraint):
        return bool(node.expressions) and all(
            _foreign_definition_supported(item) for item in node.expressions
        )
    if isinstance(node, exp.ColumnDef):
        return (
            isinstance(node.this, exp.Identifier)
            and isinstance(node.args.get("kind"), exp.DataType)
            and all(
                isinstance(constraint, exp.ColumnConstraint)
                and isinstance(constraint.args.get("kind"), _COLUMN_CONSTRAINTS)
                for constraint in node.args.get("constraints") or ()
            )
        )
    if isinstance(node, exp.Constraint):
        return len(node.expressions) == 1 and isinstance(
            node.expressions[0], exp.CheckColumnConstraint
        )
    if isinstance(node, exp.LikeProperty):
        source = node.this
        return (
            isinstance(source, exp.Table)
            and isinstance(source.this, exp.Identifier)
            and source.args.get("catalog") is None
            and (source.args.get("db") is None or isinstance(source.args.get("db"), exp.Identifier))
            and all(
                isinstance(option, exp.Property)
                and option.this in {"INCLUDING", "EXCLUDING"}
                and isinstance(option.args.get("value"), exp.Var)
                and option.args["value"].name.upper() in _LIKE_OPTIONS
                for option in node.expressions
            )
        )
    return isinstance(node, exp.CheckColumnConstraint)


def _foreign_alter_action_supported(action: exp.Expr) -> bool:
    if isinstance(action, (exp.ColumnDef, exp.AddConstraint)):
        return _foreign_definition_supported(action)
    if isinstance(action, exp.Drop):
        return action.args.get("kind") in {"COLUMN", "CONSTRAINT"}
    return isinstance(action, (exp.AlterColumn, exp.RenameColumn, exp.AlterRename))


class ForeignTableParser(PostgresParser):
    """Extend PostgreSQL DDL only where all foreign-table tokens are consumed."""

    _foreign_schema = False

    def _parse_column_constraint(self) -> exp.Expr | None:
        if self._foreign_schema and self._curr and self._curr.text.upper() == "OPTIONS":
            options = self._foreign_options(alter=False)
            if options is None:
                self.raise_error("Expected foreign column options")
            return self.expression(
                exp.ColumnConstraint(kind=ForeignColumnOptions(expressions=options))
            )
        return super()._parse_column_constraint()

    def _foreign_table_target(self) -> exp.Table | None:
        if not self._curr or self._curr.token_type not in (TokenType.VAR, TokenType.IDENTIFIER):
            return None
        table = self._parse_table_parts(schema=True)
        if not (
            isinstance(table, exp.Table)
            and isinstance(table.this, exp.Identifier)
            and table.this.name
            and (table.args.get("db") is None or isinstance(table.args.get("db"), exp.Identifier))
            and table.args.get("catalog") is None
            and not any(
                value for key, value in table.args.items() if key not in {"this", "db", "catalog"}
            )
        ):
            return None
        return table

    def _foreign_options(self, *, alter: bool) -> list[ForeignTableOption] | None:
        if not self._match_text_seq("OPTIONS") or not self._match(TokenType.L_PAREN):
            return None
        options: list[ForeignTableOption] = []
        while True:
            action = (
                self._prev.text.upper()
                if alter and self._match_texts(("ADD", "SET", "DROP"))
                else "ADD"
            )
            name = self._parse_id_var(any_token=False)
            if not isinstance(name, exp.Identifier) or not name.name:
                return None
            value = self._parse_string() if action != "DROP" else None
            if action != "DROP" and not isinstance(value, exp.Literal):
                return None
            options.append(ForeignTableOption(this=name, value=value, action=action))
            if not self._match(TokenType.COMMA):
                break
        if not self._match(TokenType.R_PAREN):
            return None
        return options

    def _parse_create(self) -> exp.Create | exp.Command:
        start = self._prev
        if not self._match_text_seq("FOREIGN", "TABLE"):
            return super()._parse_create()
        exists = self._parse_exists(not_=True)
        table = self._foreign_table_target()
        if table is None:
            return self._parse_as_command(start)
        self._foreign_schema = True
        try:
            this = self._parse_schema(this=table)
        finally:
            self._foreign_schema = False
        inherits: list[exp.Table] = []
        if self._match_text_seq("INHERITS"):
            if not self._match(TokenType.L_PAREN):
                return self._parse_as_command(start)
            while True:
                parent = self._foreign_table_target()
                if parent is None:
                    return self._parse_as_command(start)
                inherits.append(parent)
                if not self._match(TokenType.COMMA):
                    break
            if not self._match(TokenType.R_PAREN):
                return self._parse_as_command(start)
        if (
            not isinstance(this, exp.Schema)
            or not all(_foreign_definition_supported(node) for node in this.expressions)
            or not self._match_text_seq("SERVER")
        ):
            return self._parse_as_command(start)
        server = self._parse_id_var(any_token=False)
        if not isinstance(server, exp.Identifier) or not server.name:
            return self._parse_as_command(start)
        has_options = bool(self._curr and self._curr.text.upper() == "OPTIONS")
        options = self._foreign_options(alter=False) if has_options else None
        if self._curr or (has_options and options is None):
            return self._parse_as_command(start)
        return self.expression(
            ForeignTableCreate(
                this=this,
                kind="FOREIGN TABLE",
                exists=exists,
                server=server,
                options=options,
                inherits=inherits,
            )
        )

    def _parse_alter(self) -> exp.Alter | exp.Command:
        start = self._prev
        if not self._match_text_seq("FOREIGN"):
            return super()._parse_alter()
        table_index = self._index
        if not self._match(TokenType.TABLE):
            return self._parse_as_command(start)
        exists = self._parse_exists()
        only = self._match_text_seq("ONLY")
        table = self._foreign_table_target()
        if table is None:
            return self._parse_as_command(start)
        if self._curr and self._curr.token_type == TokenType.STAR:
            return self._parse_as_command(start)
        if self._curr and self._curr.text.upper() == "OPTIONS":
            options = self._foreign_options(alter=True)
            if options is None or self._curr:
                return self._parse_as_command(start)
            return self.expression(
                exp.Alter(
                    this=table, kind="FOREIGN TABLE", exists=exists, only=only, options=options
                )
            )
        if self._match_text_seq("ALTER"):
            self._match(TokenType.COLUMN)
            column = self._parse_id_var(any_token=False)
            if (
                isinstance(column, exp.Identifier)
                and self._curr
                and self._curr.text.upper() == "OPTIONS"
            ):
                options = self._foreign_options(alter=True)
                if options is None or self._curr:
                    return self._parse_as_command(start)
                return self.expression(
                    exp.Alter(
                        this=table,
                        kind="FOREIGN TABLE",
                        exists=exists,
                        only=only,
                        actions=[ForeignColumnOptions(this=column, expressions=options)],
                    )
                )
        self._retreat(table_index)
        node = super()._parse_alter()
        if isinstance(node, exp.Alter) and node.args.get("kind") == "TABLE":
            if (
                not node.args.get("actions")
                or any(
                    not _foreign_alter_action_supported(action) for action in node.args["actions"]
                )
                or node.args.get("options")
            ):
                return self._parse_as_command(start)
            node.set("kind", "FOREIGN TABLE")
        return node

    def _parse_drop(self, exists: bool = False, kind: str | None = None) -> exp.Drop | exp.Command:
        start = self._prev
        if kind is not None or not self._match_text_seq("FOREIGN"):
            return super()._parse_drop(exists=exists, kind=kind)
        if not self._match(TokenType.TABLE):
            return self._parse_as_command(start)
        if_exists = exists or self._parse_exists()
        targets = []
        while True:
            table = self._foreign_table_target()
            if table is None:
                return self._parse_as_command(start)
            targets.append(table)
            if not self._match(TokenType.COMMA):
                break
        cascade = self._match_text_seq("CASCADE")
        restrict = not cascade and self._match_text_seq("RESTRICT")
        if self._curr:
            return self._parse_as_command(start)
        return self.expression(
            exp.Drop(
                tables=targets,
                kind="FOREIGN TABLE",
                exists=if_exists,
                cascade=cascade,
                restrict=restrict,
            )
        )


class PostgresForeignTable(Postgres):
    """PostgreSQL dialect with foreign-table DDL for statement fact extraction."""

    Parser = ForeignTableParser
