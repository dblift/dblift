"""Install transitions use pip's normal resolver in fresh environments."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run(args, cwd):
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "DBLIFT_DISABLE_CLI_EXTENSIONS"):
        env.pop(name, None)
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
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
    assert details["versions"]["dblift-core"] == "4.10.0"
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
"""
    _run([str(python), "-I", "-c", script], work)
    _run([str(python), "-m", "pip", "install", f"{wheels['dblift_core']}[otel]"], work)
    _run([str(python), "-m", "pip", "check"], work)
    _run(
        [
            str(python),
            "-I",
            "-c",
            "from dblift.integrations.opentelemetry import _dblift_version; assert _dblift_version() == '4.10.0'",
        ],
        work,
    )


def test_core_to_standard_and_bundle_reinstall(wheels, tmp_path):
    python = _environment(tmp_path / "standard")
    work = tmp_path / "standard"
    core, bundle = wheels["dblift_core"], wheels["dblift"]
    _run([str(python), "-m", "pip", "install", str(core)], work)
    _run([str(python), "-m", "pip", "install", str(bundle)], work)
    _run([str(python), "-m", "pip", "check"], work)
    installed = _installed(python, work)
    assert installed["versions"] == {"dblift-core": "4.10.0", "dblift": "4.10.0"}
    assert all(installed["modules"].values())
    _assert_origins(installed, python)
    console = python.parent / ("dblift.exe" if os.name == "nt" else "dblift")
    assert "migrate" in _run([str(console), "--help"], work)
    assert "4.10.0" in _run([str(console), "--version"], work)
    _run([str(python), "-m", "pip", "uninstall", "-y", "dblift"], work)
    _run([str(python), "-m", "pip", "check"], work)
    assert not console.exists()
    assert _installed(python, work)["versions"] == {"dblift-core": "4.10.0", "dblift": None}
    _run([str(python), "-m", "pip", "install", str(bundle)], work)
    _run([str(python), "-m", "pip", "check"], work)
    assert "4.10.0" in _run([str(console), "--version"], work)
