"""Transaction policy planning for migration statement execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from dblift.core.migration.sql.execution_statement import ExecutionStatement
from dblift.db.provider_interfaces import TransactionalProvider


@dataclass(frozen=True)
class TransactionPolicyDecision:
    """Outcome of policy evaluation: whether to wrap statements in a transaction or
    run autocommit."""

    transactional: bool
    autocommit_required: bool = False
    unsupported_mixed_mode: bool = False
    reason: str = ""
    script_managed: bool = False


class TransactionPolicy:
    """Decide how a migration should be executed from statement/provider metadata."""

    def decide(
        self,
        statements: Iterable[ExecutionStatement],
        provider: Any,
        *,
        script_managed: bool = False,
    ) -> TransactionPolicyDecision:
        """Return the transaction/autocommit decision for ``statements`` on the
        given ``provider``."""
        execution_statements: Tuple[ExecutionStatement, ...] = tuple(statements)
        provider_supports_transactions = isinstance(provider, TransactionalProvider)
        if not provider_supports_transactions:
            return TransactionPolicyDecision(
                transactional=False,
                reason="Provider does not support explicit transactions",
            )

        if script_managed:
            return TransactionPolicyDecision(
                transactional=False, reason="dblift:no-transaction", script_managed=True
            )

        autocommit_statements = [
            stmt for stmt in execution_statements if not stmt.can_execute_in_transaction
        ]
        if not autocommit_statements:
            return TransactionPolicyDecision(transactional=True)

        if len(execution_statements) > len(autocommit_statements):
            reason = autocommit_statements[0].transaction_reason or (
                "Migration mixes autocommit-only statements with transactional statements"
            )
            return TransactionPolicyDecision(
                transactional=False,
                autocommit_required=True,
                unsupported_mixed_mode=True,
                reason=reason,
            )

        return TransactionPolicyDecision(
            transactional=False,
            autocommit_required=True,
            reason=autocommit_statements[0].transaction_reason
            or "Migration requires autocommit execution",
        )
