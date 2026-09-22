"""The structural-debt ratchet counts what it claims and fails only on growth."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_debt_ratchet", ROOT / "scripts" / "check_debt_ratchet.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SAMPLE = """from typing import Any, Mapping


def f(x: Any, options: Mapping[str, Any]) -> Any:
    from dblift.core import thing

    # getattr(x, "described") in a comment is not a call
    # Story 1-2: rationale kept, identifier is the debt
    try:
        return getattr(x, "y")
    except Exception:
        return hasattr(x, "z")
"""


def _write_tree(tmp_path: Path) -> Path:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "sample.py").write_text(SAMPLE, encoding="utf-8")
    (root / "big.py").write_text("x = 1\n" * 801, encoding="utf-8")
    return root


def test_measure_counts_each_signal(tmp_path: Path) -> None:
    counts = _load_script().measure(_write_tree(tmp_path))
    assert counts == {
        "function_level_imports": 1,
        "any_annotations": 1,
        "dynamic_attribute_access": 2,
        "broad_excepts": 1,
        "process_references": 1,
        "large_files": 1,
    }


def test_main_passes_at_cap_and_fails_above(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    script = _load_script()
    root = _write_tree(tmp_path)
    caps = dict(script.measure(root))
    ratchet = tmp_path / "ratchet.json"

    ratchet.write_text(json.dumps({"_comment": "ignored", **caps}), encoding="utf-8")
    assert script.main(["--root", str(root), "--ratchet", str(ratchet)]) == 0

    caps["broad_excepts"] = 0
    ratchet.write_text(json.dumps(caps), encoding="utf-8")
    assert script.main(["--root", str(root), "--ratchet", str(ratchet)]) == 1
    assert "broad_excepts: 1, cap is 0. Net +1." in capsys.readouterr().out


def test_main_prints_offending_lines_of_the_first_failing_signal(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    script = _load_script()
    root = _write_tree(tmp_path)
    caps = dict(script.measure(root))
    caps["dynamic_attribute_access"] = 0
    ratchet = tmp_path / "ratchet.json"
    ratchet.write_text(json.dumps(caps), encoding="utf-8")

    assert script.main(["--root", str(root), "--ratchet", str(ratchet)]) == 1
    out = capsys.readouterr().out
    assert "Offending lines for 'dynamic_attribute_access':" in out
    assert 'sample.py:10: return getattr(x, "y")' in out
