"""Coverage for ``cli.main._format_version`` — the ``--version`` renderer.

The published ``dblift`` wheel is the OSS *core*. The paid tiers ship as
separate distributions (``dblift-pro`` / ``dblift-enterprise``) bundled into the
compiled binary, each on its own release lifecycle, so their versions need not
match the core's. ``--version`` reports the most-derived installed tier as the
headline and lists every present component so a bare number is never ambiguous.
In a plain OSS install only the core is present, so the output stays one line.
"""

import types
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


def _fake_import_module(modules):
    """Build an ``importlib.import_module`` stand-in from a name->module map."""

    def _inner(name):
        if name in modules:
            return modules[name]
        raise ModuleNotFoundError(name)

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


@pytest.mark.unit
class TestResolveManifestVersion:
    """A ``DISTRIBUTION-MANIFEST.json`` next to the running entry point is
    stamped at build time with the version of the bundled archive/frozen
    distribution — it can't be shadowed by whatever happens to be sitting in
    the host's site-packages, unlike ``importlib.metadata``."""

    def test_reads_version_from_manifest(self, tmp_path, monkeypatch):
        from cli.main import _resolve_manifest_version

        (tmp_path / "DISTRIBUTION-MANIFEST.json").write_text(
            '{"version": "3.2.0", "artifact_type": "archive"}', encoding="utf-8"
        )
        monkeypatch.setattr("cli.main._project_root", tmp_path)

        assert _resolve_manifest_version() == "3.2.0"

    def test_returns_none_when_manifest_absent(self, tmp_path, monkeypatch):
        """A plain ``pip install`` never ships this file — no-op, not an error."""
        from cli.main import _resolve_manifest_version

        monkeypatch.setattr("cli.main._project_root", tmp_path)

        assert _resolve_manifest_version() is None

    def test_returns_none_on_malformed_manifest(self, tmp_path, monkeypatch):
        from cli.main import _resolve_manifest_version

        (tmp_path / "DISTRIBUTION-MANIFEST.json").write_text("not json", encoding="utf-8")
        monkeypatch.setattr("cli.main._project_root", tmp_path)

        assert _resolve_manifest_version() is None

    def test_returns_none_on_valid_json_that_is_not_an_object(self, tmp_path, monkeypatch):
        from cli.main import _resolve_manifest_version

        (tmp_path / "DISTRIBUTION-MANIFEST.json").write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setattr("cli.main._project_root", tmp_path)

        assert _resolve_manifest_version() is None

    def test_returns_none_when_version_field_missing(self, tmp_path, monkeypatch):
        from cli.main import _resolve_manifest_version

        (tmp_path / "DISTRIBUTION-MANIFEST.json").write_text(
            '{"artifact_type": "archive"}', encoding="utf-8"
        )
        monkeypatch.setattr("cli.main._project_root", tmp_path)

        assert _resolve_manifest_version() is None


