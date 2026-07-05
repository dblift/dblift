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

        with patch("importlib.metadata.version", _fake_version({"dblift": "2.3.0"})):
            out = _format_version()

        assert out == "dblift version 2.3.0"

    def test_pro_present_headlines_pro_and_lists_core(self):
        """With ``dblift-pro`` installed, headline is the pro version + a manifest."""
        from cli.main import _format_version

        installed = {"dblift": "2.3.0", "dblift-pro": "2.4.0"}
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

        installed = {"dblift": "2.3.0", "dblift-pro": "2.3.1", "dblift-enterprise": "2.3.1"}
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

        installed = {"dblift": "2.3.0", "dblift-enterprise": "2.5.0"}
        with patch("importlib.metadata.version", _fake_version(installed)):
            out = _format_version()

        lines = out.splitlines()
        assert lines[0] == "dblift version 2.5.0"
        assert any("core (OSS)" in line and "2.3.0" in line for line in lines[1:])
        assert not any(line.strip().startswith("pro:") for line in lines)
        assert any(line.strip().startswith("enterprise:") and "2.5.0" in line for line in lines[1:])
