"""ADR-26 E: config_from_engine derives the db_type fallback from the matched
provider's canonical_dialect_key, not a hardcoded dialect literal.
"""

from sqlalchemy import create_engine

from api._engine_config import config_from_engine


class _FlakyURL:
    """Wraps a real SQLAlchemy URL; render works but .drivername raises.

    Models the only way the except branch in config_from_engine is reached:
    after get_provider_by_url has already matched a provider, a later access
    to engine.url.drivername blows up.
    """

    def __init__(self, real_url):
        self._real = real_url

    def render_as_string(self, hide_password=False):
        return self._real.render_as_string(hide_password=hide_password)

    @property
    def drivername(self):
        raise RuntimeError("boom")


class _FlakyEngine:
    def __init__(self, real_engine):
        self._real = real_engine
        self.url = _FlakyURL(real_engine.url)


def test_fallback_uses_matched_provider_canonical_key():
    real_engine = create_engine("oracle+oracledb://u:p@localhost/app")
    engine = _FlakyEngine(real_engine)

    config = config_from_engine(engine)  # type: ignore[arg-type]

    # The matched provider is Oracle, so the except fallback must yield oracle
    # — not a hardcoded postgresql default.
    assert config.database.type == "oracle"
