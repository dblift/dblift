"""Coverage for ``cli.main._format_version`` — the ``--version`` renderer.

The published ``dblift`` wheel is the OSS *core*. The paid tiers ship as
separate distributions (``dblift-pro`` / ``dblift-enterprise``) bundled into the
compiled binary, each on its own release lifecycle, so their versions need not
match the core's. ``--version`` reports the most-derived installed tier as the
headline and lists every present component so a bare number is never ambiguous.
In a plain OSS install only the core is present, so the output stays one line.
"""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest


def _fake_version(installed):
    """Build a ``importlib.metadata.version`` stand-in from a name->version map."""

    def _inner(name):
        if name in installed:
            return installed[name]
        raise PackageNotFoundError(name)

    return _inner


@pytest.mark.unit
class TestFormatVersion:
    def test_oss_only_is_single_line(self):
        """Plain OSS install (only ``dblift``) → one unchanged line."""
        from cli.main import _format_version

        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version({})):
                out = _format_version()

        assert out == "dblift version 2.3.0"

    def test_pro_present_headlines_pro_and_lists_core(self):
        """With ``dblift-pro`` installed, headline is the pro version + a manifest."""
        from cli.main import _format_version

        installed = {"dblift-pro": "2.4.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                out = _format_version()

        lines = out.splitlines()
        assert lines[0] == "dblift version 2.4.0"
        assert any("core (OSS)" in line and "2.3.0" in line for line in lines[1:])
        assert any(line.strip().startswith("pro:") and "2.4.0" in line for line in lines[1:])
        assert not any("enterprise" in line for line in lines)

    def test_enterprise_present_headlines_enterprise_and_lists_all(self):
        """Enterprise is the most-derived tier → its version headlines; all listed."""
        from cli.main import _format_version

        installed = {"dblift-pro": "2.3.1", "dblift-enterprise": "2.3.1"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                out = _format_version()

        lines = out.splitlines()
        assert lines[0] == "dblift version 2.3.1"
        assert any("core (OSS)" in line and "2.3.0" in line for line in lines[1:])
        assert any(line.strip().startswith("pro:") and "2.3.1" in line for line in lines[1:])
        assert any(line.strip().startswith("enterprise:") and "2.3.1" in line for line in lines[1:])

    def test_enterprise_without_pro_omits_pro_line(self):
        """A tier can be absent independently — no empty ``pro:`` line then."""
        from cli.main import _format_version

        installed = {"dblift-enterprise": "2.5.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                out = _format_version()

        lines = out.splitlines()
        assert lines[0] == "dblift version 2.5.0"
        assert any("core (OSS)" in line and "2.3.0" in line for line in lines[1:])
        assert not any(line.strip().startswith("pro:") for line in lines)
        assert any(line.strip().startswith("enterprise:") and "2.5.0" in line for line in lines[1:])


@pytest.mark.unit
class TestResolveCoreVersion:
    def test_prefers_bundled_init_over_shadowed_metadata(self, tmp_path, monkeypatch):
        """A same-named ``dblift`` distribution earlier on ``sys.path`` (e.g. a
        stale global install left over from prior dev work) must not shadow
        the version actually bundled with the running code — this is the
        failure mode behind a binary reporting an unrelated, stale version."""
        from cli.main import _resolve_core_version

        (tmp_path / "__init__.py").write_text('__version__ = "9.9.9-bundled"\n', encoding="utf-8")
        monkeypatch.setattr("cli.main._project_root", tmp_path)
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch("importlib.metadata.version", _fake_version({"dblift": "0.0.1-shadowed"})):
            resolved = _resolve_core_version()

        assert resolved == "9.9.9-bundled"

    def test_prefers_metadata_when_frozen(self, tmp_path, monkeypatch):
        """Under a frozen build, the bundled ``__init__.py`` filesystem walk is
        unreliable (PyInstaller MEIPASS layout), so metadata must win."""
        from cli.main import _resolve_core_version

        (tmp_path / "__init__.py").write_text('__version__ = "9.9.9-bundled"\n', encoding="utf-8")
        monkeypatch.setattr("cli.main._project_root", tmp_path)
        monkeypatch.setattr("sys.frozen", True, raising=False)

        with patch("importlib.metadata.version", _fake_version({"dblift": "1.2.3-frozen"})):
            resolved = _resolve_core_version()

        assert resolved == "1.2.3-frozen"
