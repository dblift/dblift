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

    arg_types = {
        **exp.Create.arg_types,
        "server": True,
        "options": False,
        "inherits": False,
        "partition_parent": False,
        "partition_bound": False,
    }


class ForeignPartitionBound(exp.Expression):
    """A validated partition bound with its parsed operands."""

    arg_types = {"kind": True, "expressions": False, "upper": False}


class ForeignTableAction(exp.Expression):
    """A fully consumed foreign-table alteration."""

    arg_types = {"kind": True, "this": False, "parent": False, "value": False}


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


def _foreign_definition_supported(node: exp.Expr, *, partition: bool = False) -> bool:
    if isinstance(node, exp.AddConstraint):
        return bool(node.expressions) and all(
            _foreign_definition_supported(item, partition=partition) for item in node.expressions
        )
    if isinstance(node, exp.ColumnDef):
        return (
            isinstance(node.this, exp.Identifier)
            and (
                (node.args.get("kind") is None and bool(node.args.get("constraints")))
                if partition
                else isinstance(node.args.get("kind"), exp.DataType)
            )
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
        if partition:
            return False
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
        targets = list(action.args.get("tables") or ())
        kind = action.args.get("kind")
        return len(targets) == 1 and (
            (kind == "COLUMN" and _simple_column(targets[0]))
            or (kind == "CONSTRAINT" and _simple_table(targets[0]))
        )
    if isinstance(action, exp.RenameColumn):
        return _simple_column(action.this) and _simple_column(action.args.get("to"))
    if isinstance(action, exp.AlterRename):
        return _simple_table(action.this)
    if isinstance(action, exp.AlterColumn):
        return (
            isinstance(action.this, exp.Identifier)
            and not action.args.get("using")
            and not action.args.get("exists")
            and (
                isinstance(action.args.get("dtype"), exp.DataType)
                or action.args.get("default") is not None
                or action.args.get("drop") is True
                or action.args.get("allow_null") is not None
            )
        )
    return False


def _simple_column(node: exp.Expr | None) -> bool:
    return (
        isinstance(node, exp.Column)
        and isinstance(node.this, exp.Identifier)
        and bool(node.this.name)
        and not any(value for key, value in node.args.items() if key != "this")
    )


def _simple_table(node: exp.Expr | None) -> bool:
    return (
        isinstance(node, exp.Table)
        and isinstance(node.this, exp.Identifier)
        and bool(node.this.name)
        and not any(value for key, value in node.args.items() if key != "this")
    )


class ForeignTableParser(PostgresParser):
    """Extend PostgreSQL DDL only where all foreign-table tokens are consumed."""

    _foreign_schema = False
    _foreign_alter = False
    _foreign_unread_tail = False

    def _parse_alter_table_alter(self) -> exp.Expr | None:
        node = super()._parse_alter_table_alter()
        if (
            self._foreign_alter
            and isinstance(node, exp.AlterColumn)
            and (
                (self._prev.token_type == TokenType.USING and not node.args.get("using"))
                or (self._prev.token_type == TokenType.COLLATE and not node.args.get("collate"))
            )
        ):
            self._foreign_unread_tail = True
        return node

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

    def _foreign_bound_values(self) -> list[exp.Expr] | None:
        if not self._match(TokenType.L_PAREN):
            return None
        first = self._parse_disjunction()
        if first is None:
            return None
        values = [first]
        while self._match(TokenType.COMMA):
            value = self._parse_disjunction()
            if value is None:
                return None
            values.append(value)
        if not self._match(TokenType.R_PAREN):
            return None
        return values

    def _foreign_partition_bound(self) -> ForeignPartitionBound | None:
        if self._match_text_seq("DEFAULT"):
            return ForeignPartitionBound(kind="DEFAULT")
        if not self._match_text_seq("FOR", "VALUES"):
            return None
        if self._match_text_seq("IN"):
            values = self._foreign_bound_values()
            return ForeignPartitionBound(kind="IN", expressions=values) if values else None
        if self._match_text_seq("FROM"):
            lower = self._foreign_bound_values()
            if lower and self._match_text_seq("TO"):
                upper = self._foreign_bound_values()
                if upper:
                    return ForeignPartitionBound(kind="FROM", expressions=lower, upper=upper)
            return None
        if self._match_text_seq("WITH") and self._match(TokenType.L_PAREN):
            if not self._match_text_seq("MODULUS"):
                return None
            modulus = self._parse_number()
            if not isinstance(modulus, exp.Literal) or not modulus.is_int or int(modulus.this) < 1:
                return None
            if not self._match(TokenType.COMMA) or not self._match_text_seq("REMAINDER"):
                return None
            remainder = self._parse_number()
            if (
                not isinstance(remainder, exp.Literal)
                or not remainder.is_int
                or not 0 <= int(remainder.this) < int(modulus.this)
            ):
                return None
            if self._match(TokenType.R_PAREN):
                return ForeignPartitionBound(kind="WITH", expressions=[modulus, remainder])
        return None

    def _parse_create(self) -> exp.Create | exp.Command:
        start = self._prev
        if not self._match_text_seq("FOREIGN", "TABLE"):
            return super()._parse_create()
        exists = self._parse_exists(not_=True)
        table = self._foreign_table_target()
        if table is None:
            return self._parse_as_command(start)
        partition_parent = None
        partition_bound = None
        this: exp.Expr | None
        if self._match_text_seq("PARTITION", "OF"):
            partition_parent = self._foreign_table_target()
            if partition_parent is None:
                return self._parse_as_command(start)
            self._foreign_schema = True
            try:
                this = self._parse_schema(this=table)
            finally:
                self._foreign_schema = False
            if this is table:
                this = exp.Schema(this=table)
            partition_bound = self._foreign_partition_bound()
            if partition_bound is None:
                return self._parse_as_command(start)
        else:
            self._foreign_schema = True
            try:
                this = self._parse_schema(this=table)
            finally:
                self._foreign_schema = False
        inherits: list[exp.Table] = []
        if partition_parent is None and self._match_text_seq("INHERITS"):
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
            or not all(
                _foreign_definition_supported(node, partition=partition_parent is not None)
                for node in this.expressions
            )
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
                partition_parent=partition_parent,
                partition_bound=partition_bound,
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
        action_index = self._index
        action = None
        if self._match_text_seq("SET", "SCHEMA"):
            schema = self._parse_id_var(any_token=False)
            if isinstance(schema, exp.Identifier) and schema.name:
                action = ForeignTableAction(kind="SET SCHEMA", this=schema)
        elif self._match_text_seq("OWNER", "TO"):
            owner = self._parse_id_var(any_token=False)
            if isinstance(owner, exp.Identifier) and owner.name:
                action = ForeignTableAction(kind="OWNER TO", this=owner)
        elif self._match_texts(("ENABLE", "DISABLE")):
            verb = self._prev.text.upper()
            if self._match_text_seq("TRIGGER"):
                trigger = self._parse_id_var(any_token=False)
                if isinstance(trigger, exp.Identifier) and trigger.name:
                    action = ForeignTableAction(kind=f"{verb} TRIGGER", this=trigger)
        elif self._match_text_seq("NO", "INHERIT"):
            parent = self._foreign_table_target()
            if parent is not None:
                action = ForeignTableAction(kind="NO INHERIT", parent=parent)
        elif self._match_text_seq("INHERIT"):
            parent = self._foreign_table_target()
            if parent is not None:
                action = ForeignTableAction(kind="INHERIT", parent=parent)
        if action is not None:
            if self._curr:
                return self._parse_as_command(start)
            return self.expression(
                exp.Alter(
                    this=table, kind="FOREIGN TABLE", exists=exists, only=only, actions=[action]
                )
            )
        if self._match_text_seq("ALTER"):
            self._match(TokenType.COLUMN)
            column = self._parse_id_var(any_token=False)
            if isinstance(column, exp.Identifier) and self._match_text_seq("SET", "STORAGE"):
                storage = self._parse_id_var(any_token=False)
                if (
                    isinstance(storage, exp.Identifier)
                    and storage.name.upper() in {"PLAIN", "EXTERNAL", "EXTENDED", "MAIN"}
                    and not self._curr
                ):
                    return self.expression(
                        exp.Alter(
                            this=table,
                            kind="FOREIGN TABLE",
                            exists=exists,
                            only=only,
                            actions=[
                                ForeignTableAction(kind="SET STORAGE", this=column, value=storage)
                            ],
                        )
                    )
            self._retreat(action_index)
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
        if self._match_text_seq("ADD"):
            actions = self._parse_alter_table_add()
            if (
                actions
                and all(_foreign_alter_action_supported(item) for item in actions)
                and self._prev.token_type == TokenType.COMMA
                and self._curr
                and self._curr.text.upper() == "OPTIONS"
            ):
                options = self._foreign_options(alter=True)
                if options is not None and not self._curr:
                    return self.expression(
                        exp.Alter(
                            this=table,
                            kind="FOREIGN TABLE",
                            exists=exists,
                            only=only,
                            actions=actions,
                            options=options,
                        )
                    )
        self._retreat(table_index)
        self._foreign_alter = True
        self._foreign_unread_tail = False
        try:
            node = super()._parse_alter()
        finally:
            self._foreign_alter = False
        if isinstance(node, exp.Alter) and node.args.get("kind") == "TABLE":
            if (
                self._foreign_unread_tail
                or not node.args.get("actions")
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
