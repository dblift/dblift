"""Pin standalone release builds to the wheel served by PyPI."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_standalone_release_reuses_the_pypi_wheel():
    workflow = yaml.safe_load((WORKFLOWS / "publish-pypi.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert "standalone" in jobs, "release workflow must build standalone archives"
    standalone = jobs["standalone"]
    assert isinstance(standalone["needs"], list) and set(standalone["needs"]) == {
        "test",
        "publish",
    }, "standalone must wait for tests and PyPI publication"
    assert standalone["uses"] == "./.github/workflows/build-standalone.yml"
    assert jobs["test"].get("outputs", {}).get("source-sha") == "${{ steps.source.outputs.sha }}"
    checkout_refs = [
        step["with"]["ref"]
        for step in jobs["publish"]["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkout_refs == ["${{ needs.test.outputs.source-sha }}"]
    assert standalone["with"]["release_sha"] == "${{ needs.test.outputs.source-sha }}"
    assert not any(
        step.get("with", {}).get("name") == "dblift-release-wheel"
        for step in jobs["publish"]["steps"]
    )


def test_standalone_runner_matrix_builds_and_smokes_native_archives():
    path = WORKFLOWS / "build-standalone.yml"
    assert path.is_file(), "standalone runner workflow is missing"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert "workflow_call" in triggers and "workflow_dispatch" in triggers
    rehearsal = triggers.get("pull_request", {})
    assert rehearsal.get("paths"), "standalone workflow needs a path-scoped PR rehearsal"
    assert ".github/workflows/build-standalone.yml" in rehearsal["paths"]
    assert workflow["permissions"] == {"contents": "read"}
    build = workflow["jobs"]["build"]
    assert {entry["target"] for entry in build["strategy"]["matrix"]["include"]} == {
        "linux-x86_64",
        "macos-arm64",
        "windows-x86_64",
    }
    steps = build["steps"]
    release_wheel = [step for step in steps if "pip download" in step.get("run", "")]
    assert len(release_wheel) == 1, "standalone release must download the published wheel"
    release_wheel = release_wheel[0]
    assert release_wheel["if"] == "inputs.release_sha != ''"
    command = release_wheel["run"]
    assert "https://pypi.org/simple" in command
    assert "--no-deps" in command and "--only-binary=:all:" in command
    assert '"dblift==$VERSION"' in command
    assert any(
        step.get("if") == "inputs.release_sha == ''" and "build --wheel" in step.get("run", "")
        for step in steps
    )
    runs = "\n".join(step.get("run", "") for step in steps)
    assert "build_standalone.py" in runs
    assert "smoke_standalone.py" in runs
    assert "release upload" not in runs
    assert not any(step.get("uses", "").startswith("actions/upload-artifact@") for step in steps)
