"""Execution-time SQL statement metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, List, Optional

from dblift.core.exceptions import TransactionStatementError
from dblift.core.sql_parser.statement import Statement, executable_records, execution_strings
from dblift.core.sql_parser.statement import execution_units as unit_texts
from dblift.core.utils.row_access import strip_leading_comments


@dataclass(frozen=True)
class ExecutionStatement:
    """A SQL statement plus transaction metadata used by the execution engine."""

    sql: str
    statement_type: str = "UNKNOWN"
    can_execute_in_transaction: bool = True
    transaction_reason: Optional[str] = None


class PreparedStatements(list[str]):
    """Execution strings and scanner-derived policy views kept in the same order."""

    def __init__(self, statements: List[str], policy_texts: List[Optional[str]]):
        """Keep each policy view at the same index as its execution string."""
        super().__init__(statements)
        self.policy_texts = policy_texts


@lru_cache(maxsize=None)
def _script_parser(dialect: str) -> Any:
    """The dialect's lexical engine, which owns execution and analysis script boundaries."""
    from dblift.core.sql_parser.lexical_engine import LexicalEngine
    from dblift.db.provider_registry import ProviderRegistry

    spec = ProviderRegistry.get_quirks(dialect).lexical_spec()
    return LexicalEngine(spec) if spec is not None else None


def _statements_of(sql: str, dialect: str) -> List[str]:
    """Scanner-derived constituents of one execution unit."""
    parser = _script_parser(dialect)
    if parser is None:
        return [sql]
    return list(parser.split_for_analysis(sql))


def execution_units(sql: str, dialect: str) -> Optional[List[str]]:
    """The scanner's executable units once each, omitting skipped client batches.

    ``None`` means the dialect has no parser. A scanner refusal propagates.
    """
    from dblift.core.migration.sql.statement_splitter import StatementSplitter

    parser = _script_parser(dialect.lower())
    if parser is None:
        return None
    return unit_texts(StatementSplitter(dialect).split(sql))


