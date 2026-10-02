import pickle
import subprocess
import sys


def test_old_version_path_reexports_same_objects():
    from dblift.core.introspection import version_detector as old
    from dblift.db import version

    assert old.DatabaseVersion is version.DatabaseVersion
    assert old.parse_version is version.parse_version
    assert old.version_matches_spec is version.version_matches_spec
    parsed = version.parse_version("PostgreSQL 16.2 on x86_64")
    assert (parsed.major, parsed.minor, parsed.patch) == (16, 2, 0)
    assert version.parse_version("unknown") is None
    assert version.version_matches_spec("9.5", "9.4+") is True
    assert version.version_matches_spec("9.5", "9.4") is False


def test_old_path_pickle_resolves_to_new_class():
    from dblift.db.version import DatabaseVersion

    old_global = b"cdblift.core.introspection.version_detector\nDatabaseVersion\n."
    assert pickle.loads(old_global) is DatabaseVersion


def test_version_leaf_does_not_load_introspection():
    code = (
        "import sys; from dblift.db.version import parse_version; "
        "assert parse_version('16.2').major == 16; "
        "assert not any(n == 'dblift.core.introspection' or "
        "n.startswith('dblift.core.introspection.') for n in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
