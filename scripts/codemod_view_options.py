#!/usr/bin/env python3
"""SIMP-48 codemod: rewrite ``View(...)`` calls that pass dialect-specific
kwargs to use ``View.from_options(name, *, options=ViewOptions(...))``.

Mirror of ``codemod_table_options.py`` for the ``View`` god constructor.
Conservative: only rewrites calls that pass at least one dialect-specific
kwarg. Calls using only base parameters (name, schema, query, columns,
materialized, dialect, is_updatable, check_option) are left alone.

Usage:
    python scripts/codemod_view_options.py path/to/file.py [more files...]

Idempotent: re-running on already-rewritten code is a no-op.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import libcst as cst
from libcst import matchers as m

# Kwargs grouped by their target subdataclass.
MATERIALIZED_FIELDS = {
    "is_populated",
    "refresh_method",
    "refresh_mode",
    "fast_refreshable",
    "last_refresh",
}
POSTGRES_FIELDS = {"unlogged", "security_definer", "security_invoker"}
MYSQL_FIELDS = {"algorithm", "sql_security", "definer"}
ORACLE_FIELDS = {"force"}
TOP_LEVEL_FIELDS = {"dependencies"}

ALL_DIALECT_FIELDS: Set[str] = (
    MATERIALIZED_FIELDS | POSTGRES_FIELDS | MYSQL_FIELDS | ORACLE_FIELDS | TOP_LEVEL_FIELDS
)

# Base kwargs that stay on View.from_options directly.
BASE_FIELDS = {
    "name",
    "schema",
    "query",
    "columns",
    "materialized",
    "dialect",
    "is_updatable",
    "check_option",
}


class ViewCallRewriter(cst.CSTTransformer):
    """Rewrite ``View(...)`` → ``View.from_options(...)`` when applicable."""

    def __init__(self) -> None:
        self.rewrites = 0

    @staticmethod
    def _is_view_call(node: cst.Call) -> bool:
        # Match `View(...)` and `module.View(...)`.
        func = node.func
        if isinstance(func, cst.Name) and func.value == "View":
            return True
        if isinstance(func, cst.Attribute) and func.attr.value == "View":
            return True
        return False

    def _split_kwargs(
        self, args: List[cst.Arg]
    ) -> Tuple[List[cst.Arg], Dict[str, List[cst.Arg]], List[cst.Arg]]:
        """Return (positional, dialect-by-group, base-kwargs).

        Dialect groups are keyed by 'materialized_view' / 'postgres' / 'mysql'
        / 'oracle' / 'toplevel'.
        """
        positional: List[cst.Arg] = []
        base: List[cst.Arg] = []
        dialect: Dict[str, List[cst.Arg]] = {}

        for arg in args:
            if arg.keyword is None:
                positional.append(arg)
                continue
            kw = arg.keyword.value
            if kw in MATERIALIZED_FIELDS:
                dialect.setdefault("materialized_view", []).append(arg)
            elif kw in POSTGRES_FIELDS:
                dialect.setdefault("postgres", []).append(arg)
            elif kw in MYSQL_FIELDS:
                dialect.setdefault("mysql", []).append(arg)
            elif kw in ORACLE_FIELDS:
                dialect.setdefault("oracle", []).append(arg)
            elif kw in TOP_LEVEL_FIELDS:
                dialect.setdefault("toplevel", []).append(arg)
            else:
                base.append(arg)
        return positional, dialect, base

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        if not self._is_view_call(updated_node):
            return updated_node

        positional, dialect_groups, base_kwargs = self._split_kwargs(list(updated_node.args))
        if not dialect_groups:
            return updated_node  # no dialect kwargs → leave alone

        # Build ViewOptions(...) call.
        options_kwargs: List[cst.Arg] = []
        for group_name, group_args in dialect_groups.items():
            if group_name == "toplevel":
                # dependencies lands directly on ViewOptions
                for arg in group_args:
                    options_kwargs.append(
                        cst.Arg(
                            value=arg.value,
                            keyword=arg.keyword,
                            equal=arg.equal,
                        )
                    )
                continue

            sub_cls = {
                "materialized_view": "MaterializedViewOptions",
                "postgres": "PostgresViewOptions",
                "mysql": "MySqlViewOptions",
                "oracle": "OracleViewOptions",
            }[group_name]

            sub_call = cst.Call(
                func=cst.Name(sub_cls),
                args=[cst.Arg(value=a.value, keyword=a.keyword, equal=a.equal) for a in group_args],
            )
            options_kwargs.append(
                cst.Arg(
                    value=sub_call,
                    keyword=cst.Name(group_name),
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
                )
            )

        options_call = cst.Call(func=cst.Name("ViewOptions"), args=options_kwargs)
        options_arg = cst.Arg(
            value=options_call,
            keyword=cst.Name("options"),
            equal=cst.AssignEqual(
                whitespace_before=cst.SimpleWhitespace(""),
                whitespace_after=cst.SimpleWhitespace(""),
            ),
        )

        new_args: List[cst.Arg] = list(positional) + list(base_kwargs) + [options_arg]

        old_func = updated_node.func
        if isinstance(old_func, cst.Name):
            new_func: cst.BaseExpression = cst.Attribute(
                value=cst.Name("View"),
                attr=cst.Name("from_options"),
            )
        elif isinstance(old_func, cst.Attribute):
            new_func = cst.Attribute(
                value=old_func,
                attr=cst.Name("from_options"),
            )
        else:
            return updated_node  # unreachable

        self.rewrites += 1
        return updated_node.with_changes(func=new_func, args=new_args)


def _ensure_view_options_import(module: cst.Module, used_classes: Set[str]) -> cst.Module:
    """Insert/extend ``from core.sql_model.view_options import ...`` if needed."""
    needed = sorted(used_classes)
    if not needed:
        return module

    new_body = list(module.body)
    target_idx = -1
    for i, stmt in enumerate(new_body):
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for s in stmt.body:
            if (
                isinstance(s, cst.ImportFrom)
                and s.module is not None
                and m.matches(s.module, m.Attribute(attr=m.Name("view_options")))
            ):
                target_idx = i
                break

    new_aliases = [cst.ImportAlias(name=cst.Name(c)) for c in needed]
    new_import = cst.SimpleStatementLine(
        body=[
            cst.ImportFrom(
                module=cst.parse_expression("core.sql_model.view_options"),  # type: ignore[arg-type]
                names=new_aliases,
            )
        ]
    )

    if target_idx >= 0:
        existing = new_body[target_idx]
        existing_imp = existing.body[0]
        assert isinstance(existing_imp, cst.ImportFrom)
        existing_names = (
            {n.name.value for n in existing_imp.names}
            if isinstance(existing_imp.names, (list, tuple))
            else set()
        )
        merged = sorted(existing_names | used_classes)
        merged_aliases = [cst.ImportAlias(name=cst.Name(c)) for c in merged]
        new_body[target_idx] = existing.with_changes(
            body=[existing_imp.with_changes(names=merged_aliases)]
        )
    else:
        insert_at = 0
        for i, stmt in enumerate(new_body):
            if isinstance(stmt, cst.SimpleStatementLine) and any(
                isinstance(s, (cst.Import, cst.ImportFrom)) for s in stmt.body
            ):
                insert_at = i + 1
        new_body.insert(insert_at, new_import)
    return module.with_changes(body=new_body)


def _classes_used(source: str) -> Set[str]:
    """Inspect the rewritten source to figure out which dataclasses appear."""
    used: Set[str] = set()
    for cls in (
        "ViewOptions",
        "MaterializedViewOptions",
        "PostgresViewOptions",
        "MySqlViewOptions",
        "OracleViewOptions",
    ):
        if cls in source:
            used.add(cls)
    return used


def rewrite_file(path: Path) -> int:
    src = path.read_text()
    tree = cst.parse_module(src)
    rewriter = ViewCallRewriter()
    new_tree = tree.visit(rewriter)
    if rewriter.rewrites == 0:
        return 0

    new_src = new_tree.code
    used_classes = _classes_used(new_src)
    new_tree = _ensure_view_options_import(new_tree, used_classes)
    path.write_text(new_tree.code)
    return rewriter.rewrites


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+", type=Path)
    args = p.parse_args()

    total = 0
    for path in args.paths:
        if not path.exists():
            print(f"skip (missing): {path}", file=sys.stderr)
            continue
        n = rewrite_file(path)
        if n:
            print(f"{path}: {n} call(s) rewritten")
        total += n
    print(f"\nTotal rewrites: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