@pytest.mark.unit
class TestFormatVersionWithManifest:
    """Reproduces the exact archive-distribution failure from issue #745: a
    stale/unrelated ``dblift``/``dblift-pro``/``dblift-enterprise`` install
    sitting in the host's site-packages must not win over the version stamped
    in the bundled distribution's own manifest."""

    def test_manifest_headlines_over_disagreeing_metadata(self):
        """Host site-packages has stale 2.x installs; the archive's manifest
        says 3.2.0. The manifest must win the headline."""
        from cli.main import _format_version

        installed = {"dblift-pro": "2.2.0", "dblift-enterprise": "2.2.0"}
        with patch("cli.main._resolve_core_version", return_value="2.0.0"):
            with patch("cli.main._resolve_manifest_version", return_value="3.2.0"):
                with patch("importlib.metadata.version", _fake_version(installed)):
                    out = _format_version()

        lines = out.splitlines()
        assert lines[0] == "dblift version 3.2.0"
        # Manifest has no per-tier breakdown, so the component lines are
        # unaffected -- this documents current, not ideal, behavior.
        assert any("core (OSS)" in line and "2.0.0" in line for line in lines[1:])
        assert any(line.strip().startswith("pro:") and "2.2.0" in line for line in lines[1:])
        assert any(line.strip().startswith("enterprise:") and "2.2.0" in line for line in lines[1:])

    def test_manifest_headlines_pure_oss_archive(self):
        """A pure-OSS archive (no pro/enterprise installed at all) with a
        manifest still headlines from the manifest and stays a single line."""
        from cli.main import _format_version

        with patch("cli.main._resolve_core_version", return_value="2.0.0"):
            with patch("cli.main._resolve_manifest_version", return_value="3.2.0"):
                with patch("importlib.metadata.version", _fake_version({})):
                    out = _format_version()

        assert out == "dblift version 3.2.0"

    def test_no_manifest_is_unaffected(self):
        """No manifest present (normal ``pip install``) -- behavior is
        unchanged from before this fix."""
        from cli.main import _format_version

        installed = {"dblift-pro": "2.4.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("cli.main._resolve_manifest_version", return_value=None):
                with patch("importlib.metadata.version", _fake_version(installed)):
                    out = _format_version()

        lines = out.splitlines()
        assert lines[0] == "dblift version 2.4.0"


@pytest.mark.unit
class TestFormatVersionBreakdownPrefersDirectImport:
    """The breakdown lines resolve installed-package versions the same way the
    headline already resolves the core version: a directly-importable
    package's own ``__version__`` is preferred over installed distribution
    metadata, which can be stale if the host environment has leftover/unrelated
    metadata for a package name that a newer running copy also uses."""

    def test_prefers_direct_import_version_over_metadata(self):
        """A directly-importable package reporting its own ``__version__``
        must win over ``importlib.metadata.version``, which may be stale."""
        from cli.main import _format_version

        fake_pro = types.SimpleNamespace(__version__="9.9.9-direct")
        installed = {"dblift-pro": "2.4.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                with patch(
                    "importlib.import_module",
                    _fake_import_module({"dblift_pro": fake_pro}),
                ):
                    out = _format_version()

        lines = out.splitlines()
        assert any(
            line.strip().startswith("pro:") and "9.9.9-direct" in line for line in lines[1:]
        )
        assert not any("2.4.0" in line for line in lines)

    def test_falls_back_to_metadata_when_not_importable(self):
        """No direct-import candidate available -- metadata is used, unchanged."""
        from cli.main import _format_version

        installed = {"dblift-pro": "2.4.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                with patch("importlib.import_module", _fake_import_module({})):
                    out = _format_version()

        lines = out.splitlines()
        assert any(line.strip().startswith("pro:") and "2.4.0" in line for line in lines[1:])

    def test_falls_back_to_metadata_when_no_version_attribute(self):
        """Importable but no ``__version__`` attribute -- metadata is used."""
        from cli.main import _format_version

        fake_pro = types.SimpleNamespace()
        installed = {"dblift-pro": "2.4.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                with patch(
                    "importlib.import_module",
                    _fake_import_module({"dblift_pro": fake_pro}),
                ):
                    out = _format_version()

        lines = out.splitlines()
        assert any(line.strip().startswith("pro:") and "2.4.0" in line for line in lines[1:])

    def test_falls_back_to_metadata_when_import_raises_non_import_error(self):
        """A package that's importable but broken (raises something other than
        ImportError during import, e.g. a corrupted install) must not crash
        --version -- it falls back to metadata like any other unusable import."""
        from cli.main import _format_version

        def _broken_import(name):
            if name == "dblift_pro":
                raise AttributeError("simulated broken install")
            raise ModuleNotFoundError(name)

        installed = {"dblift-pro": "2.4.0"}
        with patch("cli.main._resolve_core_version", return_value="2.3.0"):
            with patch("importlib.metadata.version", _fake_version(installed)):
                with patch("importlib.import_module", _broken_import):
                    out = _format_version()

        lines = out.splitlines()
        assert any(line.strip().startswith("pro:") and "2.4.0" in line for line in lines[1:])
