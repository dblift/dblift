"""Tests for the shared history transaction helper."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.history.history_transaction import history_transaction
from dblift.db.provider_interfaces import TransactionalProvider


def _transactional_provider():
    return MagicMock(spec=TransactionalProvider)


def test_commits_on_success():
    provider = _transactional_provider()
    log = MagicMock()

    with history_transaction(provider, log, "baseline"):
        pass

    provider.begin_transaction.assert_called_once_with()
    provider.commit_transaction.assert_called_once_with()
    provider.rollback_transaction.assert_not_called()


def test_rolls_back_and_reraises_on_body_error():
    provider = _transactional_provider()
    log = MagicMock()

    with pytest.raises(ValueError):
        with history_transaction(provider, log, "baseline"):
            raise ValueError("boom")

    provider.rollback_transaction.assert_called_once_with()
    provider.commit_transaction.assert_not_called()


def test_commit_failure_rolls_back_and_reraises():
    provider = _transactional_provider()
    provider.commit_transaction.side_effect = RuntimeError("commit")
    log = MagicMock()

    with pytest.raises(RuntimeError, match="commit"):
        with history_transaction(provider, log, "baseline"):
            pass

    provider.rollback_transaction.assert_called_once_with()
    log.error.assert_called_once_with("Failed to commit baseline transaction: commit")


def test_begin_failure_runs_body_without_transaction():
    provider = _transactional_provider()
    provider.begin_transaction.side_effect = RuntimeError("no begin")
    log = MagicMock()
    ran = []

    with history_transaction(provider, log, "baseline"):
        ran.append(True)

    assert ran == [True]
    provider.commit_transaction.assert_not_called()
    provider.rollback_transaction.assert_not_called()
    log.warning.assert_called_once_with("Could not begin transaction for baseline: no begin")


def test_non_transactional_provider_runs_body_without_transaction():
    provider = MagicMock(spec=[])
    log = MagicMock()
    ran = []

    with history_transaction(provider, log, "baseline"):
        ran.append(True)

    assert ran == [True]
    assert provider.mock_calls == []


def test_rollback_failure_does_not_mask_body_error():
    provider = _transactional_provider()
    provider.rollback_transaction.side_effect = RuntimeError("rollback")
    log = MagicMock()

    with pytest.raises(ValueError):
        with history_transaction(provider, log, "baseline"):
            raise ValueError("boom")

    log.warning.assert_called_once_with("Could not roll back baseline transaction: rollback")
