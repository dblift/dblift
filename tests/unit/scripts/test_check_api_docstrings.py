"""Unit tests for ``scripts/check_api_docstrings``.

The linter gates the public surface of the whole ``dblift/`` package at
zero tolerance in CI; these tests pin the detection rules, exemption
mechanisms and the fail-loudly behaviour for missing roots so future
changes can't silently weaken the contract.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.check_api_docstrings import DEFAULT_ROOTS, main, scan_file

pytestmark = [pytest.mark.unit]


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def test_clean_file_has_zero_violations(tmp_path: Path) -> None:
    """Module + class + function + method all documented → no violations."""
    path = _write(
        tmp_path,
        '''
        """Module doc."""

        class Foo:
            """Class doc."""

            def __init__(self) -> None:
                """Init doc."""
                self.x = 1

            def method(self) -> int:
                """Method doc."""
                return self.x


        def helper() -> int:
            """Helper doc."""
            return 1
        ''',
    )
    assert scan_file(str(path)) == []


def test_missing_module_docstring_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, 'def f():\n    """doc."""\n    pass\n')
    violations = scan_file(str(path))
    assert ("module", "<module>") in [(v[2], v[3]) for v in violations]


def test_missing_function_docstring_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, '"""mod."""\n\ndef public_no_doc():\n    return 1\n')
    violations = scan_file(str(path))
    assert ("function", "public_no_doc") in [(v[2], v[3]) for v in violations]


def test_missing_class_docstring_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, '"""mod."""\n\nclass PublicNoDoc:\n    pass\n')
    violations = scan_file(str(path))
    kinds_names = [(v[2], v[3]) for v in violations]
    assert ("class", "PublicNoDoc") in kinds_names


def test_private_names_ignored(tmp_path: Path) -> None:
    """Names starting with ``_`` are exempt (except ``__init__``)."""
    path = _write(
        tmp_path,
        '''
        """mod."""

        def _private_helper():
            return 1


        class _PrivateClass:
            pass
        ''',
    )
    assert scan_file(str(path)) == []


def test_dunder_init_is_public(tmp_path: Path) -> None:
    """``__init__`` is treated as public because constructor docs matter."""
    path = _write(
        tmp_path,
        '''
        """mod."""

        class Foo:
            """Class doc."""

            def __init__(self) -> None:
                # No docstring — should still be flagged because the body
                # does work (assignment), so the stub-body exemption does
                # not apply.
                self.x = 1
        ''',
    )
    violations = scan_file(str(path))
    assert any(v[3] == "__init__" for v in violations)


def test_stub_body_ellipsis_exempt(tmp_path: Path) -> None:
    """Single-statement ``...`` body is treated as a protocol stub."""
    path = _write(
        tmp_path,
        '''
        """mod."""

        from typing import Protocol


        class P(Protocol):
            """Protocol doc."""

            def method(self) -> int: ...
        ''',
    )
    assert scan_file(str(path)) == []


def test_stub_body_pass_exempt(tmp_path: Path) -> None:
    """Single-statement ``pass`` body is treated as a stub."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        def stub():
            pass
        ''',
    )
    assert scan_file(str(path)) == []


def test_inner_functions_exempt(tmp_path: Path) -> None:
    """Closures defined inside another function inherit the outer docstring."""
    path = _write(
        tmp_path,
        '''
        """mod."""

        from functools import wraps


        def decorator(fn):
            """Outer doc."""

            @wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)

            return wrapper
        ''',
    )
    assert scan_file(str(path)) == []


def test_inline_annotation_exempts_function(tmp_path: Path) -> None:
    """``# lint: allow-missing-docstring: <reason>`` is honored on def lines."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        def public_no_doc():  # lint: allow-missing-docstring: legacy entrypoint
            return 1
        ''',
    )
    assert scan_file(str(path)) == []


def test_bare_none_body_is_not_a_stub(tmp_path: Path) -> None:
    """A body of literal ``None`` is not a stub — it must still be flagged.

    Regression for cursor[bot] review on PR #279: an earlier version of
    ``_is_stub_body`` accepted ``def foo(): None`` as a stub alongside
    ``...`` / ``pass``. Only ``...`` and ``pass`` are documented stub
    forms; ``None`` returned implicitly from an expression statement is
    not a Protocol/ABC idiom and must not bypass the docstring rule.
    """
    path = _write(
        tmp_path,
        '''
        """mod."""


        def public_returns_none():
            None
        ''',
    )
    violations = scan_file(str(path))
    assert any(v[3] == "public_returns_none" for v in violations)


