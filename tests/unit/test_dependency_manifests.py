"""Dependency manifest drift tests."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _canonical_package_name(requirement: str) -> str:
    """Return a normalized package name from a PEP 508-ish requirement line."""
    name = re.split(r"\s*(?:\[|==|!=|~=|>=|<=|>|<|;)", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _project_runtime_dependencies() -> set[str]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    return {
        _canonical_package_name(requirement) for requirement in pyproject["project"]["dependencies"]
    }


def _requirements_dependencies(path: Path) -> set[str]:
    dependencies: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        dependencies.add(_canonical_package_name(line))
    return dependencies


@pytest.mark.unit
@pytest.mark.parametrize("requirements_file", ["requirements.txt", "requirements-runtime.txt"])
def test_runtime_requirements_include_pyproject_runtime_dependencies(requirements_file: str):
    expected = _project_runtime_dependencies()
    actual = _requirements_dependencies(ROOT / requirements_file)

    assert expected <= actual, (
        f"{requirements_file} is missing runtime dependencies declared in pyproject.toml: "
        f"{sorted(expected - actual)}"
    )


@pytest.mark.unit
def test_requirements_txt_does_not_include_obsolete_dataclasses_backport():
    dependencies = _requirements_dependencies(ROOT / "requirements.txt")

    assert "dataclasses" not in dependencies


@pytest.mark.unit
def test_docker_manifests_do_not_install_jvm_runtime():
    dockerfiles = [
        ROOT / "Dockerfile",
        ROOT / "Dockerfile.validation",
        ROOT / "Dockerfile.validation-lite",
    ]
    forbidden_terms = ("jlink", "JAVA_HOME", "jpype", "jdbc_drivers")

    for dockerfile in dockerfiles:
        content = dockerfile.read_text(encoding="utf-8").lower()
        assert not any(term.lower() in content for term in forbidden_terms), dockerfile


@pytest.mark.unit
def test_validation_lite_image_installs_sqlalchemy():
    content = (ROOT / "Dockerfile.validation-lite").read_text(encoding="utf-8")

    assert "SQLAlchemy" in content


@pytest.mark.unit
def test_runtime_image_installs_native_driver_extra():
    content = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert ".[all]" in content


@pytest.mark.unit
def test_distribution_build_installs_native_driver_extra():
    content = (ROOT / ".github" / "workflows" / "build.yaml").read_text(encoding="utf-8")

    assert 'pip install -e ".[all]"' in content


@pytest.mark.unit
def test_legacy_jre_build_scripts_are_removed():
    assert not (ROOT / "Dockerfile.jlink").exists()
    assert not (ROOT / "scripts" / "build_with_jre.sh").exists()
    assert not (ROOT / "scripts" / "build_with_jre.bat").exists()


@pytest.mark.unit
def test_setup_scripts_do_not_create_jdbc_driver_directory():
    for setup_script in [ROOT / "scripts" / "setup.sh", ROOT / "scripts" / "setup.bat"]:
        content = setup_script.read_text(encoding="utf-8").lower()
        assert "jdbc_drivers" not in content
        assert "jdbc drivers" not in content


@pytest.mark.unit
def test_ci_workflows_do_not_install_java():
    workflow_dir = ROOT / ".github" / "workflows"
    forbidden_terms = ("setup-java", "java-version", "jdk")

    for workflow_file in workflow_dir.glob("*.yml"):
        content = workflow_file.read_text(encoding="utf-8").lower()
        assert not any(term in content for term in forbidden_terms), workflow_file


@pytest.mark.unit
def test_user_docs_do_not_describe_jdbc_or_jvm_runtime():
    doc_paths = [
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "DOCKER.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs" / "release" / "offline-delivery.md",
        ROOT / "docs" / "operations" / "recovery" / "index.md",
        ROOT / "docs" / "operations" / "recovery" / "oracle-lock-timeout.md",
        ROOT / "docs" / "operations" / "recovery" / "schema-history-corruption.md",
        ROOT / "docs" / "user-guide" / "commands.md",
        ROOT / "docs" / "user-guide" / "troubleshooting.md",
        ROOT / "docs" / "fr" / "user-guide" / "troubleshooting.md",
    ]

    for doc_path in doc_paths:
        content = doc_path.read_text(encoding="utf-8").lower()
        assert "jdbc" not in content, doc_path
        assert "jvm" not in content, doc_path
