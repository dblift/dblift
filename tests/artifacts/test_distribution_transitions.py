"""Install transitions use pip's normal resolver in fresh environments."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CURRENT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def _run(args, cwd):
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "DBLIFT_DISABLE_CLI_EXTENSIONS"):
        env.pop(name, None)
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    if result.returncode and "pip" in args:
        pytest.fail(f"pip operation failed with exit code {result.returncode}")
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def wheels(tmp_path_factory):
    output = tmp_path_factory.mktemp("transition-wheels")
    for source in (ROOT, ROOT / "packages" / "dblift"):
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(output),
                str(source),
            ],
            output,
        )
    return {path.name.split("-", 1)[0]: path for path in output.glob("*.whl")}


def _environment(path):
    path.mkdir()
    _run([sys.executable, "-m", "venv", str(path / "venv")], path)
    return path / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _installed(python, cwd):
    return json.loads(
        _run(
            [
                str(python),
                "-I",
                "-c",
                "import json,sys; from importlib import metadata; import dblift; "
                "from pathlib import Path; "
                "names=['dblift-core','dblift']; "
                "versions={name:metadata.version(name) if any("
                "d.metadata['Name'].lower()==name for d in metadata.distributions()) "
                "else None for name in names}; "
                "origins={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() "
                "if name=='dblift' or name.startswith('dblift.') if getattr(module,'__file__',None)}; "
                "print(json.dumps({'versions':versions,'origins':origins,'modules':"
                "{name:metadata.version(name) if any(d.metadata['Name'].lower()==name.lower() "
                "for d in metadata.distributions()) else None for name in ['sqlglot','rich','Jinja2']}}))",
            ],
            cwd,
        )
    )


def _assert_origins(details, python):
    environment = python.parent.parent.resolve()
    assert details["origins"]
    for origin in details["origins"].values():
        assert Path(origin).is_relative_to(environment), origin


def test_fresh_core_uses_only_minimal_dependencies(wheels, tmp_path):
    python = _environment(tmp_path / "core")
    work = tmp_path / "core"
    _run([str(python), "-m", "pip", "install", str(wheels["dblift_core"])], work)
    _run([str(python), "-m", "pip", "check"], work)
    details = _installed(python, work)
    assert details["versions"]["dblift-core"] == CURRENT_VERSION
    assert details["versions"]["dblift"] is None
    assert details["modules"] == {"sqlglot": None, "rich": None, "Jinja2": None}
    _assert_origins(details, python)
    script = """
import sys
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

work = Path.cwd()
migrations = work / "sql"
migrations.mkdir()
(migrations / "V1__create.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
(migrations / "U1__create.sql").write_text("DROP TABLE t;", encoding="utf-8")
config = DbliftConfig.from_dict({"database": {
    "type": "sqlite", "path": str(work / "db.sqlite"), "schema": "main"
}})
with DBLiftClient.from_config(config, migrations_dir=migrations,
                              logger=NullLog(), analysis_mode="execution") as client:
    assert client.migrate().success
    assert client.validate().success
    assert client.undo(target_version="0.0.0").success
assert not any(name == "sqlglot" or name.startswith("sqlglot.") for name in sys.modules)
assert not any(name == "rich" or name.startswith("rich.") for name in sys.modules)
assert not any(name == "jinja2" or name.startswith("jinja2.") for name in sys.modules)
for name, module in sys.modules.items():
    if name == "dblift" or name.startswith("dblift."):
        if getattr(module, "__file__", None):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), name
"""
    _run([str(python), "-I", "-c", script], work)
    _run([str(python), "-m", "pip", "install", f"{wheels['dblift_core']}[otel]"], work)
    _run([str(python), "-m", "pip", "check"], work)
    _run(
        [
            str(python),
            "-I",
            "-c",
            f"from dblift.integrations.opentelemetry import _dblift_version; assert _dblift_version() == {CURRENT_VERSION!r}",
        ],
        work,
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("analysis", {"sqlglot": True, "rich": False, "Jinja2": False}),
        ("presentation", {"sqlglot": False, "rich": True, "Jinja2": True}),
    ],
)
def test_core_extras_resolve_independently(wheels, tmp_path, extra, expected):
    work = tmp_path / extra
    python = _environment(work)
    _run([str(python), "-m", "pip", "install", f"{wheels['dblift_core']}[{extra}]"], work)
    _run([str(python), "-m", "pip", "check"], work)
    details = _installed(python, work)
    assert {name: version is not None for name, version in details["modules"].items()} == expected
    _assert_origins(details, python)
    script = """
import sys
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

work = Path.cwd()
sql = work / 'sql'
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);', encoding='utf-8')
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': str(work / 'db.sqlite'), 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(),
                              analysis_mode=MODE) as client:
    result = client.migrate()
    assert result.success
    assert result.journal.capture_objects == (MODE == 'full')
    if MODE == 'execution':
        from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
        assert 'Object analysis disabled' in HtmlFormatter().format_result(
            result, 'main', 'db', 'MIGRATE')
assert ('sqlglot' in sys.modules) == (MODE == 'full')
for name, module in sys.modules.items():
    if name == 'dblift' or name.startswith('dblift.'):
        if getattr(module, '__file__', None):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), name
