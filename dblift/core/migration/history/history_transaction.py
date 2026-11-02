"""Transaction scope for commands that write migration history rows."""

from contextlib import contextmanager
from typing import Iterator

from dblift.core.logger import Log
from dblift.db.error import engine_error_message
from dblift.db.provider_interfaces import TransactionalProvider


@contextmanager
def history_transaction(provider: object, log: Log, label: str) -> Iterator[None]:
    """Run the body in one provider transaction.

    The transaction is committed when the body returns and rolled back when it
    raises; the body's exception always propagates. A provider without
    transaction support, or one that cannot begin a transaction, runs the body
    unwrapped; on a caller-owned connection a body that returns is noted, so
    the next boundary commits its writes instead of rolling them back.
    """
    started = False
    in_caller_transaction = False
    if isinstance(provider, TransactionalProvider):
        try:
            provider.begin_transaction()
            started = True
        except Exception as e:
            log.warning(f"Could not begin transaction for {label}: {e}")
            in_caller_transaction = provider.is_caller_owned()

    try:
        yield
    except BaseException:
        if started:
            _rollback(provider, log, label)
        raise

    if in_caller_transaction:
        provider.note_caller_work()  # type: ignore[attr-defined]

    if started:
        try:
            provider.commit_transaction()  # type: ignore[attr-defined]
        except Exception as e:
            log.error(f"Failed to commit {label} transaction: {engine_error_message(e)}")
            _rollback(provider, log, label)
            raise


def _rollback(provider: object, log: Log, label: str) -> None:
    try:
        provider.rollback_transaction()  # type: ignore[attr-defined]
    except Exception as e:
        log.warning(f"Could not roll back {label} transaction: {e}")
