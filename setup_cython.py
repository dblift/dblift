#!/usr/bin/env python3
"""Cython build script for dblift critical-path modules.

Compiles licensing and CLI modules to native extensions (.so/.pyd)
so that the distributed package contains no readable Python source
for these security-sensitive files.

Usage:
    python setup_cython.py build_ext --inplace
"""

# Modules to compile — the license-critical path.
# After compilation the .py sources are stripped from the distribution
# (see scripts/build_distributions.py).
# This list is the single source of truth — build_distributions.py imports it.
_CYTHON_MODULES = [
    "core/licensing/license_manager.py",
    "core/licensing/exceptions.py",
    "core/licensing/_guard.py",
    "cli/main.py",
    "cli/_command_handlers.py",
    "cli/_config_helpers.py",
    "cli/_parser_setup.py",
]


def _path_to_module(path: str) -> str:
    """Convert a source path to a dotted module name.

    Example: 'core/licensing/_guard.py' -> 'core.licensing._guard'

    We cannot rely on Cython's auto-detection here: because the project root
    contains an __init__.py (for __version__), Cython walks up the directory
    tree and finds it, prefixing every module with 'dblift.'.  With --inplace
    that would write the .so files into a 'dblift/' directory — but 'dblift'
    is already a file at the project root (the CLI launcher script), causing
    a 'Not a directory' error.  Explicit Extension objects bypass this logic.
    """
    return path.replace("\\", "/").removesuffix(".py").replace("/", ".")


if __name__ == "__main__":
    from Cython.Build import cythonize
    from setuptools import Extension, setup

    extensions = [Extension(name=_path_to_module(path), sources=[path]) for path in _CYTHON_MODULES]

    setup(
        ext_modules=cythonize(
            extensions,
            compiler_directives={"language_level": "3"},
        ),
    )
