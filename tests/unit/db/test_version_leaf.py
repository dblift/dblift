import pickle
import subprocess
import sys


def test_version_leaf_parses_versions():
    from dblift.db import version

    parsed = version.parse_version("PostgreSQL 16.2 on x86_64")
    assert (parsed.major, parsed.minor, parsed.patch) == (16, 2, 0)
    assert version.parse_version("unknown") is None
    assert version.version_matches_spec("9.5", "9.4+") is True
    assert version.version_matches_spec("9.5", "9.4") is False


def test_version_leaf_pickle_roundtrip():
    from dblift.db.version import DatabaseVersion

    version = DatabaseVersion(16, 2, full_version="PostgreSQL 16.2")
    assert pickle.loads(pickle.dumps(version)) == version


def test_version_leaf_does_not_load_introspection():
    code = (
        "import sys; from dblift.db.version import parse_version; "
        "assert parse_version('16.2').major == 16; "
        "assert not any(n == 'dblift.core.introspection' or "
        "n.startswith('dblift.core.introspection.') for n in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
