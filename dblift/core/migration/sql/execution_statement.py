"""Execution-time SQL statement metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, List, Optional

from dblift.core.exceptions import TransactionStatementError
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.core.utils.row_access import strip_leading_comments


@dataclass(frozen=True)
class ExecutionStatement:
    """A SQL statement plus transaction metadata used by the execution engine."""

    sql: str
    statement_type: str = "UNKNOWN"
    can_execute_in_transaction: bool = True
    transaction_reason: Optional[str] = None


def is_comment_only_statement(sql: str, *, nested_block_comments: bool = False) -> bool:
    """True if *sql* has no executable tokens after removing block and line comments.

    MySQL/MariaDB executable comment directives (``/*!...*/``, ``/*M!...*/``) are not
    comments the server skips — it runs their contents — so they are excluded from the
    strip and never count as "comment only".

    Pass ``nested_block_comments=True`` for a dialect whose block comments nest
    (its tokenizer's ``NESTED_BLOCK_COMMENTS``): ``/* a /* b */ c */`` is then one
    comment, stripped by the same scanner the dialect parsers use. MySQL/MariaDB
    comments do not nest, so their directives always take the default path.
    """

    body = sql.strip()
    if not body:
        return True
    if nested_block_comments:
        return not strip_comments_preserving_quotes(
            body, line_prefixes=["--"], has_block_comments=True, nested_block_comments=True
        )
    body = re.sub(r"/\*(?!!|M!).*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"--.*?$", "", body, flags=re.MULTILINE)
    return not body.strip()


@lru_cache(maxsize=None)
def _script_parser(dialect: str) -> Any:
    """The dialect parser that owns execution and analysis script boundaries."""
    from dblift.db.provider_registry import ProviderRegistry

    parser_class = ProviderRegistry.get_quirks(dialect).parser_class("regex")
    return parser_class() if parser_class is not None else None


def _statements_of(sql: str, dialect: str) -> List[str]:
    """Scanner-derived constituents of one execution unit."""
    parser = _script_parser(dialect)
    if parser is None:
        return [sql]
    return list(parser.split_for_analysis(sql))


def execution_units(sql: str, dialect: str) -> Optional[List[str]]:
    """The scanner's executable units once each, omitting skipped client batches.

    ``None`` means the dialect has no record API. A scanner refusal propagates.
    """
    parser = _script_parser(dialect.lower())
    if parser is None or not hasattr(parser, "split"):
        return None
    return [
        record.text
        for record in parser.split(sql)
        if record.kind != "directive" and record.repeat > 0
    ]


def classify_execution_statement(
    sql: str, *, dialect: str, statement_type: str = "UNKNOWN"
) -> ExecutionStatement:
    """Classify transaction metadata for high-confidence dialect-specific cases."""
    from dblift.db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(dialect.lower())
    if not quirks.non_transactional_sql_patterns:
        return ExecutionStatement(sql=sql, statement_type=statement_type)

    # A batch is not transactional when any of its statements is not: SQL Server refuses that
    # statement inside the transaction the whole batch would run in.
    for statement in _statements_of(sql, dialect.lower()):
        # A comment in front of the statement (a migration's own notes, a generated script's
        # header) is not part of it; the patterns are anchored at the statement's first keyword.
        normalized = re.sub(r"\s+", " ", strip_leading_comments(statement).strip()).upper()
        for pattern, reason in quirks.non_transactional_sql_patterns:
            if re.match(pattern, normalized):
                return ExecutionStatement(
                    sql=sql,
                    statement_type=statement_type,
                    can_execute_in_transaction=False,
                    transaction_reason=reason,
                )

    return ExecutionStatement(sql=sql, statement_type=statement_type)


def neutralise_transaction_statements(
    statements: List[str],
    *,
    dialect: str,
    log: Any,
    script_name: str = "the script",
    content: str = "",
) -> List[str]:
    """*statements* with a script's ``BEGIN ... COMMIT`` envelope dropped, or a refusal.

    dblift runs a script in one transaction of its own. A script whose first statement is a
    ``begin`` and whose last is an ``end`` (``quirks.transaction_control_sql_patterns``) is that
    same transaction: both are dropped and a warning says so. Any other transaction statement
    would end or fail against dblift's transaction, and is refused before anything runs, as is
    an envelope around a statement that cannot run in a transaction.
    A dialect with no patterns gets *statements* back untouched.
    """
    from dblift.db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(dialect.lower())
    patterns = quirks.transaction_control_sql_patterns
    if not patterns:
        parser = _script_parser(dialect.lower())
        if not content or parser is None or not hasattr(parser, "split"):
            return statements
        records = [
            record
            for record in parser.split(content)
            if record.kind != "directive" and record.repeat > 0
            for _ in range(record.repeat)
        ]
        if [record.text.strip().rstrip(";") for record in records] != [
            statement.strip().rstrip(";") for statement in statements
        ]:
            return statements
        for index, record in enumerate(records):
            if not record.multi:
                continue
            parts = record.analysis_statements or (record.text,)
            if len(parts) < 2:
                continue
            for part in parts:
                text = re.sub(r"\s+", " ", _without_comments(quirks, part)).upper()
                if re.match(r"^(?:BEGIN|START TRANSACTION|COMMIT|ROLLBACK)\b", text):
                    where = _position(statements, index, dialect, content)
                    raise TransactionStatementError(
                        f"{script_name}, {where}: {text.rstrip(';')} manages the transaction "
                        "inside one execution unit, so none of its statements were executed. "
                        "Remove it from the combined unit."
                    )
        return statements
    # (index, normalised text, kind) of every executable statement.
    executable = []
    for index, statement in enumerate(statements):
        if is_comment_only_statement(statement):
            continue
        text = re.sub(r"\s+", " ", _without_comments(quirks, statement)).upper()
        executable.append((index, text, next((k for p, k in patterns if re.match(p, text)), None)))
    marked = [entry for entry in executable if entry[2]]
    if not marked:
        return statements

    def refuse(entry: Any, what: str) -> TransactionStatementError:
        where = _position(statements, entry[0], dialect, content)
        return TransactionStatementError(
            f"{script_name}, {where}: {entry[1].rstrip(';').rstrip()} {what}"
        )

    first, last = executable[0], executable[-1]
    if first[2] == "begin" and last[2] == "end" and first is not last:
        offenders = [entry for entry in marked if entry is not first and entry is not last]
        if not offenders:
            for entry in executable[1:-1]:
                reason = classify_execution_statement(
                    statements[entry[0]], dialect=dialect
                ).transaction_reason
                if reason:
                    raise refuse(
                        entry,
                        f"cannot stay inside the envelope: {reason}. The "
                        f"{first[1].rstrip(';')} ... {last[1].rstrip(';')} around it cannot be "
                        "dropped; remove the envelope.",
                    )
            log.warning(
                f"Dropped {first[1].rstrip(';').rstrip()} and {last[1].rstrip(';').rstrip()} "
                f"from {script_name}: dblift runs the script in one transaction of its own"
            )
            return [s for i, s in enumerate(statements) if i not in (first[0], last[0])]
    else:
        offenders = [entry for entry in marked if entry is not first or entry[2] != "begin"]
    offender = (offenders or marked)[0]
    if offender[2] == "begin_other" and offender is first:
        raise refuse(
            offender,
            "cannot stand in for dblift's transaction, which it opens itself for each script: "
            "only a plain BEGIN [TRANSACTION] can open a script that is closed by COMMIT or END. "
            "None of its statements were executed.",
        )
    raise refuse(
        offender,
        "manages the transaction, which dblift already opens for each script, so none of its "
        "statements were executed. Remove it; a script that is only BEGIN ... COMMIT around its "
        "whole body is accepted.",
    )


def _without_comments(quirks: Any, statement: str) -> str:
    """The statement with its comments gone, so ``COMMIT /* c */`` reads as ``COMMIT``."""
    from dblift.core.exceptions import ParserError

    try:
        statement = quirks.blank_comments(statement)
    except ParserError:  # a scanner refusal belongs to the split, which already passed
        pass
    return strip_leading_comments(statement).strip()


def _position(statements: List[str], index: int, dialect: str, content: str) -> str:
    """``line N`` of ``statements[index]``, from the splitter's own records; else ``statement N``."""
    from dblift.db.provider_registry import ProviderRegistry

    parser_class = ProviderRegistry.get_quirks(dialect.lower()).parser_class("regex")
    try:
        records = [r for r in parser_class().split(content) if r.text.strip()]  # type: ignore[misc]
    except Exception:  # noqa: BLE001 - the line is a courtesy; the refusal stands without it
        records = []
    if [r.text for r in records] == statements:
        record = records[index]
        # The record's line is where its leading comments start; the keyword is after them.
        offset = max(record.text.rfind(strip_leading_comments(record.text).strip()), 0)
        return f"line {record.line + record.text.count(chr(10), 0, offset)}"
    return f"statement {index + 1}"