def classify_execution_statement(
    sql: str,
    *,
    dialect: str,
    statement_type: str = "UNKNOWN",
    policy_text: Optional[str] = None,
) -> ExecutionStatement:
    """Classify transaction metadata for high-confidence dialect-specific cases."""
    from dblift.db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(dialect.lower())
    if not quirks.non_transactional_sql_patterns:
        return ExecutionStatement(sql=sql, statement_type=statement_type)

    # A batch is not transactional when any of its statements is not: SQL Server refuses that
    # statement inside the transaction the whole batch would run in.
    parser = _script_parser(dialect.lower())
    for statement in (
        [policy_text] if policy_text is not None else _statements_of(sql, dialect.lower())
    ):
        # Comments between keywords are whitespace too, e.g. FORCE /* flush */ CHECKPOINT.
        blanks = (
            parser.spec.text_blanks if parser is not None and parser.spec.non_ascii_names else None
        )
        commentless = (
            statement.strip(blanks)
            if policy_text is not None
            else _without_comments(quirks, statement, blanks=blanks)
        )
        if parser is not None and parser.spec.non_ascii_names:
            # Keep non-ASCII name characters and code that Python calls whitespace
            # from becoming regex separators or word boundaries after masking comments.
            commentless = "".join(
                (
                    "_"
                    if ord(char) >= 128 or (char.isspace() and char not in parser.spec.text_blanks)
                    else char
                )
                for char in commentless
            )
            normalized = re.sub(
                f"[{re.escape(parser.spec.text_blanks)}]+", " ", commentless
            ).upper()
        else:
            normalized = re.sub(r"\s+", " ", commentless).upper()
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
    records: Optional[List[Statement]] = None,
    record_policy_texts: Optional[List[Optional[str]]] = None,
) -> List[str]:
    """*statements* with a script's ``BEGIN ... COMMIT`` envelope dropped, or a refusal.

    dblift runs a script in one transaction of its own. A script whose first statement is a
    ``begin`` and whose last is an ``end`` (``quirks.transaction_control_sql_patterns``) is that
    same transaction: both are dropped and a warning says so. Any other transaction statement
    would end or fail against dblift's transaction, and is refused before anything runs, as is
    an envelope around a statement that cannot run in a transaction.
    A dialect with no patterns gets *statements* back untouched.

    Supplied scanner records must expand to exactly the strings execution will send.
    """
    from dblift.db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(dialect.lower())
    if records is not None and execution_strings(records) != statements:
        raise TransactionStatementError(
            f"{script_name}: execution strings do not match the supplied scanner records; "
            "none of its statements were executed"
        )
    if (
        records is not None
        and record_policy_texts is not None
        and len(record_policy_texts) != len(records)
    ):
        raise TransactionStatementError(
            f"{script_name}: scanner policy views do not match the supplied scanner records; "
            "none of its statements were executed"
        )
    policy_texts: List[Optional[str]] = [None] * len(statements)
    if records is not None and record_policy_texts is not None:
        policy_texts = [
            policy_text
            for record, policy_text in zip(records, record_policy_texts)
            if record.kind in ("sql", "copy_stdin")
            or (record.kind == "directive" and record.execution_text is not None)
            for _ in range(record.repeat)
        ]
        if len(policy_texts) != len(statements):
            raise TransactionStatementError(
                f"{script_name}: scanner policy views do not match execution strings; "
                "none of its statements were executed"
            )
    prepared = PreparedStatements(statements, policy_texts) if records is not None else statements
    patterns = quirks.transaction_control_sql_patterns
    if not patterns:
        parser = _script_parser(dialect.lower())
        if records is None:
            if not content or parser is None or not hasattr(parser, "split"):
                return statements
            records = parser.split(content)
        sent = 0  # how many strings the records before this one are sent as
        for record in records:
            index, sent = sent, sent + len(execution_strings([record]))
            if not (executable_records([record]) and record.multi):
                continue
            parts = record.analysis_statements or (record.text,)
            if len(parts) < 2:
                continue
            for part in parts:
                text = re.sub(r"\s+", " ", _without_comments(quirks, part)).upper()
                if re.match(r"^(?:BEGIN|START TRANSACTION|COMMIT|ROLLBACK)\b", text):
                    where = _position(statements, index, dialect, content, records)
                    raise TransactionStatementError(
                        f"{script_name}, {where}: {text.rstrip(';')} manages the transaction "
                        "inside one execution unit, so none of its statements were executed. "
                        "Remove it from the combined unit."
                    )
        return prepared
    # (index, normalised text, kind) of every executable statement.
    executable = []
    for index, statement in enumerate(statements):
        policy_text = policy_texts[index]
        text = re.sub(
            r"\s+",
            " ",
            (
                policy_text.strip()
                if policy_text is not None
                else _without_comments(quirks, statement)
            ),
        ).upper()
        executable.append((index, text, next((k for p, k in patterns if re.match(p, text)), None)))
    marked = [entry for entry in executable if entry[2]]
    if not marked:
        return prepared

    def refuse(entry: Any, what: str) -> TransactionStatementError:
        where = _position(statements, entry[0], dialect, content, records)
        return TransactionStatementError(
            f"{script_name}, {where}: {entry[1].rstrip(';').rstrip()} {what}"
        )

    first, last = executable[0], executable[-1]
    if first[2] == "begin" and last[2] == "end" and first is not last:
        offenders = [entry for entry in marked if entry is not first and entry is not last]
        if not offenders:
            for entry in executable[1:-1]:
                reason = classify_execution_statement(
                    statements[entry[0]], dialect=dialect, policy_text=policy_texts[entry[0]]
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
            kept = [i for i in range(len(statements)) if i not in (first[0], last[0])]
            return PreparedStatements(
                [statements[i] for i in kept], [policy_texts[i] for i in kept]
            )
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
    explanation = (
        "manages the transaction, which dblift already opens for each script, so none of its "
        "statements were executed. Remove it"
    )
    if any(kind == "begin" for _, kind in patterns) and any(kind == "end" for _, kind in patterns):
        explanation += "; a script that is only BEGIN ... COMMIT around its whole body is accepted"
    raise refuse(offender, explanation + ".")


def _without_comments(quirks: Any, statement: str, *, blanks: Optional[str] = None) -> str:
    """The statement with its comments gone, so ``COMMIT /* c */`` reads as ``COMMIT``."""
    from dblift.core.exceptions import ParserError

    try:
        statement = quirks.blank_comments(statement)
    except ParserError:  # a scanner refusal belongs to the split, which already passed
        pass
    return strip_leading_comments(statement).strip(blanks)


def _position(
    statements: List[str],
    index: int,
    dialect: str,
    content: str,
    records: Optional[List[Statement]] = None,
) -> str:
    """``line N`` of ``statements[index]``, from the splitter's own records; else ``statement N``."""
    if records is None:
        try:
            records = _script_parser(dialect.lower()).split(content)
        except Exception:  # noqa: BLE001 - the line is a courtesy; the refusal stands without it
            records = []
    # One entry per string execution sends, so a statement's index is its record's.
    owners = [(record, text) for record in records for text in execution_strings([record])]
    if [text for _, text in owners] == statements:
        record = owners[index][0]
        # The record's line is where its leading comments start; the keyword is after them.
        offset = max(record.text.rfind(strip_leading_comments(record.text).strip()), 0)
        return f"line {record.line + record.text.count(chr(10), 0, offset)}"
    return f"statement {index + 1}"