""".replace("MODE", repr("full" if extra == "analysis" else "execution"))
    _run([str(python), "-I", "-c", script], work)


def test_core_to_standard_and_bundle_reinstall(wheels, tmp_path):
    python = _environment(tmp_path / "standard")
    work = tmp_path / "standard"
    core, bundle = wheels["dblift_core"], wheels["dblift"]
    _run([str(python), "-m", "pip", "install", str(core)], work)
    _run([str(python), "-m", "pip", "install", str(bundle)], work)
    _run([str(python), "-m", "pip", "check"], work)
    installed = _installed(python, work)
    assert installed["versions"] == {"dblift-core": CURRENT_VERSION, "dblift": CURRENT_VERSION}
    assert all(installed["modules"].values())
    _assert_origins(installed, python)
    console = python.parent / ("dblift.exe" if os.name == "nt" else "dblift")
    assert "migrate" in _run([str(console), "--help"], work)
    assert CURRENT_VERSION in _run([str(console), "--version"], work)
    _run([str(python), "-m", "pip", "uninstall", "-y", "dblift"], work)
    _run([str(python), "-m", "pip", "check"], work)
    assert not console.exists()
    assert _installed(python, work)["versions"] == {"dblift-core": CURRENT_VERSION, "dblift": None}
    _run([str(python), "-m", "pip", "install", str(bundle)], work)
    _run([str(python), "-m", "pip", "check"], work)
    assert CURRENT_VERSION in _run([str(console), "--version"], work)


def test_published_wheel_to_candidate_uses_controlled_transition(tmp_path):
    old_dir = tmp_path / "published"
    old_dir.mkdir()
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--no-deps",
            "--only-binary=:all:",
            "--dest",
            str(old_dir),
            "dblift==4.10.0",
        ],
        tmp_path,
    )
    old_wheel = next(old_dir.glob("dblift-4.10.0-*.whl"))
    assert hashlib.sha256(old_wheel.read_bytes()).hexdigest() == (
        "b979a3ff5abb84a75e751c105b5c4fceb597e094e4e996f6df31f281ccd26dc5"
    )
    revision = _run(["git", "rev-parse", "HEAD"], ROOT).strip()
    candidate_dir = tmp_path / "candidate"
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_core_candidate.py"),
            "--revision",
            revision,
            "--output",
            str(candidate_dir),
        ],
        tmp_path,
    )
    core = next(candidate_dir.glob("dblift_core-*.whl"))
    bundle = next(candidate_dir.glob("dblift-*.whl"))
    results = {
        "revision": revision,
        "published_sha256": hashlib.sha256(old_wheel.read_bytes()).hexdigest(),
        "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
    }
    for transition in ("direct", "controlled"):
        work = tmp_path / transition
        python = _environment(work)
        cli = python.parent / ("dblift.exe" if os.name == "nt" else "dblift")
        migrations = work / "sql"
        migrations.mkdir()
        (migrations / "V1__create.sql").write_text(
            "CREATE TABLE upgraded (id INTEGER PRIMARY KEY);", encoding="utf-8"
        )
        database = work / "db.sqlite"
        config = work / "dblift.yaml"
        config.write_text(f"database:\n  type: sqlite\n  path: {database}\n", encoding="utf-8")
        _run([str(python), "-m", "pip", "install", str(old_wheel)], work)
        _run([str(python), "-m", "pip", "check"], work)
        _run([str(cli), "migrate", "--config", str(config), "--scripts", str(migrations)], work)
        if transition == "controlled":
            _run([str(python), "-m", "pip", "uninstall", "-y", "dblift"], work)
        _run([str(python), "-m", "pip", "install", str(core), str(bundle)], work)
        _run([str(python), "-m", "pip", "check"], work)
        probe = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import dblift; from importlib import metadata; "
                "assert metadata.version('dblift-core') == metadata.version('dblift') == '999.0.0.dev1'",
            ],
            cwd=work,
            capture_output=True,
            text=True,
        )
        code_file = json.loads(
            _run(
                [
                    str(python),
                    "-I",
                    "-c",
                    "import json; from importlib import metadata; "
                    "d=metadata.distribution('dblift-core'); "
                    "print(json.dumps({'recorded': 'dblift/__init__.py' in [str(x) for x in d.files or []], "
                    "'exists': d.locate_file('dblift/__init__.py').is_file()}))",
                ],
                work,
            )
        )
        help_result = subprocess.run([str(cli), "--help"], cwd=work, capture_output=True, text=True)
        version_result = subprocess.run(
            [str(cli), "--version"], cwd=work, capture_output=True, text=True
        )
        results[transition] = {
            "import_returncode": probe.returncode,
            "help_returncode": help_result.returncode,
            "version_returncode": version_result.returncode,
            "code_file": code_file,
        }
        if transition == "controlled":
            assert probe.returncode == 0, probe.stderr
            assert "999.0.0.dev1" in _run([str(cli), "--version"], work)
            _run([str(cli), "--help"], work)
            (migrations / "V2__insert.sql").write_text(
                "INSERT INTO upgraded (id) VALUES (2);", encoding="utf-8"
            )
            _run(
                [str(cli), "migrate", "--config", str(config), "--scripts", str(migrations)],
                work,
            )
            with sqlite3.connect(database) as connection:
                assert connection.execute("SELECT id FROM upgraded").fetchall() == [(2,)]
            ownership = json.loads(
                _run(
                    [
                        str(python),
                        "-I",
                        "-c",
                        "import json; from importlib import metadata; "
                        "core=metadata.distribution('dblift-core'); bundle=metadata.distribution('dblift'); "
                        "print(json.dumps({'core': [str(x) for x in core.files or []], "
                        "'bundle': [str(x) for x in bundle.files or []]}))",
                    ],
                    work,
                )
            )
            assert "dblift/__init__.py" in ownership["core"]
            assert not any(path.startswith("dblift/") for path in ownership["bundle"])
    # pip's direct behavior can improve, but the controlled transition must work.
    assert results["controlled"]["import_returncode"] == 0
    evidence_dir = os.environ.get("E4_EVIDENCE_DIR")
    if evidence_dir:
        destination = Path(evidence_dir) / "distribution-upgrade.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
