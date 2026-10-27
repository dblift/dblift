"""Lazy public formatter exports retain the types available to Python consumers."""

import os
import re
import subprocess
import sys
from pathlib import Path


def test_public_formatter_exports_reject_unknown_attributes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from dblift.core.logger import OutputFormatter, OutputFormatterFactory, JsonFormatter\n"
        "from dblift.extensions.logging import JsonFormatter as ExtensionJsonFormatter\n"
        "from dblift.core.logger.log import JsonFormatter as LegacyJsonFormatter, JINJA_AVAILABLE\n"
        "\n"
        "OutputFormatter().missing_for_contract()\n"
        "OutputFormatterFactory.missing_for_contract()\n"
        "JsonFormatter().missing_for_contract()\n"
        "ExtensionJsonFormatter().missing_for_contract()\n"
        "LegacyJsonFormatter().missing_for_contract()\n"
        "JINJA_AVAILABLE.missing_for_contract()\n",
        encoding="utf-8",
    )
    config = tmp_path / "mypy.ini"
    config.write_text("[mypy]\nfollow_imports = silent\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["MYPYPATH"] = str(root)

    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(config),
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            "--no-incremental",
            "--show-error-codes",
            "--no-pretty",
            str(consumer),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert process.returncode == 1, process.stdout + process.stderr
    assert process.stderr == "", process.stderr
    errors = [line for line in process.stdout.splitlines() if ": error:" in line]
    assert all("[attr-defined]" in error for error in errors), process.stdout
    assert re.findall(r"consumer\.py:(\d+): error:", process.stdout) == [
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
    ], process.stdout
