"""Jinja2 is only needed to render an HTML report, not to import the formatter."""

import subprocess
import sys
import textwrap

HIDE_JINJA2 = textwrap.dedent("""
    import sys

    class _Hide:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "jinja2":
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, _Hide())
    """)


def _run(code: str, *, hide: bool):
    source = (HIDE_JINJA2 if hide else "") + textwrap.dedent(code)
    return subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, timeout=300
    )


def test_importing_the_formatter_and_the_extension_logging_module_loads_no_jinja2():
    proc = _run(
        """
        import sys
        import dblift.core.logger.formatters.htmlformatter  # noqa: F401
        import dblift.extensions.logging  # noqa: F401
        print("LOADED:", sorted(m for m in sys.modules if m.split(".")[0] == "jinja2"))
        """,
        hide=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "LOADED: []" in proc.stdout, proc.stdout


def test_extension_logging_imports_without_jinja2():
    proc = _run("import dblift.extensions.logging", hide=True)
    assert proc.returncode == 0, proc.stderr


def test_building_the_formatter_without_jinja2_names_the_extra():
    proc = _run(
        """
        from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
        try:
            HtmlFormatter()
        except ImportError as exc:
            print("ERR:", exc)
        """,
        hide=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "install dblift[cli]" in proc.stdout, proc.stdout
