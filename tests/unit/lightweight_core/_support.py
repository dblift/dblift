import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run_python(
    source: str, *, blocked: tuple[str, ...] = (), cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    prefix = f"""
import importlib.abc
import sys
sys.path.insert(0, {str(ROOT)!r})
BLOCKED = {blocked!r}
class BlockImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in BLOCKED:
            raise ModuleNotFoundError('contract blocked: ' + fullname, name=fullname)
sys.meta_path.insert(0, BlockImports())
"""
    suffix = "\nassert not (set(BLOCKED) & {n.split('.')[0] for n in sys.modules})\n"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["DBLIFT_DISABLE_CLI_EXTENSIONS"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            textwrap.dedent(prefix) + textwrap.dedent(source) + suffix,
        ],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
