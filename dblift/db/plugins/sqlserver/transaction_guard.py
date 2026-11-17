"""Tell whether a SQL Server script ended or left open the transaction DBLift began."""

from typing import Optional, Tuple

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from dblift.db.provider_interfaces import TransactionOutcome
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


class SqlServerTransactionProvider(SqlAlchemyProvider):
    """Compare SQL Server's transaction depth and identity with those captured at begin."""

    _transaction_baseline: Optional[Tuple[int, int]] = None

    def _server_transaction_state(self) -> Tuple[int, int]:
        rows = self.execute_query(
            "SELECT @@TRANCOUNT AS transaction_count, CURRENT_TRANSACTION_ID() AS transaction_id"
        )
        return int(rows[0]["transaction_count"]), int(rows[0]["transaction_id"])

    def supports_script_session(self) -> bool:
        """Only SQL Server itself, not a provider that subclasses this one."""
        return self.canonical_dialect_key == "sqlserver"

    def _script_transaction_open(self, conn: Connection) -> bool:
        """Whether a transaction is open on the server."""
        return int(self._exec_unbound(conn, "SELECT @@TRANCOUNT").scalar()) > 0

    def _roll_back_script_transaction(self, conn: Connection) -> None:
        """Roll back; the driver ignores a rollback while the connection autocommits."""
        self._exec_unbound(conn, "IF @@TRANCOUNT > 0 ROLLBACK")

    def begin_transaction(self) -> None:
        """Begin, then capture the server transaction depth and identity."""
        super().begin_transaction()
        try:
            self._transaction_baseline = self._server_transaction_state()
        except SQLAlchemyError as exc:
            self._transaction_baseline = None
            self.log.debug(f"SQL Server transaction state unavailable at begin: {exc}")

    def transaction_outcome(self) -> TransactionOutcome:
        """Report whether the script kept, ended or left open the begun transaction."""
        baseline = self._transaction_baseline
        if baseline is None or baseline[0] == 0:
            return TransactionOutcome.INTACT
        current = self._server_transaction_state()
        if current == baseline:
            return TransactionOutcome.INTACT
        if current[0] == 0:
            return TransactionOutcome.ENDED
        return TransactionOutcome.OPEN

    def commit_transaction(self) -> None:
        """Commit and clear the captured baseline."""
        try:
            super().commit_transaction()
        finally:
            self._transaction_baseline = None

    def rollback_transaction(self) -> None:
        """Roll back and clear the captured baseline."""
        try:
            super().rollback_transaction()
        finally:
            self._transaction_baseline = None
