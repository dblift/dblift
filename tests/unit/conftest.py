"""Unit-test conftest for OSS dblift."""

import pytest  # noqa: E402

from tests.support.legacy_oracle_hybrid import oracle_facts_off  # noqa: E402


@pytest.fixture
def legacy_oracle():
    """Oracle served as before statement facts (the plugin's reader switched off), for tests of the
    dialect-neutral text parsers and extraction that still run Oracle SQL."""
    with oracle_facts_off():
        yield