def test_inline_annotation_exempts_class(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        """mod."""


        class Legacy:  # lint: allow-missing-docstring: pre-2026 holdover
            x = 1
        ''',
    )
    assert scan_file(str(path)) == []


# ---------------------------------------------------------------------------
# Private-class heuristic (action #4)
# ---------------------------------------------------------------------------


def test_private_class_method_exempt(tmp_path: Path) -> None:
    """Public-named methods on private classes inherit the class's privacy."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        def _make_result():
            """Factory doc."""

            class _Result:
                def __init__(self) -> None:
                    self.x = 1

                def execution_time(self) -> int:
                    return 0

            return _Result()
        ''',
    )
    # ``_make_result`` is private; ``_Result`` is private; methods of
    # ``_Result`` must NOT be flagged. The decorator/closure pattern is
    # widespread (factories, context managers, internal builders).
    assert scan_file(str(path)) == []


def test_private_class_init_exempt(tmp_path: Path) -> None:
    """``__init__`` on a private class does not need a docstring."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        class _Internal:
            def __init__(self, x: int) -> None:
                self.x = x
        ''',
    )
    assert scan_file(str(path)) == []


def test_public_class_init_still_flagged(tmp_path: Path) -> None:
    """The heuristic must not regress: ``__init__`` on a public class is still flagged."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        class Public:
            """Class doc."""

            def __init__(self, x: int) -> None:
                self.x = x
        ''',
    )
    violations = scan_file(str(path))
    assert any(v[3] == "__init__" for v in violations)


def test_public_method_on_public_class_still_flagged(tmp_path: Path) -> None:
    """Counter-test: public method on a public class is NOT exempted."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        class Public:
            """Class doc."""

            def method(self) -> int:
                return 0
        ''',
    )
    violations = scan_file(str(path))
    assert any(v[3] == "method" for v in violations)


def test_public_class_nested_under_private_class_inherits_privacy(tmp_path: Path) -> None:
    """``class _P: class Q: def m(): ...`` — ``m`` is private, not flagged.

    Regression for Bugbot #340: an earlier version of ``_enclosing_classes``
    walked up only to the nearest ``ClassDef``, missing the outer ``_P``.
    ``Q`` is public-named but lives entirely inside the private surface of
    ``_P``; its methods should inherit that privacy.
    """
    path = _write(
        tmp_path,
        '''
        """mod."""


        class _Private:
            class Inner:
                def method(self) -> int:
                    return 0

                def __init__(self) -> None:
                    self.x = 1
        ''',
    )
    assert scan_file(str(path)) == []


def test_deeply_nested_private_chain(tmp_path: Path) -> None:
    """``_A.B.C.method`` is private when *any* ancestor class is private."""
    path = _write(
        tmp_path,
        '''
        """mod."""


        class _A:
            class B:
                class C:
                    def method(self) -> int:
                        return 0
        ''',
    )
    assert scan_file(str(path)) == []


# ---------------------------------------------------------------------------
# Zero-tolerance scope
# ---------------------------------------------------------------------------


def test_default_root_is_the_whole_package() -> None:
    """The gate covers every subpackage and top-level module, not a hand-picked list."""
    assert DEFAULT_ROOTS == ("dblift",)


def test_any_violation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """There is no cap: a single missing docstring fails the run."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "fake"
    root.mkdir()
    (root / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    rc = main(["--paths", "fake"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing docstring" in out


def test_clean_tree_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "fake"
    root.mkdir()
    (root / "mod.py").write_text('"""Doc."""\n', encoding="utf-8")
    assert main(["--paths", "fake"]) == 0


def test_ratchet_option_is_gone() -> None:
    """Caps are retired; the option must not be silently accepted."""
    with pytest.raises(SystemExit):
        main(["--paths", "fake", "--ratchet", "caps.json"])


def test_missing_root_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Running from the wrong directory must not pass on an empty scan."""
    monkeypatch.chdir(tmp_path)
    rc = main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "dblift" in err and "not found" in err


def test_missing_explicit_root_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["--paths", "nope"]) == 2
