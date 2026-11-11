"""The per-function complexity ceiling blocks new hotspots and only lets listed ones shrink."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_complexity_ceiling", ROOT / "scripts" / "check_complexity_ceiling.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _branchy(name: str, branches: int, indent: str = "") -> str:
    """A function whose cyclomatic complexity is ``branches + 1``."""
    body = "".join(
        f"{indent}    if x == {i}:\n{indent}        return {i}\n" for i in range(branches)
    )
    return f"{indent}def {name}(x):\n{body}{indent}    return -1\n"


def _tree(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "mod.py").write_text(source, encoding="utf-8")
    return root


def _baseline(tmp_path: Path, exceptions: dict, ceiling: int = 20) -> Path:
    path = tmp_path / "ceiling.json"
    path.write_text(
        json.dumps({"_comment": "test", "ceiling": ceiling, "exceptions": exceptions}),
        encoding="utf-8",
    )
    return path


def _run(tmp_path: Path, source: str, exceptions: dict, ceiling: int = 20) -> int:
    script = _load_script()
    root = _tree(tmp_path, source)
    return script.main(["--baseline", str(_baseline(tmp_path, exceptions, ceiling)), str(root)])


def test_measure_names_functions_methods_and_closures(tmp_path: Path) -> None:
    source = (
        _branchy("top", 3)
        + "\n\nclass Box:\n"
        + _branchy("method", 4, indent="    ")
        + "\n\ndef outer(x):\n"
        + _branchy("inner", 2, indent="    ")
        + "    return inner(x)\n"
    )
    measured = _load_script().measure(_tree(tmp_path, source))
    by_name = {key.split("::", 1)[1]: complexity for key, (complexity, _line) in measured.items()}
    assert by_name["top"] == 4
    assert by_name["Box.method"] == 5
    assert by_name["outer.inner"] == 3
    assert all(key.startswith("mod.py::") for key in measured)


def test_function_at_the_ceiling_passes(tmp_path: Path) -> None:
    assert _run(tmp_path, _branchy("ok", 19), {}) == 0


def test_new_function_over_the_ceiling_fails(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("hot", 20), {}) == 1
    out = capsys.readouterr().out
    assert "mod.py::hot" in out
    assert "21" in out


def test_listed_function_at_its_recorded_value_passes(tmp_path: Path) -> None:
    assert _run(tmp_path, _branchy("hot", 25), {"mod.py::hot": 26}) == 0


def test_listed_function_that_grew_fails(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("hot", 27), {"mod.py::hot": 26}) == 1
    assert "mod.py::hot" in capsys.readouterr().out


def test_listed_function_that_shrank_must_lower_its_entry(tmp_path: Path, capsys) -> None:
    # Freed headroom must not be reused: the entry has to follow the code down.
    assert _run(tmp_path, _branchy("hot", 22), {"mod.py::hot": 26}) == 1
    out = capsys.readouterr().out
    assert "mod.py::hot" in out
    assert "23" in out


def test_listed_function_now_under_the_ceiling_must_be_removed(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("hot", 5), {"mod.py::hot": 26}) == 1
    out = capsys.readouterr().out
    assert "mod.py::hot" in out
    assert "Remove its entry" in out


def test_listed_function_exactly_at_the_ceiling_must_be_removed(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("hot", 19), {"mod.py::hot": 26}) == 1
    assert "Remove its entry" in capsys.readouterr().out


def test_listed_function_that_no_longer_exists_must_be_removed(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("other", 2), {"mod.py::gone": 30}) == 1
    assert "mod.py::gone" in capsys.readouterr().out


@pytest.mark.parametrize("first,second", [(21, 24), (24, 21)])
def test_same_name_defined_twice_is_held_to_the_worse_definition(
    tmp_path: Path, first: int, second: int
) -> None:
    source = _branchy("twice", first) + "\n\n" + _branchy("twice", second)
    measured = _load_script().measure(_tree(tmp_path, source))
    assert measured["mod.py::twice"][0] == 25


def test_missing_root_exits_2(tmp_path: Path) -> None:
    script = _load_script()
    baseline = _baseline(tmp_path, {})
    assert script.main(["--baseline", str(baseline), str(tmp_path / "absent")]) == 2


def test_repository_respects_its_ceiling() -> None:
    script = _load_script()
    data = json.loads((ROOT / ".complexity-ceiling.json").read_text(encoding="utf-8"))
    assert data["ceiling"] == 20
    assert (
        script.main(["--baseline", str(ROOT / ".complexity-ceiling.json"), str(ROOT / "dblift")])
        == 0
    )


def test_methods_of_nested_classes_are_measured(tmp_path: Path) -> None:
    source = "class Outer:\n    class Inner:\n" + _branchy("deep", 24, indent="        ")
    measured = _load_script().measure(_tree(tmp_path, source))
    assert measured["mod.py::Outer.Inner.deep"][0] == 25


def test_methods_of_classes_built_inside_functions_are_measured(tmp_path: Path) -> None:
    source = (
        "def factory():\n    class Local:\n"
        + _branchy("local", 24, indent="        ")
        + "    return Local\n"
    )
    measured = _load_script().measure(_tree(tmp_path, source))
    assert measured["mod.py::factory.Local.local"][0] == 25


def test_nested_class_hotspot_fails_the_gate(tmp_path: Path, capsys) -> None:
    source = "class Outer:\n    class Inner:\n" + _branchy("deep", 24, indent="        ")
    assert _run(tmp_path, source, {}) == 1
    assert "mod.py::Outer.Inner.deep" in capsys.readouterr().out


def test_renamed_hotspot_is_told_to_move_its_entry(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("renamed", 25), {"mod.py::hot": 26}) == 1
    out = capsys.readouterr().out
    assert "mod.py::renamed" in out
    assert "mod.py::hot" in out
    assert "renamed or moved" in out


def test_entry_at_or_under_the_ceiling_is_rejected(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _branchy("hot", 24), {"mod.py::hot": 15}) == 1
    out = capsys.readouterr().out
    assert "mod.py::hot" in out
    assert "not above the ceiling" in out


def test_missing_baseline_exits_2_with_a_message(tmp_path: Path, capsys) -> None:
    script = _load_script()
    root = _tree(tmp_path, _branchy("ok", 2))
    assert script.main(["--baseline", str(tmp_path / "absent.json"), str(root)]) == 2
    assert "absent.json" in capsys.readouterr().out


def test_malformed_baseline_exits_2_with_a_message(tmp_path: Path, capsys) -> None:
    script = _load_script()
    root = _tree(tmp_path, _branchy("ok", 2))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"ceiling": 20}), encoding="utf-8")
    assert script.main(["--baseline", str(bad), str(root)]) == 2
    assert "bad.json" in capsys.readouterr().out


def test_file_with_a_utf8_bom_is_measured(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "mod.py").write_bytes(b"\xef\xbb\xbf" + _branchy("bom", 3).encode("utf-8"))
    assert _load_script().measure(root)["mod.py::bom"][0] == 4


def test_only_one_root_is_accepted(tmp_path: Path) -> None:
    script = _load_script()
    root = _tree(tmp_path, _branchy("ok", 2))
    baseline = _baseline(tmp_path, {})
    with pytest.raises(SystemExit) as caught:
        script.main(["--baseline", str(baseline), str(root), str(root)])
    assert caught.value.code == 2


def test_async_functions_are_measured(tmp_path: Path) -> None:
    source = _branchy("fetch", 24).replace("def fetch", "async def fetch")
    measured = _load_script().measure(_tree(tmp_path, source))
    assert measured["mod.py::fetch"][0] == 25


def test_functions_under_compound_statements_are_measured(tmp_path: Path) -> None:
    source = (
        "import sys\n\nif sys:\n"
        + _branchy("guarded", 24, indent="    ")
        + "\n\ndef outer(x):\n    try:\n"
        + _branchy("inner", 24, indent="        ")
        + "    except ValueError:\n        pass\n    return x\n"
    )
    measured = _load_script().measure(_tree(tmp_path, source))
    assert measured["mod.py::guarded"][0] == 25
    assert measured["mod.py::outer.inner"][0] == 25


def test_rename_hint_is_absent_when_nothing_disappeared(tmp_path: Path, capsys) -> None:
    source = _branchy("hot", 25) + "\n\n" + _branchy("other", 25)
    assert _run(tmp_path, source, {"mod.py::hot": 26}) == 1
    assert "renamed or moved" not in capsys.readouterr().out
