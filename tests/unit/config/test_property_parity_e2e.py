"""End-to-end parity: a value set on any surface reaches the DbliftConfig object.

`test_property_parity.py` verifies each surface (CLI flag / env var) *exists* and
that env vars land in the intermediate dict. This file closes the loop: it drives
a value all the way through `from_all_sources` (env -> merge -> from_dict, and
args -> merge -> from_dict) and asserts it materializes on the built object with
the right type. That catches drift in the object-construction path (from_dict),
which the surface-level parity test cannot see.
"""

import pytest

from config.dblift_config import DbliftConfig
from config.property_registry import PROPERTY_REGISTRY

# Top-level scalar properties (nested database.* fields are exercised separately
# via their own connection tests; structured/cli-only specs are excluded).
_TOP_LEVEL = [s for s in PROPERTY_REGISTRY if not s.cli_only and "." not in s.name]

_SAMPLE = {"str": "xval", "int": 7, "float": 1.5, "bool": True}
_ENV_RAW = {"str": "xval", "int": "7", "float": "1.5", "bool": "true"}


def _expected(spec):
    return _SAMPLE.get(spec.type, "xval")


def _assert_landed(spec, got):
    exp = _expected(spec)
    # log_dir is path-normalized ("xval" -> "./xval"); accept the normalized form.
    if spec.name == "log_dir" and got in ("./xval", "xval"):
        return
    assert got == exp, f"{spec.name}: set {exp!r} but object has {got!r}"


@pytest.mark.parametrize("spec", _TOP_LEVEL, ids=lambda s: s.name)
def test_arg_value_reaches_object(spec):
    conf = DbliftConfig.from_all_sources(
        {"database_url": "sqlite:///x.db", spec.name: _expected(spec)}
    )
    _assert_landed(spec, getattr(conf, spec.name, "__MISSING__"))


@pytest.mark.parametrize("spec", _TOP_LEVEL, ids=lambda s: s.name)
def test_env_value_reaches_object(spec, monkeypatch):
    monkeypatch.setenv(spec.env, _ENV_RAW.get(spec.type, "xval"))
    conf = DbliftConfig.from_all_sources({"database_url": "sqlite:///x.db"})
    _assert_landed(spec, getattr(conf, spec.name, "__MISSING__"))
