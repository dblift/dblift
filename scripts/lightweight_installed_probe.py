"""Standalone probe copied into an isolated installed-wheel environment."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
import sysconfig
from importlib import metadata, resources
from pathlib import Path

import dblift
from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
from dblift.core.logger.results import MigrateResult


def run(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        args, cwd=cwd, text=True, capture_output=True, timeout=120, check=True
    )
    return completed.stdout


def main() -> None:
    origin = Path(dblift.__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    assert origin.is_relative_to(prefix), f"package origin outside target environment: {origin}"
    version = metadata.version("dblift")
    assert version == sys.argv[1]
    distribution = metadata.distribution("dblift")
    try:
        core_distribution = metadata.distribution("dblift-core")
    except metadata.PackageNotFoundError:
        core_distribution = distribution  # Published single-wheel baseline.
    core_files = {str(path) for path in core_distribution.files or ()}
    bundle_files = {str(path) for path in distribution.files or ()}
    assert "dblift/py.typed" in core_files
    assert "dblift/core/logger/templates/report.html" in core_files
    assert resources.files("dblift").joinpath("py.typed").is_file()
    assert resources.files("dblift.core.logger").joinpath("templates/report.html").is_file()
    if core_distribution is not distribution:
        assert metadata.version("dblift-core") == version
        assert not any(path.startswith("dblift/") for path in bundle_files)
    report = HtmlFormatter().format_result(MigrateResult(), "public", "installed", "MIGRATE")
    assert "<title>DBLift Migration Report — installed</title>" in report
    assert importlib.util.find_spec("dblift_pro") is None
    assert importlib.util.find_spec("dblift_enterprise") is None
    names = {ep.name for ep in core_distribution.entry_points if ep.group == "dblift.providers"}
    assert "sqlite" in names
    scripts = [
        ep
        for ep in distribution.entry_points
        if ep.group == "console_scripts" and ep.name == "dblift"
    ]
    assert len(scripts) == 1 and scripts[0].value == "dblift.cli.main:main"
    console = Path(sysconfig.get_path("scripts")) / "dblift"
    assert console.is_file()

    cwd = Path.cwd()
    cli = [sys.executable, "-I", str(console)]
    help_text = run([*cli, "--help"], cwd)
    assert "migrate" in help_text and "validate" in help_text
    for command in ("diff", "export-schema", "snapshot", "validate-sql", "plan", "preflight"):
        assert command in help_text
        try:
            run([*cli, command, "--help"], cwd)
        except subprocess.CalledProcessError as exc:
            assert exc.returncode == 4
            assert "is not included in the open-source edition" in exc.stderr
        else:
            raise AssertionError(f"{command} unexpectedly ran as an OSS command")
    assert version in run([*cli, "--version"], cwd)

    migrations = cwd / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_probe.sql").write_text(
        "CREATE TABLE installed_probe (id INTEGER PRIMARY KEY, value TEXT);\n"
        "INSERT INTO installed_probe (id, value) VALUES (1, 'installed');\n",
        encoding="utf-8",
    )
    database = cwd / "probe.sqlite"
    config = cwd / "dblift.yaml"
    config.write_text(f"database:\n  type: sqlite\n  path: {database}\n", encoding="utf-8")
    migrate = run([*cli, "migrate", "--config", str(config), "--scripts", str(migrations)], cwd)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM installed_probe WHERE id = 1").fetchone() == (
            "installed",
        )
    run([*cli, "validate", "--config", str(config), "--scripts", str(migrations)], cwd)

    installed = {"dblift": version}
    if core_distribution is not distribution:
        installed["dblift-core"] = core_distribution.version
    for name in ("PyYAML", "rich", "Jinja2", "sqlglot", "SQLAlchemy"):
        installed[name] = metadata.version(name)
    print(
        json.dumps(
            {
                "origin": str(origin),
                "installed": installed,
                "providers": sorted(names),
                "html_report_rendered": True,
                "sqlite_migrate": bool(migrate),
                "record_owners": {
                    "code": core_distribution.metadata["Name"],
                    "console": distribution.metadata["Name"],
                },
            }
        )
    )


if __name__ == "__main__":
    main()
