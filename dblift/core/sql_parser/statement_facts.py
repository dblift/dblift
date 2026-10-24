"""Statement facts: the evidence one statement gives about the objects it names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

from dblift.core.sql_model.base import SqlObject, SqlObjectType
from dblift.core.sql_parser.lexical_spec import LexicalSpec


@dataclass(frozen=True)
class NamedObject:
    """An object named by a statement and the role it plays there."""

    name: str
    type: SqlObjectType
    role: str
    schema: Optional[str] = None

    def as_sql_object(self, default_schema: Optional[str] = None, dialect: str = "") -> SqlObject:
        """Project identity into the established public object shape."""
        return SqlObject(self.name, self.type, self.schema or default_schema, dialect)


@dataclass(frozen=True)
class DeclaredConstraint:
    """A declared key or reference without a schema-model interpretation."""

    kind: str
    columns: Tuple[str, ...]
    name: Optional[str] = None
    referenced_table: Optional[str] = None
    referenced_columns: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DmlEffect:
    """A data change a statement makes besides its own: one writing CTE.

    ``target`` is the table as written (``schema.table``), ``events`` the DML events it fires.
    """

    operation: str
    target: str
    target_sql: str
    predicate: Optional[str]
    events: frozenset[str]
    affected_columns: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StatementFacts:
    """Statement-level evidence.

    ``diagnostic`` is information naming a construct whose detail was not read; ``error`` is
    reserved for text the engine would refuse (a refused script, text that does not tokenize).
    """

    operation: str
    kind: str
    objects: Tuple[NamedObject, ...] = ()
    target: Optional[str] = None
    predicate: Optional[str] = None
    declared_columns: Tuple[str, ...] = ()
    declared_constraints: Tuple[DeclaredConstraint, ...] = ()
    declared_column_comments: Optional[Tuple[str, ...]] = None
    indexed_table: Optional[str] = None
    indexed_columns: Optional[Tuple[str, ...]] = None
    affected_columns: Tuple[str, ...] = ()
    events: Optional[frozenset[str]] = None
    action: Optional[str] = None
    diagnostic: Optional[str] = None
    error: Optional[str] = None
    target_sql: Optional[str] = None
    cte_writes: Tuple[DmlEffect, ...] = ()

    @property
    def opaque(self) -> bool:
        """Whether grammar detail was unavailable for this statement."""
        return self.diagnostic is not None or self.error is not None

    @property
    def affected_objects(self) -> Tuple[NamedObject, ...]:
        """Objects this statement changes, excluding read-only references."""
        return tuple(obj for obj in self.objects if obj.role != "referenced")


class StatementFactsReader(Protocol):
    """Structural contract for a plugin-owned statement facts reader."""

    def __init__(self, dialect: Optional[str], spec: Optional[LexicalSpec] = None):
        """Bind optional grammar and lexical metadata supplied by the plugin."""
        ...

    def read(self, sql: str) -> StatementFacts:
        """Read one already-split statement."""
        ...


class SqlglotStatementFactsReader:
    """Reusable AST facts reader configured by a dialect."""

    def __init__(self, dialect: Optional[str], spec: Optional[LexicalSpec] = None):
        """Bind sqlglot grammar and optional lexical metadata."""
        if dialect is None:
            raise ValueError("A SQLGlot statement facts reader requires a dialect")
        self.dialect = dialect
        self.spec = spec

    def read(self, sql: str) -> StatementFacts:
        """Read one already-split statement."""
        try:
            from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
        except ModuleNotFoundError as exc:
            if exc.name != "sqlglot":
                raise
            raise ModuleNotFoundError(
                "reading statement facts needs SQLGlot: install it with "
                "`pip install dblift[analysis]`",
                name="sqlglot",
            ) from exc

        return read_statement_facts(sql, dialect=self.dialect)
